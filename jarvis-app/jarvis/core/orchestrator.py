"""Оркестратор — жизненный цикл команды:

ввод → нормализация → роутер правил → LLM (если не узнали) → план →
проверка политики → подтверждение (если риск) → выполнение навыком →
запись в журнал → ответ.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from ..security import Policy
from ..skills import Registry, ToolResult, validate
from ..storage import Storage
from . import system
from .context import Context
from .normalize import normalize, recover
from .router import Action, route

CONFIRM_TTL = 120  # секунд ждём ответа на подтверждение


class Orchestrator:
    def __init__(self, storage: Storage, registry: Registry | None = None, llm: Any = None,
                 dry_run: bool = False):
        self.storage = storage
        self.policy = Policy(storage)
        self.registry = registry or Registry.discover()
        self.registry.add(system.SKILL)
        self.llm = llm
        self.dry_run = dry_run
        self.pending: dict[str, dict] = {}
        self._lock = threading.Lock()   # очередь действий: команды выполняются по одной

    # ---- вход ---------------------------------------------------------
    def handle(self, text: str, source: str = "user") -> dict:
        with self._lock:
            norm = normalize(text)
            if not norm:
                return self._reply("unknown", "Пустая команда")
            plan, via = route(norm), "rules"
            if plan is None and self.llm is not None and self.llm.enabled():
                plan, via = self.llm.plan(norm, self.registry.llm_tools()), "llm"
                if plan:
                    plan = [a for a in plan if not self._is_hidden(a)] or None
            for a in plan or []:
                if a.skill == "day" and a.args.get("title"):
                    a.args["title"] = recover(a.args["title"], text)
            if not plan:
                hint = "" if self.llm and self.llm.enabled() else \
                    " Локальная модель не подключена — попробуйте типовую команду, например «открой telegram»."
                return self._reply("unknown", "Не понял команду." + hint, heard=text)
            return self._run(plan, 0, source, via, heard=text)

    def confirm(self, pending_id: str, accept: bool) -> dict:
        with self._lock:
            item = self.pending.pop(pending_id, None)
            if not item or time.time() - item["created"] > CONFIRM_TTL:
                return self._reply("error", "Подтверждение устарело. Повторите команду.")
            action: Action = item["plan"][item["index"]]
            if not accept:
                tool = self.registry.get(action.skill, action.tool)
                self.storage.add_event(action.skill, action.tool, action.args,
                                       tool.risk.label if tool else "?", "cancelled",
                                       "Отменено пользователем", source=item["source"])
                return self._reply("done", "Хорошо, не делаю.", steps=item["steps"])
            return self._run(item["plan"], item["index"], item["source"], item["via"],
                             confirmed=item["index"], steps=item["steps"])

    def run_action(self, skill: str, tool: str, args: dict | None = None, source: str = "user") -> dict:
        """Прямой вызов инструмента из интерфейса (галочка в шторке, кнопка «Отменить»)."""
        with self._lock:
            return self._run([Action(skill, tool, args or {})], 0, source, "ui")

    # ---- выполнение плана --------------------------------------------
    def _run(self, plan: list[Action], start: int, source: str, via: str,
             confirmed: int | None = None, steps: list | None = None, heard: str | None = None) -> dict:
        steps = list(steps or [])
        ui: dict = {}
        undo_available = False
        for i in range(start, len(plan)):
            action = plan[i]
            tool = self.registry.get(action.skill, action.tool)
            if tool is None:
                return self._reply("error", f"Нет такого действия: {action.name}", steps=steps, heard=heard)
            err = validate(action.args, tool.params)
            if err:
                return self._reply("error", f"Не получилось разобрать команду: {err}", steps=steps, heard=heard)

            decision = self.policy.check(action.skill, action.tool, tool.risk, action.args, source)
            if decision.verdict == "deny":
                self.storage.add_event(action.skill, action.tool, action.args, tool.risk.label,
                                       "denied", decision.reason, source=source)
                return self._reply("stopped", decision.reason, steps=steps, heard=heard)
            if decision.verdict == "confirm" and confirmed != i:
                pid = uuid.uuid4().hex[:12]
                self.pending[pid] = {"plan": plan, "index": i, "source": source, "via": via,
                                     "steps": steps, "created": time.time()}
                return self._reply("confirm", decision.reason, steps=steps, heard=heard, confirm={
                    "id": pid, "text": self._describe(action), "reason": decision.reason})

            ctx = Context(self.storage, dry_run=self.dry_run, orchestrator=self,
                          extra={"source": source, "llm": self.llm})
            try:
                result = tool.run(ctx, action.args)
            except Exception as exc:  # навык не должен ронять ядро
                result = ToolResult(False, f"Ошибка навыка: {exc}")
            self.storage.add_event(action.skill, action.tool, action.args, tool.risk.label,
                                   "done" if result.ok else "failed", result.message,
                                   task_id=result.task_id, source=source, undo=result.undo)
            steps.append({"text": result.message, "ok": result.ok})
            ui.update(result.ui)
            undo_available = bool(result.undo) if result.ok else undo_available
            if not result.ok:
                return self._reply("error", result.message, steps=steps, ui=ui, heard=heard)

        say = steps[-1]["text"] if len(steps) == 1 else "Готово: " + "; ".join(
            s["text"][0].lower() + s["text"][1:] for s in steps)
        return self._reply("done", say, steps=steps, ui=ui, undo=undo_available, via=via, heard=heard)

    def undo_last(self) -> ToolResult:
        ev = self.storage.last_undoable_event()
        if not ev:
            return ToolResult(False, "Нечего отменять")
        spec = json.loads(ev["undo"])
        skill, tool_name, tool = self.registry.resolve(spec["tool"])
        if tool is None:
            return ToolResult(False, "Это действие нельзя отменить")
        ctx = Context(self.storage, dry_run=self.dry_run, orchestrator=self)
        res = tool.run(ctx, spec["args"])
        if res.ok:
            self.storage.set_event_status(ev["id"], "undone")
            return ToolResult(True, f"Отменил: {ev['result'][0].lower()}{ev['result'][1:]}", ui=res.ui)
        return res

    # ---- вспомогательное ---------------------------------------------
    def _is_hidden(self, a: Action) -> bool:
        t = self.registry.get(a.skill, a.tool)
        return a.skill == "system" or t is None or t.hidden

    def _describe(self, a: Action) -> str:
        tool = self.registry.get(a.skill, a.tool)
        if tool.describe:
            return tool.describe(a.args)
        details = ", ".join(f"{v}" for v in a.args.values() if v not in (None, ""))
        return f"{tool.description}" + (f": {details}" if details else "")

    @staticmethod
    def _reply(status: str, say: str, steps: list | None = None, ui: dict | None = None,
               undo: bool = False, via: str | None = None, heard: str | None = None,
               confirm: dict | None = None) -> dict:
        return {"status": status, "say": say, "steps": steps or [], "ui": ui or {},
                "undo": undo, "via": via, "heard": heard, "confirm": confirm}
