// 한국투자증권(KIS) 오픈API 중계 서버 — 국내주식 실시간 시세 대시보드
// 실행: node server.js   (Node.js 18 이상 필요 / 외부 패키지 없음)
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');

// .env 파일이 있으면 읽어서 환경변수로 로드
try {
  fs.readFileSync(path.join(__dirname, '.env'), 'utf8').split('\n').forEach(function (line) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '').trim();
  });
} catch (e) {}

const APPKEY = process.env.KIS_APPKEY;
const APPSECRET = process.env.KIS_APPSECRET;
const ENV = (process.env.KIS_ENV || 'real').toLowerCase();
const PORT = process.env.PORT || 3000;
const BASE = ENV === 'mock'
  ? 'https://openapivts.koreainvestment.com:29443'
  : 'https://openapi.koreainvestment.com:9443';
const TOKEN_FILE = path.join(__dirname, '.kis_token.json');

if (!APPKEY || !APPSECRET) {
  console.error('\n[오류] 환경변수 KIS_APPKEY, KIS_APPSECRET 가 필요합니다. (README 참고)\n');
  process.exit(1);
}
if (typeof fetch !== 'function') {
  console.error('\n[오류] Node.js 18 이상이 필요합니다 (내장 fetch). node -v 로 확인하세요.\n');
  process.exit(1);
}

const sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

let tokenCache = null;
try { tokenCache = JSON.parse(fs.readFileSync(TOKEN_FILE, 'utf8')); } catch (e) {}

let tokenInflight = null; // 동시 요청 시 토큰 중복 발급 방지 (KIS tokenP는 분당 1회 제한)
async function getToken() {
  if (tokenCache && tokenCache.token && Date.now() < tokenCache.exp - 60000) return tokenCache.token;
  if (!tokenInflight) {
    tokenInflight = (async function () {
      const r = await fetch(BASE + '/oauth2/tokenP', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ grant_type: 'client_credentials', appkey: APPKEY, appsecret: APPSECRET })
      });
      const j = await r.json();
      if (!j.access_token) throw new Error('토큰 발급 실패: ' + (j.error_description || j.msg1 || JSON.stringify(j)));
      tokenCache = { token: j.access_token, exp: Date.now() + ((j.expires_in || 86400) * 1000) };
      try { fs.writeFileSync(TOKEN_FILE, JSON.stringify(tokenCache)); } catch (e) {}
      console.log('KIS 접근토큰 발급/갱신 완료');
      return tokenCache.token;
    })();
    tokenInflight.finally(function () { tokenInflight = null; });
  }
  return tokenInflight;
}
// 동시 조회 풀 — limit개씩 병렬, 호출당 소폭 간격 (KIS 실전 초당 20건 제한 대비 여유)
async function mapLimit(items, limit, fn) {
  const out = new Array(items.length);
  let idx = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async function () {
    while (true) {
      const i = idx++;
      if (i >= items.length) break;
      try { out[i] = await fn(items[i], i); }
      catch (e) { out[i] = { code: items[i], error: e.message }; }
      await sleep(90);
    }
  });
  await Promise.all(workers);
  return out;
}

