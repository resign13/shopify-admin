# API 对接与只读资源保护

## 边界

- 后台账号持有一把当前 Key；与商城客户、浏览器会话完全分离。
- 模块权限 `api-integrations`。管理员的**默认模板**含此模块，已有显式权限清单保持不变；其他员工可以勾选，客户角色不开放。
- 同时具有 `admin-users` 才能查看账号管理、禁用/恢复 API 授权或作废他人 Key。
- 管理员禁用是独立持久状态，本人生成、重置、启用均不可绕过。账号停用/删除/撤销模块会永久作废当前凭证；恢复权限不复活旧 Key。
- 普通退出、重新登录、密码更新不改变 API Key。完整 Key 只在生成/重置响应中出现一次，不进入日志、数据库、浏览器存储或普通账号响应。
- 只读当前商城上架颜色商品，不提供售价、成本、订单、客户、合同、采购阶段及内部欠货余额。商品图片继续公开。

## 本轮启用范围

本轮已获准在北京时间 2026年10月19日18:00 验收通过后发布。商城代码 `EXTERNAL_API_ENABLED` 默认 `0`，返回 `503 api_not_enabled`；不因部署代码自动开放接口。

本次启用须按已批准窗口准备兼容结构、独立数据库角色、配置及入口缓存/日志规则，先通过最新 CI、备份与预检。不要直接复用商城数据库账号或在生产自动运行夹具。

## 显式迁移和数据库身份

后台迁移入口 `scripts/migrate-external-api.py --expected-db DATABASE`，使用迁移身份，不由应用启动执行。迁移是幂等增量结构：5 个 API 表、4 个字段白名单视图、账号撤销触发器及版本标记；不修改订单、库存或成本行。

表：`api_integrations`、`api_integration_events`、`api_call_logs`、`api_rate_buckets`、`api_request_leases`。

视图：`external_api_credentials_v`、`external_api_products_v`、`external_api_images_v`、`external_api_sizes_v`。认证视图不包含密码；商品视图不包含价格和内部库存阶段。

使用 `scripts/provision-external-api-role.py --expected-db DATABASE --role ROLE` 显式创建独立运行身份。密码从 `EXTERNAL_API_DB_PASSWORD` 环境变量提供，要求独立随机至少 32 字符；脚本不打印密码。仅有：

| 对象 | 授权 |
|---|---|
| 4 个专用视图 | SELECT |
| api_integrations | SELECT(admin_user_id,key_id)、UPDATE(last_used_at) |
| api_call_logs、其序列 | INSERT、USAGE |
| api_rate_buckets | SELECT、INSERT、UPDATE |
| api_request_leases | SELECT、INSERT、DELETE（仅并发租约元数据） |

该角色没有任何业务表读取/写入、账号管理写入、DDL、对象所有权或角色成员资格。不能取得凭证存储表的 token_hash 列。脚本遇到继承自 PUBLIC 的建表/TEMP 权限会停止，由独立评审的数据库权限步骤处理，不偷偷扩大权限。

商城配置：

```dotenv
EXTERNAL_API_ENABLED=0
EXTERNAL_API_DB_USER=ROLE
EXTERNAL_API_DB_PASSWORD=TOKEN
# 未配置下列项时，只沿用原数据库的地址/端口/库名，不沿用用户或密码。
EXTERNAL_API_DB_HOST=127.0.0.1
EXTERNAL_API_DB_PORT=5432
EXTERNAL_API_DB_NAME=DATABASE
EXTERNAL_API_PUBLIC_ORIGIN=https://HOST
EXTERNAL_API_LIMIT=60
EXTERNAL_API_IP_LIMIT=300
EXTERNAL_API_GLOBAL_RPS=10
EXTERNAL_API_GLOBAL_CONCURRENCY=4
EXTERNAL_API_KEY_CONCURRENCY=2
```

`EXTERNAL_API_PUBLIC_ORIGIN` 只允许 HTTPS origin，不能含路径/凭证/查询串。图片相对路径据此生成绝对地址，不信任请求 Host；其他原图源须在既有 `PUBLIC_IMAGE_ORIGINS` 的 HTTPS 来源清单中。图库顺序保留；缺失或来源不受信任的链接为 `null`，不回取网络图片。

本机同步目录现有原图源包括 `https://img.smawell.shop` 和 `https://res.cloudinary.com`；本地验收须显式配置这两项，避免把受信任的历史原图误显示为空。后续生产启用时另行核对来源配置，不从数据库中的任意 URL 自动扩大白名单。

