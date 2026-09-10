"""导出目标选择：支持多对象 / 整个文档。

背景：export_step / export_stl 原先只接受单个 target，多零件模型必须先 fuse
成整机才能导出 —— 这正是装配阶段被迫布尔、进而删源件的根源。现在允许
target="" 导出全部，或 target=["A","B"] 导出多个（内部组合为 compound）。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "freecad_addon"))

from AICADAgent.export_selection import select_export_names  # noqa: E402

DOC = [
    ("Origin", "App::Origin", True),
    ("XY_Plane", "App::Plane", True),
    ("Leg_L", "Part::Box", True),
    ("Torso", "Part::Box", True),
    ("Mecha", "Part::Feature", True),
]


def test_empty_target_selects_whole_document():
    assert select_export_names("", DOC) == ["Leg_L", "Torso", "Mecha"]


def test_none_target_selects_whole_document():
    assert select_export_names(None, DOC) == ["Leg_L", "Torso", "Mecha"]


def test_single_name():
    assert select_export_names("Torso", DOC) == ["Torso"]


def test_multiple_names():
    assert select_export_names(["Leg_L", "Torso"], DOC) == ["Leg_L", "Torso"]


def test_skips_origin_and_datum_objects():
    names = select_export_names("", DOC)
    assert "Origin" not in names
    assert "XY_Plane" not in names


def test_whole_document_excludes_hidden_sources():
    """hole/fillet 会把原参数件 Visibility=False；整文档导出不得带上它们。"""
    doc = DOC + [("Torso_src", "Part::Box", False)]
    assert select_export_names("", doc) == ["Leg_L", "Torso", "Mecha"]


def test_explicit_target_may_be_hidden():
    """显式点名就是「我就要这个」，隐藏也放行。"""
    doc = DOC + [("Torso_src", "Part::Box", False)]
    assert select_export_names("Torso_src", doc) == ["Torso_src"]


def test_all_hidden_raises_actionable_error():
    with pytest.raises(ValueError) as err:
        select_export_names("", [("A", "Part::Box", False)])
    assert "可导出" in str(err.value)


def test_missing_object_error_lists_available_names():
    """错误必须可修复：说清缺哪个、有哪些可用（沿用 F7 的可修复化原则）。"""
    with pytest.raises(ValueError) as err:
        select_export_names(["Nope"], DOC)
    message = str(err.value)
    assert "Nope" in message
    assert "Torso" in message


def test_empty_document_raises_actionable_error():
    with pytest.raises(ValueError) as err:
        select_export_names("", [("Origin", "App::Origin", True)])
    assert "没有可导出" in str(err.value)


def test_duplicate_names_are_deduplicated_preserving_order():
    assert select_export_names(["Torso", "Torso", "Leg_L"], DOC) == ["Torso", "Leg_L"]