// ===== RSI(14) — 일봉 종가 기반, 일 단위 캐시 =====
function ymdSeoul(offsetDays) {
  const d = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
  if (offsetDays) d.setDate(d.getDate() + offsetDays);
  return '' + d.getFullYear() + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
}
function rsiWilder(closes, period) {
  period = period || 14;
  if (!closes || closes.length < period + 1) return null;
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) gain += d; else loss -= d;
  }
  let ag = gain / period, al = loss / period;
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    ag = (ag * (period - 1) + (d > 0 ? d : 0)) / period;
    al = (al * (period - 1) + (d < 0 ? -d : 0)) / period;
  }
  if (al === 0) return 100;
  return Math.round((100 - 100 / (1 + ag / al)) * 10) / 10;
}
const dailyCache = {}; // code -> { ymd, dates[], closes[] } 하루 1회만 KIS 일봉 호출
async function fetchDailyCloses(code) {
  const today = ymdSeoul();
  const c = dailyCache[code];
  if (c && c.ymd === today) return c;
  const token = await getToken();
  const url = BASE + '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
    + '?fid_cond_mrkt_div_code=J&fid_input_iscd=' + encodeURIComponent(code)
    + '&fid_input_date_1=' + ymdSeoul(-140) + '&fid_input_date_2=' + today
    + '&fid_period_div_code=D&fid_org_adj_prc=0';
  const r = await fetch(url, {
    headers: {
      'content-type': 'application/json',
      'authorization': 'Bearer ' + token,
      'appkey': APPKEY,
      'appsecret': APPSECRET,
      'tr_id': 'FHKST03010100',
      'custtype': 'P'
    }
  });
  const j = await r.json();
  const arr = (j.output2 || []).filter(function (x) { return x && x.stck_bsop_date && x.stck_clpr; });
  if (!arr.length) {
    const msg = j.msg1 || '';
    if (/초당|EGW00201|초과/.test(msg)) { await sleep(500); return fetchDailyCloses(code); }
    return null;
  }
  arr.sort(function (a, b) { return a.stck_bsop_date < b.stck_bsop_date ? -1 : 1; });
  const out = {
    ymd: today,
    dates: arr.map(function (x) { return x.stck_bsop_date; }),
    closes: arr.map(function (x) { return Number(x.stck_clpr); })
  };
  dailyCache[code] = out;
  return out;
}
async function rsiFor(code, livePrice) {
  try {
    const cached = dailyCache[code] && dailyCache[code].ymd === ymdSeoul();
    if (!cached) await sleep(110); // 캐시 없을 때만 추가 KIS 호출 → 호출 간격 유지
    const dc = await fetchDailyCloses(code);
    if (!dc) return null;
    const closes = dc.closes.slice();
    if (dc.dates[dc.dates.length - 1] === ymdSeoul()) closes[closes.length - 1] = livePrice; // 오늘 봉이 있으면 현재가로 대체
    else closes.push(livePrice); // 없으면 현재가를 오늘 봉으로 추가
    return rsiWilder(closes, 14);
  } catch (e) { return null; }
}

async function fetchQuoteOnce(code) {
  const token = await getToken();
  const url = BASE + '/uapi/domestic-stock/v1/quotations/inquire-price'
    + '?fid_cond_mrkt_div_code=J&fid_input_iscd=' + encodeURIComponent(code);
  const r = await fetch(url, {
    headers: {
      'content-type': 'application/json',
      'authorization': 'Bearer ' + token,
      'appkey': APPKEY,
      'appsecret': APPSECRET,
      'tr_id': 'FHKST01010100',
      'custtype': 'P'
    }
  });
  const j = await r.json();
  const o = j.output || {};
  if (!o.stck_prpr) {
    const msg = j.msg1 || 'no data';
    if (/초당|EGW00201|초과/.test(msg)) { await sleep(500); return fetchQuoteOnce(code); }
    return { code: code, error: msg };
  }
  const price = Number(o.stck_prpr);
  return {
    code: code,
    price: price,
    changePct: Number(o.prdy_ctrt),
    volume: Number(o.acml_vol),
    mktcapEok: Number(o.hts_avls),
    rsi: await rsiFor(code, price)
  };
}

const PUB = path.join(__dirname, 'public');

