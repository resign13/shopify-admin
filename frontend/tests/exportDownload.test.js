import test from 'node:test';
import assert from 'node:assert/strict';
import { downloadFile, createOrderExportController } from '../src/utils/exportDownload.js';

const failure = (status, code, retryAfter = '5') => new Response(JSON.stringify({ code, message: 'server message', extra: 7 }), {
  status, headers: { 'Content-Type': 'application/json', 'Retry-After': retryAfter },
});

function fakeBrowser() {
  const saved = { document: globalThis.document, setTimeout: globalThis.setTimeout, now: Date.now, create: URL.createObjectURL, revoke: URL.revokeObjectURL };
  let now = 0;
  const waits = [], calls = [], revocations = [];
  Date.now = () => now;
  globalThis.setTimeout = (fn, ms) => {
    waits.push(ms);
    if (ms === 120000) return 123;
    if (ms === 60000 && calls.includes('click')) revocations.push(fn);
    else { now += ms; queueMicrotask(fn); }
  };
  URL.createObjectURL = blob => { calls.push(blob); return 'blob:test'; };
  URL.revokeObjectURL = url => calls.push(['revoke', url]);
  globalThis.document = {
    createElement: () => ({ click() { calls.push('click'); }, remove() { calls.push('remove'); } }),
    body: { appendChild: element => calls.push(element) },
  };
  return { waits, calls, revocations, restore() { globalThis.document = saved.document; globalThis.setTimeout = saved.setTimeout; Date.now = saved.now; URL.createObjectURL = saved.create; URL.revokeObjectURL = saved.revoke; } };
}

test('error metadata and default download behavior', async () => {
  let count = 0;
  await assert.rejects(downloadFile(async () => { count++; return failure(429, 'export_capacity', '4'); }, '/x', 'x'), e => {
    assert.equal(e.message, 'server message');
    assert.equal(e.status, 429); assert.equal(e.code, 'export_capacity'); assert.equal(e.retryAfter, 4);
    assert.deepEqual(e.data, { code: 'export_capacity', message: 'server message', extra: 7 });
    return true;
  });
  assert.equal(count, 1);
});

test('only approved 429 busy codes retry, with phase callbacks and full blob download', async () => {
  const browser = fakeBrowser();
  try {
    const body = new Uint8Array([0, 255, 4, 10]);
    const responses = [failure(429, 'export_capacity', '0'), failure(429, 'export_in_progress', '2'), new Response(body)];
    const phases = [], requests = [];
    await downloadFile(async (url, options) => { requests.push([url, options]); return responses.shift(); }, '/orders', '订单.xlsx', {
      method: 'POST', busyRetry: true, onBusyWait: e => phases.push(e.message), onBusyResume: () => phases.push('resume'),
    });
    assert.deepEqual(requests, Array.from({ length: 3 }, () => ['/orders', { method: 'POST' }]));
    assert.deepEqual(browser.waits, [1000, 2000, 60000]);
    assert.deepEqual(phases, ['导出服务繁忙，正在等待空闲资源', 'resume', '已有导出任务正在进行，正在等待完成', 'resume']);
    assert.deepEqual(new Uint8Array(await browser.calls[0].arrayBuffer()), body);
    assert.equal(browser.calls[1].href, 'blob:test'); assert.equal(browser.calls[1].download, '订单.xlsx');
    assert.deepEqual(browser.calls.slice(2), ['click', 'remove']);
    browser.revocations[0](); assert.deepEqual(browser.calls.at(-1), ['revoke', 'blob:test']);
  } finally { browser.restore(); }
});

test('no automatic retry for ordinary rate limit, other status, or network error', async () => {
  for (const [status, code] of [[429, 'rate_limited'], [503, 'export_capacity'], [429, 'other']]) {
    let count = 0;
    await assert.rejects(downloadFile(async () => { count++; return failure(status, code); }, '/x', 'x', { busyRetry: true }), e => e.status === status && e.code === code);
    assert.equal(count, 1);
  }
  let count = 0;
  await assert.rejects(downloadFile(async () => { count++; throw new Error('offline'); }, '/x', 'x', { busyRetry: true }), /offline/);
  assert.equal(count, 1);
});

