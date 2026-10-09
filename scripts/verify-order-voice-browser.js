// Run via playwright-cli run-code --filename, against voice-browser-fixture.py only.
async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5358/')) throw new Error('Isolated voice browser fixture required');
  const check = (value, message) => { if (!value) throw new Error(message); };
  const instrument = () => {
    if (window.__voiceInstrumented) return;
    window.__voiceInstrumented = true;
    window.__voicePlays = 0; window.__voiceEnds = 0;
    const original = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      if (this.src.includes('new-order-zh-CN')) {
        window.__voicePlays++;
        if (!this.__observed) {
          this.__observed = true;
          this.addEventListener('ended', () => window.__voiceEnds++);
        }
      }
      return original.call(this);
    };
  };
  const context = page.context();
  await context.addInitScript(instrument);
  await page.evaluate(instrument);
  // Start a fresh enable period for repeatable QA, not another login.
  if (await page.getByRole('button', { name: '关闭语音提醒', exact: true }).count())
    await page.getByRole('button', { name: '关闭语音提醒', exact: true }).click();
  await page.getByRole('button', { name: '开启语音提醒', exact: true }).click();
  await page.getByText('正常监听', { exact: true }).waitFor({ timeout: 15000 });
  const create = async tab => {
    const token = await tab.evaluate(() => localStorage.getItem('lumiere-admin-token'));
    const response = await tab.request.post('http://127.0.0.1:5358/api/admin/orders', {
      headers: { Authorization: `Bearer ${token}` },
      data: { requestId: crypto.randomUUID(), userId: 1, contactName: 'Voice Fixture', phone: '123',
        country: 'DE', address: 'Isolated fixture', items: [{ productId: 2, sizeCode: 'M', quantity: 1, unitPrice: 29.9 }] },
    });
    check(response.ok(), `Fixture create failed: ${response.status()}`);
  };
  const started = Date.now();
  await create(page);
  await page.waitForFunction(() => window.__voicePlays === 2, null, { timeout: 10000 });
  const foregroundLatencyMs = Date.now() - started;
  check(foregroundLatencyMs <= 10000, 'Foreground playback missed the ten-second target');
  await page.waitForFunction(() => window.__voiceEnds === 2, null, { timeout: 15000 });
  const follower = await context.newPage();
  await follower.goto('http://127.0.0.1:5358/orders');
  await follower.getByRole('button', { name: '启用声音／恢复监听', exact: true }).click();
  await follower.getByText('其他标签页负责播报', { exact: true }).waitFor({ timeout: 15000 });
  await create(page);
  await page.waitForFunction(() => window.__voiceEnds === 3, null, { timeout: 20000 });
  check(await follower.evaluate(() => window.__voicePlays === 1), 'Follower repeated an order');
  await page.close();
  await follower.getByText('正常监听', { exact: true }).waitFor({ timeout: 15000 });
  await create(follower);
  await follower.waitForFunction(() => window.__voiceEnds === 2, null, { timeout: 20000 });
  await follower.reload();
  await follower.getByText('待启用声音', { exact: true }).waitFor({ timeout: 10000 });
  await follower.getByRole('button', { name: '启用声音／恢复监听', exact: true }).click();
  await follower.getByText('正常监听', { exact: true }).waitFor({ timeout: 15000 });
  check(await follower.evaluate(() => window.__voicePlays === 1), 'Refresh replayed history');
  await context.setOffline(true);
  await follower.getByText('断线重连', { exact: true }).waitFor({ timeout: 15000 });
  await create(follower); await create(follower);
  await context.setOffline(false);
  await follower.getByText('补播提醒：共 2 笔新订单', { exact: true }).waitFor({ timeout: 40000 });
  check(await follower.evaluate(() => window.__voiceEnds === 2), 'Reconnect did not combine playback');
  await context.route('**/api/auth/me', route => route.abort('connectionfailed'));
  await follower.reload();
  await follower.getByRole('button', { name: '重试连接', exact: true }).waitFor({ timeout: 15000 });
  await context.unroute('**/api/auth/me');
  await follower.getByRole('button', { name: '重试连接', exact: true }).click();
  await follower.getByText('待启用声音', { exact: true }).waitFor({ timeout: 15000 });
  await follower.getByRole('button', { name: '启用声音／恢复监听', exact: true }).click();
  await follower.getByText('正常监听', { exact: true }).waitFor({ timeout: 15000 });
  await follower.getByRole('button', { name: '关闭语音提醒', exact: true }).click();
  await follower.getByText('未开启', { exact: true }).waitFor();
  await follower.getByRole('button', { name: '开启语音提醒', exact: true }).waitFor();
  await follower.screenshot({ path: 'output/playwright/order-voice-verified.png', fullPage: false });
  await follower.getByRole('button', { name: '开启语音提醒', exact: true }).click();
  await follower.getByText('正常监听', { exact: true }).waitFor({ timeout: 15000 });
  let releaseLogout;
  const logoutGate = new Promise(resolve => { releaseLogout = resolve; });
  await context.route('**/api/auth/logout', async route => { await logoutGate; await route.continue(); });
  await follower.locator('.profile-button').click();
  await follower.getByText('退出登录', { exact: true }).click();
  await follower.waitForFunction(() => localStorage.getItem('lumiere-admin-token') === null);
  const episodes = await follower.evaluate(() => new Promise((resolve, reject) => {
    const open = indexedDB.open('gingtto-order-voice', 1);
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const db = open.result, tx = db.transaction('episodes', 'readonly');
      const request = tx.objectStore('episodes').count();
      tx.oncomplete = () => { resolve(request.result); db.close(); };
      tx.onerror = () => reject(tx.error);
    };
  }));
  check(episodes === 0, 'Logout retained a previous login episode');
  releaseLogout(); await follower.waitForURL('**/login'); await context.unroute('**/api/auth/logout');
  await follower.getByRole('textbox', { name: '账号 / 邮箱' }).fill('warehouse@gingtto.test');
  await follower.getByRole('textbox', { name: '密码' }).fill('Workbench-Test-2026');
  await follower.getByRole('button', { name: '登录工作台', exact: true }).click();
  await follower.getByRole('button', { name: '开启语音提醒', exact: true }).waitFor({ timeout: 15000 });
  check(await follower.getByText('未开启', { exact: true }).count() === 1, 'A new account inherited the old episode');
  return { foregroundLatencyMs, multiTabOnce: true, activatedTabTakeover: true,
    refreshNoHistory: true, reconnectCombinedTwoOrders: true, authTransportRetryRetainsEpisode: true, disableClearedEpisode: true,
    logoutClearedEpisodeBeforeResponse: true, newAccountStartsDisabled: true,
    note: 'Browser playback completion verified; physical Bluetooth audibility still requires manual acceptance.' };
}
