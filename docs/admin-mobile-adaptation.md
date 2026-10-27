# 后台移动端适配与本地验收

本地分支：`feature/admin-mobile-adaptation`。本次只修改后台前端及浏览器验收脚本。PR 按用户授权准备，维护时间另行确认；未部署。

## 展示与状态

- `<768px`：抽屉导航、手机卡片列表、可展开筛选、全屏弹层、底部操作和安全区域。
- `768–1023px`：抽屉导航与紧凑内容；`>=1024px`：保留桌面侧栏及表格。
- `AdaptiveTable` 复用已有列插槽、权限条件和操作事件，单次只挂载手机或桌面展示。选择、展开和排序状态在切换布局时保留。
- `DataTable` 支持可选 `mobile-card` 插槽。订单使用摘要卡片，其余列表保留原字段与操作。
- 订单与选品继续独立展示真实尺码。手机输入文字 16px，主要操作区域 44px；库存登记保留全部六个阶段。
- 导航、订单、商品、库存、财务、合同、预售、分类、账号、日志和 API 对接共用现有接口与权限。
- `useDirty` 在离开路由及同组件路由变更时使用已有未保存确认；关闭表单和浏览器离开继续沿用原确认。
- 手机“更多”包含次要操作，保存/创建保持可见。下载期间保留原输入，PI 增加重复触发拦截；下载 Blob 延迟释放，给移动浏览器留出接收时间。
- 语音提醒保持单实例，移动入口只控制显示。图表支持点击查看提示。

## 已执行的本地验收（2026-10-23）

开发前已通过既有脚本完成线上只读快照同步、53 张表校验与本地切换，保留原本地备份。手动预览仍使用 `127.0.0.1:55439/lumiere_admin`；以下自动化写入分别使用 `gingtto_admin_mobile_test`、`gingtto_admin_mobile_finance_test`、`gingtto_admin_mobile_voice_test`。

| 验收 | 结果 |
|---|---|
| 前端生产构建 | 通过 |
| 前端现有业务/通知单元测试 | 113 项通过 |
| 13 个页面 × 7 种宽度（360/390/430/768/1024/1440/1920） | 91 次通过，无整体横向溢出或未捕获运行错误 |
| 新增、改单、已发货/已完成修改、报价与库存差额 | 通过，保存后的实际数据与预期一致 |
| 选品、跨页暂存、覆盖/清零、零数量显式加入、混合尺码、草稿恢复 | 通过 |
| 返单、附件继承、目录报价冲突、来源订单不变 | 通过 |
| 六阶段库存登记、批量入库、库存 Excel 下载 | 通过 |
| 财务首次补算/后续时间节点、历史、清空、完整报表导出 | 通过 |
| 成本 Excel 导入、留空/相同/零值、版本冲突、丢失响应重试 | 通过，错误时整批不保存 |
| 商品保存、合同创建与 Excel、预售配置、账号创建 | 通过 |
| 上传失败保留输入并重试、请求失败保留列表、返回取消保留草稿 | 通过 |
| 布局切换保持选择、无额外业务查询、缩短视口后保存按钮可达 | 通过 |
| API Key 一次性展示及关闭清理、接口说明手机布局 | 通过 |
| 语音主动开启、多标签页接管、断线补播、退出清理 | 通过，隔离夹具前台提醒延迟约 5.1 秒 |
| WebKit 手机视口、横屏、仓库金额隐藏、业务员归属隔离 | 通过 |
| WebKit 财务查看、Excel 下载、成本保存 | 通过 |

浏览器验收使用 Chromium 与 WebKit；手机软键盘采用缩短视口验证。未连接实体 iPhone/安卓设备，实机软键盘、安全区域和实际扬声器听感尚未验证。

## 可复用检查

沿用项目的受保护 `order-selection-browser-fixture.py`（5360）、`finance-browser-fixture.py`（5362）及 `voice-browser-fixture.py`（5358）。启动前必须显式设置本机 PostgreSQL 和独立 `*_test` 库，测试脚本不会指向手动同步库。

使用已安装 Playwright CLI 登录夹具后执行：

```powershell
npx --no-install --package @playwright/cli playwright-cli -s=admin-mobile run-code --filename scripts/verify-admin-mobile-layout-browser.js
npx --no-install --package @playwright/cli playwright-cli -s=admin-mobile run-code --filename scripts/verify-admin-mobile-business-browser.js
npx --no-install --package @playwright/cli playwright-cli -s=admin-mobile run-code --filename scripts/verify-admin-mobile-modules-browser.js
npx --no-install --package @playwright/cli playwright-cli -s=admin-mobile run-code --filename scripts/verify-admin-mobile-navigation-browser.js
```

