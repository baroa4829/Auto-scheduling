/**
 * Auto-scheduling — 구글 앱스 스크립트 버전
 *
 * 카카오톡·당근 알림(MacroDroid) → 이 웹 앱 → Claude로 약속 추출 → 구글 캘린더 등록
 * PC나 서버 없이 구글 클라우드에서 동작합니다.
 *
 * 처음 설정: apps-script/README.md 참고
 *   1) 프로젝트 설정 → 스크립트 속성에 ANTHROPIC_API_KEY 추가
 *   2) 편집기에서 setup 함수 실행 (권한 허용) → 실행 로그에 나오는 토큰 확인
 *   3) 배포 → 새 배포 → 웹 앱 (실행: 나, 액세스: 모든 사용자)
 */

// ===================== 설정 =====================
const CONFIG = {
  MODEL: 'claude-opus-5-5',
  // 추론 강도: low / medium / high. 앱스 스크립트는 외부 요청 시간이 제한돼 있어 low 를 기본으로 둡니다.
  EFFORT: 'low',
  CALENDAR_ID: '',            // 비우면 기본 캘린더. 별도 캘린더를 만들어 그 ID를 넣는 것을 추천
  INCLUDE_TENTATIVE: false,   // true 면 미확정 약속도 [미정] 을 붙여 바로 등록
  DRY_RUN: false,             // true 면 캘린더에 쓰지 않고 로그만 남김
  CONTEXT_MESSAGES: 30,       // 함께 보낼 같은 채팅방의 최근 메시지 수
  CONTEXT_HOURS: 48,          // 그중 몇 시간 이내 메시지만
  KEEP_MESSAGES_DAYS: 7,      // 이보다 오래된 메시지는 매일 자동 삭제 (개인정보 보호)
  DUPLICATE_WINDOW_SEC: 180,  // 같은 내용의 알림이 이 시간 안에 다시 오면 무시 (알림 갱신 대비)
  DEFAULT_EVENT_MINUTES: 60,
  // 약속 단어가 없는 답장("좋아", "ㅇㅋ")도 직전 대화가 약속 이야기였다면 Claude에게 보낸다
  FOLLOWUP_MINUTES: 60,
  FOLLOWUP_MESSAGES: 5,
};

// 1M 토큰당 USD: [입력, 출력, 캐시 읽기] — https://www.anthropic.com/pricing 에서 최신 단가 확인
const PRICES = {
  'claude-opus-5-5': [4.0, 20.0, 0.2],
  'claude-sonnet-5-5': [2.0, 10.0, 0.1],
};
const CACHE_WRITE_MULTIPLIER = 1.25;

const SHEET_MESSAGES = '메시지';
const SHEET_EVENTS = '일정';
const SHEET_USAGE = '토큰사용량';
const HEADERS = {
  [SHEET_MESSAGES]: ['시각(UTC)', '앱', '채팅방', '보낸사람', '내용'],
  [SHEET_EVENTS]: ['id', '앱', '채팅방', '제목', '시작', '종료', '종일', '장소', '상태', '캘린더ID', '취소', '갱신(UTC)'],
  [SHEET_USAGE]: ['시각(UTC)', '모델', '앱', '채팅방', '입력', '출력', '캐시읽기', '캐시쓰기', '추정비용(USD)'],
};

const SOURCE_LABELS = { kakao: '카카오톡', daangn: '당근' };
const APP_TO_SOURCE = {
  'com.kakao.talk': 'kakao', 'kakao': 'kakao', 'kakaotalk': 'kakao', '카카오톡': 'kakao',
  'com.towneers.www': 'daangn', 'daangn': 'daangn', 'karrot': 'daangn', '당근': 'daangn', '당근마켓': 'daangn',
};
const TENTATIVE_PREFIX = '[미정] ';
const CANCELLED_PREFIX = '[취소] ';
const WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일'];

