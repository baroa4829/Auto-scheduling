import test from 'node:test';
import assert from 'node:assert/strict';
import { createEnv, claudeReply, ev } from './harness.mjs';

function post(env, params, contents) {
  const e = { parameter: params, postData: contents ? { contents } : undefined };
  env.ctx.__e = e;
  return env.run('doPost(__e)').json();
}

function setupEnv(opts) {
  const env = createEnv(opts);
  env.run('setup()');
  return env;
}

const tok = (env) => env.store.WEBHOOK_TOKEN;
const kakao = (env, text, extra = {}) =>
  post(env, { token: tok(env), app: '카카오톡', title: '민수', text, ...extra });

test('setup: 토큰·트리거 생성 (구글 시트·드라이브 없이)', () => {
  const env = setupEnv();
  assert.ok(env.store.WEBHOOK_TOKEN);
  assert.equal(env.ctx.ScriptApp.triggers.length, 1);
  assert.equal(env.ctx.ScriptApp.triggers[0].getHandlerFunction(), 'cleanupOldData');
  assert.ok(env.logs.some((l) => l.includes('ANTHROPIC_API_KEY 확인됨')));
  const token = env.store.WEBHOOK_TOKEN;
  env.run('setup()');  // 다시 실행해도 토큰 유지
  assert.equal(env.store.WEBHOOK_TOKEN, token);
});

test('토큰이 틀리면 거부', () => {
  const env = setupEnv();
  assert.equal(post(env, { token: 'bad', app: '카카오톡', text: '내일 7시' }).error, 'invalid token');
});

test('지원하지 않는 앱은 무시, 약속과 무관한 메시지는 Claude 호출 안 함', () => {
  const env = setupEnv();
  assert.ok(post(env, { token: tok(env), app: 'com.other', text: '내일 7시' }).ignored);
  kakao(env, 'ㅋㅋㅋㅋ');
  assert.equal(env.requests.length, 0);
});

test('약속 생성 → 캘린더 등록 + 요청 형식 확인', () => {
  const env = setupEnv({ claudeResponses: [claudeReply([ev()])] });
  const r = kakao(env, '내일 저녁 7시 강남역 어때?');
  assert.equal(r.created.length, 1);
  const [cal] = [...env.events.values()];
  assert.equal(cal.title, '민수와 저녁');
  assert.equal(cal.location, '강남역');
  assert.equal(cal.start.toISOString(), '2026-11-13T10:00:00.000Z'); // 19:00 KST
  assert.equal(cal.end.getTime() - cal.start.getTime(), 3600000);

  const req = env.requests[0];
  assert.equal(req.url, 'https://api.anthropic.com/v1/messages');
  assert.equal(req.opts.headers['anthropic-version'], '2026-10-21');
  assert.equal(req.opts.headers['anthropic-beta'], 'server-side-fallback-2026-07-01');
  assert.equal(req.body.model, 'claude-opus-5-5');
  assert.equal(req.body.fallbacks, 'default');
  assert.equal(req.body.output_config.format.type, 'json_schema');
  assert.match(req.body.messages[0].content, /민수: 내일 저녁 7시 강남역 어때\?/);
});

test('같은 알림이 다시 오면 무시', () => {
  const env = setupEnv({ claudeResponses: [claudeReply([])] });
  kakao(env, '내일 7시?');
  assert.deepEqual(kakao(env, '내일 7시?').skipped, ['중복 알림']);
  assert.equal(env.requests.length, 1);
});

test('이전 대화가 문맥으로 전달되고, 같은 약속은 중복 등록 안 함', () => {
  const env = setupEnv({ claudeResponses: [claudeReply([ev()]), claudeReply([ev()])] });
  kakao(env, '내일 저녁 7시 강남역?');
  const r = kakao(env, '좋아 그때 봐');
  assert.equal(env.events.size, 1);
  assert.ok(r.skipped[0].startsWith('이미 등록됨'));
  const prompt = env.requests[1].body.messages[0].content;
  assert.match(prompt, /내일 저녁 7시 강남역\?/);
  assert.match(prompt, /id=1 \| 민수와 저녁/);
});

test('미확정 → 기록만, 확정되면 등록', () => {
  const env = setupEnv({
    claudeResponses: [
      claudeReply([ev({ status: 'tentative' })]),
      claudeReply([ev({ action: 'update', existing_event_id: '1' })]),
    ],
  });
  const r1 = kakao(env, '내일 7시 어때?');
  assert.equal(env.events.size, 0);
  assert.ok(r1.skipped[0].startsWith('미확정'));
  const r2 = kakao(env, '좋아요 7시에 봐요');
  assert.equal(r2.updated.length, 1);
  assert.equal(env.events.size, 1);
});

test('시간 변경 → 수정, 취소 → [취소] 표시', () => {
  const env = setupEnv({
    claudeResponses: [
      claudeReply([ev()]),
      claudeReply([ev({ action: 'update', existing_event_id: '1', start: '2026-11-13T20:00' })]),
      claudeReply([ev({ action: 'cancel', existing_event_id: '1' })]),
    ],
  });
  kakao(env, '내일 7시 확정');
  kakao(env, '8시로 바꿔도 돼?');
  const cal = env.events.get('ev1');
  assert.equal(cal.start.toISOString(), '2026-11-13T11:00:00.000Z');
  const r = kakao(env, '미안 내일 취소하자');
  assert.deepEqual(r.cancelled, ['민수와 저녁']);
  assert.ok(cal.title.startsWith('[취소]'));
  assert.equal(cal.color, '8');
});

