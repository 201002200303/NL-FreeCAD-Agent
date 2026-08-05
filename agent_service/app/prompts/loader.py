"""从 app/prompts/*.md 加载提示词模板。

约定：
- 文件顶部可用 <!-- ... --> 写「用途 / 调用方 / 占位符 / 修改提示」；渲染前会剥掉
- 动态片段用 [[NAME]] 占位（避免与 JSON 花括号冲突）
- 未传入的占位符替换为空串
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"\[\[([A-Z0-9_]+)\]\]")


@lru_cache(maxsize=64)
def load_template(name: str) -> str:
    """读取 name.md（不含扩展名），剥掉 HTML 注释。

    支持子路径，如 ``packs/gear`` → ``prompts/packs/gear.md``。
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt template not found: {path}")
    text = path.read_text(encoding="utf-8")
    text = _COMMENT_RE.sub("", text)
    return text.strip()


def render_rule_packs(pack_names: tuple[str, ...] | list[str]) -> str:
    """按序拼接 prompts/packs/<name>.md；缺失的 pack 跳过。"""
    chunks: list[str] = []
    for name in pack_names:
        try:
            chunks.append(render(f"packs/{name}").rstrip())
        except FileNotFoundError:
            continue
    return "\n\n".join(chunks)


def render(name: str, **kwargs: object) -> str:
    """加载模板并把 [[KEY]] 换成 kwargs 值（缺省 → 空串）。"""
    template = load_template(name)

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        val = kwargs.get(key, "")
        return "" if val is None else str(val)

    return _PLACEHOLDER_RE.sub(_sub, template).strip() + "\n"


def clear_cache() -> None:
    """测试或热重载时可清缓存。"""
    load_template.cache_clear()
