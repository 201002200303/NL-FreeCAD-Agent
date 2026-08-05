"""execute_cad_program 运行时核心。

不 import FreeCAD；通过传入的 registry 调用具体工具 handler，便于服务端单测。
客户端以真实 TOOL_REGISTRY 调用本模块。

cad.* 使用简化签名（size/center/位置参数），在此映射到现有 TOOL_REGISTRY 参数。
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Callable, Optional

from AICADAgent.cad_program.validate import validate_cad_source

# cad.<api> → registry 中的工具名
_CAD_TO_TOOL = {
    "box": "create_box",
    "cylinder": "create_cylinder",
    "sphere": "create_sphere",
    "cone": "create_cone",
    "torus": "create_torus",
    "cut": "boolean_cut",
    "fuse": "boolean_fuse",
    "common": "boolean_common",
    "move": "move",
    "rotate": "rotate",
    "scale": "scale",
    "copy": "copy_object",
    "linear_pattern": "linear_pattern",
    "polar_pattern": "polar_pattern",
    "delete": "delete_object",
    "set_property": "modify_param",
    "fillet": "add_fillet",
    "chamfer": "add_chamfer",
    "hole": "cut_hole",
    "export_step": "export_step",
    "export_stl": "export_stl",
    "save": "save_fcstd",
}

_SAFE_BUILTINS = {
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "list": list,
    "tuple": tuple,
    "dict": dict,
    "set": set,
}

_SAFE_MATH = {name: getattr(math, name) for name in dir(math) if not name.startswith("_")}

_BOOL_COUNTER = {"fuse": 0, "cut": 0, "common": 0}


def _as_xyz(value: Any, *, label: str) -> tuple[float, float, float]:
    if value is None:
        return (0.0, 0.0, 0.0)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    raise TypeError(f"{label} must be (x,y,z), got {value!r}")


def _axis_to_name(axis: Any) -> str:
    if isinstance(axis, str) and axis.strip():
        return axis.strip().upper()[:1] or "Z"
    if isinstance(axis, (list, tuple)) and len(axis) >= 3:
        ax, ay, az = abs(float(axis[0])), abs(float(axis[1])), abs(float(axis[2]))
        if az >= ax and az >= ay:
            return "Z"
        if ay >= ax:
            return "Y"
        return "X"
    return "Z"


def _normalize_cad_args(api_name: str, args: tuple, kwargs: dict) -> dict:
    """把 cad.* 简化参数映射到 TOOL_REGISTRY handler 参数。"""
    kw = dict(kwargs)

    if api_name == "box":
        size = kw.pop("size", None)
        if size is not None:
            sx, sy, sz = _as_xyz(size, label="size")
            kw.setdefault("length", sx)
            kw.setdefault("width", sy)
            kw.setdefault("height", sz)
        center = kw.pop("center", None)
        if center is not None:
            cx, cy, cz = _as_xyz(center, label="center")
            kw.setdefault("pos_x", cx)
            kw.setdefault("pos_y", cy)
            kw.setdefault("pos_z", cz)
            kw.setdefault("anchor", "center")
        return kw

    if api_name == "cylinder":
        center = kw.pop("center", None)
        height = float(kw.get("height", 0) or 0)
        if center is not None:
            cx, cy, cz = _as_xyz(center, label="center")
            # FreeCAD 圆柱 pos 是底面中心；cad.center 按几何中心解释
            kw.setdefault("pos_x", cx)
            kw.setdefault("pos_y", cy)
            kw.setdefault("pos_z", cz - height / 2.0 if height else cz)
        return kw

    if api_name == "sphere":
        center = kw.pop("center", None)
        if center is not None:
            cx, cy, cz = _as_xyz(center, label="center")
            kw.setdefault("pos_x", cx)
            kw.setdefault("pos_y", cy)
            kw.setdefault("pos_z", cz)
        return kw

    if api_name in ("fuse", "cut", "common"):
        # cad.fuse(a, b) / cad.cut(base=a, tool=b)
        if len(args) >= 1 and "base" not in kw:
            kw["base"] = args[0]
        if len(args) >= 2 and "tool" not in kw:
            kw["tool"] = args[1]
        if "name" not in kw:
            _BOOL_COUNTER[api_name] = _BOOL_COUNTER.get(api_name, 0) + 1
            kw["name"] = f"{api_name.title()}{_BOOL_COUNTER[api_name]}"
        return kw

    if api_name == "rotate":
        if len(args) >= 1 and "target" not in kw:
            kw["target"] = args[0]
        if "axis" in kw:
            kw["axis"] = _axis_to_name(kw["axis"])
        pivot = kw.pop("pivot", None) or kw.pop("origin", None)
        if pivot is not None:
            ox, oy, oz = _as_xyz(pivot, label="pivot")
            kw.setdefault("origin_x", ox)
            kw.setdefault("origin_y", oy)
            kw.setdefault("origin_z", oz)
        return kw

    if api_name == "move":
        if len(args) >= 1 and "target" not in kw:
            kw["target"] = args[0]
        offset = kw.pop("offset", None)
        if offset is not None:
            dx, dy, dz = _as_xyz(offset, label="offset")
            kw.setdefault("dx", dx)
            kw.setdefault("dy", dy)
            kw.setdefault("dz", dz)
        return kw

    if api_name == "polar_pattern":
        # cad.polar_pattern(tooth, count=12, fuse=True, fuse_name="ToothRing")
        if len(args) >= 1 and "target" not in kw:
            kw["target"] = args[0]
        if "axis" in kw:
            kw["axis"] = _axis_to_name(kw["axis"])
        center = kw.pop("center", None) or kw.pop("pivot", None) or kw.pop("origin", None)
        if center is not None:
            ox, oy, oz = _as_xyz(center, label="center")
            kw.setdefault("origin_x", ox)
            kw.setdefault("origin_y", oy)
            kw.setdefault("origin_z", oz)
        return kw

    if api_name == "linear_pattern":
        # cad.linear_pattern(bar, count=4, offset=(12,0,0), fuse=True, fuse_name="BarRow")
        if len(args) >= 1 and "target" not in kw:
            kw["target"] = args[0]
        offset = kw.pop("offset", None) or kw.pop("spacing", None)
        if offset is not None:
            dx, dy, dz = _as_xyz(offset, label="offset")
            kw.setdefault("dx", dx)
            kw.setdefault("dy", dy)
            kw.setdefault("dz", dz)
        return kw

    # 其它 API：若有单个位置参数且无 target，当作 target
    if args and "target" not in kw and api_name in (
        "delete", "scale", "copy", "fillet", "chamfer", "hole", "set_property"
    ):
        kw["target"] = args[0]
    return kw


class _CadRuntime:
    """暴露给受限代码的 cad 对象；cad.xxx → registry 调用。"""

    def __init__(self, doc: Any, registry: dict[str, Callable], created: list[str]):
        self._doc = doc
        self._registry = registry
        self._created = created

    def __getattr__(self, api_name: str) -> Callable:
        tool_name = _CAD_TO_TOOL.get(api_name)
        if tool_name is None:
            raise AttributeError(f"cad.{api_name} not available")
        handler = self._registry.get(tool_name)
        if handler is None:
            raise RuntimeError(f"tool not registered: {tool_name}")

        def _call(*args, **kwargs):
            mapped = _normalize_cad_args(api_name, args, kwargs)
            result = handler(self._doc, **mapped) or {}
            produced = result.get("object") or result.get("name")
            if produced:
                self._created.append(produced)
            for extra in result.get("created") or []:
                if extra and extra not in self._created:
                    self._created.append(extra)
            return produced or result

        return _call


def run_cad_program(
    code: str,
    *,
    doc: Any,
    registry: dict[str, Callable],
    transaction: Optional[str] = None,
) -> dict:
    """校验并执行受限 CAD 程序；返回紧凑结果。

    第一版不直接操作 FreeCAD 事务；由调用方（客户端）负责 open/commit/abort。
    """
    verdict = validate_cad_source(code)
    if not verdict.ok:
        kind = (verdict.violations[0]["kind"] if verdict.violations else "validation_error")
        return {
            "success": False,
            "error_type": kind,
            "error_message": "; ".join(
                f"{v.get('detail','')}".strip() or v["kind"] for v in verdict.violations[:5]
            ),
            "violations": verdict.violations[:20],
            "created": [],
            "transaction": transaction or f"txn_{uuid.uuid4().hex[:8]}",
        }

    # 每次执行重置布尔命名计数，避免跨调用污染
    for k in list(_BOOL_COUNTER.keys()):
        _BOOL_COUNTER[k] = 0

    created: list[str] = []
    runtime = _CadRuntime(doc, registry, created)
    sandbox_globals = {
        "__builtins__": _SAFE_BUILTINS,
        "cad": runtime,
        "math": _SAFE_MATH,
    }

    txn = transaction or f"txn_{uuid.uuid4().hex[:8]}"
    try:
        exec(compile(code, "<cad_program>", "exec"), sandbox_globals, {})
    except Exception as exc:  # noqa: BLE001 - 须转成结构化错误
        failed_line = None
        tb = exc.__traceback__
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == "<cad_program>":
                failed_line = tb.tb_lineno
            tb = tb.tb_next
        return {
            "success": False,
            "error_type": "tool_error" if isinstance(exc, RuntimeError) else "runtime_error",
            "error_message": str(exc),
            "failed_line": failed_line,
            "created": created,
            "transaction": txn,
        }

    return {
        "success": True,
        "created": created,
        "transaction": txn,
        "checks": {"cad_calls": len(created)},
    }
