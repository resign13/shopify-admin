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
停用或已删除商城账号的模板仍可管理，但新建订单禁止套用，需重新选择有效客户。
模板新增表的迁移可重复执行，不调整现有订单和库存；本功能仅涉及后台，商城 API 不暴露模板。
