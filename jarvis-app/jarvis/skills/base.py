"""Базовые типы навыков. Навык — независимый модуль с описанием инструментов;
новый навык подключается без правки ядра (см. registry.py)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from ..security import Risk

if TYPE_CHECKING:
    from ..core.context import Context


@dataclass
class ToolResult:
    ok: bool
    message: str                       # что сделано — попадает в «Сделано Джарвисом»
    undo: dict | None = None           # {"tool": "skill.tool", "args": {...}} — как откатить
    data: Any = None                   # данные для интерфейса (список задач и т.п.)
    task_id: int | None = None
    ui: dict = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    params: dict                       # JSON-схема аргументов (её же видит LLM)
    risk: Risk
    handler: Callable[..., ToolResult]
    hidden: bool = False               # служебный инструмент (откат), LLM его не видит
    describe: Callable[[dict], str] | None = None  # текст для карточки подтверждения

    def run(self, ctx: "Context", args: dict) -> ToolResult:
        return self.handler(ctx, **args)


@dataclass
class Skill:
    name: str
    title: str
    tools: list[Tool]

    def tool(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)


def schema(properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties or {}, "required": required or [],
            "additionalProperties": False}


_TYPES = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}


def validate(args: Any, sch: dict) -> str | None:
    """Небольшое подмножество JSON Schema. Возвращает текст ошибки или None."""
    if not isinstance(args, dict):
        return "аргументы должны быть объектом"
    props = sch.get("properties", {})
    for key in sch.get("required", []):
        if args.get(key) in (None, ""):
            return f"не хватает параметра «{key}»"
    for key, value in args.items():
        if key not in props:
            if sch.get("additionalProperties") is False:
                return f"лишний параметр «{key}»"
            continue
        spec = props[key]
        if value is None and key not in sch.get("required", []):
            continue
        py = _TYPES.get(spec.get("type", ""))
        if py and (not isinstance(value, py) or (py is int and isinstance(value, bool))):
            return f"параметр «{key}» должен быть типа {spec['type']}"
        if "enum" in spec and value not in spec["enum"]:
            return f"параметр «{key}» должен быть одним из {spec['enum']}"
    return None
