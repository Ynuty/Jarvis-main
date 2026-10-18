"""Системные инструменты ядра: аварийная остановка и откат."""
from __future__ import annotations

from ..security import Risk
from ..skills.base import Skill, Tool, ToolResult, schema


def stop(ctx) -> ToolResult:
    ctx.orchestrator.policy.stop()
    ctx.orchestrator.pending.clear()
    return ToolResult(True, "Остановился. Ничего не выполняю, пока не скажете «продолжай»",
                      ui={"stopped": True})


def resume(ctx) -> ToolResult:
    ctx.orchestrator.policy.resume()
    return ToolResult(True, "Снова в работе", ui={"stopped": False})


def undo(ctx) -> ToolResult:
    return ctx.orchestrator.undo_last()


SKILL = Skill("system", "Система", [
    Tool("stop", "Аварийная остановка", schema(), Risk.SAFE, stop),
    Tool("resume", "Снять аварийную остановку", schema(), Risk.SAFE, resume),
    Tool("undo", "Отменить последнее действие", schema(), Risk.SAFE, undo),
])