const SYSTEM_PROMPT = [
  '당신은 한국어 메신저(카카오톡, 당근) 대화에서 사용자가 실제로 참여할 약속·일정을 찾아 구글 캘린더 항목으로 정리하는 도우미입니다.',
  '',
  '규칙',
  "- '나'는 캘린더 주인입니다. 대화 참여자끼리 만나거나, 거래하거나, 참석하기로 한 일정만 뽑습니다. 광고, 공지 전달, 남의 일정 이야기, 이미 지난 일에 대한 회상은 제외합니다.",
  '- 상대적 날짜(내일, 모레, 이번 주 토요일, 다음 주 화요일, 저녁 7시 등)는 해당 메시지가 보내진 시각을 기준으로 절대 날짜로 바꿉니다.',
  "  '저녁 7시'처럼 오전/오후가 애매하면 상식적으로 해석합니다 (저녁·밤 → 오후, '3시에 만나요' 같은 만남은 보통 오후).",
  '- 날짜는 정해졌지만 시각이 없으면 all_day=true 로 하고 start 에 날짜만 씁니다 (예: 2026-11-13).',
  '- 날짜를 전혀 특정할 수 없으면 일정으로 만들지 않습니다.',
  "- 한쪽이 제안만 하고 상대가 동의하지 않았으면 status=tentative, 서로 동의했거나(좋아요, 네, 그때 봬요 등) 당근 '약속 잡기' 알림처럼 확정 메시지가 있으면 confirmed 입니다.",
  "- '이미 등록된 일정' 목록에 같은 약속이 있으면 새로 만들지 마세요. 시간·장소가 바뀌었으면 action=update, 취소됐으면 action=cancel 로 그 id 를 existing_event_id 에 넣습니다. 바뀐 게 없으면 아무것도 출력하지 않습니다.",
  "- 제목은 짧게: 상대 이름/채팅방 + 목적. 당근 거래는 '당근 거래: 물건명 (상대 닉네임)' 형식을 권장합니다.",
  '- start/end 는 현지 시각 ISO 8601 (예: 2026-11-13T19:00) 형식입니다. 종료 시각 언급이 없으면 end 는 null.',
  '- 일정이 없으면 events 를 빈 배열로 반환합니다.',
].join('\n');

const NULLABLE_STRING = { anyOf: [{ type: 'string' }, { type: 'null' }] };
const EXTRACTION_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['events'],
  properties: {
    events: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['action', 'existing_event_id', 'title', 'start', 'end', 'all_day', 'location', 'status', 'evidence'],
        properties: {
          action: { enum: ['create', 'update', 'cancel'], description: '새 약속 create / 시간·장소 변경 update / 취소 cancel' },
          existing_event_id: Object.assign({ description: 'update/cancel 대상의 id. create 면 null' }, NULLABLE_STRING),
          title: { type: 'string', description: "캘린더 제목. 예: '민수와 저녁', '당근 거래: 아이패드 (당근이)'" },
          start: { type: 'string', description: '시작. 2026-11-13T19:00 또는 종일이면 2026-11-13' },
          end: Object.assign({ description: '종료. 언급 없으면 null' }, NULLABLE_STRING),
          all_day: { type: 'boolean', description: '시각 없이 날짜만 정해졌으면 true' },
          location: Object.assign({ description: '장소. 없으면 null' }, NULLABLE_STRING),
          status: { enum: ['confirmed', 'tentative'], description: '양쪽 동의 confirmed / 제안만 tentative' },
          evidence: { type: 'string', description: '근거가 된 메시지를 짧게 인용' },
        },
      },
    },
  },
};

// 비용 절약용 1차 필터: 날짜·시간·약속 관련 표현이 전혀 없으면 Claude를 호출하지 않는다.
const SCHEDULE_HINT = new RegExp(
  '\\d{1,2}\\s*(시|:\\d{2}|월|일|분)|오늘|내일|모레|글피|이번\\s*주|다음\\s*주|담주|주말|' +
  '[월화수목금토일]요일|아침|점심|저녁|밤|새벽|오전|오후|약속|만나|만날|봬|뵙|보자|볼까|' +
  '거래|직거래|예약|일정|미팅|회의|모임|취소|미루|당기|바꿔|변경|언제|몇\\s*시'
);

// ===================== 웹 앱 진입점 =====================

