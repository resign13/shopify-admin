// Private fixture only. All API responses are mocked; no account or inventory is changed.
async page => {
  const base=new URL(page.url()).origin;
  if(!['http://127.0.0.1:5360','http://127.0.0.1:5398','http://127.0.0.1:5410','http://127.0.0.1:5411'].includes(base))throw Error('Isolated maintenance fixture required');
  const check=(value,message)=>{if(!value)throw Error(message);};
  const context=await page.context().browser().newContext({viewport:{width:360,height:800}});
  const probe=await context.newPage();let healthy=false,writes=0,documents=0;const unexpected=[];
  probe.on('request',request=>{if(request.isNavigationRequest()&&request.frame()===probe.mainFrame())documents++;});
  try {
    await probe.route('**/api/**',async route=>{
      const request=route.request(),path=new URL(request.url()).pathname;
      const reply=(status,body,headers={})=>route.fulfill({status,contentType:'application/json',headers,body:JSON.stringify(body)});
      if(path==='/api/auth/me')return reply(401,{message:'Sign in required'});
      if(path==='/api/auth/csrf')return reply(200,{csrfToken:'isolated-maintenance-csrf'});
      if(path==='/api/auth/admin/captcha')return reply(200,{enabled:false});
      if(path==='/api/health')return healthy?reply(200,{status:'ok'}):reply(503,{code:'maintenance'},{'X-Gingtto-Maintenance':'1'});
      if(path.endsWith('/login')){writes++;return reply(503,{code:'maintenance',message:'Maintenance in progress'},{'X-Gingtto-Maintenance':'1'});}
      unexpected.push(path);return reply(404,{message:'Fixture has no business routes'});
    });
    await probe.goto(base+'/login');
    await probe.locator('input[type="password"]').waitFor();
    const admin=await probe.getByRole('button',{name:'登录工作台',exact:true}).count()>0;
    const account=admin?probe.locator('input[autocomplete="username"]'):probe.getByPlaceholder('Email',{exact:true});
    const password=admin?probe.locator('input[autocomplete="current-password"]'):probe.getByPlaceholder('Password',{exact:true});
    await account.fill('maintenance@fixture.test');await password.fill('unsaved-fixture-value');
    await probe.getByRole('button',{name:admin?'登录工作台':'Login to Continue',exact:true}).click();
    const dialog=probe.getByRole('alertdialog');await dialog.waitFor();
    check(await account.inputValue()==='maintenance@fixture.test'&&await password.inputValue()==='unsaved-fixture-value','Input was discarded');
    check(await probe.locator('.maintenance-content[inert]').count()===1,'Underlying form is not inert');
    const box=await dialog.boundingBox();check(box.x>=0&&box.x+box.width<=360&&box.y>=0,'Notice overflows the viewport');
    await probe.screenshot({path:`output/playwright/maintenance-${admin?'admin':'store'}-notice.png`});
    const retry=dialog.getByRole('button',{name:admin?'检查恢复情况':'Check availability',exact:true});
    const unavailable=probe.waitForResponse(r=>new URL(r.url()).pathname==='/api/health');
    await retry.click();check((await unavailable).status()===503,'Maintenance health response was not exercised');
    healthy=true;await retry.click();
    await dialog.getByRole('heading',{name:admin?'系统已恢复':'Service restored',exact:true}).waitFor();
    check(writes===1&&documents===1,'An operation was replayed or the document was reloaded');
    await dialog.getByRole('button',{name:admin?'继续操作':'Continue',exact:true}).click();await dialog.waitFor({state:'hidden'});
    check(await account.inputValue()==='maintenance@fixture.test'&&await password.inputValue()==='unsaved-fixture-value','Recovery discarded input');
    check(await probe.locator('.maintenance-content[inert]').count()===0,'Form stayed blocked after recovery');
    check(writes===1&&documents===1&&unexpected.length===0,'Unexpected business traffic');
    return {passed:true,inputPreserved:true,noAutomaticRetry:true,noReload:true,explicitRecovery:true,fixtureOnly:true};
  } finally {await context.close();}
}
