"""
============================================================
 Навыки и инструменты. Навык — модуль в jarvis/skills/, который
 регистрирует инструменты декоратором @tool. Ядро про навыки
 ничего не знает: новый навык подключается импортом в skills/__init__.

 Инструмент = имя + схема аргументов (pydantic) + уровень риска +
 функция. Вызвать инструмент можно только через Ctx.call(): там
 политика, подтверждение и журнал — обойти их нельзя.
============================================================
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from ..security import Risk

if TYPE_CHECKING:
    from ..session import Session


@dataclass
class ToolResult:
    say: str = ""
    log: str | None = None
    data: Any = None
    ok: bool = True


@dataclass
class Reply:
    """Ответ на реплику: что сказать, что показать в журнале диалога."""
    say: str = ""
    log: str | None = None
    silent: bool = False
    intent: str = ""
    data: dict | None = None

    @staticmethod
    def of(v: "str | Reply | ToolResult | None", intent: str = "") -> "Reply":
        if v is None:
            return Reply(intent=intent)
        if isinstance(v, Reply):
            v.intent = v.intent or intent
            return v
        if isinstance(v, ToolResult):
            return Reply(say=v.say, log=v.log, intent=intent, data=v.data if isinstance(v.data, dict) else None)
        return Reply(say=v, log=v, intent=intent)


@dataclass
class Tool:
    name: str
    skill: str
    title: str
    description: str
    risk: Risk
    fn: Callable[..., Any]
    args: type[BaseModel] | None = None
    network: bool = False
    explicit_re: str | None = None
    summary: Callable[[Any], str] | None = None
    llm: bool = True

    def describe(self) -> str:
        """Строка для системного промпта модели."""
        schema = ""
        if self.args:
            props = self.args.model_json_schema().get("properties", {})
            schema = ", ".join(f'"{k}": {v.get("type", "string")}' for k, v in props.items())
        return f"- {self.name}({schema}) — {self.description}"

    def human(self, args: BaseModel | None) -> str:
        if self.summary:
            try:
                return self.summary(args)
            except Exception:  # noqa: BLE001 — подпись не должна ронять действие
                pass
        tail = ""
        if args is not None:
            tail = ": " + ", ".join(f"{k}={v}" for k, v in args.model_dump().items() if v not in (None, "", []))
        return self.title + tail

    def parse(self, raw: dict | None) -> BaseModel | None:
        if self.args is None:
            return None
        return self.args.model_validate(raw or {})


TOOLS: dict[str, Tool] = {}


def tool(name: str, *, skill: str, title: str, risk: Risk, args: type[BaseModel] | None = None,
         description: str = "", network: bool = False, explicit_re: str | None = None,
         summary: Callable[[Any], str] | None = None, llm: bool = True):
    def deco(fn):
        TOOLS[name] = Tool(name=name, skill=skill, title=title, description=description or title,
                           risk=risk, fn=fn, args=args, network=network, explicit_re=explicit_re,
                           summary=summary, llm=llm)
        return fn
    return deco


async def invoke(t: Tool, ctx: "Ctx", args: BaseModel | None) -> ToolResult:
    out = t.fn(ctx, args) if t.args is not None else t.fn(ctx)
    if inspect.isawaitable(out):
        out = await out
    if isinstance(out, str):
        return ToolResult(say=out, log=out)
    return out or ToolResult()


@dataclass
class Ctx:
    """Контекст одного хода: кто, что сказал, откуда пришло, куда отвечать."""
    session: "Session"
    user_text: str = ""
    raw_text: str = ""
    origin: str = "rule"            # rule | llm | auto
    untrusted: bool = False         # в ход попали чужие данные
    extras: dict = field(default_factory=dict)

    @property
    def profile_id(self) -> int:
        return self.session.profile_id

    @property
    def db(self):
        return self.session.db

    def setting(self, key: str, fallback: Any = None) -> Any:
        return self.session.settings.get(key, fallback)

    async def call(self, name: str, args: dict | None = None, *, origin: str | None = None) -> ToolResult:
        return await self.session.call_tool(self, name, args or {}, origin=origin or self.origin)


def validation_message(err: ValidationError) -> str:
    first = err.errors()[0] if err.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []))
    return f"аргумент {loc}: {first.get('msg', 'неверное значение')}"


def tools_for_llm() -> list[Tool]:
    return [t for t in TOOLS.values() if t.llm]


def tool_names_json() -> str:
    return json.dumps(sorted(t.name for t in tools_for_llm()), ensure_ascii=False)
