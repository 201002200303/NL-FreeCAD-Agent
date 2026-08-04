"""Structured diff between two document_state snapshots.

Used for:
- resume-after-pause: detect what the user changed manually
- crash recovery: decide whether a pending action already produced side effects
"""

from __future__ import annotations

from typing import Any, Optional

_POS_TOL = 1e-6
_SIZE_TOL = 1e-6


def compact_objects(document_state: Optional[dict], limit: int = 60) -> list[dict]:
    """Reduce a document_state to a small per-object fingerprint list."""
    objects = (document_state or {}).get("objects") or []
    compact: list[dict] = []
    for obj in objects[:limit]:
        if not isinstance(obj, dict):
            continue
        bbox = obj.get("bbox") or {}
        placement = obj.get("placement") or {}
        compact.append(
            {
                "name": obj.get("name"),
                "type": obj.get("type"),
                "visible": obj.get("visible"),
                "size": bbox.get("size") if isinstance(bbox, dict) else None,
                "center": bbox.get("center") if isinstance(bbox, dict) else None,
                "pos": placement.get("base") if isinstance(placement, dict) else None,
            }
        )
    return compact


def _vec_changed(a: Any, b: Any, tol: float) -> bool:
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    try:
        return any(abs(float(x) - float(y)) > tol for x, y in zip(a, b))
    except (TypeError, ValueError):
        return a != b


def diff_documents(
    before: Optional[dict | list],
    after: Optional[dict | list],
) -> dict:
    """Diff two snapshots (full document_state dicts or compact object lists).

    Returns {added, removed, modified, changed, summary} where modified entries
    carry which aspect changed (size / position / visibility).
    """
    before_objs = before if isinstance(before, list) else compact_objects(before)
    after_objs = after if isinstance(after, list) else compact_objects(after)

    before_map = {o.get("name"): o for o in before_objs if o.get("name")}
    after_map = {o.get("name"): o for o in after_objs if o.get("name")}

    added = [name for name in after_map if name not in before_map]
    removed = [name for name in before_map if name not in after_map]

    modified: list[dict] = []
    for name in after_map:
        if name not in before_map:
            continue
        b, a = before_map[name], after_map[name]
        changes: list[str] = []
        if _vec_changed(b.get("size"), a.get("size"), _SIZE_TOL):
            changes.append("size")
        if _vec_changed(b.get("center"), a.get("center"), _POS_TOL) or _vec_changed(
            b.get("pos"), a.get("pos"), _POS_TOL
        ):
            changes.append("position")
        if b.get("visible") != a.get("visible"):
            changes.append("visibility")
        if b.get("type") != a.get("type"):
            changes.append("type")
        if changes:
            modified.append(
                {
                    "name": name,
                    "changes": changes,
                    "before": {k: b.get(k) for k in ("size", "center", "pos", "visible")},
                    "after": {k: a.get(k) for k in ("size", "center", "pos", "visible")},
                }
            )

    changed = bool(added or removed or modified)
    parts: list[str] = []
    if added:
        parts.append(f"新增 {', '.join(added[:8])}")
    if removed:
        parts.append(f"删除 {', '.join(removed[:8])}")
    if modified:
        parts.append(
            "修改 "
            + ", ".join(f"{m['name']}({'/'.join(m['changes'])})" for m in modified[:8])
        )
    summary = "；".join(parts) if parts else "无变化"

    return {
        "changed": changed,
        "added": added,
        "removed": removed,
        "modified": modified,
        "summary": summary,
    }
