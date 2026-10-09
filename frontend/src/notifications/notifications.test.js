import test from 'node:test';
import assert from 'node:assert/strict';
import { IDBFactory } from 'fake-indexeddb';
import { acceptPoll, createNotificationStorage, mergeEvents, newEpisode } from './storage.js';
import { OrderVoiceController, sessionKey } from './controller.js';
import { createVoiceAudio } from './audio.js';

const event = id => ({ eventId:id,orderId:id,orderNo:`LM-${id}`,createdAt:new Date().toISOString() });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const waitFor = async check => { for(let n=0;n<100;n++) { if(await check()) return; await sleep(10); } throw new Error('Timed out'); };
const channel = () => ({ postMessage(){}, close(){} });
const locks = { request: async (name, options, fn) => { if (!options.signal.aborted) return fn(); } };

test('session identifier never contains the bearer and changes with login', async () => {
  const a=await sessionKey(1,'fixture-token'),b=await sessionKey(1,'new-fixture-token');
  assert.notEqual(a,b); assert.ok(!a.includes('fixture-token'));
});

test('IndexedDB updates are atomic, reject async reducers and preserve old state', async () => {
  const store=createNotificationStorage(new IDBFactory());
  await store.update('a',()=>newEpisode('a','r'));
  await Promise.all(Array.from({length:12},()=>store.update('a',s=>({...s,lastPoll:s.lastPoll+1}))));
  assert.equal((await store.read('a')).lastPoll,12);
  await assert.rejects(store.update('a',()=>Promise.resolve({})),/同步/);
  assert.equal((await store.read('a')).lastPoll,12);
});

test('a transient database open failure can recover without losing the stored episode', async () => {
  const factory=new IDBFactory();let attempts=0;
  const store=createNotificationStorage({open(...args){
    if (++attempts===1) { const failed={error:new Error('temporary open failure')};queueMicrotask(()=>failed.onerror());return failed; }
    return factory.open(...args);
  }});
  await assert.rejects(store.read('a'),error=>error.code==='notification_storage');
  await store.update('a',()=>newEpisode('a','same-request'));assert.equal((await store.read('a')).requestId,'same-request');
  assert.equal(attempts,2);
});

test('poll cursor and queue persist together; all processed states deduplicate', async () => {
  const store=createNotificationStorage(new IDBFactory()); let s=newEpisode('a','r');
  s.queue=[event(1)]; s.uncertain=[event(2)]; s.processed=[{eventId:3,at:Date.now()}];
  assert.deepEqual(mergeEvents(s,[event(1),event(2),event(3),event(4)]).map(e=>e.eventId),[1,4]);
  await store.update('a',()=>s);
  await store.update('a',s=>acceptPoll(s,{cursor:'next',events:[event(4)],recovery:false}));
  s=await store.read('a'); assert.equal(s.cursor,'next'); assert.equal(s.queue.length,2);
});

test('recovery collects pages, excludes expired events and only forms one batch at its fixed end', () => {
  let s=newEpisode('a','r'); const cutoff=Date.now()/1000-600;
  s.queue=[{...event(1),createdAt:new Date((cutoff-1)*1000).toISOString()}];
  s=acceptPoll(s,{cursor:'c1',events:[event(2)],recovery:true,recoveryComplete:false,cutoffAt:cutoff});
  assert.equal(s.batch.length,0); assert.equal(s.recovery,true);
  s=acceptPoll(s,{cursor:'c2',events:[event(3)],recovery:true,recoveryComplete:true,cutoffAt:cutoff});
  assert.deepEqual(s.batch.map(e=>e.eventId),[2,3]); assert.equal(s.queue.length,0); assert.equal(s.recovery,false);
});

function controller(extra={}) {
  const store=createNotificationStorage(new IDBFactory()); const calls=[];
  const player={async play(){calls.push('audio');},stop(){}};
  const c=new OrderVoiceController({key:'test',storage:store,player,locks,channel:channel(),
    api:async operation=>{ calls.push(operation); return {enabled:true,cursor:'baseline',events:[],serverTime:new Date().toISOString(),hasMore:false}; },...extra});
  return {c,store,calls,player};
}

test('button starts audio synchronously before start API; disable clears the episode', async () => {
  const {c,store,calls}=controller(); const promise=c.enable(); assert.deepEqual(calls,['audio']);
  await promise; await waitFor(()=>calls.includes('start'));
  await c.disable(); assert.equal(await store.read('test'),null); await c.dispose();
});

test('refresh resumes existing cursor without a new start and converts in-flight items to uncertain', async () => {
  const {c,store,calls}=controller(); let s=newEpisode('test','r'); s.cursor='existing';s.inFlight=[event(1)];
  await store.update('test',()=>s); await c.refresh(); assert.equal(c.ui.status,'needs-sound');
  await c.enable(); await waitFor(()=>calls.includes('poll'));
  assert.ok(!calls.includes('start')); assert.equal((await store.read('test')).uncertain.length,1); await c.dispose();
});

test('normal playback validates, persists playing then records completion exactly once', async () => {
  const {c,store,calls}=controller({api:async op=>{calls.push(op);return {enabled:true,events:[event(1)]};}});
  let s=newEpisode('test','r');s.cursor='c';s.recovery=false;s.queue=[event(1)];await store.update('test',()=>s);
  await c.playItems(s,s.queue,false,0);
  const done=await store.read('test');assert.deepEqual(calls,['validate','audio']);assert.equal(done.processed.length,1);assert.equal(done.inFlight.length,0);
  await c.dispose();
});

