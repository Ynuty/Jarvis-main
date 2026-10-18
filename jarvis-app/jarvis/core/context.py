from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..storage import Storage

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


@dataclass
class Context:
    """То, что навык получает при вызове инструмента."""
    storage: Storage
    dry_run: bool = False               # тестовый режим: ничего не делать в системе
    platform: str = sys.platform
    orchestrator: "Orchestrator | None" = None
    extra: dict[str, Any] = field(default_factory=dict)
