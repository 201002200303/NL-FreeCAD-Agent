"""视觉 LLM 调用：评估 FreeCAD 视口截图是否合理。

不替代 bbox/topology 验证器，只补它们看不到的整体造型、左右对称、前后朝向等问题。
主模型无视觉时在 .env 里单独配 VISION_MODEL；VISION_ENABLED=0 时整条链路静默跳过。
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app import config
from app.prompts import render


def vision_available(*, request_enabled: Optional[bool] = None) -> bool:
    """服务端配置开启，且有可用的视觉模型与 key；请求侧可再关一次。"""
    if request_enabled is False:
        return False
    if request_enabled is None and not config.VISION_ENABLED:
        return False
    if request_enabled is True and not config.VISION_ENABLED:
        # 客户端想开，但服务端总开关关着 → 仍不可用
        return False
    return bool(config.VISION_API_KEY and config.VISION_MODEL)


def assess_viewport(
    *,
    image_b64: str,
    mime: str = "image/png",
    user_goal: str = "",
    phase_hint: str = "",
    focus: str = "",
) -> dict[str, Any]:
    """对一张视口截图做结构化视觉判断。

    Returns:
        {ok, verdict, issues, suggestions, raw}；不可用或失败时 ok=False 且不抛。
    """
    return assess_views(
        views=[{"name": "viewport", "image_b64": image_b64, "mime": mime}],
        user_goal=user_goal,
        phase_hint=phase_hint,
        focus=focus,
    )


def assess_views(
    *,
    views: list[dict] | None,
    user_goal: str = "",
    phase_hint: str = "",
    focus: str = "",
) -> dict[str, Any]:
    """多视图视觉评估。views=[{name, image_b64, mime}, ...]。失败/不可用 → skipped。"""
    if not vision_available(request_enabled=True):
        return {
            "ok": False,
            "skipped": True,
            "reason": "vision_disabled_or_unconfigured",
            "verdict": "skip",
            "issues": [],
            "suggestions": [],
            "revise_once": False,
        }

    cleaned: list[dict] = []
    for v in views or []:
        if not isinstance(v, dict):
            continue
        b64 = (v.get("image_b64") or "").strip()
        if not b64:
            continue
        cleaned.append(
            {
                "name": (v.get("name") or "view").strip() or "view",
                "image_b64": b64,
                "mime": v.get("mime") or "image/png",
            }
        )
    if not cleaned:
        return {
            "ok": False,
            "skipped": True,
            "reason": "empty_images",
            "verdict": "skip",
            "issues": [],
            "suggestions": [],
            "revise_once": False,
        }

    prompt = _build_prompt(
        user_goal=user_goal,
        phase_hint=phase_hint,
        focus=focus,
        view_names=[v["name"] for v in cleaned],
    )
    content: list[dict] = [{"type": "text", "text": prompt}]
    for v in cleaned:
        data_url = f"data:{v['mime']};base64,{v['image_b64']}"
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    try:
        from openai import OpenAI

        timeout = float(getattr(config, "LLM_TIMEOUT_SEC", 180) or 180)
        client = OpenAI(
            api_key=config.VISION_API_KEY,
            base_url=config.VISION_BASE_URL,
            timeout=timeout,
        )
        response = client.chat.completions.create(
            model=config.VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 CAD 造型质检助手。根据多视图截图判断模型整体是否合理。"
                        "只输出 JSON，不要 markdown。"
                    ),
                },
                {"role": "user", "content": content},
            ],
            temperature=0.2,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        text = (response.choices[0].message.content or "").strip()
        parsed = _parse_json(text)
        verdict = parsed.get("verdict", "unknown")
        result = {
            "ok": True,
            "skipped": False,
            "verdict": verdict,
            "summary": parsed.get("summary", ""),
            "issues": list(parsed.get("issues") or []),
            "suggestions": list(parsed.get("suggestions") or []),
            "views": [v["name"] for v in cleaned],
            "raw": parsed,
        }
        result["revise_once"] = needs_code_revision(result)
        return result
    except Exception as exc:
        print(f"[vision] assess failed: {exc}")
        return {
            "ok": False,
            "skipped": True,  # 渲染/VLM 失败：降级跳过，不阻断闭环
            "reason": str(exc),
            "verdict": "skip",
            "issues": [f"vision_call_failed: {exc}"],
            "suggestions": [],
            "revise_once": False,
        }


def needs_code_revision(result: dict | None) -> bool:
    """仅硬伤触发一次 code 修订（verdict=bad）。warn/ok/skip 不强制。"""
    if not result or result.get("skipped"):
        return False
    return (result.get("verdict") or "").lower() == "bad"


def format_vision_for_prompt(result: dict | None) -> str:
    """渲染进 chat/evaluate 提示词的短片段。"""
    if not result or result.get("skipped"):
        return ""
    lines = ["## 视觉检查（多视图）"]
    if views := result.get("views"):
        lines.append(f"- 视图: {', '.join(views)}")
    lines.append(f"- 结论: {result.get('verdict', 'unknown')}")
    if summary := result.get("summary"):
        lines.append(f"- 摘要: {summary}")
    for issue in (result.get("issues") or [])[:8]:
        lines.append(f"- 问题: {issue}")
    for tip in (result.get("suggestions") or [])[:6]:
        lines.append(f"- 建议: {tip}")
    if result.get("revise_once") or needs_code_revision(result):
        lines.append(
            "- 处置: 视觉硬伤 → 用一次 `execute_cad_program` 修订原程序后重跑；"
            "不要改需求语义，只修造型问题。"
        )
    lines.append("视觉结论是软约束；与用户原文冲突时以用户原文为准。数值以 query/文档状态为准。")
    return "\n".join(lines)


def _build_prompt(
    *,
    user_goal: str,
    phase_hint: str,
    focus: str,
    view_names: list[str] | None = None,
) -> str:
    """正文见 app/prompts/vision.md。"""
    goal_block = f"\n\n用户目标: {user_goal[:800]}" if user_goal else ""
    phase_block = f"\n当前阶段: {phase_hint[:400]}" if phase_hint else ""
    focus_block = f"\n特别关注: {focus[:400]}" if focus else ""
    views_block = ""
    if view_names:
        views_block = f"\n多视图顺序: {', '.join(view_names)}（front/side/top/iso）"
    return render(
        "vision",
        USER_GOAL_BLOCK=goal_block,
        PHASE_BLOCK=phase_block,
        FOCUS_BLOCK=focus_block + views_block,
    ).rstrip()


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        return {"verdict": "unknown", "summary": text[:500], "issues": [], "suggestions": []}
