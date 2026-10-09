// Reducers are synchronous: no fetch, audio or awaited work inside IDB transactions.
export function createNotificationStorage(indexedDB = globalThis.indexedDB) {
  let database;
  const open = () => database ||= new Promise((resolve, reject) => {
    let abandoned = false;
    const request = indexedDB.open('gingtto-order-voice', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('episodes', { keyPath: 'key' });
    request.onsuccess = () => {
      const db = request.result;
      if (abandoned) { db.close(); return; }
      db.onversionchange = () => { db.close(); database = null; };
      db.onclose = () => { database = null; };
      resolve(db);
    };
    request.onerror = () => { abandoned = true; reject(request.error); };
    request.onblocked = () => { abandoned = true; reject(new Error('其他标签页占用了提醒存储，请关闭旧页面后重试')); };
  }).catch(error => { database = null; throw error; });
  const storageError = error => Object.assign(error || new Error("提醒存储失败"), { code: "notification_storage" });
  const safely = operation => (...args) => operation(...args).catch(error => { throw storageError(error); });
  const operations = {
    async update(key, reducer) {
      const db = await open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('episodes', 'readwrite'), store = tx.objectStore('episodes');
        let result;
        const read = store.get(key);
        read.onsuccess = () => {
          try {
            result = reducer(read.result || null);
            if (result?.then) throw new Error('提醒存储事务只接受同步更新');
            if (result === null) store.delete(key);
            else store.put({ ...result, key });
          } catch (error) { reject(error); tx.abort(); }
        };
        tx.oncomplete = () => resolve(result);
        tx.onabort = tx.onerror = () => reject(tx.error || new Error('提醒存储失败'));
      });
    },
    async read(key) {
      const db = await open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction('episodes', 'readonly');
        const request = tx.objectStore('episodes').get(key);
        let result;
        request.onsuccess = () => { result = request.result || null; };
        tx.oncomplete = () => resolve(result);
        tx.onabort = tx.onerror = () => reject(tx.error || new Error('提醒存储读取失败'));
      });
    },
  };
  return { update: safely(operations.update), read: safely(operations.read) };
}

export function newEpisode(key, requestId) {
  return { key, requestId, enabled: true, cursor: '', queue: [], batch: [], processed: [],
    uncertain: [], inFlight: [], recovery: true, cutoffAt: null, lastPoll: 0, message: '' };
}

export function mergeEvents(state, events) {
  const known = new Set([...state.queue, ...state.batch, ...state.uncertain, ...state.inFlight,
    ...state.processed].map(e => e.eventId));
  return [...state.queue, ...events.filter(e => !known.has(e.eventId) && known.add(e.eventId))];
}

export function acceptPoll(state, data, localTime = Date.now()) {
  const next = { ...state, cursor: data.cursor, lastPoll: localTime,
    queue: mergeEvents(state, data.events), recovery: data.recovery && !data.recoveryComplete };
  if (data.recoveryComplete) {
    const cutoff = data.cutoffAt * 1000;
    const eligible = [...state.batch, ...next.queue].filter(e => Date.parse(e.createdAt) >= cutoff);
    const expired = [...state.batch, ...next.queue].filter(e => Date.parse(e.createdAt) < cutoff);
    next.batch = eligible; next.queue = [];
    next.processed = [...state.processed, ...expired.map(e => ({ eventId: e.eventId, at: localTime }))];
  }
  // Pending/uncertain items are never expired by this bookkeeping cleanup.
  next.processed = next.processed.filter(e => e.at >= localTime - 7 * 86400000);
  return next;
}
