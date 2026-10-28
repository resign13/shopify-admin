import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createApiReadTask, createApiAccountQuery } from './apiIntegrationReads.js';

function harness() {
  const calls=[],events=[],state={alive:true,loading:false,data:null,error:''};
  const request=(path,{signal})=>new Promise((resolve,reject)=>calls.push({path,signal,resolve,reject}));
  const task=createApiReadTask(request,{
    active:()=>state.alive,
    loading:value=>{state.loading=value;if(value)state.error='';events.push(['loading',value]);},
    receive:data=>{state.data=data;events.push(['data',data]);},
    fail:error=>{state.error=error.message;events.push(['error',error.message]);},
  });
  return {task,calls,events,state};
}

test('new pagination aborts old transport; ignored abort cannot commit or clear newer loading',async()=>{
  const h=harness(),page2=h.task.run('/accounts?page=2'),page3=h.task.run('/accounts?page=3');
  assert.equal(h.calls[0].signal.aborted,true);assert.equal(h.calls[1].signal.aborted,false);
  h.calls[0].resolve({page:2});await page2;
  assert.equal(h.state.data,null);assert.equal(h.state.loading,true);assert.equal(h.state.error,'');
  h.calls[1].resolve({page:3});await page3;
  assert.deepEqual(h.state.data,{page:3});assert.equal(h.state.loading,false);
});

test('late success and its finally cannot overwrite an already committed newer page',async()=>{
  const h=harness(),old=h.task.run('/accounts?page=2'),latest=h.task.run('/accounts?page=3');
  h.calls[1].resolve({page:3});await latest;const count=h.events.length;
  h.calls[0].resolve({page:2});await old;
  assert.deepEqual(h.state.data,{page:3});assert.equal(h.events.length,count);
});

test('old rejection/finally cannot replace a newer request error or loading state',async()=>{
  const h=harness(),old=h.task.run('/logs?page=2'),latest=h.task.run('/logs?page=3');
  h.calls[0].reject(new Error('old page failure'));await old;
  assert.equal(h.state.loading,true);assert.equal(h.state.error,'');
  h.calls[1].reject(new Error('current page failure'));await latest;
  assert.equal(h.state.loading,false);assert.equal(h.state.error,'current page failure');
  const retry=h.task.run('/logs?page=3');assert.equal(h.state.error,'');
  h.calls[2].resolve({page:3});await retry;assert.deepEqual(h.state.data,{page:3});
});

test('late old rejection does not replace a newer successful result',async()=>{
  const h=harness(),old=h.task.run('/logs?page=2'),latest=h.task.run('/logs?page=3');
  h.calls[1].resolve({page:3});await latest;const count=h.events.length;
  h.calls[0].reject(new Error('old page failure'));await old;
  assert.equal(h.state.error,'');assert.equal(h.events.length,count);assert.deepEqual(h.state.data,{page:3});
});

test('manager A logs cannot enter B context even if A ignores cancellation',async()=>{
  const h=harness();let account='A';const a=h.task.run('/logs?userId=A');
  account='B';const b=h.task.run('/logs?userId=B');h.calls[1].resolve({account:'B'});await b;
  h.calls[0].resolve({account:'A'});await a;
  assert.equal(account,'B');assert.equal(h.state.data.account,account);
});

test('close/tab cancellation fences old results; reopening starts an independent current read',async()=>{
  const h=harness(),closed=h.task.run('/logs?userId=A');h.task.cancel();
  assert.equal(h.calls[0].signal.aborted,true);assert.equal(h.state.loading,false);
  const reopened=h.task.run('/logs?userId=B');h.calls[0].reject(new Error('closed A failure'));await closed;
  assert.equal(h.state.error,'');assert.equal(h.state.loading,true);
  h.calls[1].resolve({account:'B'});await reopened;assert.deepEqual(h.state.data,{account:'B'});
});

test('unmount/identity invalidation prevents data, error and finally callbacks',async()=>{
  for(const reject of [false,true]){
    const h=harness(),pending=h.task.run('/logs?page=2');h.state.alive=false;h.task.cancel();const count=h.events.length;
    if(reject)h.calls[0].reject(new Error('after unmount'));else h.calls[0].resolve({page:2});
    await pending;await h.task.run('/logs?page=3');
    assert.equal(h.calls[0].signal.aborted,true);assert.equal(h.calls.length,1);assert.equal(h.events.length,count);assert.equal(h.state.data,null);assert.equal(h.state.error,'');
  }
});

test('current AbortError is silent and releases current loading',async()=>{
  const h=harness(),pending=h.task.run('/accounts?page=1');h.calls[0].reject(Object.assign(new Error('cancelled'),{name:'AbortError'}));await pending;
  assert.equal(h.state.error,'');assert.equal(h.state.loading,false);
});

test('independent resource lifetimes do not cancel or settle each other',async()=>{
  const accounts=harness(),ownLogs=harness();const a=accounts.task.run('/accounts?page=2'),l=ownLogs.task.run('/logs?page=2');
  accounts.task.cancel();assert.equal(ownLogs.calls[0].signal.aborted,false);
  accounts.calls[0].resolve({page:2});await a;assert.equal(ownLogs.state.loading,true);
  ownLogs.calls[0].resolve({page:2});await l;assert.deepEqual(ownLogs.state.data,{page:2});
});

test('pagination, returning to accounts and metadata reload retain applied keyword, not its draft',()=>{
  const query=createApiAccountQuery();query.keyword='submitted A';query.page=4;query.submit();
  assert.equal(query.page,1);query.page=2;query.keyword='unsubmitted B';
  const params=new URLSearchParams(query.params());assert.equal(params.get('keyword'),'submitted A');assert.equal(params.get('page'),'2');
  assert.equal(query.params(),params.toString());assert.equal(query.keyword,'unsubmitted B');
  query.submit();assert.equal(query.page,1);assert.equal(new URLSearchParams(query.params()).get('keyword'),'unsubmitted B');
});

test('clearing the draft does not change applied criteria until explicit submit',()=>{
  const query=createApiAccountQuery();query.keyword='A';query.submit();query.page=3;query.keyword='';
  assert.equal(new URLSearchParams(query.params()).get('keyword'),'A');assert.equal(query.page,3);
  query.submit();assert.equal(query.page,1);assert.equal(new URLSearchParams(query.params()).get('keyword'),'');
});
