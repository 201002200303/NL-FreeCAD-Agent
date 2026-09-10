"""Pure Program Receipt helpers; no FreeCAD imports."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional


def normalize_program(code: str) -> str:
    lines = str(code or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def program_hash(code: str) -> str:
    return hashlib.sha256(normalize_program(code).encode("utf-8")).hexdigest()


def _compact_object(obj: dict) -> dict:
    bbox = obj.get("bbox") or {}
    placement = obj.get("placement") or {}
    topology = obj.get("topology") or {}
    return {
        "name": obj.get("name"),
        "type": obj.get("type"),
        "visible": obj.get("visible"),
        "size": bbox.get("size") if isinstance(bbox, dict) else None,
        "center": bbox.get("center") if isinstance(bbox, dict) else None,
        "pos": placement.get("base") if isinstance(placement, dict) else None,
        "valid": topology.get("is_valid") if isinstance(topology, dict) else None,
        "solids": topology.get("solids") if isinstance(topology, dict) else None,
    }


def compact_document(document_state: Optional[dict]) -> list[dict]:
    values = [
        _compact_object(obj)
        for obj in ((document_state or {}).get("objects") or [])
        if isinstance(obj, dict) and obj.get("name")
    ]
    return sorted(values, key=lambda item: str(item.get("name")))


def document_fingerprint(document_state: Optional[dict]) -> str:
    payload = json.dumps(compact_document(document_state), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def diff_documents(before: Optional[dict], after: Optional[dict]) -> dict:
    b = {item["name"]: item for item in compact_document(before)}
    a = {item["name"]: item for item in compact_document(after)}
    added = sorted(name for name in a if name not in b)
    removed = sorted(name for name in b if name not in a)
    modified = []
    for name in sorted(set(a) & set(b)):
        changes = [key for key in ("type", "visible", "size", "center", "pos", "valid", "solids") if a[name].get(key) != b[name].get(key)]
        if changes:
            modified.append({"name": name, "changes": changes})
    parts = []
    if added:
        parts.append("新增 " + ", ".join(added[:8]))
    if removed:
        parts.append("删除 " + ", ".join(removed[:8]))
    if modified:
        parts.append("修改 " + ", ".join(item["name"] for item in modified[:8]))
    return {
        "changed": bool(added or removed or modified),
        "added": added,
        "removed": removed,
        "modified": modified,
        "summary": "；".join(parts) if parts else "无变化",
    }


def decide_replay(cached: Optional[dict], incoming_hash: str, current_state: Optional[dict]) -> str:
    """Return skip, execute, conflict, stale, or miss."""
    if not cached:
        return "miss"
    if cached.get("program_hash") != incoming_hash:
        return "conflict"
    current = document_fingerprint(current_state)
    if current == cached.get("after_fingerprint"):
        return "skip"
    if current == cached.get("before_fingerprint"):
        return "execute"
    return "stale"

