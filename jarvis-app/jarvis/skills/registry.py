"""Автоподключение навыков: каждый подпакет jarvis.skills с переменной SKILL."""
from __future__ import annotations

import importlib
import pkgutil

from .base import Skill, Tool


class Registry:
    def __init__(self, skills: list[Skill] | None = None):
        self.skills: dict[str, Skill] = {}
        for s in skills or []:
            self.add(s)

    def add(self, skill: Skill) -> None:
        self.skills[skill.name] = skill

    def get(self, skill: str, tool: str) -> Tool | None:
        s = self.skills.get(skill)
        return s.tool(tool) if s else None

    def resolve(self, full_name: str) -> tuple[str, str, Tool | None]:
        skill, _, tool = full_name.partition(".")
        return skill, tool, self.get(skill, tool)

    def llm_tools(self) -> list[dict]:
        """Описание инструментов для LLM (служебные и system не показываются)."""
        return [
            {"name": f"{s.name}.{t.name}", "description": t.description, "parameters": t.params}
            for s in self.skills.values() if s.name != "system"
            for t in s.tools if not t.hidden
        ]

    @classmethod
    def discover(cls) -> "Registry":
        from .. import skills as pkg
        reg = cls()
        for info in pkgutil.iter_modules(pkg.__path__):
            if not info.ispkg:
                continue
            module = importlib.import_module(f"{pkg.__name__}.{info.name}")
            skill = getattr(module, "SKILL", None)
            if isinstance(skill, Skill):
                reg.add(skill)
        return reg
