"""
LLM Client for Gomoku AI.
Unified prompt layer for review / personality / QA / explanation / top3.

Review-only text-section version:
- Review no longer forces strict JSON
- Review asks model to output structured text sections
- Backend lightly parses sections into frontend fields
- Personality and other capabilities remain unchanged
"""

import json
import os
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI


def strip_think(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content or "", flags=re.S).strip()


def strip_code_fence(content: str) -> str:
    text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def safe_json_loads(content: str) -> Optional[dict]:
    text = strip_code_fence(strip_think(content))
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass

    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else None
    except Exception:
        pass

    return None


def _clip_text(text: Any, limit: int = 180) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= limit:
        return s
    return s[:limit] + "..."


def _normalize_string_list(
    value: Any,
    *,
    min_items: int = 0,
    max_items: int = 3,
    fallback: Optional[List[str]] = None,
) -> List[str]:
    items: List[str] = []
    if isinstance(value, list):
        for item in value:
            text = _clip_text(item, 140)
            if text:
                items.append(text)
    elif isinstance(value, str):
        text = _clip_text(value, 140)
        if text:
            items.append(text)

    deduped: List[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)

    items = deduped[:max_items]
    for item in list(fallback or []):
        if len(items) >= min_items:
            break
        if item not in items:
            items.append(item)
    return items[:max_items]


def _compact_review_context(review_context: Dict[str, Any]) -> Dict[str, Any]:
    recent_moves = review_context.get("recent_moves", [])
    compact_recent: List[Dict[str, Any]] = []
    for item in recent_moves[-8:]:
        compact_recent.append({
            "step_id": item.get("step_id"),
            "player": item.get("player"),
            "x": item.get("x"),
            "y": item.get("y"),
            "eval_score": item.get("eval_score"),
            "reasoning": _clip_text(item.get("reasoning", ""), 80),
        })

    history_items = review_context.get("history", [])
    history_tail: List[Dict[str, Any]] = []
    for item in history_items[-8:]:
        history_tail.append({
            "step_id": item.get("step_id"),
            "player": item.get("player"),
            "x": item.get("x"),
            "y": item.get("y"),
            "eval_score": item.get("eval_score"),
        })

    return {
        "winner": review_context.get("winner"),
        "game_over": review_context.get("game_over"),
        "total_steps": review_context.get("total_steps") or review_context.get("step_count"),
        "recent_moves": compact_recent,
        "history_tail": history_tail,
    }


def _compact_key_moments(key_moments: List[Dict[str, Any]], limit: int = 4) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for m in key_moments:
        impact = m.get("impact")
        if impact is None:
            try:
                impact = abs(float(m.get("delta", 0)))
            except Exception:
                impact = 0.0
        normalized.append({
            "step_id": m.get("step_id"),
            "player": m.get("player"),
            "delta": m.get("delta"),
            "impact": impact,
            "moment_type": m.get("moment_type", "swing"),
            "summary": _clip_text(m.get("summary", ""), 120),
        })

    top = sorted(normalized, key=lambda x: (-float(x.get("impact", 0)), int(x.get("step_id", 0) or 0)))[:limit]
    top.sort(key=lambda x: int(x.get("step_id", 0) or 0))
    return top


