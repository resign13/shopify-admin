async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5364/login')) throw new Error('Isolated captcha fixture required');
  const assert=(ok,message)=>{if(!ok)throw new Error(message);};
  const account=page.getByRole('textbox',{name:'账号 / 邮箱',exact:true});
  const password=page.getByRole('textbox',{name:'密码',exact:true});
  const answer=page.getByRole('textbox',{name:'图形验证码',exact:true});
  const submit=page.getByRole('button',{name:'登录工作台',exact:true});
  const refresh=page.getByRole('button',{name:'刷新图形验证码',exact:true});
  const image=page.getByRole('img',{name:'图形验证码图片',exact:true});
  await image.waitFor();await account.fill('finance@gingtto.test');await password.fill('Wrong fixture password');
  const bad=async(expected)=>{
    const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/auth/admin/login')&&r.request().method()==='POST'),submit.click()]);
    assert(response.status()===expected,'Login status');
    await answer.waitFor();await page.waitForFunction(()=>!document.querySelector('button[type="submit"]').disabled);
    assert(await answer.inputValue()==='','Answer cleared after failure');
  };
  await answer.fill('XXXXX');await bad(400);
  assert(await account.inputValue()==='finance@gingtto.test','Account retained');
  assert(await password.inputValue()==='Wrong fixture password','Password retained');
  await answer.fill('ab7cd');await bad(401);
  const old=await image.getAttribute('src');
  await refresh.click();await page.waitForFunction(()=>!document.querySelector('button[type="submit"]').disabled);
  assert(await image.getAttribute('src')!==old,'Refresh creates a new drawing');
  await page.route('**/api/auth/admin/captcha',route=>route.abort());
  await refresh.click();await page.getByRole('button',{name:'重试加载验证码',exact:true}).waitFor();
  assert(await submit.isDisabled(),'Captcha network failure blocks login');
  await page.unroute('**/api/auth/admin/captcha');
  await page.getByRole('button',{name:'重试加载验证码',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('button[type="submit"]').disabled);
  await password.fill('Workbench-Test-2026');
  await page.setViewportSize({width:1920,height:1080});
  await answer.click();await page.screenshot({path:'output/playwright/admin-login-captcha-desktop.png'});
  await page.setViewportSize({width:375,height:812});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile login must not scroll horizontally');
  await answer.click();await page.screenshot({path:'output/playwright/admin-login-captcha-mobile.png'});
  await answer.fill('ab7cd');await submit.click();
  await page.waitForURL(url=>url.pathname==='/finance');
  await page.getByRole('navigation',{name:'快捷导航'}).getByRole('button',{name:'全部',exact:true}).click();
  const modules=page.getByRole('dialog',{name:'全部模块',exact:true});
  await modules.waitFor();
  assert(await modules.getByRole('link',{name:'合同管理',exact:true}).count()===1,'Finance contracts navigation');
  assert(await modules.getByRole('link',{name:'订单管理',exact:true}).count()===0,'No implicit order grant');
  await modules.getByRole('button',{name:/关闭|close/i}).click();
  await modules.waitFor({state:'hidden'});
  await page.locator('.profile-button').click();
  const [logout]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith('/api/auth/logout')&&r.request().method()==='POST'),
    page.getByRole('menuitem',{name:'退出登录',exact:true}).click(),
  ]);
  assert(logout.status()===200,'Logout must revoke the server session');
  await page.waitForURL(url=>url.pathname==='/login');
  await image.waitFor();
  assert(await page.getByRole('alert').count()===0,'Fresh login has no stale connection error');
  return {wrongAnswerRejected:true,wrongPasswordRejected:true,refreshWorks:true,networkFailureBlocksLogin:true,inputRetained:true,retryWorks:true,caseInsensitiveSuccess:true,desktopAndMobileChecked:true,financeDefaultContracts:true,logoutRevokesSession:true};
}
