"""execute_cad_program 运行时核心。

不 import FreeCAD；通过传入的 registry 调用具体工具 handler，便于服务端单测。
客户端以真实 TOOL_REGISTRY 调用本模块。

cad.* 使用简化签名（size/center/位置参数），在此映射到现有 TOOL_REGISTRY 参数。
"""

from __future__ import annotations

import math
import time
from types import SimpleNamespace
import uuid
from typing import Any, Callable, Optional

from AICADAgent.cad_program.validate import validate_cad_source
from AICADAgent.cad_program.manifest import CAD_TO_TOOL

# cad.<api> → registry 中的工具名
_CAD_TO_TOOL = CAD_TO_TOOL

MAX_EXPANDED_OPS = 500
MAX_LOOP_ITERATIONS = 2000
MAX_BOOLEAN_OPS = 200
MAX_EXECUTION_SECONDS = 60.0


def _safe_range(*args):
    value = range(*args)
    if len(value) > MAX_LOOP_ITERATIONS:
        raise RuntimeError(
            f"range expands to {len(value)} iterations; limit is {MAX_LOOP_ITERATIONS}"
        )
    return value

_SAFE_BUILTINS = {
    "len": len,
    "range": _safe_range,
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

_SAFE_MATH = SimpleNamespace(
    **{
        name: getattr(math, name)
        for name in (
            "pi", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
            "sqrt", "ceil", "floor", "fabs", "radians", "degrees",
        )
    }
)

_BOOL_COUNTER = {"fuse": 0, "cut": 0, "common": 0}

# 创建类 API：同名已存在时先删再建，避免 FreeCAD 自动改名成 Name001 叠影
_CREATE_APIS = frozenset({
    "box", "cylinder", "sphere", "cone", "torus",
    "fuse", "cut", "common",
    "sketch", "extrude", "pad", "pocket", "revolve", "loft",
})

# 草图几何：首参常为 sketch 名
_SKETCH_GEO_APIS = frozenset({
    "line", "rect", "circle", "arc", "polyline", "bspline", "constraint",
})


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


def _rotate_fixed_axes(
    vx: float, vy: float, vz: float, *, rot_x: float = 0, rot_y: float = 0, rot_z: float = 0
) -> tuple[float, float, float]:
    """Rotate a vector with the same composition as apply_placement (Rx*Ry*Rz, degrees)."""
    # Placement 旋转合成 R=Rx*Ry*Rz ⇒ 作用到向量时先 Rz 再 Ry 再 Rx（与 _helpers.apply_axis_rotation 一致）
    x, y, z = float(vx), float(vy), float(vz)
    for axis, angle in (("z", rot_z), ("y", rot_y), ("x", rot_x)):
        rad = math.radians(float(angle or 0))
        if abs(rad) < 1e-15:
            continue
        c, s = math.cos(rad), math.sin(rad)
        if axis == "x":
            y, z = y * c - z * s, y * s + z * c
        elif axis == "y":
            x, z = x * c + z * s, -x * s + z * c
        else:
            x, y = x * c - y * s, x * s + y * c
    return (x, y, z)


def _axis_body_base_from_center(
    center: tuple[float, float, float],
    height: float,
    *,
    rot_x: float = 0,
    rot_y: float = 0,
    rot_z: float = 0,
) -> tuple[float, float, float]:
    """Map geometric center → FreeCAD bottom-face Base after rot_*.

    Local mid-height is (0,0,h/2). World center = R*(0,0,h/2) + Base, so
    Base = center - R*(0,0,h/2). Plain Z-only offset breaks once rot_y/x ≠ 0.
    """
    cx, cy, cz = center
    if abs(float(height or 0)) < 1e-15:
        return (cx, cy, cz)
    ox, oy, oz = _rotate_fixed_axes(0.0, 0.0, float(height) / 2.0, rot_x=rot_x, rot_y=rot_y, rot_z=rot_z)
    return (cx - ox, cy - oy, cz - oz)


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

    if api_name in ("cylinder", "cone"):
        center = kw.pop("center", None)
        height = float(kw.get("height", 0) or 0)
        if center is not None:
            cx, cy, cz = _as_xyz(center, label="center")
            # FreeCAD pos = 底面圆心；cad.center = 几何中心（须在 rot_* 之后仍成立）
            bx, by, bz = _axis_body_base_from_center(
                (cx, cy, cz),
                height,
                rot_x=float(kw.get("rot_x", 0) or 0),
                rot_y=float(kw.get("rot_y", 0) or 0),
                rot_z=float(kw.get("rot_z", 0) or 0),
            )
            kw.setdefault("pos_x", bx)
            kw.setdefault("pos_y", by)
            kw.setdefault("pos_z", bz)
        return kw

    if api_name in ("sphere", "torus"):
        center = kw.pop("center", None)
        if center is not None:
            cx, cy, cz = _as_xyz(center, label="center")
            kw.setdefault("pos_x", cx)
            kw.setdefault("pos_y", cy)
            kw.setdefault("pos_z", cz)
        return kw

    if api_name in ("fuse", "cut", "common"):
        # cad.fuse(a, b[, c…]) / cad.fuse([a, b, c]) / cad.cut(base=a, tool=b)
        operands: list[str] = []
        rest = list(args)
        if rest and isinstance(rest[0], (list, tuple)):
            operands.extend(str(x) for x in rest.pop(0))
        else:
            operands.extend(str(x) for x in rest)
        for key in ("base", "tool", "targets", "objects", "parts"):
            value = kw.pop(key, None)
            if isinstance(value, (list, tuple)):
                operands.extend(str(x) for x in value)
            elif value is not None:
                operands.append(str(value))
        if "name" not in kw:
            _BOOL_COUNTER[api_name] = _BOOL_COUNTER.get(api_name, 0) + 1
            kw["name"] = f"{api_name.title()}{_BOOL_COUNTER[api_name]}"
        kw["_operands"] = [name for name in operands if name]
        return kw

    if api_name == "rotate":
        if len(args) >= 1 and "target" not in kw:
            kw["target"] = args[0]
        if "axis" in kw:
            kw["axis"] = _axis_to_name(kw["axis"])
        # center / pivot / origin 都表示绕点公转中心
        pivot = kw.pop("pivot", None) or kw.pop("origin", None) or kw.pop("center", None)
        if pivot is not None:
            ox, oy, oz = _as_xyz(pivot, label="pivot")
            kw.setdefault("origin_x", ox)
            kw.setdefault("origin_y", oy)
            kw.setdefault("origin_z", oz)
        return kw

    if api_name == "move":
        # cad.move(obj, dx, dy, dz) | offset=(…) | dx/dy/dz= | 兼容误写 x/y/z=
        if len(args) >= 1 and "target" not in kw:
            kw["target"] = args[0]
        if len(args) >= 4:
            kw.setdefault("dx", float(args[1]))
            kw.setdefault("dy", float(args[2]))
            kw.setdefault("dz", float(args[3]))
        elif len(args) == 2 and isinstance(args[1], (list, tuple)) and len(args[1]) >= 3:
            kw.setdefault("dx", float(args[1][0]))
            kw.setdefault("dy", float(args[1][1]))
            kw.setdefault("dz", float(args[1][2]))
        offset = kw.pop("offset", None)
        if offset is not None:
            dx, dy, dz = _as_xyz(offset, label="offset")
            kw.setdefault("dx", dx)
            kw.setdefault("dy", dy)
            kw.setdefault("dz", dz)
        # 模型常写 x/y/z=，语义仍是相对平移（不是绝对坐标）
        if "x" in kw and "dx" not in kw:
            kw["dx"] = float(kw.pop("x"))
        else:
            kw.pop("x", None)
        if "y" in kw and "dy" not in kw:
            kw["dy"] = float(kw.pop("y"))
        else:
            kw.pop("y", None)
        if "z" in kw and "dz" not in kw:
            kw["dz"] = float(kw.pop("z"))
        else:
            kw.pop("z", None)
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

    if api_name == "line":
        # cad.line(sk, x1, y1, x2, y2) 或 cad.line(sk, p1=(x,y), p2=(x,y))
        if len(args) >= 1 and "sketch" not in kw:
            kw["sketch"] = args[0]
        if len(args) >= 5:
            kw.setdefault("x1", float(args[1]))
            kw.setdefault("y1", float(args[2]))
            kw.setdefault("x2", float(args[3]))
            kw.setdefault("y2", float(args[4]))
        for src, (xa, ya) in (("p1", ("x1", "y1")), ("p2", ("x2", "y2")),
                              ("start", ("x1", "y1")), ("end", ("x2", "y2"))):
            pt = kw.pop(src, None)
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                kw.setdefault(xa, float(pt[0]))
                kw.setdefault(ya, float(pt[1]))
        return kw

    if api_name == "rect":
        # cad.rect(sk, x, y, w, h) 角点；或 center=(cx,cy)+width/height
        if len(args) >= 1 and "sketch" not in kw:
            kw["sketch"] = args[0]
        if len(args) >= 5:
            kw.setdefault("x", float(args[1]))
            kw.setdefault("y", float(args[2]))
            kw.setdefault("width", float(args[3]))
            kw.setdefault("height", float(args[4]))
        center = kw.pop("center", None)
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            w = float(kw.get("width", 10))
            h = float(kw.get("height", 10))
            kw["x"] = float(center[0]) - w / 2.0
            kw["y"] = float(center[1]) - h / 2.0
        return kw

    if api_name == "circle":
        # cad.circle(sk, cx, cy, r) 或 center=(cx,cy), radius=r
        if len(args) >= 1 and "sketch" not in kw:
            kw["sketch"] = args[0]
        if len(args) >= 4:
            kw.setdefault("center_x", float(args[1]))
            kw.setdefault("center_y", float(args[2]))
            kw.setdefault("radius", float(args[3]))
        center = kw.pop("center", None)
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            kw.setdefault("center_x", float(center[0]))
            kw.setdefault("center_y", float(center[1]))
        return kw

    if api_name in _SKETCH_GEO_APIS:
        # cad.polyline(sk, points=..., closed=True) 等
        if len(args) >= 1 and "sketch" not in kw:
            kw["sketch"] = args[0]
        return kw

    if api_name in ("extrude", "pad", "pocket", "revolve"):
        if len(args) >= 1 and "sketch" not in kw:
            kw["sketch"] = args[0]
        # 模型常误传 center=；拉伸后应用 cad.move，此处丢弃以免 TypeError
        kw.pop("center", None)
        direction = kw.pop("direction", None)
        if direction is not None:
            dx, dy, dz = _as_xyz(direction, label="direction")
            kw.setdefault("direction_x", dx)
            kw.setdefault("direction_y", dy)
            kw.setdefault("direction_z", dz)
        return kw

    if api_name == "loft":
        if len(args) >= 1 and "profiles" not in kw:
            kw["profiles"] = args[0]
        return kw

    # 其它 API：若有单个位置参数且无 target，当作 target
    if args and "target" not in kw and api_name in (
        "delete", "scale", "copy", "fillet", "chamfer", "hole", "set_property"
    ):
        kw["target"] = args[0]
    return kw

def _soft_delete(doc: Any, registry: dict[str, Callable], name: str) -> bool:
    """删除已有对象；不存在则跳过。返回是否实际删除。"""
    target = str(name or "").strip()
    if not target:
        return False
    getter = getattr(doc, "getObject", None)
    if callable(getter) and getter(target) is None:
        return False
    handler = registry.get("delete_object")
    if handler is None:
        return False
    try:
        handler(doc, target=target)
        return True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "not found" in msg or "does not exist" in msg:
            return False
        raise


def _delete_targets(doc: Any, registry: dict[str, Callable], target: Any) -> list[str]:
    """cad.delete 支持单名或名字列表；缺失对象不报错。"""
    if isinstance(target, (list, tuple)):
        names = [str(x).strip() for x in target if str(x).strip()]
    else:
        names = [str(target).strip()] if str(target or "").strip() else []
    deleted: list[str] = []
    for name in names:
        if _soft_delete(doc, registry, name):
            deleted.append(name)
    return deleted


class _CadRuntime:
    """暴露给受限代码的 cad 对象；cad.xxx → registry 调用。"""

    def __init__(self, doc: Any, registry: dict[str, Callable], created: list[str]):
        self._doc = doc
        self._registry = registry
        self._created = created
        self.call_count = 0
        self.boolean_count = 0
        self.started_at = time.monotonic()

    def __getattr__(self, api_name: str) -> Callable:
        tool_name = _CAD_TO_TOOL.get(api_name)
        if tool_name is None:
            known = ", ".join(sorted(_CAD_TO_TOOL))
            raise AttributeError(
                f"cad.{api_name} not available (not in runtime map). "
                f"Known: {known}. If this API was just added, retry once; "
                "executor reloads cad_program each call."
            )
        handler = self._registry.get(tool_name)
        if handler is None:
            raise RuntimeError(f"tool not registered: {tool_name}")

        def _call(*args, **kwargs):
            self.call_count += 1
            if self.call_count > MAX_EXPANDED_OPS:
                raise RuntimeError(f"expanded CAD operation limit exceeded ({MAX_EXPANDED_OPS})")
            if time.monotonic() - self.started_at > MAX_EXECUTION_SECONDS:
                raise RuntimeError(f"CAD program time budget exceeded ({MAX_EXECUTION_SECONDS}s)")
            if api_name in ("cut", "fuse", "common"):
                self.boolean_count += 1
                if self.boolean_count > MAX_BOOLEAN_OPS:
                    raise RuntimeError(f"boolean operation limit exceeded ({MAX_BOOLEAN_OPS})")
            mapped = _normalize_cad_args(api_name, args, kwargs)

            if api_name == "delete":
                deleted = _delete_targets(self._doc, self._registry, mapped.get("target"))
                return {"deleted": deleted}

            # 同名覆盖：创建前先删掉已有对象，避免 Name001 幽灵叠影
            if api_name in _CREATE_APIS:
                existing = str(mapped.get("name") or "").strip()
                if existing:
                    _soft_delete(self._doc, self._registry, existing)

            # 草图→拉伸/放样前强制 recompute，否则同事务内 Shape 仍为空
            if api_name in ("extrude", "pad", "pocket", "revolve", "loft"):
                recompute = getattr(self._doc, "recompute", None)
                if callable(recompute):
                    try:
                        recompute()
                    except Exception:
                        pass

            if api_name in ("fuse", "cut", "common"):
                return self._run_boolean_chain(api_name, handler, mapped)

            result = handler(self._doc, **mapped) or {}
            produced = result.get("object") or result.get("name")
            if produced:
                self._created.append(produced)
            for extra in result.get("created") or []:
                if extra and extra not in self._created:
                    self._created.append(extra)
            return produced or result

        return _call

    def _run_boolean_chain(self, api_name: str, handler: Callable, mapped: dict) -> Any:
        """布尔 API 支持 N 个操作数：按顺序两两折叠，中间件用完即被下一次布尔删掉。"""
        operands = [str(name) for name in mapped.pop("_operands", [])]
        if len(operands) < 2:
            raise RuntimeError(
                f"cad.{api_name} 至少需要 2 个已存在对象名，收到 {operands!r}。"
                f'正确写法：cad.{api_name}("A", "B") 或 cad.{api_name}(["A", "B", "C"])'
            )
        name = str(mapped.get("name") or "").strip() or api_name.title()
        running = operands[0]
        result: Any = None
        for index, tool in enumerate(operands[1:]):
            is_last = index == len(operands) - 2
            call_name = name if is_last else f"{name}_tmp{index + 1}"
            if not is_last:
                _soft_delete(self._doc, self._registry, call_name)
            try:
                result = handler(self._doc, name=call_name, base=running, tool=tool) or {}
            except Exception as exc:  # noqa: BLE001 - 转成可修复提示
                raise RuntimeError(
                    f"cad.{api_name} 失败：base={running!r} tool={tool!r}: {exc}。"
                    f'请确认两个对象都已创建且名字正确，例如 cad.{api_name}("A", "B")'
                ) from exc
            produced = result.get("object") or result.get("name") or call_name
            if produced:
                self._created.append(produced)
            running = produced
        return running or result


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
        "checks": {
            "cad_calls": runtime.call_count,
            "created_objects": len(created),
            "boolean_ops": runtime.boolean_count,
        },
    }
