# 商品尺码表（独立 PC 模块）

## 使用与边界

入口：商品与库存 → 商品尺码表（`/size-charts`）。按现有启用商品的标准款号汇总，每款一份；所有颜色的真实尺码精确去重，按商品及尺码配置顺序排列。标题、材质、中英文测量维度和数值独立保存；代表图固定跟随商品首图，不提供更换入口，不修改商品、可售尺码、库存、价格、成本、商城图片或素材 API。

管理员的默认模块清单包含 `size-charts`；既有显式权限清单保持原样，需要在后台账号权限中勾选。其他后台部门可单独授权；商城客户无权限。

- 空白与零不同；数值非负，最多两位小数。
- 整款统一 cm 或 in，默认 cm。按 1 in = 2.54 cm 自动换算，四舍五入保留两位小数；空白和零保留。编辑中来回切换保留换算前精度，保存后以两位小数为准。旧版混合单位按原维度单位转换为 cm 展示，读取不写库；保存后统一持久化。新维度沿用整款单位，后端拒绝混合单位。
- 只读预览右上角提供 cm/in 按钮，切换只影响本次预览，不改变保存单位、版本或更新时间，也不触发未保存提示；每次从保存原值换算，不累计舍入误差。中英文切换保留本次预览单位，关闭重开恢复已保存单位。
- 英文预览及客户表只包含勾选维度；标题、材质与可见维度英文名称须填写英文内容。两份材质都空白时允许导出。
- 保存时检测商品尺码、资料版本；冲突保留页面输入，刷新需先确认放弃修改。
- 删除维度、商品移除尺码不删除此前测量记录；当前表和客户表不展示这些旧值。
- 时间由实际变更提交时确定，北京时间日期；相同数值导入不更新日期。

## Excel

维护表每款一个工作表，含代表图、日期、当前值及签名隐藏结构元数据。英文客户表只含客户可见英文信息，没有中文维护表、隐藏维度或导入元数据。

导入只处理文件中完整存在的款号工作表，覆盖数值，空白清空、零保留、相同跳过。删除整张款号表表示不处理该款；删除必要行列、调整尺码或维度结构、公式、无效值、重复工作表、版本变化均阻止整批确认。标题、材质、单位和结构在页面编辑，图片自动使用商品首图，Excel 不是这些资料的修改入口。

预览中的“导出当前版本”跟随预览单位；列表批量导出仍沿用各款已保存单位。换算后的维护表保留签名结构及导出单位，回导时只把修改的数值换算回已保存单位，不改变整款保存单位；未改的显示值保留原始精度，避免原样导入因两位小数舍入产生变化。导入差异表显示保存单位。英文客户表仍不支持回导。

上传先预览差异，取消无写入；确认重新核对版本，整批事务保存。一个请求编号只执行一次；请求结果不明时重试原确认，不重新生成提交编号。

资源上限：100 款/批、128 个真实尺码/款、64 个维度/款；10 MB 压缩文件、50 MB 解压内容。超出时明确拒绝，不截断。商品图片读取失败时提示重试，不输出缺图的成功文件。

## 后端

Cookie、CSRF、`size-charts` 模块权限和既有导出/上传配额沿用现有机制。

| 方法 | `/api/admin/size-charts` 下路径 | 用途 |
|---|---|---|
| GET | 空路径 | 列表；keyword/category/status/page/pageSize |
| GET | `/detail?styleCode=…` | 当前资料、真实尺码、数据及目录版本 |
| POST | `/save` | requestId + changes；原子保存 |
| POST | `/export` | styleCodes + mode（maintenance / english）；可选 unit（cm / in，仅影响导出） |
| POST | `/import/preview` | multipart file；差异与签名预览 |
| POST | `/import/confirm` | requestId + proposal + previewToken；原子覆盖 |

新增三张独立表：`product_size_charts`、`product_size_chart_audit`、`product_size_chart_receipts`。由 `size_charts.migrate` 注册到现有迁移链。审计记录修改人、前后值与请求编号；保存使用款号级锁和版本检查，关联商品读取使用共享锁。读取使用同一只读快照。

**本轮仅完成本地迁移与验收。生产迁移、运行角色授权、PR 和发布需另行安排。** 不沿用此前图片展示发布许可；不包含移动端或商品资料图片展示分支。

