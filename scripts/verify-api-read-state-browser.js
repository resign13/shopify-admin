// Read-state UI regression for the existing admin-mobile 5380 *_test fixture.
// Reuse its logged-in admin page. No login, fixture setup, Key action or DB write.
// Account rows come from a real authorized GET; names/total=60 and call-record
// metadata below are client-only route.fulfill responses, not created users/logs.
async (page) => {
  const base='http://127.0.0.1:5380', root='/api/admin/api-integrations';
  if(!page.url().startsWith(base+'/')) throw new Error('Isolated admin-mobile 5380 *_test fixture required');
  const checks=[],errors=[],routeErrors=[],requests=[],expectedCancellations=[],holds=[];
  let stage='read real public account metadata',passed=false,failure,cleanupError;
  const check=(name,value)=>{if(!value)throw new Error(name);checks.push({name,passed:true});};
  const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
  const within=async(p,label)=>{let timer;try{return await Promise.race([p,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Timed out: '+label)),15000);})]);}finally{clearTimeout(timer);}};
  const paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const noError=async()=>await page.locator('.mobile-api > .el-alert').count()===0;
  const onError=e=>errors.push(e.message);
  const onFailed=request=>{
    const url=new URL(request.url());
    if(url.origin===base&&[root+'/accounts',root+'/logs'].includes(url.pathname)) {
      const error=request.failure()?.errorText||'';
      if(/abort|cancel/i.test(error))expectedCancellations.push({path:url.pathname,page:url.searchParams.get('page'),error});
      else routeErrors.push(error||'Unexpected read request failure');
    }
  };
  page.on('pageerror',onError);page.on('requestfailed',onFailed);
  const arm=(match,label,override={})=>{
    const hold={match,label,override,started:deferred(),release:deferred(),done:deferred(),used:false};holds.push(hold);return hold;
  };
  const release=async hold=>{hold.release.resolve();await within(hold.done.promise,hold.label+' released');await paint();};
  const close=async dialog=>{await dialog.getByRole('button',{name:'关闭此对话框',exact:true}).click();await dialog.waitFor({state:'hidden'});};
  const tab=name=>page.getByRole('tab',{name,exact:true});
  const pager=container=>container.locator('.el-pager');
  const goPage=(container,n)=>pager(container).getByText(String(n),{exact:true}).click();
  const list=page.locator('.mapi-account-list');
  const accountPager=page.locator('.mobile-api > .mapi-pagination');
  const keyword=page.locator('.mapi-account-search input');
  const accountTitle=(key,p)=>'API UI '+key+' page '+p;
  const expectAccounts=async(key,p)=>{
    await list.locator('strong').first().filter({hasText:accountTitle(key,p)+' A'}).waitFor();
    await list.locator('.el-loading-mask').waitFor({state:'hidden'});
    check('Account rows and selected page agree: '+key+'/'+p,(await pager(accountPager).locator('.is-active').textContent()).trim()===String(p));
    check('Current account read released loading/error: '+key+'/'+p,!(await page.locator('.mapi-account-search button').getAttribute('class')).includes('is-loading')&&await noError());
  };
  const recordDialog=name=>page.getByRole('dialog',{name:'调用记录 · '+name,exact:true});
  const openAccountLogs=async index=>{
    const card=list.locator('.mapi-account').nth(index),name=await card.locator('strong').textContent();
    await card.click();
    const account=page.getByRole('dialog',{name:name+' · API 授权',exact:true});await account.waitFor();
    await account.getByRole('button',{name:'调用记录',exact:true}).click();
    const logs=recordDialog(name);await logs.waitFor();return {name,account,logs};
  };
  let handler;
  const pattern='**/api/admin/api-integrations/**';
  try {
    const real=await page.evaluate(async path=>{
      const response=await fetch(path,{method:'GET'});
      if(!response.ok)throw new Error('Existing logged-in admin fixture required: '+response.status);
      const data=await response.json();
      const fields=['id','name','email','role','accountStatus','moduleAllowed','status','keyId','keyLabel','version','adminBlocked','expiresAt','lastUsedAt','calls24h'];
      return data.items.slice(0,2).map(row=>Object.fromEntries(fields.filter(key=>key in row).map(key=>[key,row[key]])));
    },root+'/accounts?page=1');
    check('Real authorized GET supplied two distinct public account rows',real.length===2&&real[0].id!==real[1].id);
    handler=async route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.origin!==base||![root+'/accounts',root+'/logs'].includes(url.pathname))return route.continue();
      if(request.method()!=='GET') {routeErrors.push('Unexpected mutation attempted');return route.abort('blockedbyclient');}
      const info={kind:url.pathname.endsWith('/accounts')?'accounts':'logs',page:Number(url.searchParams.get('page')||1),keyword:url.searchParams.get('keyword')||'',userId:url.searchParams.get('userId')};
      requests.push(info);
      const hold=holds.find(item=>!item.used&&item.match(info));
      let body;
      if(info.kind==='accounts')body={items:real.map((row,index)=>({...row,name:accountTitle(info.keyword,info.page)+' '+(index?'B':'A')})),total:60,pageSize:20,page:info.page};
      else body={items:[{time:'2026-10-28T04:00:00Z',route:'/api/external/v1/products?ui='+(!info.userId?'own-current':String(real[0].id)===info.userId?'manager-A-current':'manager-B-current'),status:200,durationMs:12}],total:60,pageSize:20};
      if(hold){hold.used=true;Object.assign(body,hold.override);hold.started.resolve(info);await hold.release.promise;}
      try {await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});}
      catch(error){if(!/abort|cancel/i.test(request.failure()?.errorText||''))routeErrors.push(error.message);}
      finally {if(hold)hold.done.resolve();}
    };
    await page.route(pattern,handler);
    await page.setViewportSize({width:393,height:852});
    await page.goto(base+'/api-integrations');await tab('账号管理').waitFor();await tab('账号管理').click();
    await expectAccounts('',1);

    stage='applied keyword and page2/page3 delayed response';
    const applied='state-applied-A',draft='state-draft-B';
    await keyword.fill(applied);await page.locator('.mapi-account-search').getByRole('button',{name:'查询',exact:true}).click();await expectAccounts(applied,1);
    await keyword.fill(draft);
    const page2=arm(i=>i.kind==='accounts'&&i.page===2,'old accounts page2');
    await goPage(accountPager,2);const request2=await within(page2.started.promise,'accounts page2 requested');
    check('Pagination reads applied keyword, not unsent draft',request2.keyword===applied);
    await goPage(accountPager,3);await expectAccounts(applied,3);
    await release(page2);await expectAccounts(applied,3);
    check('Late page2 cannot overwrite page3 rows, highlight, loading or error',(await list.textContent()).includes(accountTitle(applied,3))&&await noError());
    check('Pagination preserves unsent keyword draft',await keyword.inputValue()===draft);
    const beforeSubmit=requests.length;
    await page.locator('.mapi-account-search').getByRole('button',{name:'查询',exact:true}).click();await expectAccounts(draft,1);
    check('Explicit query applies draft and resets to page1',requests.slice(beforeSubmit).some(i=>i.kind==='accounts'&&i.keyword===draft&&i.page===1));

    stage='manager logs A close then B, B responds first';
    const staleA='/api/external/v1/products?ui=manager-A-stale';
    const logA=arm(i=>i.kind==='logs'&&i.userId===String(real[0].id),'old manager A logs',{items:[{route:staleA,time:'2026-10-28T04:00:00Z',status:200,durationMs:99}]});
    const a=await openAccountLogs(0);await within(logA.started.promise,'manager A requested');
    await close(a.logs);await close(a.account);
    const b=await openAccountLogs(1);
    await b.logs.locator('article strong').filter({hasText:'manager-B-current'}).waitFor();
    await release(logA);
    check('Manager B title stays paired with manager B public records',await b.logs.isVisible()&&(await b.logs.locator('article strong').allTextContents()).every(text=>text.includes('manager-B-current')));
    check('Closed A read cannot change current B loading/error',await b.logs.locator('.mobile-api-call-records').getAttribute('aria-busy')==='false'&&await noError());

    stage='closing pending manager logs and switching tab';
    const closedMarker='/api/external/v1/products?ui=manager-B-closed';
    const closed=arm(i=>i.kind==='logs'&&i.userId===String(real[1].id)&&i.page===2,'closed manager B page2',{items:[{route:closedMarker,time:'2026-10-28T04:00:00Z',status:200,durationMs:99}]});
    await goPage(b.logs,2);await within(closed.started.promise,'manager B page2 requested');
    await close(b.logs);await close(b.account);await tab('接口说明').click();await release(closed);
    check('Closing read then changing tab keeps docs selected and error clear',await tab('接口说明').getAttribute('aria-selected')==='true'&&await noError());
    await tab('账号管理').click();await expectAccounts(draft,1);
    const reopened=await openAccountLogs(1);await reopened.logs.locator('article strong').filter({hasText:'manager-B-current'}).waitFor();
    check('Reopened B logs contain only the new read',!(await reopened.logs.textContent()).includes(closedMarker)&&await reopened.logs.locator('.mobile-api-call-records').getAttribute('aria-busy')==='false');
    await close(reopened.logs);await close(reopened.account);

    stage='account tab invalidates pending page read';
    const tabRead=arm(i=>i.kind==='accounts'&&i.page===2,'tab-invalidated accounts',{items:real.map(row=>({...row,name:'API UI stale-tab'}))});
    await goPage(accountPager,2);await within(tabRead.started.promise,'tab-invalidated accounts requested');
    await tab('接口说明').click();await release(tabRead);
    check('Old account read cannot switch tab or expose an error',await tab('接口说明').getAttribute('aria-selected')==='true'&&await noError());
    await tab('账号管理').click();await expectAccounts(draft,2);
    check('Returning to account tab reloads applied query without stale rows',!(await list.textContent()).includes('stale-tab'));
    check('Only expected GET routes were simulated',requests.every(i=>['accounts','logs'].includes(i.kind))&&routeErrors.length===0);
    check('No uncaught browser error',errors.length===0);
    passed=true;
  } catch(error) {failure=error.message;}
  finally {
    // Release every pending route before removing our own handler. Leave the
    // shared admin session alive and restore real (not simulated) UI data.
    for(const hold of holds)hold.release.resolve();
    try {
      await within(Promise.all(holds.filter(hold=>hold.used).map(hold=>hold.done.promise)),'route cleanup');
      if(handler)await page.unroute(pattern,handler);
      await page.goto(base+'/api-integrations');await page.locator('.mapi-key').waitFor();
    } catch(error){cleanupError=error.message;}
    page.off('pageerror',onError);page.off('requestfailed',onFailed);
  }
  return {passed:passed&&!cleanupError&&!routeErrors.length&&!errors.length,stage,failure,cleanupError,checks,errors,routeErrors,expectedCancellations,requests,
    fixtureOnly:true,readOnly:true,clientOnlyPaginationSimulation:true,createdUsers:0,keyMutations:0};
}
