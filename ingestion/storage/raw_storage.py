from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


class RawStorage:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    @staticmethod
    def _stamp(value: datetime | None = None) -> datetime:
        return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def write_payload(self, source: str, run_id: str, payload: Any, timestamp: datetime | None = None) -> Path:
        stamp = self._stamp(timestamp)
        directory = self.root / source / stamp.strftime("%Y") / stamp.strftime("%m")
        directory.mkdir(parents=True, exist_ok=True)
        safe_run = re.sub(r"[^A-Za-z0-9_-]", "_", run_id)
        path = directory / f"{source}_{stamp.strftime('%Y%m%dT%H%M%S%fZ')}_{safe_run}.json"
        self._write_exclusive(path, payload)
        return path

    def write_normalized(self, source: str, run_id: str, records: list[dict[str, Any]], timestamp: datetime | None = None) -> Path:
        stamp = self._stamp(timestamp)
        directory = self.root.parent / "processed" / source / stamp.strftime("%Y") / stamp.strftime("%m")
        directory.mkdir(parents=True, exist_ok=True)
        safe_run = re.sub(r"[^A-Za-z0-9_-]", "_", run_id)
        path = directory / f"{source}_{stamp.strftime('%Y%m%dT%H%M%S%fZ')}_{safe_run}.json"
        self._write_exclusive(path, records)
        return path

    def write_manifest(self, run_id: str, manifest: dict[str, Any], timestamp: datetime | None = None) -> Path:
        stamp = self._stamp(timestamp)
        directory = self.root / "manifests" / stamp.strftime("%Y") / stamp.strftime("%m")
        directory.mkdir(parents=True, exist_ok=True)
        safe_run = re.sub(r"[^A-Za-z0-9_-]", "_", run_id)
        path = directory / f"ingestion_{safe_run}.json"
        self._write_exclusive(path, manifest)
        return path

    @staticmethod
    def _write_exclusive(path: Path, value: Any) -> None:
        with path.open("x", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2, default=RawStorage._json_default)
            file.write("\n")

    @staticmethod
    def _json_default(value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        raise TypeError(f"Cannot serialize {type(value).__name__}")
