import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4


class AuditLogger:
    """Append-only JSONL audit log for agent decisions and tool activity."""

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.session_id = uuid4().hex[:12]
        self.events: List[Dict[str, Any]] = []
        self.path: Optional[Path] = None
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
            self.path = directory / (self.session_id + ".jsonl")

    def record(self, event: str, **fields: Any) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": event,
        }
        item.update(fields)
        self.events.append(item)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, sort_keys=True, default=str) + "\n")
        return item
