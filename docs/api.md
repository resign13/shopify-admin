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
