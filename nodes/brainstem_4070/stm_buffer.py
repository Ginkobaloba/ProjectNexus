# nodes/brainstem_4070/stm_buffer.py
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from .config import settings


@dataclass
class STMItem:
    id: str
    text: str
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


class STMBuffer:
    """
    Simple short-term memory ring buffer.
    New items overwrite the oldest when full.
    """

    def __init__(self, max_items: Optional[int] = None) -> None:
        self.max_items = max_items or settings.max_stm_items
        self._buffer: Deque[STMItem] = deque(maxlen=self.max_items)

    def add(self, item: STMItem) -> None:
        self._buffer.append(item)

    def list(self) -> List[STMItem]:
        return list(self._buffer)

    def __len__(self) -> int:
        return len(self._buffer)


stm_buffer = STMBuffer()
