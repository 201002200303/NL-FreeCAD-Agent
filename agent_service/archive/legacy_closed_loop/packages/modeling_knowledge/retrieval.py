"""Lightweight modeling pattern retrieval for plan / next_step prompts."""

from __future__ import annotations

import re
from pathlib import Path

_PATTERNS_DIR = Path(__file__).resolve().parent / "patterns"
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_keywords(front: str) -> list[str]:
    for line in front.splitlines():
        line = line.strip()
        if not line.lower().startswith("keywords:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        parts = []
        for item in raw.split(","):
            item = item.strip().strip("'\"")
            if item:
                parts.append(item)
        return parts
    return []


def _load_patterns() -> list[dict]:
    patterns: list[dict] = []
    if not _PATTERNS_DIR.exists():
        return patterns
    for path in sorted(_PATTERNS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = _FRONT_MATTER_RE.match(text)
        if match:
            keywords = _parse_keywords(match.group(1))
            content = match.group(2).strip()
        else:
            keywords = []
            content = text.strip()
        patterns.append(
            {
                "pattern_id": path.stem,
                "keywords": keywords,
                "content": content,
            }
        )
    return patterns


def match_knowledge(text: str, limit: int = 2) -> list[dict]:
    """Keyword hit → [{"pattern_id", "content", "score"}], empty if none."""
    hay = (text or "").lower()
    if not hay.strip():
        return []
    scored: list[tuple[int, dict]] = []
    for pattern in _load_patterns():
        score = 0
        for kw in pattern.get("keywords") or []:
            if kw.lower() in hay:
                score += 1
        if score > 0:
            scored.append((score, pattern))
    scored.sort(key=lambda item: (-item[0], item[1]["pattern_id"]))
    out = []
    for score, pattern in scored[: max(0, int(limit))]:
        out.append(
            {
                "pattern_id": pattern["pattern_id"],
                "content": pattern["content"][:6000],
                "score": score,
            }
        )
    return out


def format_knowledge_for_prompt(matches: list[dict]) -> str:
    if not matches:
        return ""
    lines = ["## 建模参考（仅指导顺序与比例，禁止照抄坐标）"]
    for item in matches:
        lines.append(f"### {item.get('pattern_id')}")
        lines.append(item.get("content") or "")
    return "\n".join(lines)
