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
    acceptance: str = "",
    prior_issues: list[str] | None = None,
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
        acceptance=acceptance,
        prior_issues=prior_issues or [],
    )
    content: list[dict] = [{"type": "text", "text": prompt}]
    for v in cleaned:
        data_url = f"data:{v['mime']};base64,{v['image_b64']}"
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    try:
        from openai import OpenAI

        from app.llm.llm_provider import _message_text

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
                        "bad=明显漂移/间隙/穿模/缺件/严重不对称；warn=可问用户的细节；"
                        "对照阶段验收标准，勿重复已接受问题。"
                    ),
                },
                {"role": "user", "content": content},
            ],
            temperature=0.2,
            # 与主模型同源的推理模型：reasoning token 计入 max_tokens。
            # 1500 会被思考烧光 → JSON 截断 → 异常 → 视觉**静默**降级为 skip
            # （看起来像「没开视觉」，实际是每次都失败）。
            max_tokens=32768,
            response_format={"type": "json_object"},
        )
        choice = response.choices[0]
        # 复用主路径的取值：reasoning 模型偶发把答案放进 reasoning_content
        text = _message_text(choice.message).strip()
        usage = getattr(response, "usage", None)
        print(
            f"[vision] finish={getattr(choice, 'finish_reason', None)} "
            f"out_chars={len(text)} completion_tokens={getattr(usage, 'completion_tokens', None)} "
            f"reasoning_tokens="
            f"{getattr(getattr(usage, 'completion_tokens_details', None), 'reasoning_tokens', None)}"
        )
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
        # revise_once 由 chat 结合 vision_memory 预算最终裁定
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


def format_vision_for_prompt(
    result: dict | None,
    *,
    memory: dict | None = None,
    allow_revise: bool | None = None,
) -> str:
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

    verdict = str(result.get("verdict") or "").lower()
    do_revise = allow_revise if allow_revise is not None else bool(
        result.get("revise_once") or needs_code_revision(result)
    )
    if verdict == "bad" and do_revise:
        lines.append(
            "- 处置: 硬伤（漂移/间隙/穿模/缺件）→ 先 `cad.delete` 清旧件，再一次 "
            "`execute_cad_program` 修订；视角不清先 `capture_views`。"
        )
    elif verdict == "bad" and not do_revise:
        reason = (memory or {}).get("stop_reason") or result.get("revise_blocked") or "budget"
        lines.append(
            f"- 处置: 硬伤仍在，但本阶段视觉修订预算已用尽（{reason}）。"
            "不要继续自动改码；在 message 说明现状，用 question 问用户是否继续修或接受。"
        )
    elif verdict == "warn":
        lines.append(
            "- 处置: 细节/warn → **不要自动改码**；在 question 询问用户是否要精修这些点；"
            "可推进 soft_plan 下一阶段或 awaiting_user。"
        )
    else:
        lines.append("- 处置: 视觉可接受；继续当前阶段或标 done，勿为抛光再改。")

    lines.append("视觉是阶段验收不是无限抛光；与用户原文冲突时以用户原文为准。")
    return "\n".join(lines)


def _build_prompt(
    *,
    user_goal: str,
    phase_hint: str,
    focus: str,
    view_names: list[str] | None = None,
    acceptance: str = "",
    prior_issues: list[str] | None = None,
) -> str:
    """正文见 app/prompts/vision.md。"""
    goal_block = f"\n\n用户目标: {user_goal[:800]}" if user_goal else ""
    phase_block = f"\n当前阶段: {phase_hint[:400]}" if phase_hint else ""
    if acceptance:
        phase_block += f"\n本阶段验收标准: {acceptance[:400]}"
    focus_block = f"\n特别关注: {focus[:400]}" if focus else ""
    if prior_issues:
        focus_block += "\n已知/已提过的问题（勿重复啰嗦）: " + "；".join(
            str(x)[:120] for x in prior_issues[:8]
        )
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