def _compact_retrieved_chunks(retrieved_chunks: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    compact = []
    for c in retrieved_chunks[:limit]:
        compact.append(_clip_text(c.get("text", ""), 220))
    return compact


def _format_style_profile(style_profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "primary_style": style_profile.get("primary_style", "均衡理性型"),
        "secondary_style": style_profile.get("secondary_style", "稳健防守型"),
        "scores": style_profile.get("scores", {}),
        "reason": _clip_text(style_profile.get("reason", ""), 80),
    }


def _build_human_review_defaults(review_payload: Dict[str, Any], compact_evidence: List[str]) -> Dict[str, Any]:
    key_moments = review_payload.get("key_moments", [])
    signals = review_payload.get("signals", {}) if isinstance(review_payload.get("signals"), dict) else {}
    style_profile = review_payload.get("style_profile", {}) if isinstance(review_payload.get("style_profile"), dict) else {}

    turning_points = []
    for m in key_moments[:3]:
        summary = _clip_text(m.get("summary", ""), 140)
        if summary:
            turning_points.append(summary)

    bad_steps = signals.get("human_bad_steps", []) if isinstance(signals, dict) else []
    good_steps = signals.get("human_good_steps", []) if isinstance(signals, dict) else []

    mistakes = []
    if bad_steps:
        step = bad_steps[0]
        step_id = step.get("step_id", "?")
        moment_type = str(step.get("moment_type", ""))
        if moment_type == "missed_defense":
            mistakes.append(f"第{step_id}步，玩家没有优先处理对手的强威胁，导致局面迅速转差。")
        else:
            mistakes.append(f"第{step_id}步之后，玩家的应手让局面对自己更不利。")
    elif turning_points:
        mistakes.append("中后段对关键威胁的判断不够清晰，导致局面主动权被让出。")

    suggestions = []
    if bad_steps:
        step = bad_steps[0]
        if step.get("moment_type") == "missed_defense":
            suggestions.append("遇到对手已经形成冲四或接近冲四的压力时，应先把防守顺序放在扩张进攻之前。")
        else:
            suggestions.append("在关键步先比较防守收益和进攻收益，再决定是否继续推进自己的形状。")
    else:
        suggestions.append("在局面接近转折时，优先检查对手下一步是否存在强制手。")

    if good_steps:
        suggestions.append("当己方已经形成活三或连续连接时，可以继续围绕同一片区域集中发力。")
    else:
        suggestions.append("如果没有直接强制威胁，优先补强中心连接和局部成型效率。")

    primary_style = style_profile.get("primary_style", "均衡理性型")
    summary = f"这盘棋的关键在于关键威胁的处理顺序，以及中后段攻防转换的节奏控制。当前棋风更接近{primary_style}。"

    return {
        "summary": summary,
        "turning_points": turning_points[:3],
        "mistakes": mistakes[:2],
        "suggestions": suggestions[:3],
        "evidence": compact_evidence[:3],
    }


def _extract_heading_block(text: str, headings: List[str], next_headings: List[str]) -> str:
    for heading in headings:
        pattern = rf"(?m)^\s*{re.escape(heading)}\s*$"
        m = re.search(pattern, text)
        if not m:
            continue

        start = m.end()
        tail = text[start:]
        end_idx = len(tail)

        for nh in next_headings:
            m2 = re.search(rf"(?m)^\s*{re.escape(nh)}\s*$", tail)
            if m2:
                end_idx = min(end_idx, m2.start())

        return tail[:end_idx].strip()

    return ""


def _extract_bullets(block: str, max_items: int = 4) -> List[str]:
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    items: List[str] = []
    bullet_pat = re.compile(r"^(?:[-*•]|[0-9]+[.)、]|第\d+步[:：])\s*(.+)$")
    for ln in lines:
        m = bullet_pat.match(ln)
        if m:
            items.append(_clip_text(m.group(1), 160))
    if items:
        return items[:max_items]

    joined = " ".join(lines)
    parts = re.split(r"[；;。]\s*", joined)
    out = []
    seen = set()
    for p in parts:
        p = _clip_text(p, 160)
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out[:max_items]


# def _parse_review_text_sections(raw_text: str, review_payload: Dict[str, Any], compact_evidence: List[str]) -> Dict[str, Any]:
#     text = strip_code_fence(strip_think(raw_text))

#     summary_block = _extract_heading_block(
#         text,
#         ["Summary", "总结"],
#         ["Turning Points", "转折点", "关键点", "Mistakes", "问题", "Suggestions", "建议", "Evidence", "依据", "证据"],
#     )
#     turning_block = _extract_heading_block(
#         text,
#         ["Turning Points", "转折点", "关键点"],
#         ["Mistakes", "问题", "Suggestions", "建议", "Evidence", "依据", "证据"],
#     )
#     mistakes_block = _extract_heading_block(
#         text,
#         ["Mistakes", "问题"],
#         ["Suggestions", "建议", "Evidence", "依据", "证据"],
#     )
#     suggestions_block = _extract_heading_block(
#         text,
#         ["Suggestions", "建议"],
#         ["Evidence", "依据", "证据"],
#     )
#     evidence_block = _extract_heading_block(
#         text,
#         ["Evidence", "依据", "证据"],
#         [],
#     )

#     summary = ""
#     if summary_block:
#         summary = _clip_text(summary_block.splitlines()[0], 240)
#     else:
#         lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
#         for ln in lines:
#             if len(ln) >= 8 and "总结" not in ln and "Turning Points" not in ln:
#                 summary = _clip_text(ln, 240)
#                 break

#     turning_points = _extract_bullets(turning_block, max_items=3) if turning_block else []
#     mistakes = _extract_bullets(mistakes_block, max_items=2) if mistakes_block else []
#     suggestions = _extract_bullets(suggestions_block, max_items=3) if suggestions_block else []

#     # Evidence stays sourced from retrieved chunks unless model explicitly gives section text
#     evidence = _extract_bullets(evidence_block, max_items=3) if evidence_block else compact_evidence[:3]
#     if not evidence:
#         evidence = compact_evidence[:3]

#     defaults = _build_human_review_defaults(review_payload, compact_evidence)
#     if not summary:
#         summary = defaults["summary"]
#     if not turning_points:
#         turning_points = defaults["turning_points"][:3]
#     if not mistakes:
#         mistakes = defaults["mistakes"][:2]
#     if not suggestions:
#         suggestions = defaults["suggestions"][:3]

#     return {
#         "summary": summary,
#         "turning_points": turning_points[:3],
#         "mistakes": mistakes[:2],
#         "suggestions": suggestions[:3],
#         "evidence": evidence[:3],
#     }

def _parse_review_text_sections(raw_text: str, review_payload: Dict[str, Any], compact_evidence: List[str]) -> Dict[str, Any]:
    text = strip_code_fence(strip_think(raw_text))

    summary_block = _extract_heading_block(
        text,
        ["[SUMMARY]"],
        ["[TURNING_POINTS]", "[MISTAKES]", "[SUGGESTIONS]", "[EVIDENCE]"],
    )
    turning_block = _extract_heading_block(
        text,
        ["[TURNING_POINTS]"],
        ["[MISTAKES]", "[SUGGESTIONS]", "[EVIDENCE]"],
    )
    mistakes_block = _extract_heading_block(
        text,
        ["[MISTAKES]"],
        ["[SUGGESTIONS]", "[EVIDENCE]"],
    )
    suggestions_block = _extract_heading_block(
        text,
        ["[SUGGESTIONS]"],
        ["[EVIDENCE]"],
    )
    evidence_block = _extract_heading_block(
        text,
        ["[EVIDENCE]"],
        [],
    )

    defaults = _build_human_review_defaults(review_payload, compact_evidence)

    summary = _clip_text(summary_block.splitlines()[0], 240) if summary_block else defaults["summary"]
    turning_points = _extract_bullets(turning_block, max_items=3) if turning_block else defaults["turning_points"][:3]
    mistakes = _extract_bullets(mistakes_block, max_items=2) if mistakes_block else defaults["mistakes"][:2]
    suggestions = _extract_bullets(suggestions_block, max_items=3) if suggestions_block else defaults["suggestions"][:3]
    evidence = _extract_bullets(evidence_block, max_items=3) if evidence_block else compact_evidence[:3]

    return {
        "summary": summary,
        "turning_points": turning_points[:3],
        "mistakes": mistakes[:2],
        "suggestions": suggestions[:3],
        "evidence": evidence[:3],
    }
def _personality_defaults(personality_type: str) -> Dict[str, Any]:
    mapping: Dict[str, Dict[str, Any]] = {
        "稳健防守型": {
            "title": "稳中求胜的守势派",
            "description": "你更重视局面的安全感，遇到威胁时倾向于先补防、再寻找反击机会。整体节奏偏稳，追求少犯错。",
            "strengths": ["防守意识较强", "不容易轻易崩盘"],
            "risks": ["进攻推进偏慢", "可能错过主动施压时机"],
            "advice": ["确认安全后更主动抢节奏", "优势局面尝试持续施压"],
            "fun_comment": "你像一位会先把门关好的棋手。",
        },
        "激进进攻型": {
            "title": "主动压迫的进攻派",
            "description": "你喜欢主动出击，倾向于通过连续施压掌握局面节奏。对进攻机会很敏感，愿意以速度换主动权。",
            "strengths": ["进攻欲望强", "容易形成连续威胁"],
            "risks": ["防守可能顾及不足", "容易因抢攻留下破绽"],
            "advice": ["进攻前先确认对手强制威胁", "领先时减少无必要冒险"],
            "fun_comment": "你的棋像在不断催促对手交作业。",
        },
        "均衡理性型": {
            "title": "攻守之间，灵活应对",
            "description": "你的下法比较讲究平衡，会在进攻与防守之间做权衡。既不会一味冒进，也不会长期被动，整体风格偏理性。",
            "strengths": ["攻防切换自然", "局面判断较均衡"],
            "risks": ["关键时刻可能不够极致", "优势扩大速度有时偏慢"],
            "advice": ["在明确优势时更果断进攻", "在高压局面下优先处理最强威胁"],
            "fun_comment": "你像一位把算盘和棋盘一起带来的选手。",
        },
        "机会主义型": {
            "title": "善抓空当的猎手机",
            "description": "你擅长观察局面中的空档和对手疏漏，常在机会出现时迅速出手。节奏感不错，善于从细节中找突破。",
            "strengths": ["抓机会能力较强", "能从局部找到突破口"],
            "risks": ["整体布局可能不够连贯", "过度等机会会损失主动权"],
            "advice": ["抓机会同时兼顾全局结构", "不要把主动权完全交给对手"],
            "fun_comment": "你像在棋盘上等对手先露出破绽。",
        },
        "冲动冒险型": {
            "title": "敢赌敢拼的冒险派",
            "description": "你愿意为了局面突破去承担风险，喜欢尝试高回报的走法。整体风格有冲击力，但波动也会更大。",
            "strengths": ["敢于创造变化", "有时能打出意外效果"],
            "risks": ["忽视直接威胁", "局面容易突然失控"],
            "advice": ["冒险前先检查对手的强制手", "把高风险操作留给更合适的时机"],
            "fun_comment": "你的棋像会在转角突然踩一脚油门。",
        },
        "慢热成长型": {
            "title": "越下越清晰的成长派",
            "description": "你可能开局不算锋利，但会随着局面推进逐渐找到节奏。整体呈现出边下边修正、逐步变稳的特点。",
            "strengths": ["调整能力不错", "越到后面越容易进入状态"],
            "risks": ["开局容易被抢节奏", "前期判断有时不够果断"],
            "advice": ["加强开局阶段的基本型意识", "前几手更重视中心与连接"],
            "fun_comment": "你属于那种热身完会越下越顺的人。",
        },
    }
    return mapping.get(personality_type, mapping["均衡理性型"])


def _canonical_personality_type(value: Any) -> str:
    text = str(value or "").strip()
    allowed = [
        "稳健防守型",
        "激进进攻型",
        "均衡理性型",
        "机会主义型",
        "冲动冒险型",
        "慢热成长型",
    ]
    for item in allowed:
        if item in text:
            return item

    alias_map = {
        "防守": "稳健防守型",
        "稳健": "稳健防守型",
        "进攻": "激进进攻型",
        "攻击": "激进进攻型",
        "平衡": "均衡理性型",
        "均衡": "均衡理性型",
        "理性": "均衡理性型",
        "机会": "机会主义型",
        "冒险": "冲动冒险型",
        "冲动": "冲动冒险型",
        "成长": "慢热成长型",
        "慢热": "慢热成长型",
    }
    for key, target in alias_map.items():
        if key in text:
            return target
    return "均衡理性型"


class LLMClient:
    def __init__(self, api_url: Optional[str] = None, model: Optional[str] = None):
        self.api_url = api_url or os.getenv("LLM_API_URL", "http://localhost:8000/v1")
        self.model = model or os.getenv("LLM_MODEL", "/root/.cache/huggingface/Qwen3-4B-quantized.w4a16")
        self.client = None

    def connect(self):
        self.client = OpenAI(base_url=self.api_url, api_key="dummy")

    def _ensure_client(self):
        if self.client is None:
            self.connect()

    def generate_move(self, board: List[List[int]], player: str) -> Dict[str, Any]:
        self._ensure_client()
        prompt = self._build_prompt(board, player)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=150,
        )
        return self._parse_move_response(response.choices[0].message.content)