test('다른 채팅방의 일정은 수정·취소할 수 없음', () => {
  const env = setupEnv({
    claudeResponses: [claudeReply([ev()]), claudeReply([ev({ action: 'cancel', existing_event_id: '1' })])],
  });
  kakao(env, '내일 7시');
  const r = post(env, { token: tok(env), app: '카카오톡', title: '철수', text: '내일 취소' });
  assert.ok(r.skipped[0].startsWith('대상 일정 없음'));
  assert.ok(!env.events.get('ev1').title.startsWith('[취소]'));
});

test('종일 일정 (여러 날)', () => {
  const env = setupEnv({
    claudeResponses: [claudeReply([ev({ title: '여행', start: '2026-11-20', end: '2026-11-22', all_day: true, location: null })])],
  });
  kakao(env, '20일부터 22일까지 여행 가자');
  const cal = env.events.get('ev1');
  assert.equal(cal.allDay, true);
  assert.equal(cal.start.toISOString(), '2026-11-19T15:00:00.000Z'); // 11/20 00:00 KST
  assert.equal(cal.end.toISOString(), '2026-11-22T15:00:00.000Z');   // 11/23 00:00 KST (exclusive)
});

test('당근 + JSON 본문, 단톡방 "보낸사람: 내용" 분리', () => {
  const env = setupEnv({ claudeResponses: [claudeReply([ev({ title: '당근 거래: 아이패드 (당근이)' })]), claudeReply([])] });
  const body = JSON.stringify({ token: tok(env), app: 'com.towneers.www', title: '당근이', text: '내일 7시 역삼역 "가능"?' });
  assert.equal(post(env, {}, body).created.length, 1);
  post(env, { token: tok(env), app: 'com.kakao.talk', title: '동창회', room: '동창회', text: '영희: 토요일 6시 어때' });
  assert.match(env.requests[1].body.messages[0].content, /채팅방: 동창회[\s\S]*영희: 토요일 6시 어때/);
});

test('잘못된 날짜 형식이나 거절 응답은 건너뜀', () => {
  const env = setupEnv({
    claudeResponses: [
      claudeReply([ev({ start: '내일 저녁' })]),
      claudeReply([], undefined, { stop_reason: 'refusal', stop_details: { category: 'cyber' } }),
    ],
  });
  assert.equal(kakao(env, '내일 저녁에 봐').created.length, 0);
  assert.equal(kakao(env, '내일 7시').created.length, 0);
  assert.equal(env.events.size, 0);
});

test('API 오류(529)는 재시도', () => {
  const env = setupEnv({ claudeResponses: [{ code: 529, body: 'overloaded' }, claudeReply([ev()])] });
  assert.equal(kakao(env, '내일 7시').created.length, 1);
  assert.equal(env.requests.length, 2);
});

test('토큰 사용량 기록과 요약', () => {
  const env = setupEnv({ claudeResponses: [claudeReply([]), claudeReply([])] });
  kakao(env, '내일 7시');
  kakao(env, '모레 8시');
  env.ctx.__e = { parameter: { action: 'usage', token: tok(env) } };
  const u = env.run('doGet(__e)').json();
  assert.equal(u.all_time.calls, 2);
  assert.equal(u.today.input_tokens, 2000);
  assert.equal(u.this_month.estimated_cost_usd, (2000 * 4 + 400 * 20) / 1e6);
  env.ctx.__e = { parameter: { action: 'usage', token: 'bad' } };
  assert.equal(env.run('doGet(__e)').json().error, 'invalid token');
});

test('DRY_RUN 이면 캘린더에 쓰지 않음', () => {
  const env = setupEnv({ claudeResponses: [claudeReply([ev()])] });
  env.run('CONFIG.DRY_RUN = true');
  assert.equal(kakao(env, '내일 7시').created.length, 1);
  assert.equal(env.events.size, 0);
});

test('오래된 메시지·일정 기록 정리', () => {
  const env = setupEnv();
  const old = new Date(Date.now() - 3 * 86400000).toISOString();
  const recent = new Date().toISOString();
  env.store['m:kakao:민수'] = JSON.stringify([{ t: old, s: '민수', x: '옛날' }, { t: recent, s: '민수', x: '최근' }]);
  env.store['m:kakao:철수'] = JSON.stringify([{ t: old, s: '철수', x: '옛날' }]);
  env.store['e:1'] = JSON.stringify({ id: 1, start: '2020-01-01T10:00' });
  env.store['e:2'] = JSON.stringify({ id: 2, start: '2999-01-01T10:00' });
  env.run('cleanupOldData()');
  assert.deepEqual(JSON.parse(env.store['m:kakao:민수']).map((m) => m.x), ['최근']);
  assert.equal(env.store['m:kakao:철수'], undefined);
  assert.equal(env.store['e:1'], undefined);
  assert.ok(env.store['e:2']);
});

test('긴 메시지가 많아도 저장 한도(9KB)를 넘지 않음', () => {
  const env = setupEnv({ claudeResponses: Array.from({ length: 40 }, () => claudeReply([])) });
  for (let i = 0; i < 40; i++) kakao(env, `${i}번째 ` + '가'.repeat(400) + ' 내일 7시');
  const list = JSON.parse(env.store['m:kakao:민수']);
  assert.ok(list.length > 1 && list.length <= 30);
  assert.ok(Buffer.byteLength(env.store['m:kakao:민수']) <= 8500);
  assert.match(list[list.length - 1].x, /^39번째/);
});

test('약속 단어 없는 답장: 직전에 약속 이야기가 있었을 때만 Claude 호출', () => {
  const env = setupEnv({ claudeResponses: [claudeReply([]), claudeReply([])] });
  kakao(env, '오랜만이야');
  kakao(env, 'ㅇㅋ');
  assert.equal(env.requests.length, 0);
  kakao(env, '내일 7시 어때?');
  kakao(env, '좋아!');
  assert.equal(env.requests.length, 2);
});
