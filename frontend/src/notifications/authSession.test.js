import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Exercise actual store actions with lightweight injected Pinia/HTTP adapters.
const source = readFileSync(new URL('../stores/auth.js',import.meta.url),'utf8')
  .replace(/^import .*;\r?\n/gm,'').replace('export const useAdminAuthStore','const useAdminAuthStore');
function auth(request) {
  const values = new Map([['gingtto-admin-session-hint','public-fixture-id']]);
  const localStorage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  const defineStore=(_,definition)=>()=>{
    const state=definition.state();
    for(const [name,action] of Object.entries(definition.actions)) state[name]=action.bind(state);
    return state;
  };
  return {store:new Function('defineStore','roleModules','request','localStorage','setAuthSession','withAuthTransition',source+'\nreturn useAdminAuthStore();')
    (defineStore,()=>[],request,localStorage,()=>{},(_,fn)=>fn()), values};
}
test('transport failure retains login identity but does not authorize protected views',async()=>{
  const {store,values}=auth(async()=>{throw new Error('network');});
  await store.initialize();assert.equal(store.sessionId,'public-fixture-id');assert.equal(store.user,null);
  assert.equal(values.get('gingtto-admin-session-hint'),'public-fixture-id');assert.match(store.error,/重试/);
});
test('401 and 403 invalidate retained login identity',async()=>{
  for(const status of [401,403]) {
    const {store,values}=auth(async()=>{throw Object.assign(new Error('invalid'),{status});});
    await store.initialize();assert.equal(store.sessionId,'');assert.equal(values.get('gingtto-admin-session-hint'),'');
  }
});
test('successful retry revalidates current permissions and clears transport error',async()=>{
  let failed=true;const {store}=auth(async()=>{if(failed)throw new Error('offline');return {role:'admin',user:{id:1,permissions:['orders']},sessionId:'public-fixture-id',csrfToken:'csrf'};});
  await store.initialize();failed=false;await store.initialize();assert.deepEqual(store.user.permissions,['orders']);assert.equal(store.error,'');
});

test('logout clears the local identity immediately, before its network response',async()=>{
  let complete, sentToken;
  const {store,values}=auth(async(path,options)=>{sentToken=options.headers['X-Auth-Session'];await new Promise(resolve=>{complete=resolve;});});
  store.user={id:1};const pending=store.logout();
  assert.equal(store.sessionId,'');assert.equal(store.user,null);assert.equal(values.get('gingtto-admin-session-hint'),'');
  assert.equal(sentToken,'public-fixture-id');complete();await pending;
});

test('a late identity response cannot replace the account of a new login',async()=>{
  let complete;const {store}=auth(()=>new Promise(resolve=>{complete=resolve;}));
  const pending=store.initialize();store.revision++;store.sessionId='new-public-id';store.user={id:2};
  complete({role:'admin',user:{id:1}});await pending;assert.equal(store.user.id,2);assert.equal(store.sessionId,'new-public-id');
});
