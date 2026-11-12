"""같은 날 앞선 브리핑과 겹치는 기사, 분야끼리 겹치는 기사를 걸러낸다."""

from __future__ import annotations

import re
from pathlib import Path

from .scraper import Article

# 브리핑 마크다운의 기사 줄: "3. **[제목](https://news.nate.com/view/...)** _(언론사)_"
ARTICLE_LINE_RE = re.compile(r"\*\*\[(.+?)\]\((https://news\.nate\.com/view/[^)\s]+)\)\*\*")

SIMILARITY = 0.6  # 제목 글자 2-gram 의 자카드 유사도가 이 이상이면 같은 소식으로 본다


def previous_articles(day_dir: Path, earlier_files: list[str]) -> list[tuple[str, str]]:
    """같은 날 앞선 브리핑 파일들에서 (제목, URL) 목록을 읽는다."""
    out: list[tuple[str, str]] = []
    for name in earlier_files:
        f = day_dir / name
        if f.exists():
            out += ARTICLE_LINE_RE.findall(f.read_text(encoding="utf-8"))
    return out


def _bigrams(title: str) -> set[str]:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", title)  # [속보], (종합) 같은 머리말 제거
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", t).lower()
    return {t[i : i + 2] for i in range(len(t) - 1)}


def similar(a: str, b: str) -> bool:
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return False
    return len(ga & gb) / len(ga | gb) >= SIMILARITY


def filter_new(
    collected: dict[str, list[Article]],
    previous: list[tuple[str, str]],
    top_n: int,
) -> tuple[dict[str, list[Article]], int]:
    """앞선 브리핑·다른 분야와 겹치지 않는 기사만 분야별 최대 top_n 개 남긴다.

    순위는 네이트 원래 순위를 유지한다. (겹친 기사 수도 함께 반환)
    """
    seen_urls = {url for _, url in previous}
    seen_titles = [title for title, _ in previous]
    dropped = 0
    result: dict[str, list[Article]] = {}
    for section, articles in collected.items():
        kept: list[Article] = []
        for art in articles:
            if len(kept) >= top_n:
                break
            if art.url in seen_urls or any(similar(art.title, t) for t in seen_titles):
                dropped += 1
                continue
            kept.append(art)
            seen_urls.add(art.url)
            seen_titles.append(art.title)
        result[section] = kept
    return result, dropped