/** MacroDroid 가 보내는 알림. 쿼리 파라미터, form, JSON 본문 모두 지원. */
function doPost(e) {
  const params = readParams_(e);
  if (!checkToken_(params.token)) return json_({ error: 'invalid token' });
  const source = APP_TO_SOURCE[String(params.app || '').trim().toLowerCase()] ||
                 APP_TO_SOURCE[String(params.app || '').trim()];
  if (!source) return json_({ ignored: '지원하지 않는 앱: ' + params.app });
  if (!params.text) return json_({ ignored: '내용 없음' });

  const msg = toMessage_(params, source);
  console.log('알림 수신: 앱=%s 방=%s 보낸사람=%s 내용=%s', source, msg.room, msg.sender, msg.text.slice(0, 40));

  const lock = LockService.getScriptLock();
  lock.waitLock(60 * 1000);  // 알림이 동시에 여러 개 와도 순서대로 처리
  try {
    const report = handleMessage_(msg);
    if (report.created.length || report.updated.length || report.cancelled.length) {
      console.log('반영 결과: %s', JSON.stringify(report));
    }
    return json_(report);
  } catch (err) {
    console.error('처리 실패: %s', err && err.stack || err);
    return json_({ error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

/** 브라우저로 열어 확인: ?token=...&action=usage 로 토큰 사용량, 그 외에는 상태 확인 */
function doGet(e) {
  const params = readParams_(e);
  if (params.action === 'usage') {
    if (!checkToken_(params.token)) return json_({ error: 'invalid token' });
    return json_(usageSummary_());
  }
  return json_({ ok: true, dry_run: CONFIG.DRY_RUN });
}

// ===================== 최초 설정 =====================

/** 편집기에서 한 번 실행하세요. 시트 생성, 토큰 발급, 정리 트리거 설치. */
function setup() {
  const props = PropertiesService.getScriptProperties();
  let ssId = props.getProperty('SPREADSHEET_ID');
  let ss = null;
  if (ssId) {
    try { ss = SpreadsheetApp.openById(ssId); } catch (err) { ss = null; }
  }
  if (!ss) {
    ss = SpreadsheetApp.create('Auto-scheduling 데이터');
    props.setProperty('SPREADSHEET_ID', ss.getId());
  }
  Object.keys(HEADERS).forEach(function (name) {
    let sh = ss.getSheetByName(name);
    if (!sh) sh = ss.insertSheet(name);
    const header = HEADERS[name];
    sh.getRange(1, 1, 1, header.length).setValues([header]);
    sh.setFrozenRows(1);
  });
  const first = ss.getSheetByName('Sheet1') || ss.getSheetByName('시트1');
  if (first && ss.getSheets().length > 1) ss.deleteSheet(first);

  let token = props.getProperty('WEBHOOK_TOKEN');
  if (!token) {
    token = Utilities.getUuid().replace(/-/g, '');
    props.setProperty('WEBHOOK_TOKEN', token);
  }

  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'cleanupOldMessages') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('cleanupOldMessages').timeBased().everyDays(1).atHour(4).create();

  getCalendar_();  // 캘린더 권한 확인
  const hasKey = !!props.getProperty('ANTHROPIC_API_KEY');
  console.log('설정 완료');
  console.log('데이터 시트: %s', ss.getUrl());
  console.log('웹훅 토큰 (MacroDroid 의 token 값): %s', token);
  console.log(hasKey ? 'ANTHROPIC_API_KEY 확인됨'
    : '⚠️ ANTHROPIC_API_KEY 가 없습니다. 프로젝트 설정 → 스크립트 속성에 추가하세요.');
}

/** 편집기에서 실행해 보는 예시: 캘린더에 쓰지 않고 Claude 추출 결과만 로그로 확인 */
function tryExample() {
  const now = new Date();
  const messages = [
    { ts: new Date(now.getTime() - 5 * 60000), source: 'kakao', room: '민수', sender: '민수', text: '내일 저녁 7시에 강남역에서 볼래?' },
    { ts: new Date(now.getTime() - 4 * 60000), source: 'kakao', room: '민수', sender: '나', text: '좋아! 11번 출구에서 보자' },
  ];
  const result = extractEvents_(messages, [], '카카오톡', '민수');
  console.log(JSON.stringify(result, null, 2));
}

/** 매일 실행: 오래된 메시지 삭제 */
function cleanupOldMessages() {
  const sh = sheet_(SHEET_MESSAGES);
  const last = sh.getLastRow();
  if (last < 2) return;
  const cutoff = new Date(Date.now() - CONFIG.KEEP_MESSAGES_DAYS * 86400000).toISOString();
  const ts = sh.getRange(2, 1, last - 1, 1).getValues();
  let count = 0;
  while (count < ts.length && String(ts[count][0]) < cutoff) count++;
  if (count > 0) sh.deleteRows(2, count);
}

/** 편집기에서 실행: 토큰 사용량을 로그로 보기 */
function showUsage() {
  console.log(JSON.stringify(usageSummary_(), null, 2));
}

// ===================== 처리 흐름 =====================

function handleMessage_(msg) {
  const report = { created: [], updated: [], cancelled: [], skipped: [] };
  if (isDuplicate_(msg)) {
    report.skipped.push('중복 알림');
    return report;
  }
  appendRow_(sheet_(SHEET_MESSAGES), [msg.ts.toISOString(), msg.source, msg.room, msg.sender, msg.text]);
  const context = recentMessages_(msg.source, msg.room, msg.ts);
  const existing = activeEvents_(msg.source, msg.room);
  if (!needsExtraction_(msg, context, existing)) return report;

  const result = extractEvents_(context, existing, SOURCE_LABELS[msg.source] || msg.source, msg.room);
  result.events.forEach(function (action) {
    try {
      applyAction_(msg.source, msg.room, action, report);
    } catch (err) {
      console.error('일정 반영 실패: %s %s', JSON.stringify(action), err && err.stack || err);
      report.skipped.push('오류: ' + action.title);
    }
  });
  return report;
}

/** 비용 절약: 약속과 관련 있어 보일 때만 Claude를 호출한다. */
function needsExtraction_(msg, context, existing) {
  if (SCHEDULE_HINT.test(msg.text)) return true;
  // 아직 미확정인 약속이 있으면 "좋아요" 같은 답장으로 확정될 수 있다
  if (existing.some(function (e) { return e.status === 'tentative'; })) return true;
  const since = msg.ts.getTime() - CONFIG.FOLLOWUP_MINUTES * 60000;
  return context.slice(-CONFIG.FOLLOWUP_MESSAGES - 1, -1).some(function (m) {
    return m.ts.getTime() >= since && SCHEDULE_HINT.test(m.text);
  });
}

function applyAction_(source, room, action, report) {
  const writable = action.status === 'confirmed' || CONFIG.INCLUDE_TENTATIVE;

  if (action.action === 'update' || action.action === 'cancel') {
    const id = String(action.existing_event_id || '').trim();
    const stored = /^\d+$/.test(id) ? getEvent_(Number(id)) : null;
    if (!stored || stored.source !== source || stored.room !== room || stored.cancelled) {
      report.skipped.push('대상 일정 없음(' + action.action + '): ' + action.title);
      return;
    }
    if (action.action === 'cancel') {
      if (stored.calendarId) calendarCancel_(stored.calendarId, stored.title);
      updateEvent_(stored.id, { cancelled: true });
      report.cancelled.push(stored.title);
      return;
    }
    if (!writable) {
      if (stored.status === 'confirmed') {
        report.skipped.push('미확정 변경 제안 무시: ' + action.title);
      } else {
        updateEvent_(stored.id, fieldsFrom_(action, { status: 'tentative' }));
        report.skipped.push('미확정: ' + action.title + ' (' + action.start + ')');
      }
      return;
    }
    let calendarId = stored.calendarId;
    if (calendarId) {
      calendarUpdate_(calendarId, action, source, room);
    } else {
      calendarId = calendarCreate_(action, source, room);
    }
    updateEvent_(stored.id, fieldsFrom_(action, { calendarId: calendarId }));
    report.updated.push(action.title + ' → ' + action.start);
    return;
  }

  // create
  const dup = findDuplicate_(source, room, action.start);
  if (dup) {
    if (!dup.calendarId && writable) {
      // 미확정으로 기록만 해 둔 약속이 확정됨 → 이제 캘린더에 등록
      const cid = calendarCreate_(action, source, room);
      updateEvent_(dup.id, fieldsFrom_(action, { calendarId: cid }));
      report.created.push(displayTitle_(action) + ' (' + action.start + ')');
    } else {
      report.skipped.push('이미 등록됨: ' + action.title + ' (' + action.start + ')');
    }
    return;
  }
  if (!writable) {
    insertEvent_(source, room, action, '');  // 기억만 해 두었다가 확정되면 등록
    report.skipped.push('미확정: ' + action.title + ' (' + action.start + ')');
    return;
  }
  const cid = calendarCreate_(action, source, room);
  insertEvent_(source, room, action, cid);
  report.created.push(displayTitle_(action) + ' (' + action.start + ')');
}

function fieldsFrom_(action, extra) {
  return Object.assign({
    title: action.title, start: action.start, end: action.end || '', allDay: !!action.all_day,
    location: action.location || '', status: action.status,
  }, extra || {});
}

// ===================== Claude =====================

function extractEvents_(messages, existing, sourceLabel, room) {
  if (!messages.length) return { events: [] };
  const prompt = buildPrompt_(messages, existing, sourceLabel, room);
  const data = callClaude_(prompt);
  if (data.usage) recordUsage_(data.model || CONFIG.MODEL, data.usage, sourceLabel, room);

  if (data.stop_reason === 'refusal') {
    console.warn('Claude가 요청을 거절했습니다 (category=%s). 건너뜁니다.',
      data.stop_details && data.stop_details.category);
    return { events: [] };
  }
  if (data.stop_reason === 'max_tokens') {
    console.warn('응답이 잘렸습니다 (max_tokens). 건너뜁니다.');
    return { events: [] };
  }
  const text = (data.content || []).filter(function (b) { return b.type === 'text'; })
    .map(function (b) { return b.text; }).join('');
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    console.warn('응답 JSON 해석 실패: %s', text.slice(0, 200));
    return { events: [] };
  }
  const events = (parsed && Array.isArray(parsed.events) ? parsed.events : []).filter(validAction_);
  return { events: events };
}

function validAction_(a) {
  if (!a || ['create', 'update', 'cancel'].indexOf(a.action) < 0) return false;
  if (typeof a.title !== 'string' || typeof a.start !== 'string') return false;
  if (['confirmed', 'tentative'].indexOf(a.status) < 0) return false;
  if (a.action === 'cancel') return true;
  return parseLocal_(a.start, !!a.all_day) !== null;
}

function callClaude_(prompt) {
  const apiKey = PropertiesService.getScriptProperties().getProperty('ANTHROPIC_API_KEY');
  if (!apiKey) throw new Error('스크립트 속성에 ANTHROPIC_API_KEY 가 없습니다');
  const body = {
    model: CONFIG.MODEL,
    max_tokens: 16000,
    system: SYSTEM_PROMPT,
    messages: [{ role: 'user', content: prompt }],
    output_config: { effort: CONFIG.EFFORT, format: { type: 'json_schema', schema: EXTRACTION_SCHEMA } },
    // 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도
    fallbacks: 'default',
  };
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'x-api-key': apiKey,
      'anthropic-version': '2026-10-21',
      'anthropic-beta': 'server-side-fallback-2026-07-01',
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
  };
  let lastError = '';
  for (let attempt = 0; attempt < 3; attempt++) {
    const res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', options);
    const code = res.getResponseCode();
    const text = res.getContentText();
    if (code === 200) return JSON.parse(text);
    lastError = 'HTTP ' + code + ': ' + text.slice(0, 300);
    const retryable = code === 429 || code === 408 || code === 409 || code >= 500;
    if (!retryable) break;
    Utilities.sleep(2000 * Math.pow(2, attempt));
  }
  throw new Error('Claude API 호출 실패 — ' + lastError);
}

function buildPrompt_(messages, existing, sourceLabel, room) {
  const lines = ['앱: ' + sourceLabel, '채팅방: ' + room, '', '이미 등록된 일정:'];
  if (existing.length) {
    existing.forEach(function (e) {
      lines.push('- id=' + e.id + ' | ' + e.title + ' | 시작 ' + e.start + ' | 종료 ' + (e.end || '-') +
        ' | 장소 ' + (e.location || '-') + ' | ' + e.status);
    });
  } else {
    lines.push('- (없음)');
  }
  lines.push('', '대화 (보낸 시각 | 보낸 사람: 내용):');
  messages.forEach(function (m) {
    lines.push('[' + fmtStamp_(m.ts) + '] ' + m.sender + ': ' + String(m.text).replace(/\n/g, ' / '));
  });
  return lines.join('\n');
}

// ===================== 구글 캘린더 =====================

function getCalendar_() {
  const cal = CONFIG.CALENDAR_ID ? CalendarApp.getCalendarById(CONFIG.CALENDAR_ID) : CalendarApp.getDefaultCalendar();
  if (!cal) throw new Error('캘린더를 찾을 수 없습니다: ' + CONFIG.CALENDAR_ID);
  return cal;
}

function displayTitle_(action) {
  return (action.status === 'tentative' ? TENTATIVE_PREFIX : '') + action.title;
}

function description_(action, source, room) {
  return (SOURCE_LABELS[source] || source) + " '" + room + "' 대화에서 자동 등록\n근거: " +
    action.evidence + '\n\n(auto-scheduling)';
}

/** {allDay, start: Date, end: Date} — 종일이면 end 는 마지막 날의 다음 날(exclusive) */
function eventTimes_(action) {
  const allDay = !!action.all_day;
  const start = parseLocal_(action.start, allDay);
  let end = action.end ? parseLocal_(action.end, allDay) : null;
  if (allDay) {
    const lastDay = end && end >= start ? end : start;
    return { allDay: true, start: start, end: new Date(lastDay.getTime() + 86400000) };
  }
  if (!end || end <= start) end = new Date(start.getTime() + CONFIG.DEFAULT_EVENT_MINUTES * 60000);
  return { allDay: false, start: start, end: end };
}

function calendarCreate_(action, source, room) {
  const t = eventTimes_(action);
  const title = displayTitle_(action);
  const opts = { description: description_(action, source, room) };
  if (action.location) opts.location = action.location;
  if (CONFIG.DRY_RUN) {
    console.log('[DRY-RUN] 생성: %s %s ~ %s %s', title, t.start, t.end, action.location || '');
    return 'dry-' + Utilities.getUuid();
  }
  const cal = getCalendar_();
  const ev = t.allDay ? cal.createAllDayEvent(title, t.start, t.end, opts) : cal.createEvent(title, t.start, t.end, opts);
  return ev.getId();
}

function calendarUpdate_(calendarId, action, source, room) {
  if (CONFIG.DRY_RUN || String(calendarId).indexOf('dry-') === 0) {
    console.log('[DRY-RUN] 수정 %s: %s %s', calendarId, displayTitle_(action), action.start);
    return;
  }
  const ev = getCalendar_().getEventById(calendarId);
  if (!ev) throw new Error('캘린더에서 일정을 찾을 수 없습니다: ' + calendarId);
  const t = eventTimes_(action);
  ev.setTitle(displayTitle_(action));
  ev.setDescription(description_(action, source, room));
  ev.setLocation(action.location || '');
  if (t.allDay) ev.setAllDayDates(t.start, t.end);
  else ev.setTime(t.start, t.end);
}

function calendarCancel_(calendarId, title) {
  if (CONFIG.DRY_RUN || String(calendarId).indexOf('dry-') === 0) {
    console.log('[DRY-RUN] 취소 %s: %s', calendarId, title);
    return;
  }
  const ev = getCalendar_().getEventById(calendarId);
  if (!ev) return;
  ev.setTitle(CANCELLED_PREFIX + title);
  try { ev.setColor(CalendarApp.EventColor.GRAY); } catch (err) { /* 색 변경은 선택 사항 */ }
}

// ===================== 시트 저장소 =====================

function sheet_(name) {
  const id = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID');
  if (!id) throw new Error('setup 함수를 먼저 실행하세요');
  const sh = SpreadsheetApp.openById(id).getSheetByName(name);
  if (!sh) throw new Error('시트가 없습니다: ' + name + ' (setup 을 다시 실행하세요)');
  return sh;
}

/** 모든 칸을 '일반 텍스트'로 저장해 시트가 날짜·숫자로 자동 변환하지 않게 한다. */
function appendRow_(sh, values, numericFrom) {
  const row = sh.getLastRow() + 1;
  if (row > sh.getMaxRows()) sh.insertRowsAfter(sh.getMaxRows(), 50);
  const textCols = numericFrom ? numericFrom - 1 : values.length;
  sh.getRange(row, 1, 1, textCols).setNumberFormat('@');
  sh.getRange(row, 1, 1, values.length).setValues([values.map(function (v, i) {
    return i < textCols ? String(v == null ? '' : v) : v;
  })]);
  return row;
}

function lastRows_(sh, maxRows) {
  const last = sh.getLastRow();
  if (last < 2) return [];
  const start = Math.max(2, last - maxRows + 1);
  return sh.getRange(start, 1, last - start + 1, sh.getLastColumn()).getValues();
}

function isDuplicate_(msg) {
  const windowStart = new Date(msg.ts.getTime() - CONFIG.DUPLICATE_WINDOW_SEC * 1000).toISOString();
  return lastRows_(sheet_(SHEET_MESSAGES), 200).some(function (r) {
    return String(r[0]) >= windowStart && r[1] === msg.source && r[2] === msg.room &&
      r[3] === msg.sender && r[4] === msg.text;
  });
}

function recentMessages_(source, room, until) {
  const since = new Date(until.getTime() - CONFIG.CONTEXT_HOURS * 3600000).toISOString();
  const untilIso = until.toISOString();
  const rows = lastRows_(sheet_(SHEET_MESSAGES), 2000).filter(function (r) {
    return r[1] === source && r[2] === room && String(r[0]) >= since && String(r[0]) <= untilIso;
  });
  return rows.slice(-CONFIG.CONTEXT_MESSAGES).map(function (r) {
    return { ts: new Date(String(r[0])), source: r[1], room: r[2], sender: r[3], text: String(r[4]) };
  });
}

function rowToEvent_(r, rowIndex) {
  return {
    row: rowIndex, id: Number(r[0]), source: r[1], room: r[2], title: r[3], start: String(r[4]),
    end: String(r[5] || ''), allDay: String(r[6]) === '1', location: String(r[7] || ''),
    status: r[8], calendarId: String(r[9] || ''), cancelled: String(r[10]) === '1',
  };
}

function allEvents_() {
  const sh = sheet_(SHEET_EVENTS);
  const last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, HEADERS[SHEET_EVENTS].length).getValues()
    .map(function (r, i) { return rowToEvent_(r, i + 2); });
}

