const BUSY_MESSAGES = {
  export_capacity: '导出服务繁忙，正在等待空闲资源',
  export_in_progress: '已有导出任务正在进行，正在等待完成',
  export_queued: '导出正在排队',
};
const QUEUE_WAIT_MS = 120000;
const REQUEST_TIMEOUT_MS = 120000;

function retryAfterSeconds(value) {
  if (!value) return 0;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, seconds);
  const date = Date.parse(value);
  return Number.isFinite(date) ? Math.max(0, (date - Date.now()) / 1000) : 0;
}

async function downloadAttempt(fetcher, url, options, timeoutMs) {
  let timer, timedOut = false, externalAbort;
  const controller = timeoutMs ? new AbortController() : null;
  if (controller) {
    if (options.signal) {
      externalAbort = () => controller.abort(options.signal.reason);
      if (options.signal.aborted) externalAbort();
      else options.signal.addEventListener('abort', externalAbort, { once: true });
    }
    timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  }
  try {
    const response = await fetcher(url, controller ? { ...options, signal: controller.signal } : options);
    if (response.ok) {
      if (response.headers?.get('Content-Type')?.includes('application/json')) return { response, data: await response.json() };
      return { response, blob: await response.blob() };
    }
    let data;
    try { data = await response.json(); }
    catch (error) { if (timedOut) throw error; data = {}; }
    return { response, data };
  } catch (error) {
    if (timedOut) throw Object.assign(new Error('请求或下载超时，请先确认导出状态再重试'), { code: 'export_request_timeout' });
    throw error;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    if (externalAbort) options.signal.removeEventListener('abort', externalAbort);
  }
}

function saveBlob(blob, filename) {
  const urlObject = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = urlObject;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(urlObject), 60000);
}

function responseError(response, data) {
  return Object.assign(new Error(data?.message || '导出失败'), {
    status: response.status, code: data?.code, data,
    retryAfter: retryAfterSeconds(response.headers.get('Retry-After')),
  });
}

