import { authenticatedFetch } from './authTransport.js';
import { localizeError, responseError } from './utils/adminErrors.js';
export const API_BASE = "";
export async function request(path, options = {}) {
  const { skipGlobalLoading, ...fetchOptions } = options;
  let response;
  try {
    response = await authenticatedFetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      headers: {
        ...(options.body == null || options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...options.headers,
      },
    });
  } catch (error) {
    throw localizeError(error, "连接失败，请检查网络后重试。当前输入已保留。");
  }
  const data = await response.json().catch((error) => {
    if (error?.name === 'AbortError') throw error;
    if (response.ok && response.status !== 204 && response.status !== 205)
      throw new Error('服务器响应格式异常，请稍后重试');
    return {};
  });
  if (!response.ok) {
    throw responseError(response.status, data, response.headers.get("Retry-After"));
  }
  return data;
}
