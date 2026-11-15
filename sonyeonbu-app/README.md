# 동석교회 소년부 요람 앱

아이들 요람(사진·연락처), 앨범, 영상을 한곳에서 관리하는 웹앱입니다. (교사·학부모 포함 100명 안팎 규모 기준, 무료 요금제로 운영 가능)
휴대폰 홈 화면에 추가하면 일반 앱처럼 쓸 수 있습니다. 아이폰과 안드로이드 모두 지원합니다.

## 권한

| 역할 | 요람 (사진·연락처) | 앨범·영상 보기 | 사진·영상 올리기 | 회원 승인 |
|---|:-:|:-:|:-:|:-:|
| 승인 대기 | ✕ | ✕ | ✕ | ✕ |
| 구성원 (학부모 등) | ✕ | ○ | ✕ | ✕ |
| 교사 | ○ | ○ | ○ | ✕ |
| 관리자 | ○ | ○ | ○ | ○ |

- 권한은 데이터베이스의 행 단위 보안(RLS)으로 막습니다. 화면만 숨기는 방식이 아니어서, 앱을 우회해도 데이터를 볼 수 없습니다.
- 사진은 모두 **비공개 저장소**에 보관됩니다. 화면에는 로그인한 사람에게만 1시간짜리 임시 주소로 보여 줍니다.
- 사진은 올릴 때 자동으로 크기를 줄입니다(앨범 1920px, 요람 800px). 무료 용량 1GB로 사진 수천 장을 보관할 수 있습니다.
- 영상은 유튜브 **일부 공개** 링크로 연결합니다. 영상 파일을 직접 올리면 저장 용량이 금방 부족해지기 때문입니다.

---

## 설치 방법 (처음 한 번, 약 20분)

### 1. Supabase 프로젝트 만들기 (무료)
1. https://supabase.com 에 가입하고 **New project**를 만듭니다.
   - Region은 **Northeast Asia (Seoul)** 를 고릅니다.
   - Database Password는 안전한 곳에 적어 둡니다.
2. 왼쪽 메뉴 **SQL Editor**에서 [`supabase/schema.sql`](supabase/schema.sql) 내용을 전부 붙여넣고 **Run**을 누릅니다.
3. **Authentication → URL Configuration**에서 다음을 설정합니다.
   - **Site URL**: 4단계에서 받은 앱 주소 (예: `https://dongseok-sonyeonbu.vercel.app`)
   - **Redirect URLs**: 같은 주소에 `/**`를 붙여 추가합니다.
4. **Project Settings → API**에서 `Project URL`과 `anon public` 키를 복사해 둡니다.

### 2. 내 컴퓨터에서 실행해 보기 (선택)
```bash
cd sonyeonbu-app
cp .env.example .env      # .env 파일에 1-4에서 복사한 값을 입력
npm install
npm run dev               # http://localhost:5173
```

### 3. 인터넷에 올리기 (Vercel, 무료)
1. https://vercel.com 에 GitHub 계정으로 가입합니다.
2. **Add New → Project**에서 이 저장소를 고르고 다음과 같이 설정합니다.
   - **Root Directory**: `sonyeonbu-app`
   - **Environment Variables**: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
3. **Deploy**를 누르면 주소가 발급됩니다. 이 주소를 1-3단계의 Site URL에 넣어 주세요.

### 4. 첫 관리자 만들기
- 앱에 **가장 먼저 가입한 사람이 자동으로 관리자**가 됩니다. 담당자가 먼저 가입하세요.
- 그다음부터 가입하는 사람은 모두 "승인 대기" 상태가 되고, 관리자가 **회원관리** 탭에서 승인합니다.

---

## 운영 팁
- **가입 링크 공유**: 앱 주소를 교사 단톡방이나 학부모 단톡방에 올리고, 가입 신청을 받은 뒤 승인합니다.
- **동의서**: [`docs/개인정보_동의서.md`](docs/개인정보_동의서.md)를 인쇄해서 보호자 서명을 받고, 요람에서 "동의서 받음"을 체크하세요.
  만 14세 미만 아동의 개인정보는 **법정대리인 동의가 필수**입니다.
- **사진 공개 비동의 아동**: 요람에 "사진 공개 비동의"로 표시되므로, 앨범에 올릴 때 확인하세요.
- **졸업·전출**: 요람 상세 화면의 **삭제**를 누르면 사진까지 완전히 지워집니다.
- **회원 탈퇴**: 회원관리에서 삭제하면 앱을 쓸 수 없게 됩니다. 로그인 계정까지 지우려면 Supabase → Authentication → Users에서 삭제하세요.
- **비밀번호 분실**: 로그인 화면의 "비밀번호 찾기"를 쓰면 됩니다.
- **가입 메일 인증 (중요)**: Supabase 기본 메일 발송은 시간당 몇 건밖에 안 됩니다. 학부모 100명이 한꺼번에 가입하면 인증 메일이 밀리므로,
  **처음 설정할 때 Authentication → Sign In / Providers → Email의 "Confirm email"을 꺼 두세요.** 관리자 승인 단계가 있어서 보안에는 문제가 없습니다.
  (단, 이 경우 비밀번호 찾기 메일도 같은 한도를 받습니다. 많이 쓰게 되면 Gmail 등 SMTP를 연결하세요: Project Settings → Authentication → SMTP)
- **무료 요금제 휴면**: Supabase 무료 프로젝트는 일주일 동안 아무도 접속하지 않으면 일시정지됩니다. 대시보드에서 Restore를 누르면 다시 켜집니다.
- **백업**: Supabase → Database → Backups, 또는 Table Editor에서 students 표를 CSV로 내보내 보관하세요.

## 권한 바꾸기
- **학부모도 사진을 올리게 하려면**: `schema.sql`의 albums/photos 쓰기 정책과 `album: teachers write` 정책에서
  `is_teacher()`를 `is_member()`로 바꾸고, `AlbumDetail.tsx`의 업로드 버튼 조건을 `isMember`로 바꾸세요.

## 권한 테스트
로컬 PostgreSQL에서 RLS 규칙을 검증하는 스크립트가 있습니다.
```bash
createdb t
psql -d t -f supabase/tests/mock_supabase.sql   # Supabase auth/storage 흉내
psql -d t -f supabase/schema.sql
psql -d t -f supabase/tests/rls_test.sql        # failures = 0 이면 통과
```

## 구성
- `src/` — React + TypeScript (Vite)
- `supabase/schema.sql` — 테이블, 권한(RLS), 저장소 정책
- 데이터: `profiles`(회원), `students`(요람), `albums`/`photos`(앨범), `videos`(유튜브 링크)