#     def generate_review(self, review_payload: Dict[str, Any], retrieved_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
#         self._ensure_client()

#         context_block = review_payload.get("context") if isinstance(review_payload.get("context"), dict) else review_payload
#         key_moments = review_payload.get("key_moments", []) if isinstance(review_payload.get("key_moments"), list) else []
#         signals = review_payload.get("signals", {}) if isinstance(review_payload.get("signals"), dict) else {}
#         style_profile = review_payload.get("style_profile", {}) if isinstance(review_payload.get("style_profile"), dict) else {}

#         compact_context = _compact_review_context(context_block)
#         compact_moments = _compact_key_moments(key_moments, limit=4)
#         compact_evidence = _compact_retrieved_chunks(retrieved_chunks, limit=3)
#         compact_signals = {
#             "human_bad_steps": [
#                 {"step_id": item.get("step_id"), "summary": _clip_text(item.get("summary", ""), 120)}
#                 for item in signals.get("human_bad_steps", [])[:2]
#             ],
#             "human_good_steps": [
#                 {"step_id": item.get("step_id"), "summary": _clip_text(item.get("summary", ""), 120)}
#                 for item in signals.get("human_good_steps", [])[:2]
#             ],
#             "pattern_counts": signals.get("pattern_counts", {}),
#         }
#         compact_style = _format_style_profile(style_profile)

