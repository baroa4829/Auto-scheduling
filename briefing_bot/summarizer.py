"""Claude API로 분야별 Top10 기사를 요약한다."""

from __future__ import annotations

import json
import logging
import os

import anthropic

from .scraper import Article

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CLAUDE_EFFORT", "low")  # 요약 작업은 low 로 충분

SYSTEM_PROMPT = """\
당신은 한국 뉴스 브리핑 에디터입니다. 네이트 뉴스 분야별 '많이 본 뉴스' 상위 기사를 받아
바쁜 독자가 출근길 1~2분 안에 읽을 수 있는 브리핑을 작성합니다.

규칙:
- 각 기사마다 핵심 사실(누가/무엇을/왜/수치)을 1~2문장, 120자 이내로 요약합니다.
- 기사에 없는 내용은 추측하거나 덧붙이지 않습니다. 본문이 비어 있으면 제목만으로 짧게 요약합니다.
- 자극적인 표현은 중립적으로 바꾸고, 존댓말이 아닌 간결한 '~했다/~이다' 체를 씁니다.
- headline 은 해당 분야 오늘의 흐름을 한 문장(60자 이내)으로 정리합니다.
- items 는 입력 순위를 그대로 유지합니다.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "summary": {"type": "string"},
                },
                "required": ["rank", "summary"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "items"],
    "additionalProperties": False,
}


def _build_prompt(section: str, articles: list[Article]) -> str:
    parts = [f"[분야] {section}\n"]
    for art in articles:
        parts.append(
            f"<article rank=\"{art.rank}\">\n"
            f"제목: {art.title}\n"
            f"언론사: {art.press or '알 수 없음'}\n"
            f"본문: {art.body or '(본문 없음)'}\n"
            f"</article>"
        )
    return "\n".join(parts)


OVERVIEW_PROMPT = """\
당신은 한국 뉴스 브리핑 에디터입니다. 오늘 하루 분야별 '많이 본 뉴스' 요약을 받아
하루를 마무리하는 '오늘 하루 한눈에' 3~5개 항목을 작성합니다.

규칙:
- 분야를 가로질러 오늘 가장 중요하거나 화제가 된 흐름을 고릅니다.
- 각 항목은 한 문장, 80자 이내, '~했다/~이다' 체로 씁니다.
- 입력에 없는 내용은 추측하지 않습니다.
"""

OVERVIEW_SCHEMA = {
    "type": "object",
    "properties": {"points": {"type": "array", "items": {"type": "string"}}},
    "required": ["points"],
    "additionalProperties": False,
}


def _ask_json(client: anthropic.Anthropic, system: str, schema: dict, content: str, label: str) -> dict:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system,
        output_config={
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": schema},
        },
        # 안전 분류기가 요청을 거절하면 서버가 자동으로 대체 모델로 재시도
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"[{label}] 요약 요청이 거절되었습니다")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"[{label}] 응답이 max_tokens 에서 잘렸습니다")

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def summarize_section(
    client: anthropic.Anthropic, section: str, articles: list[Article], tone: str = ""
) -> dict:
    """한 분야의 기사들을 요약해 {"headline": str, "items": [{rank, summary}]} 를 반환."""
    system = SYSTEM_PROMPT + (f"\n{tone}\n" if tone else "")
    return _ask_json(client, system, SCHEMA, _build_prompt(section, articles), section)


def summarize_overview(
    collected: dict[str, list[Article]], summaries: dict[str, dict]
) -> list[str]:
    """하루 마무리용: 분야를 가로지르는 '오늘 하루 한눈에' 항목들."""
    parts = []
    for section, articles in collected.items():
        summ = {it["rank"]: it["summary"] for it in summaries.get(section, {}).get("items", [])}
        parts.append(f"[{section}] {summaries.get(section, {}).get('headline', '')}")
        parts += [f"- {a.title}: {summ.get(a.rank, '')}" for a in articles]
    try:
        out = _ask_json(anthropic.Anthropic(), OVERVIEW_PROMPT, OVERVIEW_SCHEMA, "\n".join(parts), "overview")
        return out["points"]
    except (anthropic.APIError, RuntimeError, json.JSONDecodeError, KeyError) as exc:
        log.error("하루 정리 요약 실패: %s", exc)
        return []


def summarize_all(collected: dict[str, list[Article]], tone: str = "") -> dict[str, dict]:
    client = anthropic.Anthropic()
    results: dict[str, dict] = {}
    for section, articles in collected.items():
        if not articles:
            continue
        try:
            results[section] = summarize_section(client, section, articles, tone)
            log.info("[%s] 요약 완료", section)
        except (anthropic.APIError, RuntimeError, json.JSONDecodeError) as exc:
            log.error("[%s] 요약 실패, 제목만 사용: %s", section, exc)
            results[section] = {
                "headline": "",
                "items": [{"rank": a.rank, "summary": ""} for a in articles],
            }
    return results
