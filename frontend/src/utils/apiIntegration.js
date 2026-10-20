export const apiStates = {
  not_generated: '未生成', enabled: '启用', owner_disabled: '本人停用',
  admin_blocked: '管理员禁用', expired: '已过期',
};
export const apiCommonHeaders = [
  {name:'Authorization',location:'请求头',required:true,type:'字符串',defaultValue:'无',description:'填写本人启用中的完整 API Key；固定使用 Bearer 加一个空格，再接 Key。',example:'Authorization: Bearer TOKEN'},
  {name:'Accept',location:'请求头',required:false,type:'字符串',defaultValue:'不传',description:'可省略；接口始终返回 JSON。',example:'Accept: application/json'},
];
export const apiReadEndpoints = [
  {
    id:'products',path:'/products',requiredLabel:'无查询参数必填',optionalLabel:'limit、cursor、keyword、categoryId、styleCodes、skus',
    returns:'items、nextCursor、limit、readAt、requestId',exampleKey:'curl',
    introduction:'仅携带认证请求头即可获取第一页。筛选参数可组合使用，组合时须同时满足；同一列表中的多个款号或 SKU 表示匹配其中任意一项。',
    parameters:[
      {name:'limit',location:'查询参数',required:false,type:'整数',defaultValue:'50',description:'每页颜色 SKU 数量，取值 1–100。',example:'limit=50'},
      {name:'cursor',location:'查询参数',required:false,type:'字符串',defaultValue:'不传，查询第一页',description:'后续分页原样传入上次返回的 nextCursor；保持筛选条件一致。nextCursor 为 null 时结束。',example:'cursor=123'},
      {name:'keyword',location:'查询参数',required:false,type:'字符串',defaultValue:'不筛选',description:'模糊搜索款号、颜色 SKU 或商城英文标题，最多 200 字符。',example:'keyword=CS2209'},
      {name:'categoryId',location:'查询参数',required:false,type:'正整数',defaultValue:'全部分类',description:'商品返回的 category.id，不是分类名称。',example:'categoryId=1'},
      {name:'styleCodes',location:'查询参数',required:false,type:'字符串列表',defaultValue:'全部款号',description:'精确匹配款号；逗号分隔或重复传参，最多 100 项，每项最多 200 字符。',example:'styleCodes=CS2209,CS2211'},
      {name:'skus',location:'查询参数',required:false,type:'字符串列表',defaultValue:'全部 SKU',description:'精确匹配接口返回的颜色 SKU；逗号分隔或重复传参，最多 100 项，每项最多 200 字符。',example:'skus=CS2209-Black,CS2209-Khaki'},
    ],
  },
  {
    id:'product',path:'/products/{productId}',requiredLabel:'productId（路径）',optionalLabel:'无',
    returns:'item、readAt、requestId；下架或缺失返回 404',exampleKey:'curlProduct',
    introduction:'把路径中的 {productId} 替换为商品列表返回的 productId。这是颜色商品 ID，不是款号或 SKU；无需另传查询参数。',
    parameters:[{name:'productId',location:'路径参数',required:true,type:'正整数',defaultValue:'无',description:'颜色商品 ID；与商品列表返回的 productId 一致。',example:'/products/123'}],
  },
  {
    id:'inventory',path:'/inventory',requiredLabel:'productIds（查询）',optionalLabel:'无',
    returns:'items、notFoundIds、readAt、requestId',exampleKey:'curlInventory',
    introduction:'必填 1–100 个颜色商品 ID，不接受款号或 SKU。超过 100 个时分批查询；省略或传空列表返回 400。',
    parameters:[{name:'productIds',location:'查询参数',required:true,type:'正整数列表',defaultValue:'无',description:'逗号分隔或重复传参；每次 1–100 项。重复 ID 会合并；ID 来自商品列表。',example:'productIds=123,456 或 productIds=123&productIds=456'}],
  },
];
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
      `  '${baseUrl}/products'`,
    ].join('\n'),
    curlFiltered: [
      'curl --get --fail-with-body \\',
      "  -H 'Authorization: Bearer TOKEN' \\",
      "  --data-urlencode 'limit=50' \\",
      "  --data-urlencode 'styleCodes=CS2209,CS2211' \\",
      `  '${baseUrl}/products'`,
    ].join('\n'),
    curlProduct: [
      'curl --fail-with-body \\',
      "  -H 'Authorization: Bearer TOKEN' \\",
      `  '${baseUrl}/products/123'`,
    ].join('\n'),
    curlInventory: [
      'curl --get --fail-with-body \\',
      "  -H 'Authorization: Bearer TOKEN' \\",
      "  --data-urlencode 'productIds=123,456' \\",
      `  '${baseUrl}/inventory'`,
    ].join('\n'),
    python: `import os
import time
import requests

base = "${baseUrl}"
# 在服务端环境变量中设置 TOKEN，不放入网页或 URL。
headers = {"Authorization": "Bearer " + os.environ["TOKEN"]}

def get_json(path, params=None):
    # 只重试 GET 限流响应，最多 3 次；其他错误结束本轮同步。
    for attempt in range(3):
        response = requests.get(base + path, headers=headers,
                                params=params, timeout=20)
        retry_after = response.headers.get("Retry-After", "")
        if response.status_code == 429 and retry_after.isdigit() and attempt < 2:
            time.sleep(max(1, int(retry_after)))
            continue
        response.raise_for_status()
        return response.json()

cursor = None
products = []
while True:
    params = {"limit": 50}  # 可选；不传时也是每页 50 个。
    if cursor:
        params["cursor"] = cursor
    data = get_json("/products", params)
    products.extend(data["items"])
    cursor = data["nextCursor"]
    if not cursor:
        break
# 仅在全量分页全部成功后执行目录对账。
# 库存必填 productIds；全部商品每 100 个 ID 分批查询，不只取前 100 个。
ids = [str(p["productId"]) for p in products]
inventory = []
not_found_ids = []
for start in range(0, len(ids), 100):
    data = get_json("/inventory", {"productIds": ",".join(ids[start:start + 100])})
    inventory.extend(data["items"])
    not_found_ids.extend(data["notFoundIds"])
`,
  };
}