function activeEvents_(source, room) {
  return allEvents_().filter(function (e) { return e.source === source && e.room === room && !e.cancelled; });
}

function getEvent_(id) {
  return allEvents_().filter(function (e) { return e.id === id; })[0] || null;
}

function findDuplicate_(source, room, start) {
  return activeEvents_(source, room).filter(function (e) { return e.start === start; })[0] || null;
}

function insertEvent_(source, room, action, calendarId) {
  const events = allEvents_();
  const nextId = events.reduce(function (m, e) { return Math.max(m, e.id || 0); }, 0) + 1;
  appendRow_(sheet_(SHEET_EVENTS), [
    nextId, source, room, action.title, action.start, action.end || '', action.all_day ? '1' : '0',
    action.location || '', action.status, calendarId || '', '0', new Date().toISOString(),
  ]);
  return nextId;
}

function updateEvent_(id, fields) {
  const e = getEvent_(id);
  if (!e) return;
  const merged = Object.assign({}, e, fields);
  const values = [
    e.id, e.source, e.room, merged.title, merged.start, merged.end || '', merged.allDay ? '1' : '0',
    merged.location || '', merged.status, merged.calendarId || '', merged.cancelled ? '1' : '0',
    new Date().toISOString(),
  ].map(String);
  const range = sheet_(SHEET_EVENTS).getRange(e.row, 1, 1, values.length);
  range.setNumberFormat('@');
  range.setValues([values]);
}

