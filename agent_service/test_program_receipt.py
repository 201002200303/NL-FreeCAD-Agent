import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "freecad_addon"))

from AICADAgent.cad_program.receipt import (
    decide_replay,
    document_fingerprint,
    normalize_program,
    program_hash,
)


def test_program_hash_ignores_line_endings_and_trailing_space():
    a = "x = cad.box(name='X')  \r\n"
    b = "x = cad.box(name='X')\n"
    assert normalize_program(a) == normalize_program(b)
    assert program_hash(a) == program_hash(b)


def test_replay_skips_only_when_document_matches_cached_after_state():
    before = {"objects": []}
    after = {"objects": [{"name": "X", "type": "Part::Box", "visible": True}]}
    cached = {
        "program_hash": program_hash("cad.box(name='X')"),
        "before_fingerprint": document_fingerprint(before),
        "after_fingerprint": document_fingerprint(after),
    }

    assert decide_replay(cached, cached["program_hash"], after) == "skip"
    assert decide_replay(cached, cached["program_hash"], before) == "execute"
    assert decide_replay(cached, program_hash("cad.box(name='Y')"), after) == "conflict"
    assert decide_replay(cached, cached["program_hash"], {"objects": [{"name": "Z"}]}) == "stale"
