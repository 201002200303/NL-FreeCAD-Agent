"""execute_cad_program 源码静态校验（AST 白名单）。

目标：模型只填一段「只用 cad.* / 基础字面量 / 简单 for」的 Python。
不允许：import、属性逃逸、下划线、getattr/eval、函数/类定义、while 等。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

# cad.* 允许的方法名（薄包装现有 TOOL_REGISTRY；此处只校验名字存在）
CAD_API_METHODS = frozenset({
    "box", "cylinder", "sphere", "cone", "torus",
    "cut", "fuse", "common",
    "move", "rotate", "scale", "copy",
    "linear_pattern", "polar_pattern",
    "delete", "set_property", "get",
    "sketch", "pad", "pocket", "revolve", "extrude",
    "line", "rect", "circle", "arc", "polyline", "bspline", "constraint",
    "fillet", "chamfer", "hole",
    "export_step", "export_stl", "save",
    "document", "validate", "measure",
})

# 可选的 math 白名单
MATH_ATTRS = frozenset({
    "pi", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "sqrt", "ceil", "floor", "fabs", "radians", "degrees",
})

# 本地 list/dict 安全方法（允许 teeth.append / d.get）
_SAFE_COLLECTION_METHODS = frozenset({
    "append", "extend", "insert", "pop", "remove", "clear",
    "get", "keys", "values", "items", "update", "copy",
    "count", "index", "sort", "reverse",
})


MAX_NODES = 4000
MAX_FOR_LOOPS = 64
MAX_CAD_CALLS = 500

_ALLOWED_NODES = (
    ast.Module, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr,
    ast.Call, ast.Name, ast.Load, ast.Constant,
    ast.Tuple, ast.List, ast.Dict, ast.Set,
    ast.If, ast.For, ast.Compare, ast.BoolOp, ast.BinOp, ast.UnaryOp,
    ast.Subscript, ast.Slice, ast.Index,
    ast.JoinedStr, ast.FormattedValue,
    ast.Store, ast.comprehension, ast.ListComp, ast.GeneratorExp,
    ast.keyword, ast.Attribute,  # Attribute 另行白名单（cad.x / math.x）
    ast.Pass, ast.Break, ast.Continue,
    # operators / context / cmp (leaf nodes in CPython AST)
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv,
    ast.UAdd, ast.USub, ast.Not, ast.Invert,
    ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot,
    ast.In, ast.NotIn,
)

_FORBIDDEN_CALL_NAMES = {
    "eval", "exec", "compile", "open", "input", "getattr", "setattr",
    "globals", "locals", "vars", "dir", "__import__", "print", "breakpoint",
    "help", "exit", "quit", "iter", "next", "super", "type", "isinstance",
    "hasattr", "delattr", "memoryview", "bytearray", "bytes", "object",
}


@dataclass
class CadProgramVerdict:
    ok: bool
    violations: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def _violation(kind: str, node: ast.AST, detail: str = "") -> dict:
    return {
        "kind": kind,
        "line": getattr(node, "lineno", None),
        "col": getattr(node, "col_offset", None),
        "detail": detail,
    }


class _Validator(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[dict] = []
        self.for_count = 0
        self.cad_calls = 0
        self.node_count = 0

    def generic_visit(self, node: ast.AST) -> Any:
        self.node_count += 1
        if self.node_count > MAX_NODES:
            self.violations.append(_violation("resource_limit", node, "too many AST nodes"))
            return
        if not isinstance(node, _ALLOWED_NODES):
            self.violations.append(
                _violation("forbidden", node, type(node).__name__)
            )
            return
        super().generic_visit(node)

    # ---- statements -------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        self.violations.append(_violation("forbidden", node, "import"))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.violations.append(_violation("forbidden", node, "import-from"))

    def visit_While(self, node: ast.While) -> None:
        self.violations.append(_violation("forbidden", node, "while"))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.violations.append(_violation("forbidden", node, "def"))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.violations.append(_violation("forbidden", node, "async def"))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.violations.append(_violation("forbidden", node, "class"))

    def visit_With(self, node: ast.With) -> None:
        self.violations.append(_violation("forbidden", node, "with"))

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.violations.append(_violation("forbidden", node, "async with"))

    def visit_Try(self, node: ast.Try) -> None:
        self.violations.append(_violation("forbidden", node, "try"))

    def visit_Raise(self, node: ast.Raise) -> None:
        self.violations.append(_violation("forbidden", node, "raise"))

    def visit_Assert(self, node: ast.Assert) -> None:
        self.violations.append(_violation("forbidden", node, "assert"))

    def visit_Global(self, node: ast.Global) -> None:
        self.violations.append(_violation("forbidden", node, "global"))

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.violations.append(_violation("forbidden", node, "nonlocal"))

    def visit_Delete(self, node: ast.Delete) -> None:
        self.violations.append(_violation("forbidden", node, "delete"))

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.violations.append(_violation("forbidden", node, "lambda"))

    def visit_Yield(self, node: ast.Yield) -> None:
        self.violations.append(_violation("forbidden", node, "yield"))

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self.violations.append(_violation("forbidden", node, "yield-from"))

    def visit_Await(self, node: ast.Await) -> None:
        self.violations.append(_violation("forbidden", node, "await"))

    def visit_For(self, node: ast.For) -> None:
        self.for_count += 1
        if self.for_count > MAX_FOR_LOOPS:
            self.violations.append(_violation("resource_limit", node, "too many for loops"))
            return
        self.generic_visit(node)

    # ---- names / attributes / calls --------------------------------
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            self.violations.append(_violation("forbidden", node, "dunder attr"))
            return
        root = node.value
        if isinstance(root, ast.Name):
            if root.id == "cad":
                if node.attr not in CAD_API_METHODS:
                    self.violations.append(
                        _violation("unknown", node, f"cad.{node.attr}")
                    )
                    return
                self.generic_visit(node)
                return
            if root.id == "math":
                if node.attr not in MATH_ATTRS:
                    self.violations.append(
                        _violation("unknown", node, f"math.{node.attr}")
                    )
                    return
                self.generic_visit(node)
                return
            # 本地变量上仅允许安全集合方法（如 teeth.append）
            if node.attr in _SAFE_COLLECTION_METHODS:
                self.generic_visit(node)
                return
            self.violations.append(
                _violation("forbidden", node, f"attr on {root.id!r}")
            )
            return
        self.violations.append(_violation("forbidden", node, "attr chain"))
        return

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in _FORBIDDEN_CALL_NAMES:
                self.violations.append(_violation("forbidden", node, func.id))
                return
            # 允许无参内置构造（list/dict/tuple/set）之外，其它裸 Name 调用拒绝
            if func.id not in ("list", "dict", "tuple", "set", "range", "len", "enumerate", "min", "max", "abs", "round"):
                self.violations.append(
                    _violation("forbidden", node, f"call {func.id}")
                )
                return
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "cad":
            self.cad_calls += 1
            if self.cad_calls > MAX_CAD_CALLS:
                self.violations.append(_violation("resource_limit", node, "too many cad calls"))
                return
        self.generic_visit(node)


def validate_cad_source(code: str) -> CadProgramVerdict:
    """校验 execute_cad_program 的 code。ok=True 才可下发客户端执行。"""
    if not code or not code.strip():
        return CadProgramVerdict(
            ok=False,
            violations=[{"kind": "syntax_error", "line": None, "col": None, "detail": "empty code"}],
        )
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return CadProgramVerdict(
            ok=False,
            violations=[{
                "kind": "syntax_error",
                "line": exc.lineno,
                "col": exc.offset,
                "detail": exc.msg,
            }],
        )

    checker = _Validator()
    checker.visit(tree)
    ok = not checker.violations
    return CadProgramVerdict(
        ok=ok,
        violations=checker.violations,
        meta={
            "for_loops": checker.for_count,
            "cad_calls": checker.cad_calls,
            "nodes": checker.node_count,
        },
    )
