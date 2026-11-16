# 订单取消审批与草稿 PI 导出

## 状态与审批

- 待付款、部分配货可互相调整并直接取消。已配货及之后保留向前跳转，但禁止回退；发货仍须物流单号。
- 已配货、已付款、已发货、已完成通过取消申请处理。申请不改变业务状态、金额或库存。
- 待审冻结状态、完整资料编辑、发货、删除及重复申请。账号关联导致的历史订单归属回填也执行冻结检查。查看和导出不受影响。
- 申请人可以撤回。驳回须填写意见；撤回、驳回不改变订单或库存，支持重新申请，各次申请单独保留。
- 审批通过在同一事务内完成订单取消、库存返还和审计。订单锁、申请版本和待审唯一索引保证并发审批或撤回仅成功一次；等待人工审核时不持有数据库锁。
- 已取消订单只可恢复至取消前状态，恢复沿用现有扣库存逻辑。历史订单仅从可靠的取消操作日志一次性补齐来源；缺少来源的订单使用“再来一单”。

## 权限和入口

`orders.cancel.approve` 是订单管理下的独立操作勾选项，不是导航模块；同时需要订单模块权限。

- 已有订单模块权限的管理员一次性默认获得审批权限；后续人工撤销不会因重复迁移而重新获得。其他岗位按需授权。
- 审批人可以查看公司申请，可以明确审批自己的申请。普通订单的业务员范围、仓库金额隐藏不变。
- 后台列表右上角的“取消审批”包含待审计数、待审核和已处理；订单详情显示紧凑提示、撤回入口和申请记录。
- 商城客户只操作本人订单及本人提交的申请。商城 UI 使用英文；返回值不含后台身份信息，也不显示后台发起申请的内部原因/意见。客户自己的申请显示审批进度与驳回意见。

接口：

| 接口 | 作用 |
|---|---|
| `GET/POST /api/admin/orders/{id}/cancellation-requests` | 订单范围内的历史/提交申请 |
| `GET /api/admin/orders/cancellation-requests?state=pending\|processed&page=1` | 有审批权的公司列表 |
| `GET /api/admin/orders/cancellation-requests/{id}` | 公司申请详情，保留仓库脱敏 |
| `POST /api/admin/orders/cancellation-requests/{id}/approve\|reject\|withdraw` | 显式决定，提交申请版本；驳回必填 `reviewNote` |
| `POST /api/store/orders/{id}/cancellation-requests` | 客户提交必填 `reason` |
| `POST /api/store/orders/cancellation-requests/{id}/withdraw` | 客户按申请版本撤回 |

## 草稿详情导出

`GET /api/admin/orders/drafts/{id}/invoice?version={revision}`

- “我的草稿”列表及已保存的草稿编辑页使用相同导出控制器；未保存改动时禁用并提示先保存。
- 只读取服务器的指定已保存版本。至少一行正数量即可，缺少客户、地址可留空，运费允许为零；正式订单 PI 的正运费校验不变。
- 沿用 PI 模板、图片、备注、附件布局；标题、编号及文件名标识草稿/非正式订单，不分配正式单号。
- 使用保存的报价、数量、币种和汇率；现有 USD PI 对历史 CNY 草稿按其保存汇率换算，不读取当前售价或当前汇率。
- 待核对、已删除/停用商品或失效尺码的保存明细继续导出并标记，包含保存商品名称，不静默遗漏。
- 复用现有导出排队、最长 90 秒生成时限、结果恢复和会话权限校验；结果单独绑定草稿 ID/版本，正式订单 ID 列表为空。
- 生成后用短事务锁定并复核草稿版本。更新、删除或转正式后，旧结果下载返回冲突并提示重新导出。不生成订单、不占库存、不写仓库打单记录。

## 数据与以后发布

新增 `order_cancellation_requests`、`order_cancellation_migrations`、`orders.cancelled_from_status`；导出队列表新增 `result_draft_id` 和 `result_draft_revision`，版本升级为 `order-export-queue-v3`。

后台和商城的 `order_cancel_policy.py` 保持一致。两个仓库应成套发布；本次仅本地开发验收，未发布。

正式发布前需使用既有迁移入口执行迁移，并用后台仓库既有 `scripts/provision-db-roles.py`、现有数据库角色及其凭据应用增量权限。商城仅获得申请表读取、限定字段插入及撤回更新权限，不获得审批字段、内部审计表或后台账号表权限。后台和商城运行时只执行只读 schema readiness 检查。不要只更新前端或只更新其中一个旧取消接口。

## 本地验收

自动化仅运行于独立 `*_test` 数据库，包括真实数据库运行时角色及浏览器回归。手动项目统一使用 `127.0.0.1:55439/lumiere_admin` 同步库和原有真实账号；不得将 seed 或自动化夹具写入该镜像库，更不向远程生产写测试记录。

新增测试：`test_order_cancellation_approval.py`、`test_draft_invoice.py`；现有导出子进程图片集成测试也包含 `draft_invoice`。对应浏览器脚本为 `verify-cancellation-approval-browser.js`、`verify-draft-invoice-browser.js`；商城配套脚本在商城仓库。实现没有增加多级会签、通知、退款或退货物流流程。
