// Keep the current page mounted. Never replay a failed business request.
export function createMaintenance({ fetcher = (...args) => fetch(...args), schedule = setTimeout, cancel = clearTimeout } = {}) {
  let state = { active: false, recovered: false, checking: false };
  let timer, pending, controller;
  const listeners = new Set();
  const update = patch => {
    state = { ...state, ...patch };
    listeners.forEach(listener => listener(state));
  };
  const stopTimer = () => { if (timer != null) cancel(timer); timer = undefined; };
  const pollLater = () => {
    stopTimer();
    if (state.active && !state.recovered) timer = schedule(() => { timer = undefined; check(); }, 30000);
  };
  function enter() {
    if (state.active && !state.recovered) return;
    update({ active: true, recovered: false });
    pollLater();
  }
  async function observe(response) {
    if (response.status !== 503) return;
    let declared = response.headers.get('X-Gingtto-Maintenance') === '1';
    if (!declared) {
      try { declared = (await response.clone().json()).code === 'maintenance'; } catch { /* Original response remains readable. */ }
    }
    if (declared) enter();
  }
  function check() {
    if (pending) return pending;
    if (!state.active || state.recovered) return Promise.resolve();
    stopTimer();
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 8000);
    update({ checking: true });
    pending = Promise.resolve().then(async () => {
      try {
        const response = await fetcher('/api/health', { method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal: controller.signal });
        const data = await response.json();
        if (response.status === 200 && data.status === 'ok') update({ recovered: true });
      } catch { /* A network error is not proof that maintenance ended. */ }
    }).finally(() => {
      clearTimeout(timeout); controller = undefined; pending = undefined;
      update({ checking: false });
      pollLater();
    });
    return pending;
  }
  return {
    observe, check,
    get state() { return state; },
    subscribe(listener) { listeners.add(listener); listener(state); return () => listeners.delete(listener); },
    continue() {
      if (!state.recovered) return false;
      stopTimer(); update({ active: false, recovered: false }); return true;
    },
    dispose() { stopTimer(); controller?.abort(); listeners.clear(); },
  };
}

export const maintenance = createMaintenance();