#         prompt = f"""你是一个五子棋复盘助手。

# 请根据给定的对局摘要、关键步、结构化信号和策略资料，输出一份给“玩家（黑棋）”看的复盘。不要输出 JSON，请直接按下面栏目输出中文内容：

# Summary:
# 用1-2句总结整盘棋的关键。

# Turning Points:
# - 2到3条关键步说明，尽量写明第几步。

# Mistakes:
# - 1到2条玩家的问题，只写玩家，不要写AI的问题。

# Suggestions:
# - 2到3条给玩家的具体建议。

# Evidence:
# - 2到3条策略资料依据。

# 对局摘要：
# {json.dumps(compact_context, ensure_ascii=False)}

# 关键步：
# {json.dumps(compact_moments, ensure_ascii=False)}

# 结构化信号：
# {json.dumps(compact_signals, ensure_ascii=False)}

# 玩家棋风：
# {json.dumps(compact_style, ensure_ascii=False)}

# 策略资料：
# {json.dumps(compact_evidence, ensure_ascii=False)}
# """
#         response = self.client.chat.completions.create(
#             model=self.model,
#             messages=[
#                 {"role": "system", "content": "你是严谨的五子棋复盘助手。不要输出 JSON，不要输出思考过程，只按 Summary/Turning Points/Mistakes/Suggestions/Evidence 五个栏目输出。"},
#                 {"role": "user", "content": prompt},
#             ],
#             temperature=0.2,
#             max_tokens=650,
#         )

