// All writes are confined to the guarded local *_test storefront sidecar.
async (page) => {
  const base='http://127.0.0.1:5364';
  if(!page.url().startsWith(base+'/')) throw new Error('Isolated security fixture required');
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const login=async(target,email,password)=>{
    await target.goto(base+'/login');
    await target.waitForFunction(()=>document.querySelector('input[placeholder="Email"]')||[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Logout'));
    if(!await target.getByPlaceholder('Email',{exact:true}).count()){
      await target.getByRole('button',{name:'Logout',exact:true}).click();
      await target.waitForURL(u=>u.pathname==='/login');
    }
    await target.getByPlaceholder('Email',{exact:true}).waitFor();
    await target.getByPlaceholder('Email',{exact:true}).fill(email);
    await target.getByPlaceholder('Password',{exact:true}).fill(password);
    await target.getByRole('button',{name:'Login to Continue',exact:true}).click();
    await target.waitForURL(u=>u.pathname==='/shop');
    await target.locator('.style-group').first().waitFor();
  };
  const api=(target,path,method='GET',body)=>target.evaluate(async({path,method,body})=>{
    const csrf=await fetch('/api/auth/csrf').then(r=>r.json());
    const response=await fetch(path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.csrfToken},...(body?{body:JSON.stringify(body)}:{})});
    return {status:response.status,data:await response.json().catch(()=>({}))};
  },{path,method,body});
  await login(page,'buyer@gingtto.test','Fixture-Only');
  const cookies=await page.context().cookies(base);
  const session=cookies.find(c=>c.name==='gingtto-store-session');
  check(session?.httpOnly&&session.sameSite==='Lax','Cookie attributes missing');
  const storage=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage)));
  check(!storage['lumiere-store-token']&&storage['gingtto-store-session-hint'],'Legacy bearer storage survived');
  check(!JSON.stringify(storage).includes(session.value),'Cookie credential leaked into JS storage');
  const created=await api(page,'/api/orders','POST',{
    contact:{value:'buyer@gingtto.test'},delivery:{country:'DE',lastName:'Store security fixture',address:'Fixture Street',city:'Berlin',state:'Berlin',zip:'10000'},
    items:[{productId:2,sizeCode:'M',quantity:1}]
  });
  check(created.status===201,'Customer checkout failed');
  const ownNo=created.data.order.orderNo;
  await page.goto(base+'/orders');
  await page.getByText(ownNo,{exact:true}).first().waitFor();
  await page.goto(base+'/inventory');
  await page.getByRole('button',{name:/Export PDF/i}).waitFor();
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:/Export PDF/i}).click();
  const download=await downloadPromise;
  await download.saveAs('output/playwright/security-inventory.pdf');
  await page.goto(base+'/orders');
  await page.getByText(ownNo,{exact:true}).first().waitFor();
  const second=await page.context().newPage();
  await second.goto(base+'/shop');
  await second.getByText('Logout',{exact:true}).click();
  await second.waitForURL(u=>u.pathname==='/login');
  await login(second,'security-second@fixture.test','Store-Fixture-Password-2026');
  const own=await api(second,'/api/store/orders');
  check(own.status===200&&own.data.items.length===0,'Customer order isolation failed');
  const current=await api(page,'/api/auth/me');
  check(current.data.user.email==='security-second@fixture.test','Shared cookie did not switch identity');
  await page.waitForFunction(no=>!document.body.textContent.includes(no),ownNo);
  await second.setViewportSize({width:390,height:844});
  await second.goto(base+'/inventory');
  await second.getByRole('button',{name:/Export PDF/i}).waitFor();
  await second.screenshot({path:'output/playwright/security-store-mobile.png',fullPage:true});
  await second.close();
  return {cookieHttpOnly:true,legacyTokenRemoved:true,checkout:true,customerOrdersIsolated:true,crossTabCacheCleared:true,inventoryPdf:true,mobile:true};
}