// ===================== 토큰 사용량 =====================

function costUsd_(model, input, output, cacheRead, cacheWrite) {
  const p = PRICES[model];
  if (!p) return null;
  return (input * p[0] + output * p[1] + cacheRead * p[2] + cacheWrite * p[0] * CACHE_WRITE_MULTIPLIER) / 1e6;
}

function recordUsage_(model, usage, sourceLabel, room) {
  const input = usage.input_tokens || 0;
  const output = usage.output_tokens || 0;
  const cacheRead = usage.cache_read_input_tokens || 0;
  const cacheWrite = usage.cache_creation_input_tokens || 0;
  const cost = costUsd_(model, input, output, cacheRead, cacheWrite);
  console.log('Claude 토큰 사용 [%s / %s] %s: 입력 %s / 출력 %s 토큰 %s', sourceLabel, room, model, input, output,
    cost === null ? '(가격표 없음)' : '≈ $' + cost.toFixed(4));
  appendRow_(sheet_(SHEET_USAGE),
    [new Date().toISOString(), model, sourceLabel, room, input, output, cacheRead, cacheWrite, cost === null ? '' : cost], 5);
}

function usageSummary_() {
  const sh = sheet_(SHEET_USAGE);
  const last = sh.getLastRow();
  const rows = last < 2 ? [] : sh.getRange(2, 1, last - 1, HEADERS[SHEET_USAGE].length).getValues();
  const today = fmt_(new Date(), 'yyyy-MM-dd');
  const month = today.slice(0, 7);
  function empty() { return { calls: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, estimated_cost_usd: 0 }; }
  const out = { today: empty(), this_month: empty(), all_time: empty() };
  rows.forEach(function (r) {
    const day = fmt_(new Date(String(r[0])), 'yyyy-MM-dd');
    const buckets = [out.all_time];
    if (day.slice(0, 7) === month) buckets.push(out.this_month);
    if (day === today) buckets.push(out.today);
    buckets.forEach(function (b) {
      b.calls += 1;
      b.input_tokens += Number(r[4]) || 0;
      b.output_tokens += Number(r[5]) || 0;
      b.cache_read_tokens += Number(r[6]) || 0;
      b.cache_write_tokens += Number(r[7]) || 0;
      b.estimated_cost_usd += Number(r[8]) || 0;
    });
  });
  Object.keys(out).forEach(function (k) { out[k].estimated_cost_usd = Math.round(out[k].estimated_cost_usd * 1e6) / 1e6; });
  out.note = '비용은 토큰 수 × 공개 단가로 계산한 추정치입니다. 정확한 청구액은 console.anthropic.com 에서 확인하세요.';
  return out;
}

