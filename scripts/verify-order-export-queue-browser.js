// Run only in the already-authenticated, isolated 5380 *_test browser fixture.
// Every order-export request is intercepted; no order or account is modified.
async (page) => {
  const base = 'http://127.0.0.1:5380';
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated 5380 *_test fixture required');
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const errors = [], calls = [];
  const errorListener = error => errors.push(error.message);
  const excel = Buffer.from('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', 'base64');
  const exportPattern = /\/api\/admin\/orders\/(?:export|export-by-sheet|\d+\/invoice)(?:\?|$)/;
  let scenario = '', round = 0, release, listHandler;
  let resultTicket, resultDownloads = 0;
  const resultPattern = /\/api\/admin\/orders\/export-results\/[0-9a-f-]+(?:\/download)?$/;
  const listPattern = /\/api\/admin\/orders\?/;
  let gate = Promise.resolve();
  const prepare = name => {
    scenario = name; round = 0;
    gate = new Promise(resolve => { release = resolve; });
  };
  const handler = async route => {
    const request = route.request();
    calls.push({ scenario, url: request.url(), method: request.method(), ticket: request.headers()['x-export-ticket'] });
    round++;
    if (scenario === 'result-recovery') {
      resultTicket = request.headers()['x-export-ticket'];
      const path = '/api/admin/orders/export-results/' + resultTicket;
      await route.fulfill({status:200, contentType:'application/json',body:JSON.stringify({ticketId:resultTicket,status:'ready',statusUrl:path,downloadUrl:path+'/download',filename:'订单-结果重下.xlsx',expiresAt:'2099-01-01T00:00:00Z'})});
      return;
    }
    if (scenario === 'ordinary-limit') {
      await route.fulfill({ status: 429, contentType: 'application/json', headers: {'Retry-After': '1'}, body: JSON.stringify({code:'rate_limited', message:'普通限流测试'}) });
      return;
    }
    if ((scenario === 'list-queued' || scenario === 'invoice-busy') && round === 1) {
      await route.fulfill({ status: 429, contentType: 'application/json', headers: {'Retry-After': '1'}, body: JSON.stringify(scenario === 'list-queued' ? {code:'export_queued', ticketId:request.headers()['x-export-ticket'], position:2, retryAfter:1} : {code:'export_in_progress', message:'busy'}) });
      return;
    }
    await gate;
    await route.fulfill({ status: 200, contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body: excel });
  };
  const resultHandler = async route => {
    check(route.request().method()==='GET','Result download must be GET');
    check(route.request().url().endsWith('/'+resultTicket+'/download'),'Unexpected result URL');
    resultDownloads++;
    if (resultDownloads===1) { await gate; await route.abort('failed'); return; }
    await route.fulfill({status:200,contentType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',body:excel});
  };
  const readDownload = async event => {
    const download = await event;
    check(!await download.failure(), 'Download failed');
    const chunks = [];
    for await (const chunk of await download.createReadStream()) chunks.push(chunk);
    check(Buffer.concat(chunks).equals(excel), 'Downloaded XLSX bytes are incomplete or changed');
    check(download.suggestedFilename().endsWith('.xlsx'), 'Incorrect download filename');
  };
  const menu = () => page.getByRole('dialog', {name:'订单操作', exact:true});
  const detail = () => page.getByRole('dialog', {name:'订单详情', exact:true});
  const sheet = () => page.getByRole('dialog', {name:'更多操作', exact:true});
  const progress = () => page.getByTestId('order-export-progress');
  const openOrderMenu = async () => { await page.getByRole('button', {name:'订单操作', exact:true}).click(); await menu().waitFor(); };
  const beginListExport = async () => {
    await openOrderMenu();
    await menu().getByRole('button', {name:/合并导出/}).click();
    await menu().waitFor({state:'hidden'});
  };
  const openDetail = async () => {
    await page.locator('.m-order-card').first().click();
    await page.getByTestId('mobile-order-detail').waitFor();
  };
  const openDetailMenu = async () => { await detail().locator('.mobile-more-trigger').click(); await sheet().waitFor(); };
  const closeDetailMenu = async () => { await sheet().getByRole('button',{name:'取消',exact:true}).click(); await sheet().waitFor({state:'hidden'}); };
  const waitGenerating = async () => page.waitForFunction(() => document.querySelector('[data-testid="order-export-progress"]')?.textContent.includes('正在生成'));
  const waitWaiting = async text => page.waitForFunction(value => document.querySelector('[data-testid="order-export-progress"]')?.textContent.includes(value), text);
  page.on('pageerror', errorListener);
  await page.route(exportPattern, handler);
  await page.route(resultPattern, resultHandler);
  try {
    await page.setViewportSize({width:393,height:852});
    await page.goto(base + '/orders?page=1&pageSize=25');
    await page.locator('.m-order-card').first().waitFor();
    // List export: mobile action sheet closes, but the persistent page indicator remains.
    prepare('list-queued');
    const firstDownload = page.waitForEvent('download');
    await beginListExport();
    await waitWaiting('队列位置：第 2 位'); check(await progress().isVisible(), 'Queue position hidden after mobile menu closed');
    await waitGenerating();
    await openDetail(); await openDetailMenu();
    check(await sheet().getByRole('button',{name:'导出订单详情',exact:true}).isDisabled(), 'Invoice can overlap list export');
    await closeDetailMenu(); await detail().getByRole('button',{name:'关闭',exact:true}).click();
    await detail().waitFor({state:'hidden'});
    check(await progress().isVisible(), 'Indicator disappeared while export still generating');
    check(calls.filter(c=>c.scenario==='list-queued').length===2, 'Unexpected list/PI duplicate request');
    const listCalls = calls.filter(c=>c.scenario==='list-queued');
    check(/^[0-9a-f-]{36}$/i.test(listCalls[0].ticket) && listCalls[0].ticket===listCalls[1].ticket, 'Queue polls did not preserve one UUID ticket');
    release(); await readDownload(firstDownload); await progress().waitFor({state:'hidden'});

    // Invoice export: closing the detail drawer must not cancel it, and list actions share the lock.
    prepare('invoice-busy');
    await openDetail(); await openDetailMenu();
    const secondDownload = page.waitForEvent('download');
    await sheet().getByRole('button',{name:'导出订单详情',exact:true}).click();
    await sheet().waitFor({state:'hidden'});
    await detail().getByRole('button',{name:'关闭',exact:true}).click(); await detail().waitFor({state:'hidden'});
    await waitWaiting('正在等待'); check(await progress().isVisible(), 'Closed drawer lost PI waiting indicator');
    await waitGenerating();
    await openOrderMenu();
    check(await menu().getByRole('button',{name:/合并导出/}).isDisabled(), 'List export can overlap PI');
    await menu().getByRole('button',{name:'取消',exact:true}).click(); await menu().waitFor({state:'hidden'});
    const invoiceCalls = calls.filter(c=>c.scenario==='invoice-busy');
    check(invoiceCalls.length===2, 'Unexpected invoice/list duplicate request');
    check(invoiceCalls[0].ticket===invoiceCalls[1].ticket && invoiceCalls[0].ticket!==listCalls[0].ticket, 'Invoice ticket was not stable and unique');
    release(); await readDownload(secondDownload); await progress().waitFor({state:'hidden'});

    // Other 429 codes are surfaced immediately; the same action can then succeed.
    prepare('ordinary-limit'); await beginListExport();
    await page.getByText('普通限流测试',{exact:true}).waitFor();
    await progress().waitFor({state:'hidden'});
    await page.waitForTimeout(1200);
    check(calls.filter(c=>c.scenario==='ordinary-limit').length===1, 'Ordinary 429 was retried');
    prepare('recovery'); release();
    const thirdDownload = page.waitForEvent('download');
    await beginListExport(); await readDownload(thirdDownload); await progress().waitFor({state:'hidden'});
    check(calls.filter(c=>c.scenario==='recovery').length===1, 'Retry after failure did not issue exactly one request');
    // Isolated response overlays exercise paging and selection without writing fixture data.
    const original = await page.evaluate(async () => {
      const response = await fetch('/api/admin/orders?page=1&pageSize=25');
      if (!response.ok) throw new Error('Fixture orders unavailable');
      return response.json();
    });
    check(original.items.length > 0, 'Fixture must contain an order');
    const first = original.items[0], second = {...first, id:Number(first.id)+100000, orderNo:first.orderNo+'-scope2'}, third = {...first, id:Number(first.id)+100001, orderNo:first.orderNo+'-scope3'};
    listHandler = async route => {
      const pageNo = Number(new URL(route.request().url()).searchParams.get('page') || 1);
      await route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({...original, total:51, items:pageNo===1 ? [first, second] : pageNo===2 ? [third] : []})});
    };
    await page.route(listPattern, listHandler);
    await page.goto(base+'/orders?page=1&pageSize=25');
    await page.waitForFunction(() => document.querySelectorAll('.m-order-card').length===2);
    const exportedIds = name => calls.filter(c=>c.scenario===name).map(c=>new URL(c.url).searchParams.get('orderIds'));
    const runImmediate = async name => {
      prepare(name); release();
      const file = page.waitForEvent('download'); await beginListExport(); await readDownload(file); await progress().waitFor({state:'hidden'});
    };
    await openOrderMenu();
    check(await menu().getByRole('button',{name:'本页 2 笔订单 · 合并导出',exact:true}).isVisible(), 'Default scope is not the current page');
    check(await menu().getByRole('button',{name:'本页 2 笔订单 · 分 Sheet 导出',exact:true}).isVisible(), 'Sheet scope is not the current page');
    await menu().getByRole('button',{name:'取消',exact:true}).click(); await menu().waitFor({state:'hidden'});
    await runImmediate('scope-page1');
    check(exportedIds('scope-page1')[0] === [first.id, second.id].join(','), 'Page-one export IDs differ from visible rows');
    await openOrderMenu(); await menu().getByRole('button',{name:'选择订单',exact:true}).click();
    await page.locator('.m-order-card').first().click();
    await openOrderMenu(); check(await menu().getByRole('button',{name:'已选 1 笔订单 · 合并导出',exact:true}).isVisible(), 'Selected scope label missing');
    await menu().getByRole('button',{name:'取消',exact:true}).click(); await menu().waitFor({state:'hidden'});
    await runImmediate('scope-selected'); check(exportedIds('scope-selected')[0] === String(first.id), 'Selection did not override page IDs');
    await page.getByTestId('mobile-order-selection').getByRole('button',{name:'完成',exact:true}).click();
    await page.locator('.el-pagination .btn-next').click();
    await page.waitForFunction(no => document.querySelectorAll('.m-order-card').length===1 && document.querySelector('.m-order-card')?.textContent.includes(no), third.orderNo);
    await runImmediate('scope-page2'); check(exportedIds('scope-page2')[0] === String(third.id), 'Page change retained stale IDs');
    await page.locator('.el-pagination .btn-next').click();
    await page.waitForFunction(() => document.querySelectorAll('.m-order-card').length===0);
    await openOrderMenu();
    const beforeEmpty = calls.length;
    const emptyMerge = menu().getByRole('button',{name:'本页 0 笔订单 · 合并导出',exact:true});
    const emptySheet = menu().getByRole('button',{name:'本页 0 笔订单 · 分 Sheet 导出',exact:true});
    check(await emptyMerge.isDisabled() && await emptySheet.isDisabled(), 'Empty page export was enabled');
    await emptyMerge.evaluate(button => button.click()); await emptySheet.evaluate(button => button.click());
    await page.waitForTimeout(100); check(calls.length===beforeEmpty, 'Empty page sent an export request');
    await menu().getByRole('button',{name:'取消',exact:true}).click();
    await page.unroute(listPattern,listHandler); listHandler=null;
    await page.goto(base+'/orders?page=1&pageSize=25'); await page.locator('.m-order-card').first().waitFor();
    prepare('result-recovery'); await beginListExport();
    await waitWaiting('正在下载导出文件');
    release(); await progress().waitFor({state:'hidden'});
    const recoveryButton = page.getByTestId('order-export-recovery').getByRole('button',{name:'重新下载上次文件',exact:true});
    await recoveryButton.waitFor();
    const recoveredFile=page.waitForEvent('download'); await recoveryButton.click(); await readDownload(recoveredFile);
    await progress().waitFor({state:'hidden'});
    check(resultDownloads===2,'Manual recovery did not retry only the file download');
    check(calls.filter(c=>c.scenario==='result-recovery').length===1,'Download recovery regenerated the workbook');
    check(errors.length===0, 'Browser errors: '+errors.join('; '));
    return {passed:true, listAndInvoiceMutualExclusion:true, queuePositionAndGeneratingVisible:true, stableDistinctTickets:true, closeContinues:true, completeDownloads:3, ordinary429NoRetry:true, recovery:true, pageScopeAndSelection:true, pageChange:true, emptyPageNoRequest:true,readyDownloadPhase:true,manualRedownloadWithoutGeneration:true,calls};
  } finally {
    release?.();
    await page.unroute(exportPattern, handler);
    await page.unroute(resultPattern,resultHandler);
    if (listHandler) await page.unroute(listPattern, listHandler);
    page.off('pageerror', errorListener);
  }
}
