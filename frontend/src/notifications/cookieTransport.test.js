import test from 'node:test';
import assert from 'node:assert/strict';
import {setAuthSession, csrfHeaders, authenticatedFetch} from '../authTransport.js';

test('writes carry same-origin cookies, public identity guard and CSRF; no bearer', async()=>{
  const original=global.fetch;let sent;
  try {
    setAuthSession('public-session','csrf-token');
    global.fetch=async(path,opts)=>{sent=opts;return new Response('{}');};
    await authenticatedFetch('/api/admin/orders',{method:'POST',headers:{Authorization:'Bearer obsolete'},body:'{}'});
    assert.equal(sent.credentials,'same-origin');assert.equal(sent.headers.has('Authorization'),false);
    assert.equal(sent.headers.get('X-Auth-Session'),'public-session');assert.equal(sent.headers.get('X-CSRF-Token'),'csrf-token');
  } finally {global.fetch=original;setAuthSession();}
});
test('late CSRF token from another identity is rejected',async()=>{
  const original=global.fetch;let complete;
  try {
    setAuthSession('old');global.fetch=()=>new Promise(resolve=>{complete=resolve;});
    const pending=csrfHeaders();setAuthSession('new','new-csrf');complete(new Response(JSON.stringify({csrfToken:'old-csrf'})));
    await assert.rejects(pending,e=>e.code==='session_changed');assert.equal((await csrfHeaders())['X-CSRF-Token'],'new-csrf');
  } finally {global.fetch=original;setAuthSession();}
});
test('business response from previous identity is discarded',async()=>{
  const original=global.fetch;let complete;
  try {
    setAuthSession('old','csrf');global.fetch=()=>new Promise(resolve=>{complete=resolve;});
    const pending=authenticatedFetch('/api/admin/orders');setAuthSession('new','csrf-new');complete(new Response('{}'));
    await assert.rejects(pending,e=>e.code==='session_changed');
  } finally {global.fetch=original;setAuthSession();}
});