test('busy retries stop at 120 seconds with metadata and friendly timeout', async () => {
  const browser = fakeBrowser();
  try {
    let count = 0;
    await assert.rejects(downloadFile(async () => { count++; return failure(429, 'export_capacity', '7'); }, '/x', 'x', { busyRetry: true }), e => {
      assert.equal(e.message, '导出排队等待超时，请稍后重试'); assert.equal(e.status, 429); assert.equal(e.code, 'export_capacity'); assert.equal(e.retryAfter, 7); return true;
    });
    assert.equal(count, 18); assert.equal(browser.waits.reduce((a, b) => a + b, 0), 120000);
  } finally { browser.restore(); }
});

test('shared controller prevents overlap and releases state on completion or failure', async () => {
  const state = { busy: false, phase: '', position: null }, controller = createOrderExportController(state);
  let release, count = 0;
  const first = controller.run(async options => {
    count++;
    assert.equal(state.phase, 'generating');
    options.onBusyWait({ data: { position: 3 } }); assert.equal(state.phase, 'waiting'); assert.equal(state.position, 3);
    assert.equal(options.busyRetry, true); assert.equal(options.requestTimeout, 120000); assert.match(options.headers['X-Export-Ticket'], /^[0-9a-f-]{36}$/i);
    options.onBusyResume(); assert.equal(state.phase, 'generating'); assert.equal(state.position, null);
    await new Promise(resolve => { release = resolve; });
  });
  assert.equal(state.busy, true);
  assert.equal(await controller.run(async () => { count++; }), false);
  assert.equal(count, 1);
  release(); assert.equal(await first, true); assert.deepEqual(state, { busy: false, phase: '', position: null });
  await assert.rejects(controller.run(async () => { throw new Error('failure'); }), /failure/);
  assert.deepEqual(state, { busy: false, phase: '', position: null });
  assert.equal(await controller.run(async () => {}), true);
});


test('queued ticket and position stay stable on retries; terminal queue errors are not retried', async () => {
  const browser = fakeBrowser();
  try {
    const state = { busy: false, phase: '', position: null }, controller = createOrderExportController(state);
    const headers = [], positions = [];
    await controller.run(async options => {
      const onBusyWait = options.onBusyWait;
      options.onBusyWait = error => { onBusyWait(error); positions.push(state.position); };
      await downloadFile(async (_url, request) => {
        headers.push(request.headers['X-Export-Ticket']);
        if (headers.length < 3) return new Response(JSON.stringify({code:'export_queued', ticketId:headers[0], position:headers.length}), {status:429, headers:{'Retry-After':'1'}});
        return new Response(new Uint8Array([42]));
      }, '/orders', 'queue.xlsx', options);
    });
    assert.deepEqual(positions, [1, 2]);
    assert.equal(new Set(headers).size, 1);
    for (const code of ['export_queue_full', 'export_ticket_started', 'export_ticket_finished', 'export_ticket_expired']) {
      let attempts = 0;
      await assert.rejects(downloadFile(async () => { attempts++; return failure(429, code); }, '/orders', 'x', { busyRetry: true }), e => e.code === code);
      assert.equal(attempts, 1);
    }
    await assert.rejects(downloadFile(async () => failure(504, 'export_timeout'), '/orders', 'x', { busyRetry: true }), e => e.message === '导出生成超时，请稍后重新发起');
  } finally { browser.restore(); }
});