export async function downloadFile(fetcher, url, filename, options = {}) {
  const { busyRetry = false, onBusyWait, onBusyResume, onExportReady, onStatusAvailable,
    onExportUnavailable, onDownloadStart, requestTimeout = 0, ...requestOptions } = options;
  const ticket = new Headers(requestOptions.headers).get('X-Export-Ticket');
  const resultPath = busyRetry && /^[0-9a-f-]{36}$/i.test(ticket || '') ? `/api/admin/orders/export-results/${ticket}` : null;
  const readOptions = { method: 'GET', ...(requestOptions.signal ? { signal: requestOptions.signal } : {}) };
  const unavailable = error => {
    const terminal = [400,401,403,404,410].includes(error.status)
      || ['export_timeout','export_image_unavailable','rate_limited','export_poll_limited',
        'export_queue_full','export_ticket_finished','export_ticket_expired','export_ticket_mismatch'].includes(error.code);
    if (terminal) onExportUnavailable?.();
    return error;
  };
  const downloadReady = async data => {
    if (!resultPath || data?.status !== 'ready' || data.ticketId !== ticket
      || data.statusUrl !== resultPath || data.downloadUrl !== `${resultPath}/download`) {
      onExportUnavailable?.();
      throw Object.assign(new Error('导出结果信息无效，请重新查询状态'), { code: 'export_result_invalid' });
    }
    const again = async () => {
      onDownloadStart?.();
      const result = await downloadAttempt(fetcher, data.downloadUrl, readOptions, requestTimeout);
      if (!result.response.ok) throw unavailable(responseError(result.response, result.data));
      if (!result.blob) throw Object.assign(new Error('下载内容不是有效文件，请重新查询状态'), { code: 'export_result_invalid' });
      saveBlob(result.blob, data.filename || filename);
    };
    onExportReady?.(data, again);
    await again();
  };
  const checkStatus = async () => {
    const result = await downloadAttempt(fetcher, resultPath, readOptions, requestTimeout);
    if (!result.response.ok) throw unavailable(responseError(result.response, result.data));
    const data = result.data;
    if (data?.status === 'ready') return downloadReady(data);
    if (data?.status === 'started' || data?.status === 'waiting') {
      throw Object.assign(new Error(data.status === 'started' ? '文件仍在生成，请稍后再次检查' : '导出仍在排队，请稍后再次检查'), { code: 'export_pending' });
    }
    onExportUnavailable?.();
    throw Object.assign(new Error(data?.message || '本次导出已结束，请重新发起'), { code: data?.code || 'export_finished' });
  };
  if (resultPath) onStatusAvailable?.(checkStatus);
  let queueStarted;
  let blob;
  while (true) {
    const result = await downloadAttempt(fetcher, url, requestOptions, requestTimeout);
    const { response, data } = result;
    if (response.ok) {
      if (result.data) { await downloadReady(result.data); return; }
      blob = result.blob;
      onExportUnavailable?.();
      break;
    }
    const retryAfter = retryAfterSeconds(response.headers.get('Retry-After'));
    const code = data?.code;
    const message = busyRetry && response.status === 429 && Object.hasOwn(BUSY_MESSAGES, code)
      ? BUSY_MESSAGES[code]
      : busyRetry && code === 'export_timeout' ? '导出生成超时，请稍后重新发起' : (data?.message || '导出失败');
    const error = Object.assign(new Error(message), { status: response.status, code, retryAfter, data });
    if (!busyRetry || response.status !== 429 || !Object.hasOwn(BUSY_MESSAGES, code)) throw unavailable(error);
    if (queueStarted === undefined) queueStarted = Date.now();
    const remaining = QUEUE_WAIT_MS - (Date.now() - queueStarted);
    if (remaining <= 0) {
      error.message = '导出排队等待超时，请稍后重试';
      onExportUnavailable?.();
      throw error;
    }
    const delay = Math.max(1000, retryAfter * 1000);
    onBusyWait?.(error);
    await new Promise(resolve => setTimeout(resolve, Math.min(delay, remaining)));
    if (Date.now() - queueStarted >= QUEUE_WAIT_MS) {
      error.message = '导出排队等待超时，请稍后重试';
      onExportUnavailable?.();
      throw error;
    }
    onBusyResume?.();
  }
  saveBlob(blob, filename);
}

export function createOrderExportController(state) {
  let recovery;
  const clearRecovery = () => {
    recovery = null;
    if ('recovery' in state) state.recovery = null;
  };
  return {
    async run(action) {
      if (state.busy) return false;
      state.busy = true;
      state.phase = 'generating';
      state.position = null;
      clearRecovery();
      try {
        await action({
          busyRetry: true,
          requestTimeout: REQUEST_TIMEOUT_MS,
          headers: { 'X-Export-Ticket': crypto.randomUUID() },
          onBusyWait: error => {
            state.phase = 'waiting';
            state.position = Number.isInteger(error.data?.position) && error.data.position > 0 ? error.data.position : null;
          },
          onBusyResume: () => { state.phase = 'generating'; state.position = null; },
          onStatusAvailable: action => { recovery = action; state.recovery = 'status'; },
          onExportReady: (_data, action) => { recovery = action; state.recovery = 'download'; },
          onExportUnavailable: clearRecovery,
          onDownloadStart: () => { state.phase = 'downloading'; state.position = null; },
        });
        return true;
      } finally {
        state.busy = false;
        state.phase = '';
        state.position = null;
      }
    },
    async recover() {
      if (state.busy || !recovery) return false;
      state.busy = true;
      state.phase = state.recovery === 'download' ? 'downloading' : 'checking';
      try {
        await recovery();
        return true;
      } finally {
        state.busy = false;
        state.phase = '';
        state.position = null;
      }
    },
  };
}
