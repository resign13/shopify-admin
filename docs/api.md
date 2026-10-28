# Gingtto Admin API

## 基础信息

- 本地后台后端: `http://127.0.0.1:5002`
- 管理后台鉴权: `Authorization: Bearer <token>`
- 商城内部服务鉴权: `X-Service-Token: lumiere-service-token`
- 数据格式: `application/json`

## 通用状态码

- `200` 请求成功
- `201` 创建成功
- `400` 参数错误或业务校验失败
- `401` 未授权
- `404` 资源不存在

## 1. 认证接口

### `POST /api/auth/admin/login`

请求体:
```json
{
  "email": "admin@lumiere.com",
  "password": "admin123"
}
```

### `GET /api/auth/me`

返回当前登录管理员信息。

### `POST /api/auth/logout`

退出当前登录会话。

## 2. 公共商城接口

### `GET /api/public/home`

返回首页轮播图、精选商品、分类和统计数据。

### `GET /api/public/products`

查询参数:
- `category`
- `keyword`
- `lang`

返回的商品字段包含:
- `productCode`
- `colorGroup`
- `colorName`
- `colorHex`
- `colorOptions[]`

### `GET /api/public/products/:slug`

返回商品详情和相关推荐。

## 3. 商城内部接口

### `POST /api/internal/store-users/authenticate`

校验商城账号密码，供商城前端登录时调用后台管理端。

### `GET /api/internal/store-users/:userId`

返回商城账号资料。

### `GET /api/internal/orders`

查询参数:
- `userId` 可选，按商城账号过滤订单

### `POST /api/internal/orders`

创建订单并自动扣减库存。

请求体:
```json
{
  "userId": 1,
  "productId": 1,
  "sizeCode": "M",
  "quantity": 2,
  "contactName": "Demo Buyer",
  "phone": "13800138000",
  "country": "China",
  "shippingAddress": "Shanghai Pudong",
  "note": "optional"
}
```

## 4. 后台首页

### `GET /api/admin/dashboard`

返回商品数、轮播图数、商城账号数、后台账号数、订单数和最近订单。

## 5. 商品管理

### `GET /api/admin/products`

返回商品列表。

### `POST /api/admin/products`

创建商品。

### `PUT /api/admin/products/:productId`

更新商品。

### `DELETE /api/admin/products/:productId`

软删除商品。

商品创建/更新请求体:
```json
{
  "categoryKey": "menswear",
  "familyCode": "zm393",
  "title": "Stripe Print Contrast Collar Split Neck Flutter Sleeve Short Dress",
  "featured": true,
  "origin": "Guangzhou, China",
  "sizes": ["S", "M", "L", "XL", "XXL"],
  "sizeChartImage": "https://example.com/size-chart.jpg",
  "descriptionImage": "https://example.com/description.jpg",
  ],
  "variants": [
    {
      "productCode": "zm393-blk",
      "sku": "zm393-blk",
      "slug": "zm393-blk",
      "colorName": "黑色",
      "colorHex": "#111111",
      "imageUrls": [
        "https://example.com/black-1.jpg",
        "https://example.com/black-2.jpg",
        "https://example.com/black-3.jpg"
      ],
      "sizePrices": [
        { "sizeCode": "S", "price": 36.99, "stock": 20 },
        { "sizeCode": "M", "price": 38.99, "stock": 30 }
      ]
    }
  ]
}
```

字段说明:
- `categoryKey`: 商品分类 key，来自商品分类管理
- `familyCode`: 一个产品的唯一编码，用来聚合同款不同颜色
- `title`: 商品标题，后台会自动写入中英法三种语言字段
- `productCode`: 单个颜色款式的唯一编码，后台必须唯一
- `colorGroup`: 同款不同颜色的分组编码，前台通过它聚合同色组选项
- `colorName`: 当前商品颜色名称
- `colorHex`: 当前商品颜色色值
- `sizePrices[].price`: 当前颜色 + 当前尺码的单价
- `sizePrices[].stock`: 当前颜色 + 当前尺码的库存

## 6. 轮播图管理

### `GET /api/admin/banners`
### `POST /api/admin/banners`
### `PUT /api/admin/banners/:bannerId`
### `DELETE /api/admin/banners/:bannerId`

说明:
- 轮播图为软删除

## 7. 商城账号管理

### `GET /api/admin/store-users`
### `POST /api/admin/store-users`
### `PUT /api/admin/store-users/:userId`
### `DELETE /api/admin/store-users/:userId`

## 8. 后台账号管理

### `GET /api/admin/admin-users`
### `POST /api/admin/admin-users`
### `PUT /api/admin/admin-users/:userId`
### `DELETE /api/admin/admin-users/:userId`

