const CODE_MESSAGES = {
  session_changed: '登录账号已改变，请重新打开页面',
  login_failed: '账号或密码错误',
  rate_limited: '请求过于频繁，请稍后重试',
  export_capacity: '导出服务繁忙，请稍后重试',
  export_in_progress: '已有导出任务正在进行，请等待完成',
  export_queued: '导出正在排队，请稍后重试',
  export_queue_full: '导出队列已满，请稍后重试',
  export_timeout: '导出生成超时，请稍后重新发起',
  export_poll_limited: '导出状态查询过于频繁，请稍后重试',
  export_ticket_started: '导出任务已开始，请查询导出状态',
  export_ticket_finished: '导出任务已结束，请重新发起',
  export_ticket_expired: '导出结果已过期，请重新发起',
  export_ticket_mismatch: '导出任务信息不匹配，请重新发起',
  export_image_unavailable: '导出所需图片暂不可用，请稍后重试',
};

const STATUS_MESSAGES = {
  401: '登录已失效，请重新登录',
  403: '没有执行此操作的权限',
  404: '请求的内容不存在或已被移除',
  409: '数据已更新，请核对最新版本后重试',
  429: '请求过于频繁，请稍后重试',
  502: '服务暂时不可用，请稍后重试',
  503: '服务暂时不可用，请稍后重试',
  504: '请求超时，请稍后重试',
};

// Backend Chinese explanations may contain SKU, field names, and other identifiers.
export function errorMessage(error, fallback = '操作失败，请重试') {
  const message = typeof error === 'string' ? error : error?.message;
  if (typeof message === 'string' && /[\u3400-\u9fff]/u.test(message)) return message;
  const code = error?.code;
  const status = error?.status;
  return (Object.hasOwn(CODE_MESSAGES, code) && CODE_MESSAGES[code]) ||
    (Object.hasOwn(STATUS_MESSAGES, status) && STATUS_MESSAGES[status]) || fallback;
}

export function localizeError(error, fallback) {
  if (error?.name === 'AbortError' || error === 'cancel' || error === 'close') return error;
  const message = errorMessage(error, fallback);
  const localized = new Error(message);
  if (error && typeof error === 'object') {
    Object.assign(localized, error);
    for (const key of ['status', 'code', 'retryAfter', 'data']) {
      if (key in error) localized[key] = error[key];
    }
    localized.name = error.name || 'Error';
  }
  localized.message = message;
  return localized;
}

export function retryAfterSeconds(value) {
  if (!value) return 0;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, seconds);
  const date = Date.parse(value);
  return Number.isFinite(date) ? Math.max(0, (date - Date.now()) / 1000) : 0;
}

export function responseError(status, data, retryAfter, fallback = '请求失败，请重试') {
  const error = Object.assign(new Error(data?.message), {
    status, code: data?.code, retryAfter: retryAfterSeconds(retryAfter), data,
  });
  return localizeError(error, fallback);
}