## 验收与复现

自动化只连接本机独立 `*_test` 库；`test_workbench` 及浏览器夹具在导入前检查数据库名和主机。不要对同步库运行 seed。

后端（设置本机测试库环境后）：

```powershell
python scripts/verify-security-regression.py --suite business --modules test_size_charts test_permissions test_finance_cost_excel test_product_weights
```

前端：`npm run build --prefix frontend`，以及现有 orderSelection、apiIntegration、finance、catalogOrder 的 Node 测试。

浏览器复现：
1. 构建前端；指定独立测试库后运行 `python scripts/size-charts-browser-fixture.py`，默认 5366 端口。
2. Playwright CLI 打开 `http://127.0.0.1:5366/login`，用夹具账号 `admin@gingtto.test` / `Workbench-Test-2026` 登录。只适用于夹具，绝不用于手动同步库。
3. 打开 `/size-charts`，点击 CS2211 的编辑；1920×1080 视口，在仓库根目录依次运行：
   - `playwright-cli run-code --filename=scripts/verify-size-charts-edit.js`
   - `python scripts/verify-size-charts-workbooks.py`
   - `playwright-cli run-code --filename=scripts/verify-size-charts-import.js`
   - `playwright-cli run-code --filename=scripts/verify-size-charts-boundaries.js`
4. 每步须返回成功结果而非仅判断 CLI 退出码。截图与下载位于 `output/playwright/`。

2026-10-23 本地结果：后端 48 项、前端 31 项通过；构建通过；浏览器完成保存、零值、英文隐藏、两类下载、导入差异、取消、清空、覆盖、旧版单位标签修改、自定义维度、未保存退出与旧模板阻止。下载的两份工作簿已校验内嵌图片、现值和元数据隔离；未以桌面 Microsoft Excel 做视觉验证。

人工入口：`http://127.0.0.1:5012/size-charts`，连接本机 `127.0.0.1:55439/lumiere_admin`，使用同步的真实账号；不创建替代账号、不重置密码。每日同步规则保持不变。

## 2026-10-23 展示调整

- 代表图固定采用当前款号商品首图；旧自选图片和客户端传入图片不改变该规则。列表、预览、保存与 Excel 一致。
- 全后台抽屉顶部标题不再可视展示；保留辅助技术名称、关闭按钮和原有未保存确认。页面主标题、字段标签和确认对话框标题不变。
- 订单号及已打单信息移入订单详情正文，继续可见。
- 此前本地图片失败原因：数据库已同步图片 URL，但本机 uploads 缺少对应原文件；本地服务没有 R2 凭证，回源返回 503。下述本地图片同步用于补齐文件，不改变线上图片配置。

## 本地商品图片

预览二次重设计：只读预览改为居中、随内容高度伸缩的窗口；商品首图和资料集中在顶部横向信息栏，尺寸矩阵独占下方全宽，取消左侧图片列和全屏高度留白。编辑仍使用原抽屉，英文预览共用新版信息栏；Excel 格式不变。1920px、1366px 下中英文预览、图片、两类下载及切回编辑验收通过。示例窗口高 631px，表格无容器溢出。截图：`D:/dulizhan/output/playwright/size-chart-preview-window-1366-en.png`。

`scripts/sync-local-product-images.py` 从明确指定的本机同步库只读取得商品图片地址，将公开图片下载到本机 uploads。已有有效文件跳过；保留 TLS 证书验证、下载上限及两路并发，不携带业务凭证。原 `/uploads/` 地址保持原路径，Cloudinary 原图使用本地文件映射；不改数据库里的 URL，不上传图片，也不改变每日数据库同步。

设置既有本机连接环境后运行（不要把密码写进命令或报告）：

```powershell
python scripts/sync-local-product-images.py --upload-dir D:/dulizhan/shopify-admin/admin-backend/uploads --report D:/dulizhan/output/local-product-images-sync.json --proxy-from-env
```

`--proxy-from-env` 只用于本机已有代理；没有代理时省略。同步后本地 `/uploads/` 缩略图直接读取文件。手动服务启动时显式调用 `scripts/local_product_image_cache.install(app)`，让 Excel 读取同一份本地原图，避免每次导出重新依赖外网。它只接受本机同步库或独立测试库，不接入生产启动链；图片映射更新后重启本地服务即可。手动启动器为 `D:/dulizhan/output/start-size-charts-manual.py`。