test('request and blob body each share a bounded attempt timeout; timeout is not retried', async () => {
  const oldSet = globalThis.setTimeout, oldClear = globalThis.clearTimeout;
  let timer, cleared = 0;
  globalThis.setTimeout = (fn, ms) => { assert.equal(ms, 120000); timer = fn; return 123; };
  globalThis.clearTimeout = id => { assert.equal(id, 123); cleared++; };
  try {
    for (const phase of ['request', 'body']) {
      let calls = 0, signal;
      const pending = downloadFile(async (_url, options) => {
        calls++; signal = options.signal;
        const abortable = () => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once:true }));
        return phase === 'request' ? abortable() : { ok:true, blob:abortable };
      }, '/orders', 'x', { busyRetry:true, requestTimeout:120000 });
      await Promise.resolve(); timer();
      await assert.rejects(pending, e => e.code === 'export_request_timeout' && e.message.includes('确认导出状态'));
      assert.equal(signal.aborted, true); assert.equal(calls, 1);
    }
    assert.equal(cleared, 2);
  } finally { globalThis.setTimeout = oldSet; globalThis.clearTimeout = oldClear; }
});
test('attempt timer and caller abort listener are cleaned up; caller abort is not retried', async () => {
  const browser = fakeBrowser();
  const originalClear = globalThis.clearTimeout;
  let clears = 0, added = 0, removed = 0;
  const parent = new AbortController(), signal = parent.signal;
  const add = signal.addEventListener.bind(signal), remove = signal.removeEventListener.bind(signal);
  signal.addEventListener = (...args) => { added++; return add(...args); };
  signal.removeEventListener = (...args) => { removed++; return remove(...args); };
  globalThis.clearTimeout = () => { clears++; };
  try {
    await downloadFile(async () => new Response(new Uint8Array([1])), '/orders', 'x', { requestTimeout:120000, signal });
    assert.equal(clears, 1); assert.equal(added, 1); assert.equal(removed, 1);
    let attempts = 0;
    const request = downloadFile(async (_url, options) => {
      attempts++;
      return new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once:true}));
    }, '/orders', 'x', { busyRetry:true, requestTimeout:120000, signal });
    parent.abort(); await assert.rejects(request, { name:'AbortError' });
    assert.equal(attempts, 1); assert.equal(clears, 2); assert.equal(added, 2); assert.equal(removed, 2);
  } finally { globalThis.clearTimeout = originalClear; browser.restore(); }
});
import { orderExportIds } from '../src/utils/orderExportScope.js';

test('order export scope uses selected IDs or exactly the current page; empty means no export', () => {
  const page25 = Array.from({length:25}, (_, i) => ({id:i + 1}));
  const page50 = Array.from({length:50}, (_, i) => ({id:i + 26}));
  assert.deepEqual(orderExportIds([], page25), page25.map(row => row.id));
  assert.deepEqual(orderExportIds([], page50), page50.map(row => row.id));
  assert.deepEqual(orderExportIds([{id:2}, {id:8}], page50), [2, 8]);
  assert.deepEqual(orderExportIds([], []), []);
  assert.deepEqual(orderExportIds([{id:null}], page25), []);
});

function readyResult(ticket) {
  const path = `/api/admin/orders/export-results/${ticket}`;
  return { ticketId: ticket, status: 'ready', statusUrl: path, downloadUrl: `${path}/download`, filename: '真实订单.xlsx', expiresAt: '2099-01-01T00:00:00Z' };
}
const jsonResponse = data => new Response(JSON.stringify(data), {headers:{'Content-Type':'application/json'}});

test('ready JSON and complete download have independent attempts; retry downloads the same file without regeneration', async () => {
  const browser = fakeBrowser();
  try {
    const state = {busy:false,phase:'',position:null}, controller = createOrderExportController(state);
    const calls = [], body = new Uint8Array([80,75,255,0]);
    let ticket, downloads = 0;
    const fetcher = async (url, options) => {
      calls.push([url,options.method]);
      if (url === '/generate') {
        ticket = options.headers['X-Export-Ticket'];
        return jsonResponse(readyResult(ticket));
      }
      assert.equal(url, readyResult(ticket).downloadUrl);
      assert.equal(options.method,'GET');
      assert.equal(state.phase,'downloading');
      downloads++;
      if (downloads===1) throw new TypeError('Download disconnected');
      return new Response(body);
    };
    await assert.rejects(controller.run(options => downloadFile(fetcher,'/generate','x.xlsx',{method:'POST',...options})), /disconnected/);
    assert.equal(state.busy,false); assert.equal(state.recovery,'download');
    assert.equal(await controller.recover(),true);
    assert.deepEqual(calls,[['/generate','POST'],[readyResult(ticket).downloadUrl,'GET'],[readyResult(ticket).downloadUrl,'GET']]);
    assert.equal(browser.calls[1].download,'真实订单.xlsx');
    assert.deepEqual(new Uint8Array(await browser.calls[0].arrayBuffer()),body);
    assert.equal(browser.waits.filter(ms => ms===120000).length,3);
  } finally { browser.restore(); }
});

