"""네이트 뉴스 분야별 랭킹 페이지 및 기사 본문 스크래퍼."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://news.nate.com"
RANK_URL = BASE_URL + "/rank/interest"

# 네이트 뉴스 랭킹 페이지의 분야 코드(sc 파라미터) → 표시 이름
SECTIONS: dict[str, str] = {
    "pol": "정치",
    "eco": "경제",
    "soc": "사회",
    "int": "세계",
    "its": "IT/과학",
    "ent": "연예",
    "spo": "스포츠",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 기사 링크 형태: //news.nate.com/view/20261112n12345?mid=n1006
ARTICLE_RE = re.compile(r"/view/(\d{8}n\d+)")

# 본문 컨테이너 후보 (네이트 기사 페이지 구조 변경에 대비해 여러 개 시도)
BODY_SELECTORS = [
    "#realArtcContents",
    "#articleContetns",
    "#articleContents",
    ".articleContetns",
    "#RealArtcContents",
    "article",
]

MAX_BODY_CHARS = 2500  # 기사당 요약에 넘기는 본문 길이 (비용 관리용)


@dataclass
class Article:
    rank: int
    title: str
    url: str
    press: str = ""
    body: str = ""
    extra: dict = field(default_factory=dict)


def _get(session: requests.Session, url: str, *, retries: int = 3) -> str:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return _decode(resp)
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"요청 실패: {url}") from last_exc


def _decode(resp: requests.Response) -> str:
    """네이트는 EUC-KR(CP949) 페이지가 섞여 있어 charset을 직접 판별한다."""
    raw = resp.content
    head = raw[:2048].decode("ascii", errors="ignore").lower()
    m = re.search(r"charset=[\"']?([\w-]+)", head)
    candidates = []
    if m:
        candidates.append(m.group(1))
    if resp.encoding:
        candidates.append(resp.encoding)
    candidates += ["utf-8", "cp949"]
    for enc in candidates:
        enc = "cp949" if enc.lower() in ("euc-kr", "euckr", "ks_c_5601-1987") else enc
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_url(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return BASE_URL + href
    return href


def _extract_articles(scope, top_n: int) -> list[Article]:
    articles: list[Article] = []
    seen: set[str] = set()
    for a in scope.find_all("a", href=True):
        m = ARTICLE_RE.search(a["href"])
        if not m or m.group(1) in seen:
            continue
        title_el = a.select_one("h2, strong, .tit") or a
        title = _clean(title_el.get_text(" "))
        if len(title) < 5:  # 이미지 전용 링크 등은 건너뛰고 같은 기사의 텍스트 링크를 기다림
            continue
        seen.add(m.group(1))

        press = ""
        container = a.find_parent(["li", "div", "dl"])
        if container:
            press_el = container.select_one(".medium, .press")
            if press_el:
                # "언론사 2026-11-12 09:00" 형태에서 날짜(<em>)를 빼고 언론사만 추출
                em = press_el.find("em")
                text = press_el.get_text(" ")
                if em:
                    text = text.replace(em.get_text(" "), "")
                press = _clean(text)

        articles.append(
            Article(
                rank=len(articles) + 1,
                title=title,
                url=_normalize_url(a["href"]).split("?")[0],
                press=press,
            )
        )
        if len(articles) >= top_n:
            break
    return articles


def fetch_ranking(
    session: requests.Session, section: str, day: date, top_n: int = 10
) -> list[Article]:
    """분야별 '많이 본 뉴스' 랭킹 상위 top_n 개 기사 목록을 가져온다."""
    url = f"{RANK_URL}?sc={section}&p=day&date={day:%Y%m%d}"
    soup = BeautifulSoup(_get(session, url), "html.parser")

    # 랭킹 영역 후보: 알려진 컨테이너 → 그 상위 요소들 → 페이지 전체.
    # 1~5위와 6~10위가 서로 다른 블록에 있는 경우가 있어,
    # top_n 개를 채우는 가장 좁은 영역을 고른다.
    candidates = []
    for sel in (".postRankSubjectList", ".mduRankSubject", "#newsContents"):
        el = soup.select_one(sel)
        while el is not None and el.name != "[document]":
            candidates.append(el)
            el = el.parent
    candidates.append(soup)

    articles: list[Article] = []
    for scope in candidates:
        found = _extract_articles(scope, top_n)
        if len(found) > len(articles):
            articles = found
        if len(articles) >= top_n:
            break

    if len(articles) < top_n:
        # 다음 수정 때 참고할 수 있도록 기사 링크를 담은 컨테이너 class 를 기록
        holders = []
        for a in soup.find_all("a", href=ARTICLE_RE):
            parent = a.find_parent(class_=True)
            if parent is not None:
                holders.append(".".join(parent.get("class", [])))
        log.warning(
            "[%s] 랭킹 기사 %d/%d건만 찾음. 링크 컨테이너: %s",
            section, len(articles), top_n, sorted(set(holders))[:15],
        )
    if not articles:
        log.warning("[%s] 랭킹 기사를 찾지 못했습니다: %s", section, url)
    return articles


def fetch_body(session: requests.Session, article: Article) -> None:
    """기사 본문을 가져와 article.body 에 채운다. 실패해도 예외를 던지지 않는다."""
    try:
        soup = BeautifulSoup(_get(session, article.url), "html.parser")
    except RuntimeError as exc:
        log.warning("본문 수집 실패 (%s): %s", article.url, exc)
        return

    body = ""
    for sel in BODY_SELECTORS:
        el = soup.select_one(sel)
        if el:
            for junk in el.select("script, style, figure, figcaption, .ad, iframe"):
                junk.decompose()
            body = _clean(el.get_text(" "))
            if len(body) > 100:
                break

    if len(body) <= 100:
        meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find(
            "meta", attrs={"name": "description"}
        )
        if meta and meta.get("content"):
            body = _clean(meta["content"])

    article.body = body[:MAX_BODY_CHARS]


def collect(
    sections: dict[str, str], day: date, top_n: int = 10, delay: float = 0.3
) -> dict[str, list[Article]]:
    """모든 분야의 랭킹 + 본문을 수집한다."""
    result: dict[str, list[Article]] = {}
    with requests.Session() as session:
        for code, name in sections.items():
            try:
                articles = fetch_ranking(session, code, day, top_n)
            except RuntimeError as exc:
                log.error("[%s] 랭킹 수집 실패: %s", name, exc)
                articles = []
            for art in articles:
                fetch_body(session, art)
                time.sleep(delay)  # 서버 부하 방지
            log.info("[%s] %d건 수집", name, len(articles))
            result[name] = articles
    return result
