async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5366/')) throw new Error('Isolated API browser fixture required');
  const check=(value,label)=>{if(!value)throw new Error(label);};
  const errors=[];
  page.on('pageerror',e=>errors.push(e.name));
  const idle=()=>page.waitForFunction(()=>![...document.querySelectorAll('.el-loading-mask')].some(n=>n.getClientRects().length));
  const root='/api/admin/api-integrations';
  const call=async(token,path='/api/external/v1/products')=>{
    for(let attempt=0;attempt<3;attempt++){
      const response=await page.request.get('http://127.0.0.1:5367'+path,{headers:{Authorization:'Bearer '+token}});
      if(response.status()!==429 || attempt===2)return response;
      const seconds=Number(response.headers()['retry-after']);
      check(Number.isFinite(seconds)&&seconds>0&&seconds<=2,'Bounded read-only rate retry');
      await page.waitForTimeout(seconds*1000+50);
    }
  };
  await page.goto('http://127.0.0.1:5366/api-integrations');await idle();
  await page.getByRole('heading',{name:'我的 Key',exact:true}).waitFor();
  let state=await (await page.request.get('http://127.0.0.1:5366'+root+'/me')).json();
  if(state.item.keyId) {
    // Repeatable runs revoke only their isolated fixture account's existing key.
    const csrf=await (await page.request.get('http://127.0.0.1:5366/api/auth/csrf')).json();
    const auth=await (await page.request.get('http://127.0.0.1:5366/api/auth/me')).json();
    await page.request.post('http://127.0.0.1:5366'+root+'/accounts/'+auth.user.id+'/revoke',{
      data:{version:state.item.version},headers:{Origin:'http://127.0.0.1:5366','X-CSRF-Token':csrf.csrfToken}});
    await page.getByRole('button',{name:'刷新',exact:true}).click();await idle();
  }
  await page.getByRole('button',{name:'生成 Key',exact:true}).click();
  let dialog=page.getByRole('dialog',{name:'生成 Key',exact:true});
  await dialog.getByRole('button',{name:'确认生成',exact:true}).click();
  let secretDialog=page.getByRole('dialog',{name:'请立即保存完整 Key',exact:true});
  await secretDialog.waitFor();
  const first=await secretDialog.getByRole('textbox',{name:'完整 API Key'}).inputValue();
  check(/^gapi_[A-Za-z0-9_-]{43}$/.test(first),'Generated key format');
  await secretDialog.getByRole('button',{name:'已保存，关闭'}).click();await secretDialog.waitFor({state:'hidden'});
  check(!(await page.content()).includes(first),'Key cleared from DOM');
  let response=await call(first);check(response.status()===200,'Actual storefront key authentication');
  const body=await response.json();check(body.items.length===50&&body.nextCursor,'Default 50 with cursor');
  check(body.items[0].sizes[0].stock===0,'Negative internal stock clamped to zero');
  check(!JSON.stringify(body).includes('price'),'No price fields');
  const next=await call(first,'/api/external/v1/products?cursor='+body.nextCursor);
  check((await next.json()).items.length===7,'Full cursor traversal');
  check((await call(first,'/api/external/v1/inventory?productIds=1,999999')).status()===200,'Batch inventory');
  const refreshed=page.waitForResponse(r=>r.url().endsWith(root+'/me') && r.request().method()==='GET');
  await page.getByRole('button',{name:'刷新',exact:true}).click();await refreshed;await idle();
  await page.waitForFunction(()=>[...document.querySelectorAll('.key-facts strong')][3]?.textContent!=='—');
  await page.getByRole('cell',{name:'/api/external/v1/inventory',exact:true}).first().waitFor();
  await page.screenshot({path:'output/playwright/api-integrations-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'停用',exact:true}).click();
  await page.getByRole('button',{name:/^(确定|OK)$/}).click();await idle();
  await page.getByRole('button',{name:'启用',exact:true}).waitFor();
  check((await call(first)).status()===401,'Pause invalidates key');
  await page.getByRole('button',{name:'启用',exact:true}).click();await page.getByRole('button',{name:/^(确定|OK)$/}).click();await idle();
  await page.getByRole('button',{name:'停用',exact:true}).waitFor();
  check((await call(first)).status()===200,'Resume works');
  await page.getByRole('button',{name:'重置 Key',exact:true}).click();
  dialog=page.getByRole('dialog',{name:'重置 Key',exact:true});
  await dialog.getByRole('button',{name:'确认重置'}).click();await secretDialog.waitFor();
  const second=await secretDialog.getByRole('textbox',{name:'完整 API Key'}).inputValue();
  await secretDialog.getByRole('button',{name:'已保存，关闭'}).click();await secretDialog.waitFor({state:'hidden'});
  check((await call(first)).status()===401 && (await call(second)).status()===200,'Reset retires old key');
  const persisted=await page.evaluate(()=>JSON.stringify({...localStorage})+JSON.stringify({...sessionStorage}));
  check(!persisted.includes(first)&&!persisted.includes(second),'No credential persisted in browser storage');
  // Server commits, but the response is lost. No automatic second generation.
  let resetCount=0;
  await page.route('**/api/admin/api-integrations/me/reset',async route=>{
    resetCount++;await route.fetch();await route.abort('connectionreset');
  });
  await page.getByRole('button',{name:'重置 Key',exact:true}).click();
  await page.getByRole('dialog',{name:'重置 Key',exact:true}).getByRole('button',{name:'确认重置'}).click();
  await page.getByRole('alert').filter({hasText:'未取得完整 Key'}).waitFor();
  check(resetCount===1,'Ambiguous generation not retried');
  check(await secretDialog.isHidden(),'No stale plaintext after response loss');
  await page.unroute('**/api/admin/api-integrations/me/reset');
  await page.getByRole('button',{name:'刷新',exact:true}).click();await idle();
  await page.getByRole('tab',{name:'接口说明'}).click();
  await page.getByRole('heading',{name:'连接地址'}).waitFor();
  check((await page.locator('pre').first().innerText()).includes('Bearer TOKEN'),'Docs use placeholder');
  const common=page.getByRole('region',{name:'公共请求头',exact:true});
  check((await common.getByRole('row').filter({hasText:'Authorization'}).innerText()).includes('必填'),'Authorization is a required header');
  check((await common.getByRole('row').filter({hasText:'Accept'}).innerText()).includes('可选'),'Accept is optional');
  const overview=page.getByRole('region',{name:'接口一览',exact:true});
  check((await overview.innerText()).includes('无查询参数必填'),'List requires no query parameters');
  const productParams=page.getByRole('region',{name:'/products 请求参数',exact:true});
  check(await productParams.getByRole('row').count()===7,'All six optional list parameters documented');
  check(await productParams.getByRole('cell',{name:'可选',exact:true}).count()===6,'List filters all marked optional');
  check((await page.getByRole('region',{name:'/products/{productId} 请求参数',exact:true}).innerText()).includes('路径参数'),'Product ID is a path parameter');
  const inventoryParams=page.getByRole('region',{name:'/inventory 请求参数',exact:true});
  check((await inventoryParams.innerText()).includes('必填') && (await inventoryParams.innerText()).includes('productIds'),'Inventory requires productIds');
  check(await page.locator('.endpoint-docs pre').count()===4,'Minimal, filtered, product and inventory curl examples');
  check((await page.locator('pre').last().innerText()).includes('range(0, len(ids), 100)'),'Python queries all inventory batches');
  await page.screenshot({path:'output/playwright/api-integrations-docs.png',fullPage:true});
  await page.getByRole('tab',{name:'账号管理',exact:true}).click();await idle();
  await page.getByRole('cell',{name:'api_••••_',exact:false}).first().waitFor();
  const self=page.getByRole('row').filter({hasText:'admin@gingtto.test'});
  await self.getByRole('button',{name:'禁用授权'}).click();await page.getByRole('button',{name:/^(确定|OK)$/}).click();await idle();
  await self.getByRole('button',{name:'恢复授权'}).waitFor();
  await page.getByRole('tab',{name:'我的 Key',exact:true}).click();await idle();
  await page.waitForFunction(()=>document.querySelector('.key-heading .el-tag')?.textContent.includes('管理员禁用'));
  check(await page.getByRole('button',{name:'重置 Key',exact:true}).isDisabled(),'Persistent admin block prevents own reset');
  await page.getByRole('tab',{name:'账号管理',exact:true}).click();await idle();
  await self.getByRole('button',{name:'恢复授权'}).click();await page.getByRole('button',{name:/^(确定|OK)$/}).click();await idle();
  await self.getByRole('button',{name:'禁用授权'}).waitFor();
  await page.getByRole('tab',{name:'我的 Key',exact:true}).click();await idle();
  await page.waitForFunction(()=>[...document.querySelectorAll('.key-actions button')].find(b=>b.textContent.includes('重置 Key'))?.disabled===false);
  await page.getByRole('tab',{name:'账号管理',exact:true}).click();await idle();
  await page.screenshot({path:'output/playwright/api-integrations-accounts.png',fullPage:true});
  await page.getByRole('tab',{name:'我的 Key',exact:true}).click();await idle();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'output/playwright/api-integrations-mobile.png',fullPage:true});
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile has no page overflow');
  await page.getByRole('tab',{name:'接口说明',exact:true}).click();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Docs table scrolls internally');
  await productParams.focus();
  check(await productParams.evaluate(el=>el.scrollWidth>el.clientWidth && document.activeElement===el),'Mobile parameter table is keyboard-scrollable');
  await page.screenshot({path:'output/playwright/api-integrations-docs-mobile.png',fullPage:true});
  await page.setViewportSize({width:1280,height:900});
  // New browser context proves an API-only department can use its own key,
  // without receiving account management or unrelated modules.
  const context=await page.context().browser().newContext({viewport:{width:1100,height:850}});
  const other=await context.newPage();await other.goto('http://127.0.0.1:5366/login');
  await other.getByRole('textbox',{name:'账号 / 邮箱'}).fill('api-only@gingtto.test');
  await other.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await other.getByRole('button',{name:'登录工作台'}).click();
  await other.getByRole('heading',{name:'我的 Key',exact:true}).waitFor();
  check(await other.getByRole('tab',{name:'账号管理',exact:true}).count()===0,'No management tab without account permission');
  check((await other.request.get('http://127.0.0.1:5366'+root+'/accounts')).status()===403,'Account management denied server-side');
  check((await other.request.get('http://127.0.0.1:5366/api/admin/orders')).status()===403,'No unrelated order grants');
  await context.close();
  check(errors.length===0,'No browser runtime errors');
  return {keyGeneratedOnce:true,noPlaintextPersistence:true,pauseResumeReset:true,
    committedResponseLossNotRetried:true,actualStorefrontReadOnlyAPI:true,cursorAndInventory:true,
    adminBlockAndRestore:true,apiOnlyRoleIsolation:true,desktopAndMobile:true,
    requiredOptionalParameterDocs:true,requestExamplesAndInventoryBatches:true,runtimeErrors:0};
}