启用时启动核验真实数据库有效权限（包括列级授权），错误即失败，不回退到商城大权限连接。商品和图片/尺码读取使用单次 `REPEATABLE READ READ ONLY` 事务；计数与调用元数据单独事务，均使用 API 身份。

已有 `security-maintenance.py` 与其 metadata-only 身份负责调用记录 30 天、密钥审计 90 天、过期配额 2 天清理；更新身份授权后沿用既有保留任务，不新增自动化。每日只读同步脚本与线上加密导出通道不修改。

## 后台管理接口

管理接口仍要求后台 Cookie、CSRF、Origin 与模块权限。

| 方法与路径（前缀 /api/admin/api-integrations） | 用途 |
|---|---|
| GET /me | 本人脱敏状态、版本、固定权限、文档地址、管理能力 |
| POST /me/generate | 首次生成；version 必填，可选 expiresAt（带时区 ISO） |
| POST /me/reset | 重置；旧凭证立即失效 |
| PUT /me/status | 启停；version、enabled 必填 |
| GET /logs | 本人调用记录；管理人员可指定 userId；page，每页 20 |
| GET /accounts | 管理人员查看后台员工；keyword、page，每页 20 |
| PUT /accounts/{id}/authorization | 管理人员禁用/恢复；version、blocked 必填 |
| POST /accounts/{id}/revoke | 作废；不代替本人生成；version 必填 |

`expiresAt=null` 为长期有效；页面输入和显示均按北京时间。并发由账号行锁及版本检查保护，过期版本 `409 api_key_conflict`。每次重置随机生成 256 位 Key，只保存 SHA-256 摘要。网络响应丢失先刷新状态，不自动重试生成；本人手动重置可重新取得一次性明文。

状态：`not_generated / enabled / owner_disabled / admin_blocked / expired`。日调用数按本人所有 Key 的有效鉴权请求统计（包括限流/查询错误）；无效或已撤销凭证不透露所属账号。记录只含接口模板、状态、耗时、时间及非凭证标识，不含 URL 参数/请求头/正文。

## 商城只读接口

仅下列已注册路径接受 `Authorization: Bearer TOKEN`。不接受 URL 凭证、Cookie 认证、跨域授权或写方法；未知 external 路径也不落回浏览器会话。Key 对既有商城/后台接口无效。

### GET /api/external/v1/products

| 参数 | 规则 |
|---|---|
| limit | 默认 50、1–100，颜色 SKU 分页 |
| cursor | 上一页 nextCursor，按商品 ID 递增，末页 null |
| keyword | 最多 200 字符，搜索款号、SKU、商城英文标题 |
| categoryId | 分类 ID |
| styleCodes / skus | 逗号分隔或重复参数，最多 100 项，每项最多 200 字符 |

```json
{
  "items": [{
    "productId": 1,
    "styleCode": "CS2209",
    "sku": "CS2209-Black",
    "color": "Black",
    "category": {"id": 1, "key": "pants", "name": "Pants"},
    "title": "Nylon Pants",
    "summary": "",
    "description": "",
    "images": {"main": "https://HOST/uploads/image.jpg", "gallery": [], "sizeChart": null, "detail": null},
    "sizes": [{"size": "M", "stock": 12}, {"size": "L", "stock": 0}]
  }],
  "limit": 50,
  "nextCursor": null,
  "readAt": "2026-10-19T00:00:00+00:00",
  "requestId": "00000000-0000-4000-8000-000000000000"
}
```

description 保留现有原始内容；接入系统如需渲染 HTML，先自行净化。真实尺码不合并、不换算，使用 productId＋size 关联，不使用数组位置关联。库存负余额按尺码逐个截为 0，不返回欠货或采购阶段。

### GET /api/external/v1/products/{productId}

返回 `item / readAt / requestId`。商品下架、删除或不存在统一 `404 product_not_found`。

### GET /api/external/v1/inventory?productIds=1,2

最多 100 个 ID。返回 `items / notFoundIds / readAt / requestId`；items 只含 productId、styleCode、sku、sizes。`notFoundIds` 与库存 0 明确区分，不为缺失尺码补造库存。

## 同步、重试与缓存

