# Auto-scheduling

## 📰 데일리 브리핑 봇 (날씨 + 네이트 뉴스 Top10)

매일 정해진 시간에 날씨와 [네이트 뉴스](https://news.nate.com/rank/interest) 분야별 **많이 본 뉴스 Top10** 요약을
텔레그램으로 보내 줍니다. GitHub Actions가 자동으로 실행합니다.

### 하루 일정 (KST)

| 시각 | 내용 | 명령 |
|------|------|------|
| 07:30 | 🌤️ 오늘의 날씨 (기온, 시간대별 날씨, 강수확률, 미세먼지, 우산·옷차림 팁) | `weather --edition morning` |
| 08시 | 🌅 1차 뉴스 브리핑 | `news --edition morning` |
| 12시 | ☀️ 2차 뉴스 브리핑 | `news --edition noon` |
| 16시 | 🌇 3차 뉴스 브리핑 | `news --edition afternoon` |
| 17시 | 🌆 저녁 날씨 & 내일 예보 (저녁·밤 날씨, 내일 기온·강수확률, 퇴근길 우산 팁) | `weather --edition evening` |
| 22시 | 🌙 하루 마무리 뉴스 브리핑 + "오늘 하루 한눈에" | `news --edition evening` |

- 같은 날 앞선 브리핑에 이미 나온 기사, 여러 분야에 겹친 기사, 제목이 거의 같은 기사는 빼고 보냅니다. 빠진 만큼 다음 순위 기사로 채워 분야별 최대 10개를 보냅니다.
- 08시에 오늘 랭킹이 아직 충분히 쌓이지 않은 분야는 어제 랭킹으로 대신하고, 브리핑에 그 사실을 표시합니다.
- GitHub 예약 실행은 몇 분에서 30분가량 늦게 시작됩니다. 그래서 cron을 목표 시각보다 일찍 걸어 두었습니다.
- 늦게 온 예약 실행과 수동 실행이 겹쳐도 같은 브리핑은 한 번만 갑니다. 수동 실행(Run workflow)은 항상 다시 보냅니다.

### 📈 증시 리포트 (거래일만)

| 시각 (KST) | 내용 | 명령 |
|------|------|------|
| 08:30 (화~토) | 🌅 아침 증시 브리핑: 간밤 미국 증시(S&P500·나스닥·다우·반도체·VIX), 환율·달러인덱스·유가·금·미 10년물 금리·비트코인, 관심 종목 + 오늘 국내장 체크포인트 | `stock --edition morning` |
| 16:10 (월~금) | 📊 장 마감 증시 리포트: 코스피·코스닥, 아시아 증시(닛케이·상해·항셍), 원/달러·원/엔, 관심 종목 + 오늘 장 정리 | `stock --edition close` |

- 시세는 [Yahoo Finance](https://finance.yahoo.com) 차트 API에서 가져옵니다. API 키는 필요 없습니다.
- 종목마다 전일 대비 등락, 5일·20일 수익률, RSI(14)를 계산하고, 눈에 띄는 움직임에 신호를 붙입니다:
  🚀 52주 신고가 / 🧊 52주 신저가, ↗️ 20일선 돌파 / ↘️ 20일선 이탈, 🔥 과열(RSI 70↑) / 🥶 과매도(RSI 30↓),
  📢 거래량 급증(20일 평균의 2배↑), ⚡ 급등·급락(±5%↑).
- Claude가 시세와 네이트 경제 분야 많이 본 뉴스 제목을 함께 보고 한 줄 요약, 시장 코멘트, 체크포인트를 씁니다.
  매수/매도 추천은 하지 않도록 지시해 두었습니다.
- 휴장일은 자동으로 건너뜁니다. 아침 리포트는 미국장이 전날 열렸는지, 마감 리포트는 코스피가 오늘 거래됐는지로 판단합니다.
- 리포트는 `briefings/YYYY-MM-DD/stock-<morning|close>.md`로 아카이브됩니다.

**관심 종목 바꾸기**: 저장소 Settings → Secrets and variables → Actions → **Variables** 탭에서
`STOCK_WATCHLIST`를 만들고 `이름:야후심볼`을 쉼표로 이어 적습니다.

```
삼성전자:005930.KS,SK하이닉스:000660.KS,에코프로:086520.KQ,엔비디아:NVDA,애플:AAPL
```

- 코스피 종목은 `6자리코드.KS`, 코스닥 종목은 `6자리코드.KQ`, 미국 종목은 티커(`NVDA`) 그대로 씁니다.
- 비워 두면 기본값(삼성전자·SK하이닉스·현대차, 국내 ETF 4종, 미국 종목 15종(스페이스X, 엔비디아, 팔란티어, 테슬라 등))을 씁니다.

### 동작 순서

1. **뉴스 수집** (`briefing_bot/scraper.py`): `news.nate.com/rank/interest?sc=<분야>&p=day&date=<날짜>`에서
   분야별 상위 10개 기사와 본문(최대 2,500자)을 가져옵니다.
2. **요약** (`briefing_bot/summarizer.py`): 분야마다 Claude API를 한 번 호출해 분야 헤드라인 1줄과 기사별 요약을 받습니다.
   22시 브리핑은 분야를 아우르는 하루 정리를 만들기 위해 한 번 더 호출합니다.
3. **날씨** (`briefing_bot/weather.py`): [Open-Meteo](https://open-meteo.com) 예보와 대기질 API를 씁니다. API 키는 필요 없습니다.
4. **전송** (`briefing_bot/notifier.py`): 텔레그램으로 보냅니다.
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

### 설정 방법 (처음 한 번만, 약 10분)

준비물은 휴대폰 텔레그램 앱, GitHub 계정, Claude API 키 세 가지입니다.
값은 모두 **GitHub 저장소 설정**에 넣습니다. 텔레그램에는 봇만 만들고, 거기서 받은 값을 GitHub에 옮겨 적는 구조입니다.

#### 1단계 — 텔레그램 봇 만들기 → `토큰` 받기

1. 텔레그램에서 **@BotFather**를 검색해 대화를 시작합니다 (파란 체크 표시가 있는 공식 계정).
2. `/newbot`을 보냅니다.
3. 봇 이름을 입력합니다 (예: `내 뉴스 브리핑`).
4. 봇 아이디를 입력합니다. 반드시 `bot`으로 끝나야 합니다 (예: `my_daily_brief_bot`).
5. BotFather가 `123456789:AAH...` 같은 긴 문자열을 줍니다. 이것이 **봇 토큰**이니 복사해 두세요.
   토큰은 비밀번호와 같으니 다른 사람에게 보여 주지 마세요.

#### 2단계 — 내 `채팅 ID` 알아내기

1. 방금 만든 봇을 텔레그램에서 검색해 열고 **시작(Start)**을 누른 뒤 아무 메시지(예: `안녕`)나 보냅니다.
   이 단계를 건너뛰면 봇이 나에게 메시지를 보낼 수 없습니다.
2. PC나 휴대폰 브라우저 주소창에 아래 주소를 입력합니다. `<토큰>` 자리에는 1단계의 토큰을 넣습니다.
   ```
   https://api.telegram.org/bot<토큰>/getUpdates
   ```
3. 화면에 나온 글자 중 `"chat":{"id":123456789` 부분의 숫자가 **채팅 ID**입니다. 복사해 두세요.
   결과가 `"result":[]`처럼 비어 있으면 봇에게 메시지를 한 번 더 보내고 새로고침하세요.

#### 3단계 — Claude API 키 만들기

1. https://console.anthropic.com 에 로그인합니다.
2. **API Keys → Create Key**로 키를 만들고 복사합니다 (`sk-ant-...`로 시작).
3. **Billing**에서 결제 수단을 등록하거나 크레딧을 충전합니다.

#### 4단계 — GitHub에 값 3개 등록 (Secret)

1. GitHub에서 이 저장소 페이지를 열고 **Settings** 탭을 누릅니다.
2. 왼쪽 메뉴에서 **Secrets and variables → Actions**를 엽니다.
3. **New repository secret**을 눌러 아래 3개를 하나씩 등록합니다. 이름은 철자까지 똑같이 입력해야 합니다.

| Name | Secret (값) |
|------|------|
| `TELEGRAM_BOT_TOKEN` | 1단계의 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 2단계의 채팅 ID 숫자 |
| `ANTHROPIC_API_KEY` | 3단계의 Claude API 키 |

#### 5단계 — 기본 브랜치에 합치기

예약 실행은 저장소의 **기본 브랜치(main)**에 있는 설정만 동작합니다. 이 작업 브랜치를 main에 병합(merge)하세요.

#### 6단계 — 테스트 실행

1. 저장소의 **Actions** 탭 → 왼쪽 **Daily Briefing** → 오른쪽 **Run workflow**를 누릅니다.
2. task에서 `weather`를 고르고 실행하면 1~2분 안에 텔레그램으로 날씨가 옵니다.
3. 같은 방법으로 `morning`을 실행해 뉴스 브리핑이 오는지 확인합니다.
4. 실행에 실패하면(빨간 X) 해당 실행을 눌러 로그를 확인하세요. 대부분 Secret 이름 오타이거나, 봇에게 먼저 메시지를 보내지 않은 경우입니다.

여기까지 하면 매일 07·08·12·16·22시에 자동으로 메시지가 옵니다.

#### (선택) 바꾸고 싶을 때

같은 화면의 **Variables** 탭에서 등록합니다.

| Name | 예시 | 설명 |
|------|------|------|
| `WEATHER_LOCATIONS` | `화성 동탄9동:37.1830:127.1130,화성 반월동:37.2220:127.0650` | 날씨 지역 `이름:위도:경도`. 쉼표로 여러 곳을 넣을 수 있습니다. 기본값은 동탄9동과 반월동입니다 |
| `NATE_SECTIONS` | `pol,eco,its` | 받을 뉴스 분야. 기본값은 7개 분야 전체입니다 |

시각을 바꾸려면 `.github/workflows/daily-briefing.yml`의 `cron`(UTC 기준)과 그 아래 `case` 매핑을 함께 수정하세요.

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