限制:
- 不能禁用当前登录管理员
- 系统至少保留一个激活状态管理员
- 不能删除当前登录管理员

## 9. 订单管理

### `GET /api/admin/orders`
### `PUT /api/admin/orders/:orderId`

更新订单状态请求体:
```json
{
  "status": "paid",
  "trackingNo": "SF123456789CN",
  "paymentLink": "https://pay.example.com/order/LM-000012"
}
```

允许状态:
- `pending_payment`
- `paid`
- `shipped`
- `completed`
- `cancelled`

说明:
- `paymentLink` 为可选字段，后台可随时维护
- 当状态改为 `shipped` 时，必须同时传入 `trackingNo`
- 改为 `completed` 时可继续保留原有物流单号
- 订单返回字段包含 `trackingNo / paymentLink / shippedAt / completedAt / items[] / totalAmount`

### 订单导出与排队

- `POST /api/admin/orders/export` 合并导出，`POST /api/admin/orders/export-by-sheet` 分 Sheet 导出；`GET /api/admin/orders/:orderId/invoice` 导出订单详情 PI。列表页面未勾选时导出本页可见订单，已勾选时导出已选订单；列表请求显式传逗号分隔的 `orderIds`，空页不发起导出。接口兼容性上，缺失或空的 `orderIds` 不代表空集合，不应以此请求空页。
- 页面对上述三个订单导出每次新建一个 UUID，通过 `X-Export-Ticket` 发送；同一任务轮询必须复用该 UUID，且账号、会话、方法、路径和查询参数须保持一致。不带票据的兼容请求不进入此队列。排队按可执行账号先来先服务，同账号已有运行任务不会阻塞其他账号；最多 10 个等待票据，票据最长等待 120 秒，20 秒未轮询会过期。
- 未获执行名额时返回 HTTP 429 `export_queued`，JSON 含 `ticketId`、从 1 开始的 `position` 和 `retryAfter`，响应头 `Retry-After: 5`。页面显示位置，按该间隔轮询，最多等待 120 秒；兼容旧的 429 `export_capacity` / `export_in_progress`。队列满、票据失效或已开始/结束等其他错误不会自动重放。
- 同账号同时运行上限为 1。代码的全局并发默认值为 1（`SECURITY_EXPORT_GLOBAL_CONCURRENT`）；全局 2 是候选部署配置，不代表现网已调整。采用 2 时需同时配置协调连接池 `DB_COORDINATION_POOL_MAX=3`，并结合部署内存配置评估承载能力。实际获准的导出默认每账号 5 次/分钟（`SECURITY_LIMIT_EXPORT`），排队/准入请求另按每账号 30 次/分钟（`SECURITY_LIMIT_EXPORT_POLL`）限流，排队轮询不扣实际导出额度。
- 工作簿生成在独立子进程中执行，默认 90 秒（`ORDER_EXPORT_TIMEOUT_SECONDS`）；超时终止子进程并返回 HTTP 504 `export_timeout`。页面对每次请求及其完整文件读取另设 120 秒上限，与排队等待预算分开；请求或下载超时后提示先确认状态，不自动重放网络错误、503、504、普通限流或其他非排队错误。
- 携带票据的导出成功返回 JSON `{ticketId,status:"ready",statusUrl,downloadUrl,filename,expiresAt}`，不在生成请求中传输文件；页面再用独立 GET 下载，每阶段单独计时。不带票据的旧调用仍直接返回工作簿。生成超时配置只允许缩短，上限为 90 秒。
- `GET /api/admin/orders/export-results/:ticket` 查询本人当前登录会话的结果，状态包括 `waiting/started/ready/failed/expired`；`GET /api/admin/orders/export-results/:ticket/download` 下载已生成文件。结果保留 30 分钟，到期禁止下载，并在后续导出/结果访问时清理文件。状态和下载走普通读取额度，不占生成名额；重复下载不重新生成、不重复记录仓库打单。每次重查会话、模块权限、角色与订单归属；其他账号/会话返回 404。
- 生成响应丢失时页面保留“检查上次导出状态”；文件下载中断时保留“重新下载上次文件”。两个操作只读取原票据，不自动重新提交生成。图片读取失败返回 HTTP 502 `export_image_unavailable`，整次导出失败，不以缺图文件记为成功打单。
- 商品图继续最长边 640px、附件 1600px、JPEG 质量参数 94（透明图 PNG），本轮不降低画质。私有磁盘缓存跨请求/进程复用原图与转换图，同源下载合并；源的现有版本或本地文件修改时间变化会重新读取。无版本公网地址和旧对象短缓存默认 300 秒，版本化来源默认 24 小时，总容量默认 512MiB；缓存命中仍执行当次来源授权。`ORDER_EXPORT_IMAGE_CACHE_DIR`、`ORDER_EXPORT_RESULT_DIR` 应使用仅后台服务可读写的持久目录，排除构建产物和公开静态目录；测试按 `*_test` 数据库隔离。缓存容量/版本化 TTL 可通过 `ORDER_EXPORT_IMAGE_CACHE_MAX_BYTES` / `ORDER_EXPORT_IMAGE_CACHE_TTL_SECONDS` 配置，短源 TTL 配置 `ORDER_EXPORT_IMAGE_CACHE_SOURCE_TTL_SECONDS` 上限 300 秒。
- 每个生成任务默认 2 路图片读取（`ORDER_EXPORT_IMAGE_WORKERS`，允许 1–4），与全局生成任务并发独立。同图合并读取；单图超时最多重试一次，所有尝试共享 25 秒图片预算，重试重新校验 DNS、固定公网 IP 与 TLS。证书、权限、404 和无效图片不重试。个别图片失败后仍尝试缓存其余已授权图片，但最终整次导出失败，不输出缺图工作簿；父进程 90 秒硬期限始终有效。
- 对严格匹配的公开、无签名 Cloudinary `/image/upload/v<版本>/<图片ID>` 原图，先按用途请求商品 640px / 附件 1600px 的 `c_limit` 导出图，再下载与缓存，避免先传输多MB原图。保留原扩展名，不设置质量/格式转换；等比、不裁剪、不放大（[Cloudinary limit 说明](https://cloudinary.com/documentation/transformation_reference#c_limit)）。原 URL 当次授权与来源校验仍先执行，派生 URL 同样校验；私有、签名、已有转换参数、非 Cloudinary 或不匹配的地址仍沿原路径。数据库、商城及对外素材接口的原图地址不改。缓存自然键包含实际请求地址，640/1600用途不混用。

## 10. 共享客户模板

- `GET /api/admin/orders/templates?page=1&pageSize=25&keyword=...`：分页搜索（25/50/100）。
- `GET /api/admin/orders/templates/:id`：读取最新资料。
- `POST /api/admin/orders/templates`：创建，格式为 `{name, profile}`。
- `PUT /api/admin/orders/templates/:id`：更新，格式为 `{name, profile, version}`。
- `DELETE /api/admin/orders/templates/:id`：删除，必须提交 `{version}`。
- `POST /api/admin/orders/templates/attachments`：multipart `files` 上传一个 PDF，最大 32 MB，检查文件头。

需要 `orders` 模块权限，且角色为管理员或外贸。两者共享全部模板，仓库及客户角色不开放。
模板版本冲突返回 409，缺失版本或无效资料返回 400；修改及删除记录到订单模块操作日志。

`profile` 仅包含 `userId`、`contactName`、`phone`、`country`、`contactValue`、`address`、
`apartment`、`city`、`state`、`zip`、`note`、`labelImageUrls`（最多 9 张图片）、`labelPdfUrl`（一个 PDF）。
模板名称及有效商城账号必填，其余资料可提前分次保存，正式下单继续执行原有必填校验。
备注最大 5000 字符，其余文本最大 500 字符，附件 URL 最大 2048 字符。
商品、数量、价格、运费、付款链接、物流、状态、订单版本和幂等编号不进入模板。

模板在订单管理页“客户模板”独立维护，也可在新增订单中“保存当前资料为模板”。
选择模板读取最新版本，再将客户资料、备注和附件复制入订单草稿；覆盖已填写资料前确认。
订单保存的是独立快照，后续修改/删除模板不修改历史订单或删除上传文件；模板操作不扣/退库存。

## 图片上传大小标准

- `POST /api/admin/uploads` 的商品、订单、合同图片统一在存储前优化到 **≤1,000,000 bytes（十进制1MB）**，Cloudinary、本地及私有存储使用同一规则。原件输入安全上限不改，历史大图读取上限不改；PDF不属于此图片大小标准。
- 已≤1MB保留原字节。大照片先尝试JPEG质量92/90和完整色度，仍超限再等比缩小，不裁剪、不放大；商品长边最低640px，订单/合同最低为原长边与1600px中的较小值。透明图保留alpha，动画保留帧、时长与循环；达细节底线仍超限则报错，不写超限文件。
- 输出格式可能变化，返回URL、文件后缀、MIME、存储大小及现有完整性字段均以最终字节为准。服务端优化减少保存及后续下载体积，不代表客户端上传原件流量已经减少。
- 历史资源需另行有备份、可恢复地处理；上传规则不会自动覆盖已存原件或改写既有业务引用。
停用或已删除商城账号的模板仍可管理，但新建订单禁止套用，需重新选择有效客户。
模板新增表的迁移可重复执行，不调整现有订单和库存；本功能仅涉及后台，商城 API 不暴露模板。
