# Auto-scheduling

카카오톡·당근 채팅에서 약속을 찾아 **구글 캘린더에 자동으로 등록**합니다.
"내일 저녁 7시 강남역 어때?" → "좋아!" 같은 대화를 Claude가 읽고, 날짜·시간·장소를 정리해 일정으로 만듭니다.
시간이 바뀌면(“8시로 미룰까?”) 일정을 수정하고, 취소되면 제목에 `[취소]`를 붙입니다.

## 두 가지 버전

| 버전 | 위치 | 이럴 때 추천 |
|---|---|---|
| **구글 앱스 스크립트** (추천) | [`apps-script/`](apps-script/README.md) | 안드로이드 폰 알림으로 실시간 등록. **PC·서버가 필요 없습니다** |
| Python | 이 문서 아래 | 카카오톡 '대화 내보내기' 파일을 PC에서 한꺼번에 처리하거나, 직접 서버를 운영할 때 |

👉 처음이라면 **[앱스 스크립트 설치 안내](apps-script/README.md)**부터 보세요. 아래 내용은 Python 버전 설명입니다.

## 먼저 알아둘 점: 채팅을 어떻게 읽어오나

카카오톡과 당근은 **개인 채팅을 읽을 수 있는 공식 API를 제공하지 않습니다.** 그래서 다음 두 가지 방법을 씁니다.

| 방법 | 카카오톡 | 당근 | 자동 여부 | 필요한 것 |
|---|---|---|---|---|
| **① 휴대폰 알림 전달** (추천) | ✅ | ✅ | 실시간 자동 | **안드로이드** 폰 + 자동화 앱(MacroDroid/Tasker) |
| **② 대화 내보내기 파일** | ✅ | ❌ | 수동 | 카카오톡 `대화 내보내기` txt 파일 (아이폰도 가능) |

- **아이폰**은 다른 앱의 알림을 읽을 수 없어서 ① 방식이 불가능합니다. 카카오톡은 ② 방식만, 당근은 지원이 어렵습니다.
- 알림 방식은 **알림이 뜨는 메시지만** 볼 수 있습니다. 채팅방을 열어둔 상태라 알림이 안 오거나, 알림을 꺼둔 방은 읽지 못합니다.
  알림 미리보기(메시지 내용 표시)가 켜져 있어야 합니다.
- 채팅 내용은 일정 추출을 위해 **Claude API(Anthropic)로 전송**됩니다. 날짜·시간·약속 관련 단어가 없는 메시지("ㅋㅋㅋ" 등)는 보내지 않습니다.

```
[안드로이드 폰]                          [서버: PC / 라즈베리파이 / 클라우드]
 카카오톡·당근 알림                         autoscheduler serve
   └ MacroDroid ── HTTP POST ──────────▶  /webhook/notification
                                             ├ SQLite에 저장 (같은 방 최근 대화 = 문맥)
 카톡 대화 내보내기 .txt                     ├ Claude: 약속 추출 (생성/수정/취소, 확정/미정)
   └ autoscheduler import-kakao ───────▶    └ Google Calendar API로 등록
```

## 1. 설치

Python 3.10 이상이 필요합니다.

```bash
git clone <이 저장소> && cd Auto-scheduling
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env    # 열어서 값 채우기
```

## 2. Claude API 키

1. https://console.anthropic.com 에서 API 키 발급
2. `.env`의 `ANTHROPIC_API_KEY=` 에 입력

## 3. 구글 캘린더 API 준비 (최초 1회)

1. https://console.cloud.google.com 에서 새 프로젝트 생성
2. **API 및 서비스 → 라이브러리** → `Google Calendar API` 사용 설정
3. **OAuth 동의 화면** → 외부(External) → 앱 이름 입력 → **테스트 사용자**에 본인 구글 계정 추가
4. **사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID → 데스크톱 앱**
5. JSON 다운로드 → 프로젝트 폴더에 `credentials.json` 으로 저장
6. 로그인:
   ```bash
   autoscheduler auth            # 브라우저가 열리면 로그인·허용 → token.json 생성
   ```
   화면 없는 서버라면 `autoscheduler auth --no-browser` 로 URL을 받아 PC 브라우저에서 열거나,
   PC에서 먼저 인증한 뒤 `token.json` 을 서버로 복사하세요.

