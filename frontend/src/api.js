import { authenticatedFetch } from './authTransport';
export const API_BASE = "";
export async function request(path, options = {}) {
  const { skipGlobalLoading, ...fetchOptions } = options;
  let response;
  try {
    response = await authenticatedFetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      headers: {
        ...(options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...options.headers,
      },
    });
  } catch (error) {
    if (error.name === "AbortError" || error.status) throw error;
    throw new Error("连接失败，请检查网络后重试。当前输入已保留。");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(
      data.message ||
        { 403: "没有执行此操作的权限", 409: "数据已更新，请核对最新版本" }[
          response.status
        ] ||
        "请求失败，请重试",
    );
    error.status = response.status;
    error.retryAfter = Number(response.headers.get("Retry-After") || 0);
    error.code = data.code;
    error.data = data;
    throw error;
  }
  return data;
}
