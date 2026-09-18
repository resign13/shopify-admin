export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").trim();
export async function request(path, options = {}) {
  const { skipGlobalLoading, ...fetchOptions } = options;
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      headers: {
        ...(options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        ...options.headers,
      },
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("连接失败，请检查网络后重试。当前输入已保留。");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.includes("/login") && !path.includes("/logout"))
      window.dispatchEvent(new Event("admin-session-expired"));
    const error = new Error(
      data.message ||
        { 403: "没有执行此操作的权限", 409: "数据已更新，请核对最新版本" }[
          response.status
        ] ||
        "请求失败，请重试",
    );
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}
