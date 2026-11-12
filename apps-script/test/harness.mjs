// 앱스 스크립트 전역 서비스를 흉내 내서 Code.gs 를 Node 에서 실행하는 테스트 도구
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const CODE = fs.readFileSync(path.join(here, '..', 'Code.gs'), 'utf8');
const KST = 9 * 3600000; // 테스트는 Asia/Seoul 고정

function pad(n, w = 2) { return String(n).padStart(w, '0'); }

function formatDate(d, tz, pattern) {
  const k = new Date(d.getTime() + KST);
  const map = {
    yyyy: k.getUTCFullYear(), MM: pad(k.getUTCMonth() + 1), dd: pad(k.getUTCDate()),
    HH: pad(k.getUTCHours()), mm: pad(k.getUTCMinutes()), u: ((k.getUTCDay() + 6) % 7) + 1,
  };
  return pattern.replace(/yyyy|MM|dd|HH|mm|u/g, (t) => String(map[t]));
}

function parseDate(s, tz, pattern) {
  let m;
  if (pattern === 'yyyy-MM-dd' && (m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/))) {
    return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]) - KST);
  }
  if (pattern === 'yyyy-MM-dd HH:mm' && (m = s.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/))) {
    return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) - KST);
  }
  throw new Error('parse error');
}

class Range {
  constructor(sheet, row, col, nr, nc) { Object.assign(this, { sheet, row, col, nr, nc }); }
  setNumberFormat() { return this; }
  setValues(values) {
    values.forEach((rowVals, i) => {
      const r = this.row + i - 1;
      while (this.sheet.data.length <= r) this.sheet.data.push([]);
      rowVals.forEach((v, j) => { this.sheet.data[r][this.col + j - 1] = v; });
    });
    return this;
  }
  getValues() {
    const out = [];
    for (let i = 0; i < this.nr; i++) {
      const row = this.sheet.data[this.row + i - 1] || [];
      const vals = [];
      for (let j = 0; j < this.nc; j++) { const v = row[this.col + j - 1]; vals.push(v === undefined ? '' : v); }
      out.push(vals);
    }
    return out;
  }
}

class Sheet {
  constructor(name) { this.name = name; this.data = []; }
  getName() { return this.name; }
  getLastRow() { return this.data.length; }
  getLastColumn() { return Math.max(0, ...this.data.map((r) => r.length)); }
  getMaxRows() { return 1000; }
  insertRowsAfter() {}
  getRange(row, col, nr = 1, nc = 1) { return new Range(this, row, col, nr, nc); }
  setFrozenRows() {}
  deleteRows(start, count) { this.data.splice(start - 1, count); }
}

class Spreadsheet {
  constructor() { this.sheets = [new Sheet('Sheet1')]; this.id = 'ss-1'; }
  getId() { return this.id; }
  getUrl() { return 'https://docs.google.com/spreadsheets/d/ss-1'; }
  getSheetByName(n) { return this.sheets.find((s) => s.name === n) || null; }
  insertSheet(n) { const s = new Sheet(n); this.sheets.push(s); return s; }
  getSheets() { return this.sheets; }
  deleteSheet(s) { this.sheets = this.sheets.filter((x) => x !== s); }
}

class CalEvent {
  constructor(id, title, start, end, opts, allDay) {
    Object.assign(this, { id, title, start, end, allDay, location: opts.location || '', description: opts.description || '', color: null });
  }
  getId() { return this.id; }
  setTitle(t) { this.title = t; }
  setDescription(d) { this.description = d; }
  setLocation(l) { this.location = l; }
  setTime(s, e) { this.start = s; this.end = e; this.allDay = false; }
  setAllDayDates(s, e) { this.start = s; this.end = e; this.allDay = true; }
  setColor(c) { this.color = c; }
}

export function createEnv({ claudeResponses = [], props = {} } = {}) {
  const store = { ANTHROPIC_API_KEY: 'test-key', ...props };
  const ss = new Spreadsheet();
  const events = new Map();
  const requests = [];
  const responses = [...claudeResponses];
  const logs = [];

  const calendar = {
    createEvent(title, start, end, opts) {
      const ev = new CalEvent('ev' + (events.size + 1), title, start, end, opts, false); events.set(ev.id, ev); return ev;
    },
    createAllDayEvent(title, start, end, opts) {
      const ev = new CalEvent('ev' + (events.size + 1), title, start, end, opts, true); events.set(ev.id, ev); return ev;
    },
    getEventById(id) { return events.get(id) || null; },
  };

  const ctx = {
    console: { log: (...a) => logs.push(a.join(' ')), warn: (...a) => logs.push(a.join(' ')), error: (...a) => logs.push(a.join(' ')) },
    PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => store[k] ?? null, setProperty: (k, v) => { store[k] = v; } }) },
    SpreadsheetApp: {
      create: () => ss,
      openById: (id) => { if (id !== ss.id) throw new Error('not found'); return ss; },
    },
    CalendarApp: { getDefaultCalendar: () => calendar, getCalendarById: () => calendar, EventColor: { GRAY: '8' } },
    UrlFetchApp: {
      fetch(url, opts) {
        requests.push({ url, opts, body: JSON.parse(opts.payload) });
        const next = responses.shift();
        if (!next) throw new Error('예상치 못한 Claude 호출');
        const r = typeof next === 'function' ? next(JSON.parse(opts.payload)) : next;
        const code = r.code || 200;
        const text = typeof r.body === 'string' ? r.body : JSON.stringify(r.body);
        return { getResponseCode: () => code, getContentText: () => text };
      },
    },
    Utilities: { formatDate, parseDate, getUuid: () => crypto.randomUUID(), sleep: () => {} },
    Session: { getScriptTimeZone: () => 'Asia/Seoul' },
    LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
    ContentService: {
      MimeType: { JSON: 'json' },
      createTextOutput: (t) => ({ text: t, setMimeType() { return this; }, json() { return JSON.parse(t); } }),
    },
    ScriptApp: {
      triggers: [],
      getProjectTriggers() { return this.triggers; },
      deleteTrigger() {},
      newTrigger(fn) {
        const t = { getHandlerFunction: () => fn };
        const chain = { timeBased: () => chain, everyDays: () => chain, atHour: () => chain, create: () => { ctx.ScriptApp.triggers.push(t); return t; } };
        return chain;
      },
    },
  };
  vm.createContext(ctx);
  vm.runInContext(CODE, ctx, { filename: 'Code.gs' });
  const run = (code) => vm.runInContext(code, ctx);
  return { ctx, run, ss, events, requests, logs, store };
}

/** Claude 응답 본문 */
export function claudeReply(events, usage = { input_tokens: 1000, output_tokens: 200 }, extra = {}) {
  return {
    body: {
      id: 'msg', type: 'message', role: 'assistant', model: 'claude-opus-5-5',
      content: [{ type: 'thinking', thinking: '' }, { type: 'text', text: JSON.stringify({ events }) }],
      stop_reason: 'end_turn', usage, ...extra,
    },
  };
}

export function ev(overrides = {}) {
  return {
    action: 'create', existing_event_id: null, title: '민수와 저녁', start: '2026-11-13T19:00', end: null,
    all_day: false, location: '강남역', status: 'confirmed', evidence: '내일 저녁 7시', ...overrides,
  };
}
