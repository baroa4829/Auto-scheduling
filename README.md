# Auto-scheduling

## 📰 네이트 뉴스 분야별 Top10 브리핑 봇

매일 아침 [네이트 뉴스](https://news.nate.com/rank/interest) 분야별 **많이 본 뉴스 Top10**을 모아
Claude가 기사별 1~2문장으로 요약하고, 텔레그램 / 슬랙 / 디스코드로 보내 주는 봇입니다.
GitHub Actions에서 매일 자동으로 실행됩니다.

### 동작 순서

1. **수집** (`briefing_bot/scraper.py`): `news.nate.com/rank/interest?sc=<분야>&p=day&date=<날짜>`에서
   분야별 상위 10개 기사를 가져오고, 기사 본문을 최대 2,500자까지 수집합니다.
2. **요약** (`briefing_bot/summarizer.py`): 분야마다 Claude API를 한 번 호출해 분야 헤드라인 1줄과
   기사별 요약을 JSON(structured output)으로 받습니다.
3. **전송** (`briefing_bot/notifier.py`): 마크다운 브리핑을 `briefings/YYYY-MM-DD.md`에 저장하고,
   설정된 채널로 보냅니다.

기본 분야는 다음과 같습니다.

| 코드 | 분야 |
|------|------|
| `pol` | 정치 |
| `eco` | 경제 |
| `soc` | 사회 |
| `int` | 세계 |
| `its` | IT/과학 |
| `ent` | 연예 |
| `spo` | 스포츠 |

### 브리핑 예시

```
## 경제
> 환율 급등과 반도체 수출 호조가 엇갈린 하루였다.

1. **[원·달러 환율 1,450원 돌파…](https://news.nate.com/view/...)** _(연합뉴스)_
   - 원·달러 환율이 장중 1,450원을 넘어 2년 만에 최고치를 기록했다. …
```

### 설정 방법 (GitHub Actions)

저장소의 **Settings → Secrets and variables → Actions**에서 Secret을 등록합니다.

| Secret | 필수 여부 | 설명 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | 필수 | Claude API 키 |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 선택 | 텔레그램 전송 (@BotFather로 봇 생성) |
| `SLACK_WEBHOOK_URL` | 선택 | 슬랙 Incoming Webhook |
| `DISCORD_WEBHOOK_URL` | 선택 | 디스코드 Webhook |

- 받을 분야를 바꾸려면 Variables에 `NATE_SECTIONS`(예: `pol,eco,its`)를 추가합니다.
- 실행 시각은 `.github/workflows/nate-briefing.yml`의 `cron`으로 정합니다. 기본값은 매일 **06:47 KST**이며, 전날 랭킹을 요약합니다.
- **Actions → Nate News Top10 Briefing → Run workflow**에서 날짜와 분야를 지정해 수동으로 실행할 수도 있습니다.
- 생성된 브리핑은 `briefings/` 폴더에 커밋되어 아카이브로 남고, Actions 실행 요약 화면에도 표시됩니다.

### 로컬 실행

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python -m briefing_bot.main --yesterday --no-send            # 전송 없이 출력과 파일 저장만
python -m briefing_bot.main --date 20261111 --sections pol,eco
python -m briefing_bot.main --no-summary --no-send           # API 키 없이 제목만 수집
```

| 환경변수 | 기본값 | 설명 |
|------|------|------|
| `CLAUDE_MODEL` | `claude-opus-5-5` | 요약에 쓸 모델 |
| `CLAUDE_EFFORT` | `low` | 요약 깊이 (`low`/`medium`/`high`) |
| `TOP_N` | `10` | 분야별 기사 수 |

### 테스트

```bash
pip install pytest && python -m pytest -q
```

### 참고

- 네이트 페이지 구조가 바뀌면 `scraper.py`의 선택자(`BODY_SELECTORS`, 랭킹 영역)를 조정해야 합니다.
  랭킹 영역을 찾지 못하면 페이지 전체에서 `/view/` 기사 링크를 순서대로 모으는 방식으로 대체됩니다.
- 기사 저작권은 각 언론사에 있습니다. 개인 브리핑 용도로만 사용하세요.