#         raw_content = response.choices[0].message.content or ""
#         print("=== review raw content ===")
#         print(raw_content)

#         parsed = _parse_review_text_sections(raw_content, review_payload, compact_evidence)
#         print("=== review parsed from text sections ===")
#         print(json.dumps(parsed, ensure_ascii=False, indent=2))
#         return parsed
    def generate_review(self, review_payload: Dict[str, Any], retrieved_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._ensure_client()

        context_block = review_payload.get("context") if isinstance(review_payload.get("context"), dict) else review_payload
        key_moments = review_payload.get("key_moments", []) if isinstance(review_payload.get("key_moments"), list) else []
        signals = review_payload.get("signals", {}) if isinstance(review_payload.get("signals"), dict) else {}
        style_profile = review_payload.get("style_profile", {}) if isinstance(review_payload.get("style_profile"), dict) else {}

        compact_context = _compact_review_context(context_block)
        compact_moments = _compact_key_moments(key_moments, limit=4)
        compact_evidence = _compact_retrieved_chunks(retrieved_chunks, limit=3)
        compact_signals = {
            "human_bad_steps": [
                {"step_id": item.get("step_id"), "summary": _clip_text(item.get("summary", ""), 120)}
                for item in signals.get("human_bad_steps", [])[:2]
            ],
            "human_good_steps": [
                {"step_id": item.get("step_id"), "summary": _clip_text(item.get("summary", ""), 120)}
                for item in signals.get("human_good_steps", [])[:2]
            ],
            "pattern_counts": signals.get("pattern_counts", {}),
        }
        compact_style = _format_style_profile(style_profile)

        prompt = f"""你是一个五子棋复盘助手。

    请根据给定的对局摘要、关键步、结构化信号和策略资料，
    输出一份给“玩家（黑棋）”看的复盘。

    严格要求：
    1. 不要输出 JSON
    2. 不要输出 Markdown
    3. 不要输出思考过程
    4. 所有自然语言必须使用简体中文
    5. 必须严格使用下面 5 个分隔标记，且每个标记独占一行
    6. 不要输出任何额外标题，不要解释这些标记

    输出格式必须严格如下：

    [SUMMARY]
    用 1-2 句总结整盘棋的关键。

    [TURNING_POINTS]
    - 2到3条关键步说明，尽量写明第几步。

    [MISTAKES]
    - 1到2条玩家的问题，只写玩家，不要写 AI 的问题。

    [SUGGESTIONS]
    - 2到3条给玩家的具体建议。

    [EVIDENCE]
    - 2到3条策略资料依据。

    对局摘要：
    {json.dumps(compact_context, ensure_ascii=False)}

    关键步：
    {json.dumps(compact_moments, ensure_ascii=False)}

    结构化信号：
    {json.dumps(compact_signals, ensure_ascii=False)}

    玩家棋风：
    {json.dumps(compact_style, ensure_ascii=False)}

    策略资料：
    {json.dumps(compact_evidence, ensure_ascii=False)}
    """

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是严谨的五子棋复盘助手。不要输出 JSON，不要输出思考过程，只允许使用 [SUMMARY]、[TURNING_POINTS]、[MISTAKES]、[SUGGESTIONS]、[EVIDENCE] 五个分隔标记，且每个标记必须独占一行。"
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
            max_tokens=650,
        )

        raw_content = response.choices[0].message.content or ""
        print("=== review raw content ===")
        print(raw_content)

        required_markers = ["[SUMMARY]", "[TURNING_POINTS]", "[MISTAKES]", "[SUGGESTIONS]", "[EVIDENCE]"]
        if not all(marker in raw_content for marker in required_markers):
            defaults = _build_human_review_defaults(review_payload, compact_evidence)
            parsed = {
                "summary": defaults["summary"],
                "turning_points": defaults["turning_points"][:3],
                "mistakes": defaults["mistakes"][:2],
                "suggestions": defaults["suggestions"][:3],
                "evidence": defaults["evidence"][:3],
            }
            print("=== review fallback parsed ===")
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
            return parsed

        parsed = _parse_review_text_sections(raw_content, review_payload, compact_evidence)
        print("=== review parsed from marker sections ===")
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        return parsed
    def _build_personality_from_style_profile(self, style_profile: Dict[str, Any], review_result: Dict[str, Any]) -> Dict[str, Any]:
        primary = _canonical_personality_type(style_profile.get("primary_style"))
        defaults = _personality_defaults(primary)
        secondary = _canonical_personality_type(style_profile.get("secondary_style", "均衡理性型"))
        scores = style_profile.get("scores", {}) if isinstance(style_profile.get("scores"), dict) else {}

        description = defaults["description"]
        reason = _clip_text(style_profile.get("reason", ""), 70)
        if reason:
            description = _clip_text(f"{defaults['description']} 本局特征：{reason}", 220)

        strengths = list(defaults["strengths"])
        risks = list(defaults["risks"])
        advice = list(defaults["advice"])

        if scores.get("attack", 0) >= 68 and "主动施压能力不错" not in strengths:
            strengths = [strengths[0], "主动施压能力不错"]
        if scores.get("defense", 0) >= 68 and "关键防守意识较强" not in strengths:
            strengths = [strengths[0], "关键防守意识较强"]
        if scores.get("risk", 0) >= 65:
            risks = [risks[0], "高压局面下偶尔会走得偏急"]
            advice = [advice[0], "关键步先排查对手的强制手"]
        elif scores.get("balance", 0) >= 70:
            strengths = [strengths[0], "整体节奏把控比较均衡"]

        title = defaults["title"]
        if secondary and secondary != primary:
            title = f"{defaults['title']}（偏{secondary[:-1]}）"

        return {
            "personality_type": primary,
            "title": title,
            "description": description,
            "strengths": strengths[:2],
            "risks": risks[:2],
            "advice": advice[:2],
            "fun_comment": defaults["fun_comment"],
        }

    def generate_personality_test(self, review_result: Dict[str, Any], retrieved_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        style_profile = review_result.get("style_profile", {}) if isinstance(review_result.get("style_profile"), dict) else {}
        if style_profile:
            return self._build_personality_from_style_profile(style_profile, review_result)

        compact_review = {
            "summary": _clip_text(review_result.get("summary", ""), 180),
            "turning_points": review_result.get("turning_points", [])[:3],
            "mistakes": review_result.get("mistakes", [])[:2],
            "suggestions": review_result.get("suggestions", [])[:2],
        }
        primary = "均衡理性型"
        merged = " ".join([compact_review["summary"]] + compact_review["turning_points"] + compact_review["mistakes"] + compact_review["suggestions"]).lower()
        if "防守" in merged or "威胁" in merged:
            primary = "稳健防守型"
        elif "进攻" in merged or "施压" in merged:
            primary = "激进进攻型"

        return self._build_personality_from_style_profile(
            {"primary_style": primary, "secondary_style": "均衡理性型", "scores": {}, "reason": "根据复盘特征估计。"},
            review_result,
        )

    def classify_question_intent(self, question: str) -> str:
        self._ensure_client()
        prompt = f"""
你是一个五子棋问题分类器。
只能返回 JSON，不要解释。
类型只能是 moves / explanation / qa / analysis。

用户问题：{question}

返回格式：{{"type":"qa"}}
"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=80,
        )
        parsed = safe_json_loads(response.choices[0].message.content or "")
        intent = str((parsed or {}).get("type", "qa")).strip().lower()
        if intent in {"moves", "explanation", "qa", "analysis"}:
            return intent
        return "qa"

    def generate_move_explanation(self, question: str, step_context: Dict[str, Any], chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._ensure_client()
        evidence = _compact_retrieved_chunks(chunks, limit=2)

        prompt = f"""
    你是五子棋讲解助手。请结合一步棋的上下文，解释“为什么 AI 这样下”。

    问题：
    {question}

    落子上下文：
    {json.dumps(step_context, ensure_ascii=False)}

    策略资料：
    {json.dumps(evidence, ensure_ascii=False)}

    要求：
    1. 所有自然语言输出必须使用简体中文
    2. 不要输出英文标题
    3. 不要输出 Markdown
    4. 只输出 JSON，不要输出任何解释文字或思考过程

    返回格式：
    {{
    "explanation": "用中文解释这一步为什么这样下",
    "evidence": ["中文依据1", "中文依据2"],
    "alternatives": ["中文备选思路1", "中文备选思路2"]
    }}
    """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是严格输出中文 JSON 的五子棋解释助手。除 JSON 外不要输出任何内容。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=260,
            )
            parsed = safe_json_loads(response.choices[0].message.content or "")
            if isinstance(parsed, dict):
                return {
                    "explanation": _clip_text(
                        parsed.get("explanation") or step_context.get("reasoning") or "AI 根据当前局面的攻防关系选择了这一步。",
                        220,
                    ),
                    "evidence": _normalize_string_list(parsed.get("evidence"), max_items=2, fallback=evidence),
                    "alternatives": _normalize_string_list(parsed.get("alternatives"), max_items=2),
                }
        except Exception:
            pass

        return {
            "explanation": _clip_text(step_context.get("reasoning") or "AI 根据当前局面的攻防关系选择了这一步。", 220),
            "evidence": evidence,
            "alternatives": [],
        }

    def generate_move_top3(self, question: str, board: List[List[int]], current_player: int, chunks: List[dict]) -> Dict[str, Any]:
        self._ensure_client()
        context = "\n".join(str(c.get("text", ""))[:900] for c in chunks)
        board_str = "\n".join(" ".join(map(str, row)) for row in board)

        prompt = f"""
你是五子棋 AI 助手。黑棋=1，白棋=2，空位=0。当前用户执黑棋。

棋盘：
{board_str}

用户问题：
{question}

RAG 知识：
{context}

任务：给出最多 3 个黑棋下一步合法候选点。
严格要求：
1. 只推荐空位。
2. move 格式是 [row, col]。
3. reason 必须说明防守价值、进攻价值、优先级理由。
4. 只输出 JSON，不输出 Markdown，不输出推理过程。

格式：
{{
  "top3": [
    {{"move": [7, 7], "reason": "..."}}
  ]
}}
"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_tokens=900,
        )
        parsed = safe_json_loads(response.choices[0].message.content or "")
        if parsed:
            return parsed
        return {"top3": []}

    def generate_qa_answer(self, question: str, chunks: List[dict], board: Optional[List[List[int]]] = None, intent: str = "qa") -> str:
        self._ensure_client()
        context = "\n".join(str(c.get("text", ""))[:900] for c in chunks)

        board_part = ""
        if board is not None and intent == "analysis":
            board_part = "\n当前棋盘：\n" + "\n".join(" ".join(map(str, row)) for row in board) + "\n"

        prompt = f"""
你是一个五子棋讲解助手。

以下是参考知识：
{context}
{board_part}
用户问题：{question}

请直接回答这个问题。
要求：
1. 所有自然语言输出必须使用简体中文
2. 只输出最终答案
3. 不要重复题目或提示词
4. 不要输出“你是一个……”之类说明
5. 不要输出英文标题
6. 用简洁、自然、直接的中文解释
"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )
        return strip_think(response.choices[0].message.content or "")

    def _build_prompt(self, board: List[List[int]], player: str) -> str:
        board_str = "\n".join([str(row) for row in board])
        ai_color = "白棋" if player == "white" else "黑棋"

        return f"""你是一个五子棋 AI。请分析当前棋局并给出最佳落子位置。