test('cancelled or no-longer-visible orders are removed without playback', async () => {
  const {c,store,calls}=controller();let s=newEpisode('test','r');s.cursor='c';s.recovery=false;s.queue=[event(1)];await store.update('test',()=>s);
  await c.playItems(s,s.queue,false,0); assert.ok(!calls.includes('audio'));assert.equal((await store.read('test')).queue.length,0);await c.dispose();
});

test('audio failure preserves uncertain items and pauses rather than retrying them automatically', async () => {
  const {c,store}=controller({player:{async play(){throw new Error('audio failed');},stop(){}},api:async()=>({enabled:true,events:[event(1)]})});
  let s=newEpisode('test','r');s.cursor='c';s.recovery=false;s.queue=[event(1)];await store.update('test',()=>s);
  await assert.rejects(c.playItems(s,s.queue,false,0),/audio failed/);
  assert.equal((await store.read('test')).uncertain.length,1); await c.dispose();
});

test('late response after stopping cannot advance persisted cursor', async () => {
  let resolve; const {c,store}=controller({api:()=>new Promise(r=>{resolve=r;})});
  let s=newEpisode('test','r');s.cursor='original';s.recovery=false;await store.update('test',()=>s);
  const pending=c.poll(0);await waitFor(()=>!!resolve);await c.disable();resolve({enabled:true,cursor:'late',events:[event(1)]});
  await pending;assert.equal(await store.read('test'),null);await c.dispose();
});

test('permission revocation stops audio and clears queue', async () => {
  const {c,store}=controller({api:async()=>{throw Object.assign(new Error('permission revoked'),{status:403});}});
  await store.update('test',()=>newEpisode('test','r'));await c.call('poll',{},0);
  assert.equal(await store.read('test'),null);assert.equal(c.ui.status,'stopped');await c.dispose();
});

test('storage failure pauses and does not advance cursor or play', async () => {
  const {c}=controller({storage:{read:async()=>{throw Object.assign(new Error('storage failed'),{code:'notification_storage'});},update:async()=>{throw new Error('storage failed');}}});
  await c.poll(0);assert.equal(c.ui.status,'error');await c.dispose();
});

test('request timeout is retryable instead of leaving a permanently hanging poll', async () => {
  const {c}=controller({requestTimeoutMs:5,api:async(op,body,signal)=>new Promise((resolve,reject)=>{
    signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')));
  })});
  await assert.rejects(c.call('poll',{},0),error=>error.status===503&&error.code==='notification_network');await c.dispose();
});

test('validation network failure retains queue and waits for automatic recovery', async () => {
  const {c,store}=controller({api:async()=>{throw Object.assign(new Error('network'),{status:503});}});
  let s=newEpisode('test','r');s.cursor='c';s.recovery=false;s.queue=[event(1)];await store.update('test',()=>s);
  await c.pump(0);const saved=await store.read('test');assert.equal(saved.queue.length,1);
  assert.equal(saved.uncertain.length,0);assert.equal(saved.recovery,true);assert.equal(c.ui.status,'reconnecting');await c.dispose();
});

test('closing from another tab during sound activation cannot recreate an episode', async () => {
  let finish;
  const {c,store,calls}=controller({player:{play:()=>new Promise(resolve=>{finish=resolve;}),stop(){}}});
  const activating=c.enable(); await c.disable(); finish(); await activating;
  assert.equal(await store.read('test'),null);assert.ok(!calls.includes('start'));await c.dispose();
});

test('a late old leader initialization cannot stop the current generation', async () => {
  let finish;
  const {c}=controller({storage:{update:()=>new Promise(resolve=>{finish=resolve;}),read:async()=>null}});
  const old=c.begin(0);c.halt('off');c.emit({status:'listening'});
  const current=c.generation;finish(newEpisode('test','r'));await old;
  assert.equal(c.generation,current);assert.equal(c.ui.status,'listening');await c.dispose();
});

test('recovered polling removes the stale network failure message', async () => {
  const {c,store}=controller();let s=newEpisode('test','r');s.cursor='existing';await store.update('test',()=>s);
  c.emit({status:'reconnecting',message:'network failed'});await c.poll(0);
  assert.equal(c.ui.status,'listening');assert.equal(c.ui.message,'');await c.dispose();
});

test('an old reconnect summary cannot overwrite a new playback failure', async () => {
  const {c,store}=controller();const s=newEpisode('test','r');s.message='补播提醒：共 2 笔新订单';await store.update('test',()=>s);
  c.fail(new Error('audio failed'));await c.refresh();assert.equal(c.ui.message,'audio failed');await c.dispose();
});

class FakeAudio extends EventTarget {
  static latest;
  constructor() {super();FakeAudio.latest=this;this.paused=true;this.calls=0;}
  play() {this.paused=false;this.calls++;return Promise.resolve();}
  pause() {this.paused=true;}
}

test('fixed audio completes on ended and cancellation releases the player', async () => {
  const player=createVoiceAudio('fixture.wav',{AudioClass:FakeAudio,maxPlaybackMs:1000});
  const done=player.play();assert.equal(FakeAudio.latest.calls,1);FakeAudio.latest.dispatchEvent(new Event('ended'));await done;
  const cancelled=player.play();player.stop();await assert.rejects(cancelled,error=>error.name==='AbortError');
  assert.equal(FakeAudio.latest.paused,true);
});

test('stalled fixed audio pauses and exposes a recoverable playback error', async () => {
  const player=createVoiceAudio('fixture.wav',{AudioClass:FakeAudio,maxPlaybackMs:5});
  await assert.rejects(player.play(),error=>error.code==='notification_audio'&&error.message.includes('超时'));
  assert.equal(FakeAudio.latest.paused,true);
});