业务检查应从新建隔离夹具开始。现有订单选品、独立尺码、改单、返单、财务和语音浏览器检查也已回归；涉及手机表格行的旧断言已适配卡片结构。

本机结果汇总：`D:/dulizhan/output/admin-mobile-acceptance.json`。实际截图保存在 `D:/dulizhan/output/playwright/admin-mobile-*-final.png`，使用隔离验收数据。

## iPhone 16 视觉调整（2026-10-23）

- 以 393 × 852 CSS 像素为设计基准，调整手机字体、16px 页边距、圆角、背景、数据层级和触控操作。桌面保留原表格及操作入口。
- 手机顶部改为品牌和导航、提醒、账号入口；页面保留大标题。经营工作台使用主指标和次级指标分层，款号高级筛选与统计说明可展开。
- 订单主操作保留新增，客户模板、草稿和导出收入“更多”；表格批量操作收入“列表操作”。选择、排序、分页和业务事件不变。
- 库存首屏保留关键汇总，全部库存阶段可展开；六阶段登记仍完整保留。财务将汇率和 Excel 工具放入可展开工具区。
- 既有只读同步成功，校验 53 张表并保留备份。此次自动化仅使用独立 `gingtto_iphone16_ui_test`，本地手动页面仍连接同步库。
- 构建通过、115 项前端单元测试通过；13 页面 × 6 宽度共 78 次检查通过。覆盖“更多”中的订单导出、缩放后选择保留且不重复查询、选品/数量/未保存确认、库存概览与批量入口、六阶段输入、成本导出及导入入口。
- WebKit iPhone 16 设备模拟下经营、订单、库存、财务均无整体横向溢出（393px 宽、DPR 3，浏览器可用视口 659px 高）。这是浏览器模拟，未使用实体 iPhone。
- 结果：`D:/dulizhan/output/iphone16-ui-acceptance.json`；截图：`D:/dulizhan/output/playwright/iphone16-{dashboard,orders,inventory,finance}.png`。

境内直连入口沿用 `https://office.gingtto.store` 的 HTTPS 443，无需新增手机专用端口。现有配置记录显示它与原后台共用应用；本次仅只读确认登录页 200，未修改线上入口、服务或发布代码。发布范围和维护时间待用户确认。

手动本地入口：`http://127.0.0.1:5010`。该服务从当前工作目录读取已构建前端，继续使用同步库真实账号；本次未重启线上或改动商城。

## 继续构建与主分支兼容（2026-10-26）

- 已合入最新主分支的商品尺码表和 PDF 图片读取修复，移动版不回退已上线功能。未修改这些功能的后台业务逻辑、数据库结构或依赖版本。
- 日期范围控件修复桌面最小宽度及 table-cell 布局残留；手机双月历上下排列、内部滚动，日期单元触控区域至少 44px，支持跨月选择。
- 紧凑屏幕及横屏抽屉使用实际可视高度，底部创建操作保持可达。
- 新增商品尺码表手机卡片、筛选及更多操作；维护表单单列，尺寸对照表只在内部横向滚动，预览单位切换及未保存退出继续共用原逻辑。
- 增加可移植 `scripts/admin-mobile-browser-fixture.py` 和登录脚本，拒绝非 `*_test` 数据库；已将手机布局及交互检查接入 PR CI。发布作业仍排除 pull_request 事件。
- 开发前既有只读同步成功，56 张表核对通过并保留原本地备份；自动化仅写 `gingtto_admin_mobile_continue_test`。手动服务保持本机同步库，并已加载当前分支代码与构建。

本轮结果：生产构建通过、117 项前端单元测试通过；14 页面 × 6 宽度（360/393/430/768/1024/1440）共 84 次布局检查通过。订单导出、选品、零数量加入、数量保留、库存六阶段、成本导出等关键交互通过。Chromium 与 WebKit iPhone 16 模拟均验证完整月历、跨月选择、横屏订单操作、汇率输入保留、尺码表编辑/预览和未保存确认。未使用实体手机。

本轮结果汇总：`D:/dulizhan/output/admin-mobile-continue-acceptance-20261026.json`；实际截图：`D:/dulizhan/output/playwright/mobile-20261026-{dashboard,orders,inventory,finance}.png`。

重复执行：先以显式本机 PostgreSQL 和独立 `*_test` 环境启动 `python scripts/admin-mobile-browser-fixture.py`，再用 Playwright CLI 在 5380 登录并运行 `verify-admin-mobile-iphone16-browser.js` 和 `verify-admin-mobile-interactions-browser.js`。手动同步库入口仍为 `http://127.0.0.1:5010`，使用真实账号，首次进入需重新登录。
