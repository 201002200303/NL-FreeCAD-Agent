"""L3/L4 geometry oracle runner (requires FreeCAD).

Usage
-----
  D:\\freecad\\bin\\freecadcmd.exe -c "import sys; sys.path.insert(0, r'...\\geometry_oracle'); import runner; raise SystemExit(runner.main())"

Stdout is flushed explicitly because FreeCADCmd drops buffered output when the
process exits via SystemExit.

Writes a JSON + Markdown report to agent_service/data/.  With no FreeCAD
available the caller must report SKIPPED_NO_FREECAD — never a fake pass.
"""

from __future__ import print_function

import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_PARENT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
for _path in (_HERE, ADDON_PARENT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from cases import CASES  # noqa: E402
from oracle import evaluate_facts, validate_cases  # noqa: E402

from AICADAgent.geometry_facts import exact_bbox  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
REPORT_DIR = os.path.join(REPO_ROOT, "agent_service", "data")


def _facts(obj) -> dict:
    shape = obj.Shape
    bb = exact_bbox(shape)  # same source the host's document_state reports
    return {
        "object": obj.Name,
        "bbox_size": [bb.XLength, bb.YLength, bb.ZLength],
        "bbox_center": [
            (bb.XMin + bb.XMax) / 2.0,
            (bb.YMin + bb.YMax) / 2.0,
            (bb.ZMin + bb.ZMax) / 2.0,
        ],
        "solids": len(shape.Solids),
        "volume": shape.Volume,
        "valid": bool(shape.isValid()),
    }


def _execute(case, FreeCAD, registry, run_cad_program):
    doc = FreeCAD.newDocument("Oracle_%s" % case["id"])
    try:
        if case["layer"] == "L4":
            result = run_cad_program(
                case["code"], doc=doc, registry=registry, transaction=case["id"]
            )
            if not result.get("success"):
                return None, "execute_cad_program failed: %s" % (
                    result.get("error_message") or result.get("error_type")
                )
            object_name = case.get("object") or ""
        else:
            handler = registry.get(case["tool"])
            if handler is None:
                return None, "unknown tool %s" % case["tool"]
            result = handler(doc, **dict(case.get("args") or {})) or {}
            object_name = case.get("object") or result.get("object") or ""

        doc.recompute()
        obj = doc.getObject(object_name) if object_name else None
        if obj is None:
            return None, "object %r not found after execution" % object_name
        return _facts(obj), None
    finally:
        FreeCAD.closeDocument(doc.Name)


def run_all(*, layers=None, only=None) -> dict:
    import FreeCAD  # noqa: F401  (imported here so the module stays loadable without it)

    from AICADAgent.cad_tools import TOOL_REGISTRY
    from AICADAgent.cad_program import run_cad_program

    schema_errors = validate_cases(CASES)
    if schema_errors:
        return {"status": "error", "errors": schema_errors, "results": []}

    wanted = {str(x).upper() for x in (layers or [])}
    results = []
    for case in CASES:
        if wanted and case["layer"] not in wanted:
            continue
        if only and case["id"] not in only:
            continue
        try:
            facts, error = _execute(case, FreeCAD, TOOL_REGISTRY, run_cad_program)
        except Exception as exc:  # noqa: BLE001
            facts, error = None, "%s: %s" % (type(exc).__name__, exc)
            traceback.print_exc()

        if error:
            results.append(
                {
                    "id": case["id"],
                    "layer": case["layer"],
                    "ref": case["ref"],
                    "status": "fail",
                    "error": error,
                    "checks": [],
                }
            )
            continue

        checks = evaluate_facts(facts, case["expect"])
        results.append(
            {
                "id": case["id"],
                "layer": case["layer"],
                "ref": case["ref"],
                "status": "pass" if all(c["passed"] for c in checks) else "fail",
                "error": None,
                "checks": checks,
                "actual": facts,
            }
        )

    passed = sum(1 for r in results if r["status"] == "pass")
    return {
        "status": "ok",
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


def write_report(report: dict) -> tuple[str, str]:
    os.makedirs(REPORT_DIR, exist_ok=True)
    json_path = os.path.join(REPORT_DIR, "_geometry_oracle_report.json")
    md_path = os.path.join(REPORT_DIR, "_geometry_oracle_report.md")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    lines = [
        "# Geometry Oracle Report",
        "",
        "- schema: %s" % report.get("status"),
        "- passed: %s, failed: %s" % (report.get("passed", 0), report.get("failed", 0)),
        "",
    ]
    if report.get("errors"):
        lines.append("## Schema errors")
        lines += ["- %s" % err for err in report["errors"]]
        lines.append("")
    if report.get("results"):
        lines += ["## Cases", "", "| layer | case | status | detail |", "|---|---|---|---|"]
        for row in report["results"]:
            if row["error"]:
                detail = row["error"]
            else:
                detail = "; ".join(
                    "%s want=%s got=%s" % (c["kind"], c["expected"], c["actual"])
                    if not c["passed"]
                    else "%s ok" % c["kind"]
                    for c in row["checks"]
                )
            lines.append(
                "| %s | %s | %s | %s |"
                % (row["layer"], row["id"], row["status"], detail.replace("|", "/"))
            )
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return json_path, md_path


def main() -> int:
    report = run_all()
    json_path, md_path = write_report(report)
    print("=" * 60)
    print("Geometry Oracle (L3 registry / L4 cad.*)")
    print("=" * 60)
    for row in report.get("results") or []:
        print("[%s] %s %s" % (row["status"].upper(), row["layer"], row["id"]))
        if row["error"]:
            print("      %s" % row["error"])
        for check in row["checks"]:
            if not check["passed"]:
                print(
                    "      %s expected=%s actual=%s"
                    % (check["kind"], check["expected"], check["actual"])
                )
    for err in report.get("errors") or []:
        print("[SCHEMA] %s" % err)
    print("=" * 60)
    print(
        "Results: %s passed, %s failed"
        % (report.get("passed", 0), report.get("failed", 0))
    )
    print("report: %s" % json_path)
    print("report: %s" % md_path)
    print("=" * 60)
    sys.stdout.flush()
    sys.stderr.flush()
    return 0 if report.get("status") == "ok" and not report.get("failed") else 1


if __name__ == "__main__":
    _code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    raise SystemExit(_code)