当前棋盘状态 (0=空, 1=黑棋, 2=白棋):
黑棋先手，你执{ai_color}。

棋盘:
{board_str}

你必须用以下 JSON 格式回复，不能有其他内容：
{{"x": 整数(0-14), "y": 整数(0-14), "reasoning": "你的思考过程(10字以内)"}}

注意：
1. 只回复 JSON，不要有其他文字
2. x 是列索引(左到右0-14)，y 是行索引(上到下0-14)
3. 选择对自己最有利的落子点
4. 确保选择的位置是空位"""

    def _parse_move_response(self, content: str) -> Dict[str, Any]:
        content = strip_think(content)
        try:
            data = json.loads(content)
            return {
                "x": int(data.get("x", 7)),
                "y": int(data.get("y", 7)),
                "reasoning": str(data.get("reasoning", "")),
            }
        except Exception:
            pass

        match = re.search(r'"x"\s*:\s*(\d+)', content)
        y_match = re.search(r'"y"\s*:\s*(\d+)', content)

        if match and y_match:
            return {
                "x": int(match.group(1)),
                "y": int(y_match.group(1)),
                "reasoning": "Parsed from response",
            }

        return {"x": 7, "y": 7, "reasoning": "Default fallback"}

    def _parse_json_response(self, content: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        parsed = safe_json_loads(content)
        if isinstance(parsed, dict):
            return parsed
        return fallback


llm_client = LLMClient()