test('unknown generation response can be recovered through status, without replaying generation', async () => {
  const browser = fakeBrowser();
  try {
    const state = {busy:false,phase:'',position:null}, controller = createOrderExportController(state);
    const calls = []; let ticket, statusCalls = 0;
    const fetcher = async (url, options) => {
      calls.push([url,options.method]);
      if (url==='/generate') { ticket=options.headers['X-Export-Ticket']; throw new TypeError('Generation response lost'); }
      if (url===readyResult(ticket).statusUrl) {
        statusCalls++;
        return jsonResponse(statusCalls===1 ? {status:'started'} : readyResult(ticket));
      }
      assert.equal(url,readyResult(ticket).downloadUrl);
      return new Response(new Uint8Array([80,75]));
    };
    await assert.rejects(controller.run(options => downloadFile(fetcher,'/generate','x.xlsx',{method:'POST',...options})), /lost/);
    assert.equal(state.recovery,'status');
    await assert.rejects(controller.recover(),e => e.code==='export_pending');
    assert.equal(state.recovery,'status');
    assert.equal(await controller.recover(),true);
    assert.equal(calls.filter(([,method])=>method==='POST').length,1);
    assert.equal(calls.length,4);
  } finally { browser.restore(); }
});

test('foreign result download URLs are rejected and no file request is sent', async () => {
  const browser = fakeBrowser();
  try {
    const state = {busy:false,phase:'',position:null}, controller = createOrderExportController(state);
    let calls=0;
    await assert.rejects(controller.run(options => downloadFile(async()=>{
      calls++;
      return jsonResponse({...readyResult(options.headers['X-Export-Ticket']),downloadUrl:'https://example.com/steal'});
    },'/generate','x.xlsx',options)),e=>e.code==='export_result_invalid');
    assert.equal(calls,1); assert.equal(state.recovery,null);
    assert.equal(await controller.recover(),false);
  } finally { browser.restore(); }
});

test('expired or forbidden result clears recovery rather than starting another export', async () => {
  const browser = fakeBrowser();
  try {
    const state = {busy:false,phase:'',position:null}, controller = createOrderExportController(state);
    let calls=0;
    const fetcher=async()=>{ calls++; if(calls===1) throw new TypeError('offline'); return failure(404,'not_found'); };
    await assert.rejects(controller.run(options=>downloadFile(fetcher,'/generate','x.xlsx',options)),/offline/);
    await assert.rejects(controller.recover(),e=>e.status===404);
    assert.equal(calls,2); assert.equal(state.recovery,null);
  } finally { browser.restore(); }
});

test('temporary download service failure keeps the manual download action without automatic replay', async () => {
  const browser = fakeBrowser();
  try {
    const state={busy:false,phase:'',position:null},controller=createOrderExportController(state);
    let calls=0;
    const fetcher=async(_url,options)=>{
      calls++;
      if(calls===1) return jsonResponse(readyResult(options.headers['X-Export-Ticket']));
      if(calls===2) return failure(503,'database_busy');
      return new Response(new Uint8Array([80,75]));
    };
    await assert.rejects(controller.run(options=>downloadFile(fetcher,'/generate','x.xlsx',options)),e=>e.status===503);
    assert.equal(calls,2);assert.equal(state.recovery,'download');
    await controller.recover();assert.equal(calls,3);
  } finally {browser.restore();}
});