> 테스트 모드의 OAuth 앱은 refresh token이 7일 후 만료될 수 있습니다. 계속 쓰려면 동의 화면을 '프로덕션'으로 게시하세요(개인용이면 검수 없이 사용 가능, 경고 화면만 표시).

## 4-A. 카카오톡 대화 파일로 등록 (아이폰·안드로이드 공통)

1. 카카오톡 채팅방 → `≡` 메뉴 → ⚙️ → **대화 내용 내보내기** → **텍스트만 보내기** → PC로 전달
2. 실행:
   ```bash
   autoscheduler --dry-run import-kakao "KakaoTalk_20261112.txt" --since 2026-11-01   # 먼저 미리보기
   autoscheduler import-kakao "KakaoTalk_20261112.txt" --since 2026-11-01             # 실제 등록
   ```
   안드로이드·아이폰·PC(Windows) 내보내기 형식을 모두 읽습니다. 같은 파일을 다시 넣어도 중복 등록되지 않습니다.

## 4-B. 휴대폰 알림으로 실시간 등록 (안드로이드)

### 서버 실행

```bash
autoscheduler serve --port 8000          # 처음엔 --dry-run 으로 동작 확인 권장
```

휴대폰이 이 서버에 접속할 수 있어야 합니다.
- **같은 와이파이**: `http://<PC의 내부 IP>:8000` (PC가 켜져 있을 때만 동작)
- **밖에서도**: [Tailscale](https://tailscale.com)(추천, 무료) 또는 Cloudflare Tunnel, 혹은 상시 켜둔 라즈베리파이/클라우드 VM에서 실행

`.env`의 `AUTOSCHEDULER_WEBHOOK_TOKEN` 을 길고 무작위한 문자열로 꼭 바꾸세요. 이 토큰이 없으면 요청이 거부됩니다.

### MacroDroid 설정 (무료)

1. Play 스토어에서 **MacroDroid** 설치 → 알림 접근 권한 허용, 배터리 최적화 제외
2. 매크로 추가
   - **트리거**: `알림 수신` → 앱 선택: **카카오톡**, **당근** → 내용: 모두(아무 텍스트)
   - **액션**: `HTTP 요청`
     - 방식: `POST`
     - URL: `http://<서버주소>:8000/webhook/notification`
     - **쿼리 파라미터**(메시지 속 따옴표 때문에 JSON이 깨지지 않도록 이 방식을 추천):

       | 이름 | 값 (매직 텍스트) |
       |---|---|
       | `token` | `.env`에 넣은 토큰 |
       | `app` | 알림 앱 패키지명 (또는 앱 이름) |
       | `title` | 알림 제목 |
       | `text` | 알림 텍스트 |
       | `room` | (선택) 알림 서브텍스트 — 카카오톡 단톡방 이름 |
3. 친구에게 "내일 7시 어때?" 메시지를 받아 보고 서버 로그를 확인합니다.

Tasker 등 다른 앱도 같은 주소로 보내면 됩니다. 본문은 JSON(`{"app": "...", "title": "...", "text": "..."}`)이나 form 형식도 받습니다.
헤더 `X-Auth-Token` 으로 토큰을 보내도 됩니다.

| 필드 | 설명 |
|---|---|
| `app` | `com.kakao.talk` / `com.towneers.www` 또는 `카카오톡` / `당근` (그 외 앱은 무시) |
| `title` | 알림 제목 (1:1 채팅은 상대 이름 = 채팅방 이름으로 사용) |
| `text` | 메시지 내용. 단톡방에서 `보낸사람: 내용` 형태면 자동으로 분리 |
| `room` | 단톡방 이름 (선택) |
| `timestamp` | 받은 시각 ISO 8601 (선택, 없으면 서버 현재 시각) |

## 동작 방식

- 알림 한 건이 오면 **같은 채팅방의 최근 48시간·30개 메시지**를 함께 Claude에 보내, "내일 7시 어때?"→"좋아" 처럼 여러 메시지에 걸친 약속도 이해합니다.
  "내일", "이번 주 토요일" 같은 표현은 **메시지를 받은 시각 기준**으로 계산합니다.
- 이미 등록한 일정 목록도 함께 보내므로, 같은 약속을 두 번 만들지 않고 시간 변경·취소를 반영합니다.
- **미확정(제안만 있고 답이 없음)** 약속은 기본적으로 캘린더에 넣지 않고 기억만 해두었다가, 상대가 동의하면 등록합니다.
  `.env`에서 `AUTOSCHEDULER_INCLUDE_TENTATIVE=true` 로 하면 `[미정]` 을 붙여 바로 등록합니다.
- 일정 설명란에 근거가 된 메시지가 적혀 있어 왜 등록됐는지 확인할 수 있습니다.
- 데이터는 `data/autoscheduler.db`(SQLite)에 저장됩니다.

## 토큰 사용량 확인

Claude를 호출할 때마다 사용한 토큰 수가 `data/autoscheduler.db` 에 기록되고 로그에도 찍힙니다.

```
INFO autoscheduler.extractor: Claude 토큰 사용 [카카오톡 / 민수] claude-opus-5-5: 호출 1회, 입력 1,240 / 출력 310 토큰 ≈ $0.0112
```

- `autoscheduler usage` — 오늘 / 이번 달 / 전체 사용량과 추정 비용
- `import-kakao` 실행이 끝나면 그 실행에서 쓴 사용량을 함께 출력
- 서버 실행 중에는 `GET /usage?token=<토큰>` 으로 JSON 확인 (휴대폰 브라우저에서도 가능)

비용은 토큰 수 × 공개 단가(`autoscheduler/usage.py` 의 `PRICES`)로 계산한 **추정치**입니다. 정확한 청구액은 console.anthropic.com 에서 확인하세요.

## 설정 (.env)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Claude API 키 |
| `AUTOSCHEDULER_WEBHOOK_TOKEN` | – | 웹훅 인증 토큰 (serve에 필수) |
| `AUTOSCHEDULER_CALENDAR_ID` | `primary` | 등록할 캘린더. 별도 캘린더를 만들어 그 ID를 넣는 것을 추천 |
| `AUTOSCHEDULER_TIMEZONE` | `Asia/Seoul` | 시간대 |
| `AUTOSCHEDULER_INCLUDE_TENTATIVE` | `false` | 미확정 약속도 `[미정]`으로 등록 |
| `AUTOSCHEDULER_DRY_RUN` | `false` | 캘린더에 쓰지 않고 로그만 |
| `AUTOSCHEDULER_MODEL` | `claude-opus-5-5` | 사용할 Claude 모델 |
| `AUTOSCHEDULER_CONTEXT_MESSAGES` / `_HOURS` | `30` / `48` | 함께 보낼 문맥 크기 |

## 개발

```bash
pip install -e ".[dev]"
pytest
```

| 파일 | 역할 |
|---|---|
| `autoscheduler/parsers/kakao_export.py` | 카카오톡 내보내기 파일 파서 |
| `autoscheduler/extractor.py` | Claude 프롬프트·구조화 출력으로 일정 추출 |
| `autoscheduler/pipeline.py` | 생성/수정/취소·중복·미확정 처리 |
| `autoscheduler/gcal.py` | 구글 캘린더 OAuth·이벤트 생성/수정 |
| `autoscheduler/server.py` | 알림 웹훅 (FastAPI) |
| `autoscheduler/usage.py` | 토큰 사용량·추정 비용 계산 |
| `autoscheduler/cli.py` | `auth` / `import-kakao` / `usage` / `serve` 명령 |
