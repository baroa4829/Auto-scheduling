"""Claude API로 채팅 대화에서 약속(일정)을 추출한다."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Callable, Protocol, Sequence

import anthropic

from .models import ChatMessage, ExtractionResult
from .store import StoredEvent
from .usage import Usage, from_response

log = logging.getLogger(__name__)

_WEEKDAYS = "월화수목금토일"

SYSTEM_PROMPT = """\
당신은 한국어 메신저(카카오톡, 당근) 대화에서 사용자가 실제로 참여할 약속·일정을 찾아 구글 캘린더 항목으로 정리하는 도우미입니다.

규칙
- '나'는 캘린더 주인입니다. 대화 참여자끼리 만나거나, 거래하거나, 참석하기로 한 일정만 뽑습니다.
  광고, 공지 전달, 남의 일정 이야기, 이미 지난 일에 대한 회상은 제외합니다.
- 상대적 날짜(내일, 모레, 이번 주 토요일, 다음 주 화요일, 저녁 7시 등)는 해당 메시지가 보내진 시각을 기준으로 절대 날짜로 바꿉니다.
  '저녁 7시'처럼 오전/오후가 애매하면 상식적으로 해석합니다 (저녁·밤 → 오후, '3시에 만나요' 같은 만남은 보통 오후).
- 날짜는 정해졌지만 시각이 없으면 all_day=true 로 하고 start 에 날짜만 씁니다.
- 날짜를 전혀 특정할 수 없으면 일정으로 만들지 않습니다.
- 한쪽이 제안만 하고 상대가 동의하지 않았으면 status=tentative, 서로 동의했거나(좋아요, 네, 그때 봬요 등) 당근 '약속 잡기' 알림처럼 확정 메시지가 있으면 confirmed 입니다.
- '이미 등록된 일정' 목록에 같은 약속이 있으면 새로 만들지 마세요. 시간·장소가 바뀌었으면 action=update, 취소됐으면 action=cancel 로 그 id 를 existing_event_id 에 넣습니다. 바뀐 게 없으면 아무것도 출력하지 않습니다.
- 제목은 짧게: 상대 이름/채팅방 + 목적. 당근 거래는 '당근 거래: 물건명 (상대 닉네임)' 형식을 권장합니다.
- 일정이 없으면 events 를 빈 배열로 반환합니다.
"""

# 비용 절약용 1차 필터: 날짜·시간·약속 관련 표현이 전혀 없으면 Claude를 호출하지 않는다.
_SCHEDULE_HINT = re.compile(
    r"\d{1,2}\s*(시|:\d{2}|월|일|분)|오늘|내일|모레|글피|이번\s*주|다음\s*주|담주|주말|"
    r"[월화수목금토일]요일|아침|점심|저녁|밤|새벽|오전|오후|약속|만나|만날|봬|뵙|보자|볼까|"
    r"거래|직거래|예약|일정|미팅|회의|모임|취소|미루|당기|바꿔|변경|언제|몇\s*시"
)


def looks_like_schedule(text: str) -> bool:
    return bool(_SCHEDULE_HINT.search(text))


def _fmt_ts(ts: datetime) -> str:
    return f"{ts:%Y-%m-%d}({_WEEKDAYS[ts.weekday()]}) {ts:%H:%M}"


def build_prompt(
    messages: Sequence[ChatMessage],
    existing: Sequence[StoredEvent],
    source_label: str,
    room: str,
) -> str:
    lines = [f"앱: {source_label}", f"채팅방: {room}", ""]
    lines.append("이미 등록된 일정:")
    if existing:
        for e in existing:
            lines.append(
                f"- id={e.id} | {e.title} | 시작 {e.start} | 종료 {e.end or '-'} | "
                f"장소 {e.location or '-'} | {e.status}"
            )
    else:
        lines.append("- (없음)")
    lines.append("")
    lines.append("대화 (보낸 시각 | 보낸 사람: 내용):")
    for m in messages:
        text = m.text.replace("\n", " / ")
        lines.append(f"[{_fmt_ts(m.timestamp)}] {m.sender}: {text}")
    return "\n".join(lines)


class Extractor(Protocol):
    def extract(
        self, messages: Sequence[ChatMessage], existing: Sequence[StoredEvent],
        source_label: str, room: str,
    ) -> ExtractionResult: ...


class ClaudeExtractor:
    def __init__(
        self,
        model: str = "claude-opus-5-5",
        client: anthropic.Anthropic | None = None,
        on_usage: Callable[[Usage, str, str], None] | None = None,
    ):
        self.model = model
        self.client = client or anthropic.Anthropic()
        # 호출마다 (사용량, 앱, 채팅방) 을 넘겨받는 콜백 — 보통 Store.record_usage
        self.on_usage = on_usage

    def extract(
        self, messages: Sequence[ChatMessage], existing: Sequence[StoredEvent],
        source_label: str, room: str,
    ) -> ExtractionResult:
        if not messages:
            return ExtractionResult(events=[])
        prompt = build_prompt(messages, existing, source_label, room)
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=ExtractionResult,
            output_config={"effort": "medium"},
            # 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        usage = from_response(response)
        log.info("Claude 토큰 사용 [%s / %s] %s", source_label, room, usage.describe())
        if self.on_usage is not None:
            self.on_usage(usage, source_label, room)
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            log.warning("Claude가 요청을 거절했습니다 (category=%s). 이 대화는 건너뜁니다.", category)
            return ExtractionResult(events=[])
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            log.warning("응답을 해석하지 못했습니다 (stop_reason=%s).", response.stop_reason)
            return ExtractionResult(events=[])
        return response.parsed_output