// ===== 전 종목 스냅샷 — 장중 백그라운드 사전 갱신 → 화면은 즉시 응답 =====
let KTOPCODES = [];
try {
  const kt = JSON.parse(fs.readFileSync(path.join(PUB, 'ktop10.json'), 'utf8'));
  Object.keys(kt.stocks).forEach(function (s) { kt.stocks[s].forEach(function (x) { KTOPCODES.push(x[0]); }); });
  console.log('ktop10.json 로드: ' + KTOPCODES.length + '종목');
} catch (e) { console.error('ktop10.json 로드 실패:', e.message); }
const snapshot = { data: {}, ts: 0, sweeping: false, lastEnd: 0 };
function seoulHour() { try { return new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Seoul' })).getHours(); } catch (e) { return 12; } }
async function sweep() {
  if (snapshot.sweeping || !KTOPCODES.length) return;
  snapshot.sweeping = true;
  const t0 = Date.now();
  try {
    await mapLimit(KTOPCODES, 2, async function (code) {
      const q = await fetchQuoteOnce(code);
      snapshot.data[code] = q;
      snapshot.ts = Date.now();
      return q;
    });
  } catch (e) {}
  snapshot.lastEnd = Date.now();
  snapshot.sweeping = false;
  console.log('스냅샷 갱신 완료: ' + Object.keys(snapshot.data).length + '종목, ' + Math.round((Date.now() - t0) / 1000) + '초');
}
setTimeout(sweep, 2000); // 서버 기동 직후 1회
setInterval(function () {
  const h = seoulHour();
  const stale = Date.now() - snapshot.lastEnd > 180000; // 3분
  if (h >= 8 && h < 18 && stale && !snapshot.sweeping) sweep();
}, 60000);
const server = http.createServer(async function (req, res) {
  const u = new URL(req.url, 'http://x');
  res.setHeader('Access-Control-Allow-Origin', '*');

  if (u.pathname === '/api/quotes') {
    const codes = (u.searchParams.get('codes') || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean).slice(0, 200);
    try {
      const out = await mapLimit(codes, 3, function (code) { return fetchQuoteOnce(code); });
      out.forEach(function (q) { if (q && q.code && !q.error) { snapshot.data[q.code] = q; snapshot.ts = Date.now(); } });
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ data: out, ts: Date.now() }));
    } catch (e) {
      res.statusCode = 500;
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  if (u.pathname === '/api/summary') {
    // 백그라운드 스냅샷 즉시 응답 (전체 섹터 화면용)
    const done = KTOPCODES.filter(function (c) { return snapshot.data[c] && !snapshot.data[c].error; }).length;
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({
      data: KTOPCODES.map(function (c) { return snapshot.data[c] || { code: c, pending: true }; }),
      ts: snapshot.ts,
      complete: KTOPCODES.length > 0 && done >= KTOPCODES.length - 3, // 일부 실패(거래정지 등) 허용
      progress: done + '/' + KTOPCODES.length
    }));
    return;
  }

  if (u.pathname === '/api/history') {
    // 일봉 종가 이력 (dailyCache 재활용 — /api/quotes 이후 호출하면 대부분 캐시 적중)
    const codes = (u.searchParams.get('codes') || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean).slice(0, 200);
    const days = Math.min(Number(u.searchParams.get('days') || 60) || 60, 100);
    try {
      const out = await mapLimit(codes, 3, async function (code) {
        const dc = await fetchDailyCloses(code);
        return dc ? { code: code, dates: dc.dates.slice(-days), closes: dc.closes.slice(-days) } : { code: code, error: 'no data' };
      });
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ data: out, ts: Date.now() }));
    } catch (e) {
      res.statusCode = 500;
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  const rel = u.pathname === '/' ? '/index.html' : u.pathname;
  const full = path.join(PUB, rel);
  if (!full.startsWith(PUB)) { res.statusCode = 403; res.end('forbidden'); return; }
  fs.readFile(full, function (err, data) {
    if (err) { res.statusCode = 404; res.end('not found'); return; }
    const ext = path.extname(full);
    const ct = ext === '.html' ? 'text/html; charset=utf-8'
      : ext === '.js' ? 'text/javascript; charset=utf-8'
      : ext === '.css' ? 'text/css; charset=utf-8' : 'text/plain; charset=utf-8';
    res.setHeader('content-type', ct);
    res.end(data);
  });
});

server.listen(PORT, function () {
  console.log('KIS 한국 섹터 대시보드 서버 실행 중  ->  http://localhost:' + PORT + '  (KIS_ENV=' + ENV + ')');
  console.log('브라우저로 위 주소를 여세요. 종료하려면 Ctrl+C');
});
