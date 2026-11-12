# Auto-scheduling

## 📰 데일리 브리핑 봇 (날씨 + 네이트 뉴스 Top10)

매일 정해진 시간에 날씨와 [네이트 뉴스](https://news.nate.com/rank/interest) 분야별 **많이 본 뉴스 Top10** 요약을
텔레그램 / 슬랙 / 디스코드로 보내 줍니다. GitHub Actions가 자동으로 실행합니다.

### 하루 일정 (KST)

| 시각 | 내용 | 명령 |
|------|------|------|
| 07시 | 🌤️ 오늘의 날씨 (기온, 시간대별 날씨, 강수확률, 미세먼지, 우산·옷차림 팁) | `weather` |
| 08시 | 🌅 1차 뉴스 브리핑 | `news --edition morning` |
| 12시 | ☀️ 2차 뉴스 브리핑 | `news --edition noon` |
| 16시 | 🌇 3차 뉴스 브리핑 | `news --edition afternoon` |
| 22시 | 🌙 하루 마무리 뉴스 브리핑 + "오늘 하루 한눈에" | `news --edition evening` |

- 2차 브리핑부터는 그날 앞선 브리핑에 없던 기사에 🆕 표시가 붙습니다.
- 08시에 오늘 랭킹이 아직 충분히 쌓이지 않은 분야는 어제 랭킹으로 대신하고, 브리핑에 그 사실을 표시합니다.
- GitHub 예약 실행은 보통 몇 분에서 십여 분 늦게 시작됩니다. 그래서 cron을 정각 10분 전으로 걸어 두었습니다.

### 동작 순서

1. **뉴스 수집** (`briefing_bot/scraper.py`): `news.nate.com/rank/interest?sc=<분야>&p=day&date=<날짜>`에서
   분야별 상위 10개 기사와 본문(최대 2,500자)을 가져옵니다.
2. **요약** (`briefing_bot/summarizer.py`): 분야마다 Claude API를 한 번 호출해 분야 헤드라인 1줄과 기사별 요약을 받습니다.
   22시 브리핑은 분야를 아우르는 하루 정리를 만들기 위해 한 번 더 호출합니다.
3. **날씨** (`briefing_bot/weather.py`): [Open-Meteo](https://open-meteo.com) 예보와 대기질 API를 씁니다. API 키는 필요 없습니다.
4. **전송** (`briefing_bot/notifier.py`): 텔레그램, 슬랙, 디스코드 중 설정된 채널로 보냅니다.
   뉴스 브리핑은 `briefings/YYYY-MM-DD/<순서>-<에디션>.md`로 커밋되어 아카이브로 남습니다.

뉴스 분야 코드는 다음과 같습니다.

| 코드 | 분야 |
|------|------|
| `pol` | 정치 |
| `eco` | 경제 |
| `soc` | 사회 |
| `int` | 세계 |
| `its` | IT/과학 |
| `ent` | 연예 |
| `spo` | 스포츠 |

### 설정 방법 (GitHub Actions)

**Settings → Secrets and variables → Actions**에서 설정합니다.

| 종류 | 이름 | 필수 여부 | 설명 |
|------|------|------|------|
| Secret | `ANTHROPIC_API_KEY` | 필수 | Claude API 키 (뉴스 요약에 사용) |
| Secret | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | 선택 | 텔레그램 전송 (@BotFather로 봇 생성) |
| Secret | `SLACK_WEBHOOK_URL` | 선택 | 슬랙 Incoming Webhook |
| Secret | `DISCORD_WEBHOOK_URL` | 선택 | 디스코드 Webhook |
| Variable | `WEATHER_LOCATIONS` | 선택 | 날씨 지역 `이름:위도:경도`, 쉼표로 여러 개. 기본값은 `서울:37.5665:126.9780` |
| Variable | `NATE_SECTIONS` | 선택 | 뉴스 분야 (예: `pol,eco,its`). 기본값은 전체 7개 분야 |

- 예약 실행은 **기본 브랜치**에 있는 워크플로만 동작합니다.
- **Actions → Daily Briefing → Run workflow**에서 작업을 골라 수동으로 실행할 수 있습니다.
- 시각을 바꾸려면 `.github/workflows/daily-briefing.yml`의 `cron`(UTC 기준)과 바로 아래 `case` 매핑을 함께 수정하세요.

### 로컬 실행

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python -m briefing_bot.main weather --no-send                 # 전송 없이 출력만
python -m briefing_bot.main news --edition noon --no-send
python -m briefing_bot.main news --edition evening --sections pol,eco
python -m briefing_bot.main news --no-summary --no-send       # API 키 없이 제목만 수집
python -m briefing_bot.main auto                              # 현재 시각에 맞는 작업 실행 (cron 서버용)
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
- 기사 저작권은 각 언론사에 있습니다. 개인 브리핑 용도로만 사용하세요.
