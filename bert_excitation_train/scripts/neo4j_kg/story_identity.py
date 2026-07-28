"""Stable story-instance identifiers used to isolate memory and graph data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


DEFAULT_STORY_ID = "default"


def story_id_for_clusters(path: Path) -> str:
    """Derive an opaque ID from the exact planning input for one story."""
    path = Path(path)
    try:
        payload = path.read_bytes()
        try:
            parsed = json.loads(payload.decode("utf-8"))
            payload = json.dumps(
                parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    except OSError:
        payload = str(path.resolve()).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
