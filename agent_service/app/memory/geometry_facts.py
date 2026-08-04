"""Normalize and judge CAD query geometry facts across tool result schemas."""

from __future__ import annotations

from typing import Any, Optional


def normalize_bbox(bbox: Any) -> Optional[dict]:
    """Accept document_state bbox or list_topology bbox; return size/center form."""
    if not isinstance(bbox, dict) or not bbox:
        return None

    if bbox.get("size") and bbox.get("center"):
        return {
            "xmin": bbox.get("xmin"),
            "xmax": bbox.get("xmax"),
            "ymin": bbox.get("ymin"),
            "ymax": bbox.get("ymax"),
            "zmin": bbox.get("zmin"),
            "zmax": bbox.get("zmax"),
            "size": list(bbox["size"]),
            "center": list(bbox["center"]),
        }

    # list_topology style: {"x":[min,max], "y":[...], "z":[...]}
    if all(k in bbox for k in ("x", "y", "z")):
        try:
            xmin, xmax = float(bbox["x"][0]), float(bbox["x"][1])
            ymin, ymax = float(bbox["y"][0]), float(bbox["y"][1])
            zmin, zmax = float(bbox["z"][0]), float(bbox["z"][1])
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        size = [xmax - xmin, ymax - ymin, zmax - zmin]
        center = [(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2]
        return {
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "zmin": zmin,
            "zmax": zmax,
            "size": size,
            "center": center,
        }

    # min/max fields without size/center
    keys = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
    if all(k in bbox for k in keys):
        try:
            xmin, xmax = float(bbox["xmin"]), float(bbox["xmax"])
            ymin, ymax = float(bbox["ymin"]), float(bbox["ymax"])
            zmin, zmax = float(bbox["zmin"]), float(bbox["zmax"])
        except (TypeError, ValueError):
            return None
        return {
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "zmin": zmin,
            "zmax": zmax,
            "size": [xmax - xmin, ymax - ymin, zmax - zmin],
            "center": [(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2],
        }
    return None


def extract_spatial_facts(query_result: dict | None) -> dict:
    """Pull usable size/center/volume from a query_result of any tool."""
    if not isinstance(query_result, dict):
        return {}
    facts: dict[str, Any] = {}
    bbox = normalize_bbox(query_result.get("bbox"))
    if bbox:
        facts["bbox"] = bbox
        facts["size"] = bbox["size"]
        facts["center"] = bbox["center"]

    # summarize_document nested object
    for obj in query_result.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        nested = normalize_bbox(obj.get("bbox"))
        if nested:
            facts.setdefault("bbox", nested)
            facts.setdefault("size", nested["size"])
            facts.setdefault("center", nested["center"])
            break
        if obj.get("size") and obj.get("center"):
            facts.setdefault("size", obj["size"])
            facts.setdefault("center", obj["center"])
            break

    topo = query_result.get("topology") or {}
    if isinstance(topo, dict):
        if topo.get("volume") is not None:
            facts["volume"] = topo.get("volume")
        if topo.get("solids") is not None:
            facts["solids"] = topo.get("solids")

    if query_result.get("volume") is not None:
        facts.setdefault("volume", query_result.get("volume"))
    return facts


def has_spatial_facts(query_result: dict | None = None, cache_entry: dict | None = None) -> bool:
    """True only when the query gives actionable placement facts (size/center)."""
    if cache_entry:
        if cache_entry.get("has_spatial_facts") is True:
            return True
        if cache_entry.get("size") and cache_entry.get("center"):
            return True
        facts = extract_spatial_facts(cache_entry.get("query_result"))
        if facts.get("size") and facts.get("center"):
            return True
        summary = str(cache_entry.get("summary") or "")
        if "size=" in summary and "center=" in summary:
            return True
    facts = extract_spatial_facts(query_result)
    return bool(facts.get("size") and facts.get("center"))


_QUERY_TOOLS = {
    "summarize_document",
    "get_object_detail",
    "measure_gap",
    "compare_orientation",
    "list_topology",
}


def query_cache_covers_target(session_memory: dict, target: str) -> bool:
    """缓存命中且含可用空间事实时才算覆盖。"""
    target = (target or "").strip()
    if not target or not session_memory:
        return False
    query_cache = session_memory.get("query_cache") or {}
    entry = query_cache.get(target)
    if entry and has_spatial_facts(cache_entry=entry):
        return True
    full_cache = session_memory.get("_query_cache_full") or {}
    entry = full_cache.get(target)
    return bool(entry and has_spatial_facts(cache_entry=entry))


def recent_query_covers_target(execution_history: dict, target: str) -> bool:
    """最近执行历史里是否已有针对 target 且含空间事实的 query。"""
    target = (target or "").strip()
    for entry in (execution_history or {}).get("recent", [])[-8:]:
        tool = entry.get("tool", "")
        if entry.get("kind") != "query" and tool not in _QUERY_TOOLS:
            continue
        query_result = entry.get("query_result") or {}
        matched = False
        if entry.get("query_target") == target:
            matched = True
        if target in (entry.get("query_targets") or []):
            matched = True
        if query_result.get("name") == target:
            matched = True
        objects = query_result.get("objects") or []
        if any(obj.get("name") == target for obj in objects if isinstance(obj, dict)):
            matched = True
        if matched and has_spatial_facts(query_result=query_result):
            return True
    return False


def summarize_query_result(query_result: dict | None) -> str:
    if not query_result:
        return ""
    if query_result.get("summary"):
        return str(query_result["summary"])

    parts: list[str] = []
    if query_result.get("name"):
        parts.append(f"name={query_result['name']}")
    if query_result.get("type"):
        parts.append(f"type={query_result['type']}")

    facts = extract_spatial_facts(query_result)
    if facts.get("size"):
        parts.append(f"size={facts['size']}")
    if facts.get("center"):
        parts.append(f"center={facts['center']}")
    if facts.get("volume") is not None:
        parts.append(f"volume={facts['volume']}")
    if facts.get("solids") is not None:
        parts.append(f"solids={facts['solids']}")

    placement = query_result.get("placement") or {}
    if isinstance(placement, dict) and placement.get("base"):
        parts.append(f"pos={placement['base']}")

    if query_result.get("face_count") is not None:
        parts.append(f"faces={query_result['face_count']}")
    if query_result.get("edge_count") is not None:
        parts.append(f"edges={query_result['edge_count']}")

    if query_result.get("gap") is not None:
        parts.append(f"gap={query_result['gap']}")
    orientation = query_result.get("orientation") or query_result.get("axis")
    if orientation:
        parts.append(f"orientation={orientation}")

    objects = query_result.get("objects") or []
    if objects:
        names = [obj.get("name") for obj in objects if isinstance(obj, dict) and obj.get("name")]
        if names:
            parts.append(f"objects={', '.join(names[:8])}")
        # include first object with spatial facts
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            nested = extract_spatial_facts(obj)
            if nested.get("size"):
                parts.append(f"{obj.get('name')}.size={nested['size']}")
                if nested.get("center"):
                    parts.append(f"{obj.get('name')}.center={nested['center']}")
                break

    if query_result.get("message"):
        parts.append(str(query_result["message"]))

    if not facts.get("size"):
        parts.append("spatial_facts=incomplete")

    return "; ".join(parts) or "query ok"
