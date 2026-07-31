import ast
import os
import sys

sys.path.insert(0, ".")
from app.tools.tool_registry import validate_registry_alignment
from app.tools.tool_specs import TOOL_SPECS

print("registry errors:", validate_registry_alignment())

cad_dir = r"D:\project_main\NL-FreeCAD-Agent\freecad_addon\AICADAgent\cad_tools"
impl_params = {}
for fn in os.listdir(cad_dir):
    if not fn.endswith(".py") or fn.startswith("_"):
        continue
    with open(os.path.join(cad_dir, fn), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            impl_params[node.name] = set(a.arg for a in node.args.args)

mismatch = []
for tool, spec in sorted(TOOL_SPECS.items()):
    spec_params = set(spec["parameters"].keys())
    if tool not in impl_params:
        mismatch.append((tool, "NO_IMPL"))
        continue
    impl = impl_params[tool]
    if spec_params - impl:
        mismatch.append((tool, "spec有实现缺: %s" % sorted(spec_params - impl)))
    extra = impl - spec_params - {"doc"}
    if extra:
        mismatch.append((tool, "实现有spec缺: %s" % sorted(extra)))

print("spec/impl mismatches:", mismatch if mismatch else "NONE (all aligned)")
sys.exit(1 if mismatch else 0)