- 每页是一致只读快照，但多页不是全库同一时点。完整拉取全部成功后再对账移除；中途失败保留旧目录。库存按批次定时读取，不把商品 updated_at 当库存变更时间。
- 默认每 Key 60 次/分钟，独立数据库共享计数；另有 API IP 共享额度与入口 IP 限流。`429` 按 `Retry-After` 等待。
- `401 invalid_api_key` 不透露账号；`400 invalid_query` 检查数量/格式；`405` 不支持写入；`503 api_not_enabled` 表示尚未启用。错误及响应头携带 requestId 便于对账。
- 所有 API 响应 `Cache-Control:no-store`、`Vary:Authorization`。未来启用前在 CDN 明确绕过 `/api/external/*`，保留现有 HTTP API 拒绝和可信代理规则。
- 外部 API 访问日志只记录 `$uri` 等无查询参数字段，不记录 `$request`/`$request_uri`、Authorization、Cookie 或正文；不要把 TOKEN 放到 URL。代码不新增全局匿名例外、默认令牌或通配 CORS。
- 应用、Werkzeug 与 Gunicorn 日志过滤器会遮盖 API Key；外部 API 访问日志同时去除查询串，Gunicorn 认证/Cookie 字段被遮盖。生产入口 Nginx/CDN 的无参数日志配置仍须在另行启用前核验，不能由应用过滤器替代。

接口说明页附有 curl/Python 的 `TOKEN` 占位符示例。

## 本地验收

- 自动化仅显式本机 `*_test`，禁止指向 `lumiere_admin`。测试角色也以 `_test` 结尾。
- 后台 `test_api_integrations` 覆盖生命周期、并发生成、旧版本拒绝、授权撤销、账号恢复不复活、字段白名单、分页、库存、真实数据库 ACL、多进程共享配额、脱敏日志和幂等迁移。
- 商城 `test_external_api` 使用真实商城应用路由，覆盖 Cookie/Key 边界、数据白名单、库存不变和撤销；复用现有商城业务回归。
- `api-integrations-browser-fixture.py` 与 `verify-api-integrations-browser.js` 仅在独立测试库检查真实页面、一次性展示、响应丢失、管理阻断、独立部门权限及桌面/手机布局。原始 Key 仅保留在测试函数内存，不写入结果文件或截图。
- `verify-security-aux-roles.py` 验证真实低权限清理角色能清理 30 天调用记录，却读不到 Key、会话或业务数据。
- 手动预览连接本机同步库，使用已有真实账号；不重置密码，不创建替代测试账号。本地增量迁移先后核对业务表摘要，保留同步备份。

本轮按已批准的 18:00 窗口发布；未达到验收、CI、备份及预检条件时维持原服务，不提前维护。

### 本地真实 HTTP 测速

`scripts/benchmark-external-api-local.py` 提供可重复的有界测试：

- 必须显式提供 `PGHOST=127.0.0.1`、`PGPORT=55439` 和独立 `PGDATABASE=*_test`；连接密码只从运行环境读取。端口已有进程时直接退出，不接管现有服务。
- 从 `--source-db lumiere_admin` 的只读快照复制公开商品素材视图到测试库；不复制客户、订单、会话、售价或财务数据。测试账号及 Key 仅生成在测试库。
- 使用当前商城应用、真实 Bearer 鉴权及独立最小权限角色，经过本机 HTTP 请求测试素材 50/100 条、单品、库存 1/50/100 个、款号/SKU/关键词筛选、完整分页同步和 1/4/8 客户端并发。
- 用两个实际服务进程验证默认 60 次/分钟共用同一配额；仅在容量阶段显式将**测试进程**配额提高至 10000 次/分钟，并提高测试并发预算，防止把预期限流计作容量瓶颈。生产默认额度不改变。
- 输出样本数、成功率、传输错误、响应大小、均值、P50/P95/P99、吞吐量和业务表不变校验。Key、Cookie 和连接密码不写入报告；结束后关闭本脚本启动的进程。
- `--image-samples 0..4` 独立低频抽测公开原图，不携带 Key，不做线上压力测试。接口 JSON 只包含图片链接，其延迟不代表图片下载耗时。
- 结果仅代表 Windows 本机 Flask/Werkzeug、当前数据量和回环网络条件，不等同于生产 Gunicorn、HTTPS/CDN 或公网带宽。应在其他回归和构建完成后采集最终基准；小样本尾延迟不是性能承诺。

```powershell
# 先在当前进程安全设置测试库连接环境变量，不把密码写在命令或报告中。
python scripts/benchmark-external-api-local.py `
  --source-db lumiere_admin `
  --store-backend D:/dulizhan/worktrees/storefront-style-catalog-presale/shopify/storefront-backend `
  --output D:/dulizhan/output/api-integrations-performance.json `
  --samples 30 --image-samples 4 `
  --image-origin https://img.smawell.shop `
  --image-origin https://res.cloudinary.com