// ===================== 도우미 =====================

function tz_() {
  return Session.getScriptTimeZone() || 'Asia/Seoul';
}

function fmt_(date, pattern) {
  return Utilities.formatDate(date, tz_(), pattern);
}

function fmtStamp_(date) {
  const weekday = WEEKDAYS[Number(fmt_(date, 'u')) - 1];
  return fmt_(date, 'yyyy-MM-dd') + '(' + weekday + ') ' + fmt_(date, 'HH:mm');
}

/** '2026-11-13T19:00' 또는 '2026-11-13' 을 스크립트 시간대 기준 Date 로. 형식이 틀리면 null */
function parseLocal_(s, allDay) {
  s = String(s || '').trim();
  const m = s.match(/^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?/);
  if (!m) return null;
  try {
    if (allDay || !m[2]) return Utilities.parseDate(m[1], tz_(), 'yyyy-MM-dd');
    return Utilities.parseDate(m[1] + ' ' + m[2], tz_(), 'yyyy-MM-dd HH:mm');
  } catch (err) {
    return null;
  }
}

function readParams_(e) {
  const params = Object.assign({}, (e && e.parameter) || {});
  const contents = e && e.postData && e.postData.contents;
  if (contents && String(contents).trim().charAt(0) === '{') {
    try {
      const body = JSON.parse(contents);
      Object.keys(body).forEach(function (k) { if (body[k] != null) params[k] = String(body[k]); });
    } catch (err) {
      console.warn('JSON 본문 해석 실패 — 쿼리 파라미터 방식을 쓰면 따옴표 문제를 피할 수 있습니다');
    }
  }
  return params;
}

function checkToken_(token) {
  const expected = PropertiesService.getScriptProperties().getProperty('WEBHOOK_TOKEN');
  return !!expected && !!token && String(token) === expected;
}

function toMessage_(params, source) {
  let room = String(params.room || params.title || '알 수 없음').trim();
  let sender = String(params.sender || params.title || '상대').trim();
  let text = String(params.text);
  // 카카오톡 단톡방 알림은 본문이 '보낸사람: 내용' 형태로 오기도 한다
  if (params.room && !params.sender && text.indexOf(': ') > 0) {
    const head = text.slice(0, text.indexOf(': '));
    if (head.length <= 20) {
      sender = head.trim();
      text = text.slice(text.indexOf(': ') + 2);
    }
  }
  let ts = params.timestamp ? new Date(params.timestamp) : new Date();
  if (isNaN(ts.getTime())) ts = new Date();
  return { ts: ts, source: source, room: room, sender: sender, text: text };
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
