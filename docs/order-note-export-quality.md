# 订单备注图片导出

本地优化范围：合并订单 Excel、分订单 Excel 和 PI 的备注附件。商品小图和原始上传文件不变，不改变导出排队、权限及超时规则。

## 编码规则

- 备注附件长边上限由 1600 提至 2400 像素；只缩小，不放大原图。
- 方向正常、长边不超过 2400、文件不超过 1 MB 的 PNG 直接嵌入原始字节，不转 JPEG、不重复编码。符合相同条件的 JPEG 也直接复用。
- 需要缩小或校正方向的 PNG 仍保存为 PNG，保留透明通道；超过 1 MB 的旧 PNG 进行无损重压缩，无尺寸变化时不使用比原图更大的重压缩结果。
- 其他需要处理的不透明照片使用 JPEG quality=90、4:4:4；透明图片仍为 PNG。
- 商品小图仍为长边 640、JPEG quality=94 / 原有透明 PNG 逻辑，旧缓存身份保持不变。
- 备注使用独立版本的编码缓存身份，避免误用旧 JPEG 结果；继续复用已有跨进程缓存。
- Excel 中的备注显示大小不变（最大 320×400），提升的是嵌入像素，方便放大查看。
- 仅改写原有受支持的公开 Cloudinary 原图尺寸参数；私有、签名及已有变换的地址继续按既有规则处理。

## 真实图片本地对比

`scripts/compare-order-note-image-quality.py` 使用预先下载的真实备注图片和一张真实商品图，离线生成修改前后的 Excel、逐图同位置 2 倍放大对比和 JSON 指标。修改前编码函数来自脚本内注明的基线提交，不模拟线上网络提速。

```powershell
$env:APP_ENV = 'test'
$env:PGHOST = '127.0.0.1'
$env:PGPORT = '55439'
$env:PGDATABASE = 'note_export_quality_comparison_test'
$env:DB_SCHEMA_AUTO_MIGRATE = '0'
D:/Programs/Python314/python.exe D:/dulizhan/worktrees/order-note-export-quality/scripts/compare-order-note-image-quality.py --samples D:/dulizhan/output/order-note-image-quality-20261113/samples --output D:/dulizhan/output/order-note-image-quality-20261113/comparison
```

该脚本不读写数据库，禁止联网；仅在显式 `*_test` 环境运行。冷/热缓存耗时包含本地读取、图片处理和 Excel 生成，不含网络、排队和下载。自动比较商品小图嵌入字节，确保完全不变。真实样图和生成文件仅保存在本机输出目录，不提交仓库。

回归覆盖：PNG 原字节保留、透明及调色板图片、方向校正、旧大 PNG 无损压缩、照片尺寸与编码、商品小图不变、跨请求缓存和三种订单导出格式。