```

### 数据库连接复用与容量

后台、商城使用 `psycopg_pool` 的进程内有界连接池。不同用途和数据库身份物理隔离，不把商城 API 的连接借给后台业务：

| 用途 | 配置前缀 | 每进程默认最大连接数 |
|---|---|---:|
| 普通业务 | `DB` | 4 |
| 导出协调锁 | `DB_COORDINATION` | 2 |
| 独立只读 API 角色 | `EXTERNAL_API` | 2 |

- 各前缀支持 `_POOL_ENABLED`（默认 `1`）、`_POOL_MAX`（1–16）、`_POOL_MAX_WAITING`（默认 32，1–128）、`_POOL_TIMEOUT_SECONDS`（默认 2 秒，0.1–10）。容量是**每进程**，部署时应按两端 worker 数累加，并给迁移、运维和其他服务预留数据库连接；不是全站共用 8 条连接。
- 池从 0 条连接开始，首次请求才建立；生产启动检查、独立迁移和 Gunicorn 主进程导入不建立业务池。凭证或数据库配置变化会淘汰旧池；退出关闭连接。导出持有的协调锁使用独立预算，避免阻塞所有业务连接。
- 每次借用检查连接，并重新设置受控超时；归还时提交或回滚后执行 `DISCARD ALL`，清理角色、只读状态、临时对象和会话锁。不缓存账号授权或 Key 校验结果，不重放失败的 SQL，也不通过新增无限制连接绕过上限。
- 排队超时或队列已满返回 `503 database_busy`、`Retry-After: 2`，保留 requestId，不将容量不足当作退出登录。客户端可对只读 GET 有界重试；不要自动重放订单、保存、上传等写请求。现有事务、幂等与权限不变。
- `test_database_pool` 检查并发上限、连接失效、事务回滚、状态清理、重复关闭、环境隔离和故障响应。测速额外记录真实 API 连接峰值与负载结束后的空闲事务数量。
- `--soak-seconds 120` 可在独立测试库追加 8 客户端持续 API 负载，并同步发起后台查询。高配额只用于测试进程；真实默认仍为每 Key 每分钟 60 次。

### 图片 TLS 与慢连接复测

API 仅返回原图链接。图片下载的网络耗时与 JSON 查询、数据库连接耗时分别验收，不把第三方 CDN 波动计为数据库故障。

`scripts/api_image_probe.py` 是本地验收下载器：同源连接复用，连接超时 15 秒、读取超时 20 秒、逻辑预算 60 秒、最多 2 次尝试、每次至多 4 个请求（3 次重定向）、10 MiB。预算在请求前和读取分块之间检查，单次阻塞仍受读取超时限制，不承诺严格 60 秒墙钟截止。瞬时 GET 连接失败允许一次新连接重试；证书校验失败直接报错，403/404/429 不重试。保留 HTTPS 及 `verify=True`，不降低 TLS、不传 API Key 或 Cookie，校验最终图像内容、来源白名单及重定向。

默认直连并拒绝非公网地址。若验收电脑明确使用可信 HTTPS 代理，可显式添加 `--image-proxy-from-env`，只为图片样本读取当前 `HTTPS_PROXY`；不自动继承代理、不改变系统网络。代理通过目标域名建立 CONNECT，不将本机代理的 fake-IP DNS 结果当作公开图片 IP；该模式仅用于显式指定的可信 HTTPS 原站。

输出单次尝试、首字节、完整文件大小、总耗时及下载速度，不记录凭证、代理认证或图片 URL 查询串。大原图和冷连接仍可能较慢；小批下载成功不等于公网延迟承诺。本轮未修改生产导出抓图器的地址校验或 SSRF 防护，也未修改源图、CDN 或代理配置。

### 全局速率与并发保护

- 默认每 Key 滚动 60 秒 60 次、每 IP 300 次；所有 Key 与域名别名共享滚动一秒 10 次额度。额度均由数据库事务和行锁协调，不是每个 worker 独立获得一份。
- 全局同时处理最多 4 个、单 Key 最多 2 个。短事务登记 `api_request_leases`，不为持锁而占住一个连接；拒绝返回 `429 concurrency_limited`、`Retry-After: 1`。普通结果、异常与 teardown 都释放自己的租约；进程崩溃遗留记录最多 180 秒失效。
- Nginx 外部 API 独立入口同时按 IP 5 次/秒、全局 10 次/秒平滑，突发等待上限 10；全局连接处理中上限 4。该入口不占用商城和后台浏览器原有配额，也不恢复旧 public/internal 路由。
- 429 在接入方按 Retry-After 退避并加入随机抖动。库存建议每 30 秒批量同步；素材每 5–10 分钟或按需查询；JSON 配额不覆盖已公开的图片 CDN 下载。
- 降低分钟配额并不等于逐秒均匀调度。原容量测试中的 48 客户端突发曾触发受控 503；新增入口与应用层限制用于在数据查询前优先返回 429。