测试入口：`test_size_charts`、`test_api_image_probe`、`test_local_product_images`；自动化始终使用独立 `*_test` 库。真实商品图片的自动化验收仅复制公开商品资料与图片到测试库，不向本机同步库创建测试数据。

2026-10-23 图片修复验收：734 张原图下载并解码检查通过，347 个本地 `/uploads/` 缩略图地址全部返回有效图片；30 项相关回归通过。独立 `gingtto_size_chart_images_test` 库中，47 款真实商品首图的详情关联正确，中文与英文两份批量工作簿各含 47 张可解码图片，比例和锚点正确。浏览器实测 CS2209（本地 uploads）与 CS5103-BAOLAN（Cloudinary）的中英文预览及四次下载，另外验证 CS2209 编辑代表图和放大原图；四份浏览器下载文件均有有效内嵌图片。工作簿图片做了解码与位置核验，未使用桌面 Excel 渲染。截图与工作簿位于 `D:/dulizhan/output/playwright/size-charts-real-*`，批量工作簿位于 `D:/dulizhan/output/size-charts-real-images-*.xlsx`。本地手动服务继续运行于 5012；未部署。


## 统一单位与紧凑 Excel（本地）

导出改为顶部首图与商品资料，下方全宽测量表；统一边框、居中数值、紧凑行高，移除 END 标记，网格线继续显示、不冻结窗格。维护表为 v2 版式，仍支持结构和资料版本未变化的 v1 维护表；旧混合单位表须重新导出，避免错误覆盖。单位不在 Excel 内修改，两种导出均使用整款保存单位。

本轮验证：20 项后端测试、83 项前端工具测试和前端构建通过；隔离浏览器库完成保存、导入覆盖、清空、零值、旧表冲突、整款换算/取消、来回切换、中英文预览及四份 cm/in 下载。47 款真实图片在两份批量文件中均有效内嵌；已用工作簿渲染器检查中英文首图及排版（非桌面 Excel）。`verify-size-charts-units.js` 在 boundaries/preview 后执行，再运行 `verify-size-charts-unit-workbooks.py` 校验单位与换算值。所有自动化写入均限独立测试库；同步库原始混合单位数据仅在读取时转换，用户保存时才写入和记录审计。

## 2026-10-26 本地复验

- 执行既有只读线上同步，未改变同步脚本及每日配置；自动化写入仅使用 `gingtto_size_charts_20261026_test`、`gingtto_size_chart_images_20261026_test`。同步库尺码表、审计及回执行数未被测试改变。
- 45 项后端及 28 项相关前端测试通过，前端构建通过。补充 cm/in 各自的 Excel 覆盖、清空、零值、幂等与不变跳过，以及多款 Excel 错误／确认前冲突的整批不写入回归。
- 浏览器完成保存、导入取消及确认、自定义维度、未保存退出、旧模板阻止、单位切换确认／取消、往返精度、英文隐藏与四份 cm/in 文件下载。文件单位、换算值、网格线和无冻结窗格校验通过。
- 734 张本地原图检查通过，无缺失；47 款真实首图的中文维护表及英文客户表分别含 47 张有效内嵌图片。列表两页 48 张图片（含 1 张夹具图）加载成功。uploads 与 Cloudinary 两类商品的中英文预览及四份浏览器下载均正常。
- 1920px、1366px 预览布局无溢出；四份导出文件完成工作簿渲染检查，真实商品图清晰、比例正常。未使用桌面 Excel 做视觉验收。
- 手动入口继续为 `http://127.0.0.1:5012/size-charts`，连接本机同步库并使用原真实账号。本轮只增加回归测试与验收记录，保留既有修改，未创建 PR、未部署。

验收记录：`D:/dulizhan/output/size-charts-20261026-acceptance.json`。

### 预览单位切换补充验收

48 项相关后端测试、29 项前端测试及构建通过。浏览器验证预览独立切换、2.54 cm → 1.00 in、100.50 cm → 39.57 in、零值与空白、中英文同步、四份单位对应导出、关闭重开复位及 1920/1366px 排版。换算导出和预览均不修改保存记录；维护表原样回导无变化，修改、清空及零值按原保存单位处理。仅本地修改，未提交 PR、未部署。
