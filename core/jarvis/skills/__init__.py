"""
Навыки. Импорт модуля регистрирует его инструменты в TOOLS.
Чтобы подключить новый навык — добавьте его в список ниже.
"""
from . import base  # noqa: F401
from . import system, timers, notes, info, memory, day, desktop, order, order_auto, mail, knowledge  # noqa: F401
from .base import TOOLS, Ctx, Reply, Tool, ToolResult, tool  # noqa: F401
