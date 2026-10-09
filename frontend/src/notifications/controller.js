import { acceptPoll, newEpisode } from './storage.js';

export async function sessionKey(userId, token, crypto = globalThis.crypto) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(token));
  return `order-voice:${userId}:${Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('')}`;
}

export class OrderVoiceController {
  constructor({ key, storage, player, api, locks = navigator.locks,
    channel = new BroadcastChannel('gingtto-order-voice'), onState = () => {}, requestTimeoutMs = 15000 }) {
    Object.assign(this, { key, storage, player, api, locks, channel, onState, requestTimeoutMs });
    this.ui = { status: 'off', message: '', uncertainCount: 0, enabled: false, playing: false };
    this.generation = 0; this.soundReady = false; this.disposed = false;
    this.channel.onmessage = e => {
      if (e.data.key !== this.key) return;
      if (e.data.type === 'stop') this.halt('off');
      this.refresh().catch(error => this.fail(error));
    };
  }
  emit(values = {}) { Object.assign(this.ui, values); this.onState({ ...this.ui }); }
  announce(type = 'changed') { this.channel.postMessage({ key: this.key, type }); }
  async refresh() {
    const state = await this.storage.read(this.key);
    const retainFailure = ['error','stopped','server-off','unsupported'].includes(this.ui.status);
    this.emit({ enabled: !!state?.enabled, uncertainCount: state?.uncertain.length || 0,
      message: retainFailure ? this.ui.message : state?.message || '' });
    if (!state?.enabled && this.release) this.halt('off');
    else if (state?.enabled && !this.soundReady && !['error','stopped','server-off'].includes(this.ui.status)) this.emit({ status: 'needs-sound' });
    return state;
  }
  // The first operation is audio.play(), preserving the user gesture.
  async enable() {
    if (this.ui.playing || this.disposed) return;
    const generation = this.generation;
    this.emit({ playing: true });
    try {
      await this.player.play();
      if (!this.active(generation)) return;
      this.soundReady = true;
      await this.storage.update(this.key, state => !this.active(generation) || state?.enabled ? state : newEpisode(this.key, crypto.randomUUID()));
      if (!this.active(generation)) return;
      this.announce(); await this.refresh(); this.lead();
    } catch (error) { if (error.name !== 'AbortError') this.fail(error); }
    finally { this.emit({ playing: false }); }
  }
  async test() {
    if (this.ui.playing || this.disposed) return;
    this.manualPlaying = true; this.emit({ playing: true });
    try { await this.player.play(); }
    catch (error) { if (error.name !== 'AbortError') this.fail(error); }
    finally { this.manualPlaying = false; this.emit({ playing: false }); }
  }
  async disable() {
    this.halt('off'); this.announce('stop');
    try { await this.storage.update(this.key, () => null); this.emit({ enabled: false, uncertainCount: 0, message: '' }); this.announce(); }
    catch (error) { this.fail(error); }
  }
  lead() {
    if (this.lockRequest || !this.soundReady || this.disposed) return;
    const generation = ++this.generation;
    this.lockAbort = new AbortController(); this.emit({ status: 'follower' });
    this.lockRequest = this.locks.request(this.key, { signal: this.lockAbort.signal }, async () => {
      if (!this.active(generation)) return;
      await new Promise(resolve => {
        this.release = resolve;
        this.begin(generation).catch(error => this.fail(error));
      });
      this.release = null;
    }).catch(error => { if (error.name !== 'AbortError') this.fail(error); })
      .finally(() => { this.lockRequest = null; });
  }
  active(generation) { return !this.disposed && generation === this.generation; }
  async write(requestId, reducer) {
    const generation = this.generation;
    return this.storage.update(this.key, state => this.active(generation) && state?.enabled && state.requestId === requestId ? reducer(state) : state);
  }
  async begin(generation) {
    let state = await this.storage.update(this.key, state => this.active(generation) && state?.enabled ? {
      ...state, recovery: true, uncertain: [...state.uncertain, ...state.inFlight], inFlight: [],
    } : state);
    if (!this.active(generation)) return;
    if (!state?.enabled) { this.halt('off'); return; }
    if (!state.cursor) {
      const data = await this.call('start', { requestId: state.requestId }, generation);
      if (!data || !this.active(generation)) return;
      state = await this.write(state.requestId, s => ({ ...s, cursor: data.cursor, recovery: false }));
    }
    if (!state?.enabled || !this.active(generation)) return;
    this.backoff = 0; this.emit({ status: 'listening', message: state.message || '' }); this.announce();
    this.poll(generation); this.pump(generation);
  }
  async call(operation, body, generation) {
    const abort = new AbortController(); this.requests ||= new Set(); this.requests.add(abort);
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; abort.abort(); }, this.requestTimeoutMs);
    try {
      const data = await this.api(operation, body, abort.signal);
      if (!this.active(generation)) return null;
      if (!data.enabled) {
        await this.disable(); this.emit({ status: 'server-off', message: '服务器尚未开启语音提醒' }); return null;
      }
      return data;
    } catch (error) {
      if (timedOut && this.active(generation))
        throw Object.assign(new Error('提醒请求超时，等待网络恢复'), { status: 503, code: 'notification_network' });
      if (!this.active(generation) || error.name === 'AbortError') return null;
      if ([401, 403, 409].includes(error.status)) {
        await this.disable(); this.emit({ status: 'stopped', message: error.message }); return null;
      }
      throw error;
    } finally { clearTimeout(timeout); this.requests.delete(abort); }
  }
  async poll(generation) {
    if (!this.active(generation)) return;
    let delay = 5000;
    try {
      const state = await this.storage.read(this.key);
      if (!state?.enabled || !this.active(generation)) return;
      const interrupted = state.recovery || (state.lastPoll && Date.now() - state.lastPoll > 15000);
      const data = await this.call('poll', { cursor: state.cursor, recovery: !!interrupted }, generation);
      if (!data || !this.active(generation)) return;
      const saved = await this.write(state.requestId, s => acceptPoll(s, data));
      if (!saved?.enabled || !this.active(generation)) return;
      this.backoff = 0; this.emit({ status: 'listening', message: saved.message || '' }); this.announce();
      if (data.hasMore) delay = 0;
    } catch (error) {
      if (!this.active(generation)) return;
      if (error.code === 'notification_storage') { this.fail(error); return; }
      if (!error.status || error.status >= 500) {
        // Failure to persist the recovery marker must stop delivery, not silently advance.
        try {
          const state = await this.storage.read(this.key);
          if (state) await this.write(state.requestId, s => ({ ...s, recovery: true }));
        } catch (storageError) { this.fail(storageError); return; }
        this.emit({ status: 'reconnecting', message: '连接中断，恢复后合并补播最近 10 分钟的新订单' });
        delay = [5000, 10000, 20000, 30000][Math.min(this.backoff++, 3)];
      } else { this.fail(error); return; }
    }
    if (this.active(generation)) this.pollTimer = setTimeout(() => this.poll(generation), delay);
  }
  async pump(generation) {
    if (!this.active(generation)) return;
    try {
      const state = await this.storage.read(this.key);
      if (!state?.enabled || !this.active(generation)) return;
      if (!state.recovery && !this.manualPlaying) {
        const items = state.batch.length ? state.batch : state.queue.slice(0, 1);
        if (items.length) await this.playItems(state, items, !!state.batch.length, generation);
      }
    } catch (error) {
      if (!this.active(generation)) return;
      if ((!error.status || error.status >= 500) && !['notification_audio','notification_storage'].includes(error.code)) {
        try {
          const state = await this.storage.read(this.key);
          if (state) await this.write(state.requestId, s => ({ ...s, recovery: true }));
          this.emit({ status: 'reconnecting', message: '播放前核验连接中断，等待恢复后合并补播' });
        } catch (storageError) { this.fail(storageError); return; }
      } else { this.fail(error); return; }
    }
    if (this.active(generation)) this.playTimer = setTimeout(() => this.pump(generation), 500);
  }
  async playItems(state, items, combined, generation) {
    const valid = [];
    for (let i = 0; i < items.length; i += 100) {
      const data = await this.call('validate', { cursor: state.cursor, eventIds: items.slice(i, i + 100).map(e => e.eventId) }, generation);
      if (!data || !this.active(generation)) return;
      valid.push(...data.events);
    }
    if (this.manualPlaying || !this.active(generation)) return;
    const ids = new Set(items.map(e => e.eventId));
    const saved = await this.write(state.requestId, s => s.recovery ? s : ({ ...s,
      queue: s.queue.filter(e => !ids.has(e.eventId)), batch: s.batch.filter(e => !ids.has(e.eventId)),
      inFlight: valid, processed: [...s.processed, ...items.filter(e => !valid.some(v => v.eventId === e.eventId))
        .map(e => ({ eventId: e.eventId, at: Date.now() }))],
    }));
    if (!saved?.enabled || saved.recovery || !this.active(generation) || !valid.length) return;
    this.emit({ playing: true });
    try {
      await this.player.play();
      if (!this.active(generation)) return;
      await this.write(state.requestId, s => ({ ...s, inFlight: [],
        processed: [...s.processed, ...valid.map(e => ({ eventId: e.eventId, at: Date.now() }))],
        message: combined ? `补播提醒：共 ${valid.length} 笔新订单` : s.message,
      }));
      await this.refresh(); this.announce();
    } catch (error) {
      if (!this.active(generation)) return;
      await this.write(state.requestId, s => ({ ...s, inFlight: [], uncertain: [...s.uncertain, ...valid] }));
      error.code ||= "notification_audio";
      throw error;
    } finally { this.emit({ playing: false }); }
  }
  async replay() {
    if (this.ui.playing || this.disposed) return;
    if (!this.soundReady) { this.emit({ status: 'needs-sound' }); return; }
    try {
      await this.storage.update(this.key, s => s?.enabled ? {
        ...s, batch: [...s.batch, ...s.uncertain], uncertain: [],
      } : s);
      this.announce(); await this.refresh(); this.lead();
    } catch (error) { this.fail(error); }
  }
  fail(error) {
    this.halt('error'); this.emit({ message: error.message || '提醒发生异常，请点击恢复监听', playing: false });
    this.refresh().catch(() => {});
  }
  halt(status) {
    ++this.generation; clearTimeout(this.pollTimer); clearTimeout(this.playTimer);
    this.requests?.forEach(abort => abort.abort()); this.player.stop();
    this.lockAbort?.abort(); this.release?.(); this.soundReady = false; this.emit({ status, playing: false });
  }
  async dispose(clear = false) {
    this.disposed = true; this.halt('off'); this.channel.close();
    if (clear) await this.storage.update(this.key, () => null).catch(() => {});
  }
}
