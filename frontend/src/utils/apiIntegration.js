export const apiStates = {
  not_generated: '未生成', enabled: '启用', owner_disabled: '本人停用',
  admin_blocked: '管理员禁用', expired: '已过期',
};
export function beijingTime(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(new Date(value)).replaceAll('/', '-');
}
export function expiryISO(value) {
  if (!value) return null;
  const date = new Date(value.replace(' ', 'T') + '+08:00');
  if (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) {
    throw new Error('请选择未来的北京时间，或留空表示长期有效');
  }
  return date.toISOString();
}
export function apiExamples(baseUrl) {
  return {
    curl: [
      'curl --fail-with-body \\',
      "  -H 'Authorization: Bearer TOKEN' \\",
      `  '${baseUrl}/products?limit=50'`,
    ].join('\n'),
    python: `import os
import requests

base = "${baseUrl}"
# 在服务端环境变量中设置 TOKEN，不放入网页或 URL。
headers = {"Authorization": "Bearer " + os.environ["TOKEN"]}
cursor = None
products = []
while True:
    params = {"limit": 50}
    if cursor:
        params["cursor"] = cursor
    response = requests.get(base + "/products", headers=headers,
                            params=params, timeout=20)
    # 429 按 Retry-After 等待；其他错误保留旧目录并结束本轮同步。
    response.raise_for_status()
    data = response.json()
    products.extend(data["items"])
    cursor = data["nextCursor"]
    if not cursor:
        break
# 仅在全量分页全部成功后执行目录对账。
ids = [str(p["productId"]) for p in products[:100]]
if ids:
    response = requests.get(base + "/inventory", headers=headers,
        params={"productIds": ",".join(ids)}, timeout=20)
    response.raise_for_status()
    inventory = response.json()
`,
  };
}
