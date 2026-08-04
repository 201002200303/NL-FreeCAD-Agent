"""Tests for spatial-fact normalization and query coverage."""

from app.memory.geometry_facts import (
    extract_spatial_facts,
    has_spatial_facts,
    normalize_bbox,
    query_cache_covers_target,
    recent_query_covers_target,
    summarize_query_result,
)


def test_normalize_topology_bbox():
    bbox = normalize_bbox({"x": [-60, 60], "y": [-32, 32], "z": [0, 38]})
    assert bbox is not None
    assert bbox["size"] == [120, 64, 38]
    assert bbox["center"] == [0, 0, 19]


def test_summarize_includes_size_from_topology_bbox():
    summary = summarize_query_result(
        {
            "name": "MouseBody",
            "type": "Part::Feature",
            "bbox": {"x": [-59.958, 59.96], "y": [-32.497, 32.497], "z": [0.0, 38.0]},
            "face_count": 3,
        }
    )
    assert "size=" in summary
    assert "center=" in summary
    assert "spatial_facts=incomplete" not in summary


def test_incomplete_get_object_detail_marked():
    summary = summarize_query_result(
        {
            "name": "MouseBody",
            "type": "Part::Feature",
            "bbox": None,
            "placement": {"base": [0, 0, 0]},
            "topology": {"solids": 1, "volume": 179543.8},
        }
    )
    assert "spatial_facts=incomplete" in summary
    assert "volume=" in summary
    assert not has_spatial_facts(
        query_result={
            "name": "MouseBody",
            "bbox": None,
            "topology": {"solids": 1, "volume": 179543.8},
        }
    )


def test_query_cache_requires_spatial_facts():
    memory = {
        "query_cache": {
            "MouseBody": {
                "tool": "get_object_detail",
                "summary": "name=MouseBody; type=Part::Feature; pos=[0,0,0]; spatial_facts=incomplete",
                "has_spatial_facts": False,
            }
        }
    }
    assert not query_cache_covers_target(memory, "MouseBody")

    memory["query_cache"]["MouseBody"] = {
        "tool": "list_topology",
        "summary": "name=MouseBody; size=[120, 64, 38]; center=[0, 0, 19]",
        "has_spatial_facts": True,
        "size": [120, 64, 38],
        "center": [0, 0, 19],
    }
    assert query_cache_covers_target(memory, "MouseBody")


def test_recent_query_covers_only_with_bbox():
    history = {
        "recent": [
            {
                "kind": "query",
                "tool": "get_object_detail",
                "query_target": "MouseBody",
                "query_result": {
                    "name": "MouseBody",
                    "bbox": None,
                    "topology": {"volume": 1},
                },
            }
        ]
    }
    assert not recent_query_covers_target(history, "MouseBody")

    history["recent"].append(
        {
            "kind": "query",
            "tool": "list_topology",
            "query_target": "MouseBody",
            "query_result": {
                "name": "MouseBody",
                "bbox": {"x": [-60, 60], "y": [-32, 32], "z": [0, 38]},
            },
        }
    )
    assert recent_query_covers_target(history, "MouseBody")


def test_extract_spatial_facts_from_document_bbox():
    facts = extract_spatial_facts(
        {
            "bbox": {
                "xmin": -1,
                "xmax": 1,
                "ymin": -2,
                "ymax": 2,
                "zmin": 0,
                "zmax": 4,
                "size": [2, 4, 4],
                "center": [0, 0, 2],
            }
        }
    )
    assert facts["size"] == [2, 4, 4]
    assert facts["center"] == [0, 0, 2]
