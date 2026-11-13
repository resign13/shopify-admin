"""Offline old/new exports using downloaded real images; no DB or network access."""
import argparse
import ast
from contextlib import ExitStack
from io import BytesIO
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat


ROOT = Path(__file__).resolve().parents[1]
BASE = 'ed87573849ad4447c22de098ed05274b4070ca82'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('APP_ENV') != 'test' or os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
        raise SystemExit('Explicit isolated *_test environment required; database will not be accessed')
    samples, output = args.samples.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((samples / 'manifest.json').read_text(encoding='utf-8'))
    product, = list(samples.glob('product.*'))
    sys.path.insert(0, str(ROOT / 'admin-backend'))
    import db
    with patch.object(db, 'ensure_database_ready'):
        import app
    import export_image_cache
    import order_matrix_export

    original = subprocess.check_output(['git', 'show', BASE + ':admin-backend/app.py'], cwd=ROOT).decode('utf-8')
    tree = ast.parse(original)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'build_excel_image')
    namespace = dict(app.__dict__)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<accepted-image-baseline>', 'exec'), namespace)
    baseline_image = namespace['build_excel_image']

    def old_image(raw, *, note=False, **options):
        return baseline_image(raw, **options)

    def source(url, attachment):
        path = (samples / url.rsplit('/', 1)[-1]).resolve()
        if path.parent != samples or not path.is_file():
            raise ValueError('Image is outside the chosen sample directory')
        return {'legacy_channel': 'admin', 'legacy_path': str(path)}

    orders = [{'orderNo': f'LOCAL-SAMPLE-{i+1:02}', 'shippingFee': 0, 'currency': 'USD',
               'note': 'Local image-quality acceptance; real attachment, no business write',
               'labelImageUrls': ['https://fixture.invalid/' + item['file']],
               'items': [{'sku': 'PRODUCT-UNCHANGED', 'image': 'https://fixture.invalid/' + product.name,
                          'sizeCode': 'M', 'quantity': 1, 'unitPrice': 20}]}
              for i, item in enumerate(manifest)]
    app.app.logger.disabled = True
    runs, workbooks = {}, {}
    with patch.object(app, '_export_image_source', side_effect=source), \
         patch.dict(app.media.uploads, {'admin': samples}), \
         patch('safe_images.fetch_image', side_effect=AssertionError('Offline acceptance must not use the network')):
        for name in ('before', 'after'):
            cold, warm = [], []
            for repetition in range(3):
                with TemporaryDirectory(prefix='note-image-benchmark-') as folder, ExitStack() as stack:
                    stack.enter_context(patch.dict(os.environ, {'ORDER_EXPORT_IMAGE_CACHE_DIR': folder}))
                    if name == 'before':
                        stack.enter_context(patch.object(app, 'build_excel_image', old_image))
                        stack.enter_context(patch.object(app, 'NOTE_PIXELS', 1600))
                        stack.enter_context(patch.object(order_matrix_export, 'NOTE_PIXELS', 1600))
                    for hot, times in ((False, cold), (True, warm)):
                        start = perf_counter()
                        with app.app.test_request_context('/'):
                            book = app.build_orders_export(orders).getvalue()
                        times.append((perf_counter() - start) * 1000)
                        if repetition == 0 and not hot:
                            workbooks[name] = book
                            (output / (name + '.xlsx')).write_bytes(book)
                    export_image_cache._configured.cache_clear()
            runs[name] = {'coldLocalMsMedian': round(statistics.median(cold), 1),
                          'warmLocalMsMedian': round(statistics.median(warm), 1),
                          'xlsxBytes': len(workbooks[name]), 'trials': 3}

    def entries(raw):
        with ZipFile(BytesIO(raw)) as archive:
            return [archive.read(path) for path in archive.namelist() if path.startswith('xl/media/')]

    old, new = entries(workbooks['before']), entries(workbooks['after'])
    assert len(old) == len(new) == len(manifest) * 2
    assert all(old[i] == new[i] for i in range(0, len(old), 2)), 'Product thumbnails changed'
    rows = []
    for i, item in enumerate(manifest):
        source_bytes = (samples / item['file']).read_bytes()
        before, after = old[i * 2 + 1], new[i * 2 + 1]
        with Image.open(BytesIO(source_bytes)) as original_picture:
            original_picture = ImageOps.exif_transpose(original_picture).convert('RGB')
        pictures = []
        row = {'sample': item['index'], 'sourceSize': [item['width'], item['height']], 'sourceFormat': item['format'],
               'sourceBytes': len(source_bytes), 'pngExactBytesPreserved': item['format'] == 'PNG' and after == source_bytes}
        for name, raw in [('before', before), ('after', after)]:
            with Image.open(BytesIO(raw)) as picture:
                row[name] = {'format': picture.format, 'size': list(picture.size), 'bytes': len(raw)}
                decoded = picture.convert('RGB')
            aligned = decoded.resize(original_picture.size, Image.Resampling.LANCZOS)
            delta = ImageStat.Stat(ImageChops.difference(original_picture, aligned))
            row[name]['meanAbsoluteRgbError'] = round(sum(delta.mean) / 3, 3)
            pictures.append(aligned)
        width, height = original_picture.size
        crop_width, crop_height = min(500, width), min(340, height)
        x, y = max(0, (width-crop_width)//2), max(0, (height-crop_height)//2)
        box = (x, y, x+crop_width, y+crop_height)
        crops = [pic.crop(box).resize((crop_width*2, crop_height*2), Image.Resampling.NEAREST)
                 for pic in [original_picture, *pictures]]
        panel = Image.new('RGB', (crop_width*6 + 40, crop_height*2 + 48), '#eef2f6')
        draw = ImageDraw.Draw(panel)
        for col, (label, crop) in enumerate(zip(('SOURCE / 2x', 'BEFORE / 2x', 'AFTER / 2x'), crops)):
            draw.text((col*(crop_width*2+20)+8, 12), label, fill='#16243a')
            panel.paste(crop, (col*(crop_width*2+20), 40))
        panel.save(output / f"sample-{item['index']:02}-2x.png")
        rows.append(row)

    report = {'baselineCommit': BASE, 'afterWorkingTree': True, 'afterBranch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
              'databaseAccess': False, 'networkAccess': False, 'businessWrites': False,
              'realImages': len(manifest), 'orderCount': len(orders), 'productThumbnailsByteIdentical': True,
              'timingMeaning': 'Local file read + image cache + XLSX build; excludes Internet, queue wait and download',
              'runs': runs, 'images': rows}
    (output / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>备注图片导出本地验收</title>',
             '<style>body{font:15px system-ui;margin:32px;background:#f5f7fb;color:#20324b}article{background:white;padding:20px;margin:20px 0;border-radius:12px}img{max-width:100%;height:auto}a{color:#2457c9}table{border-collapse:collapse}td,th{padding:10px 18px;border-bottom:1px solid #dde4ed}</style>',
             '<h1>备注图片导出 · 同图前后对比</h1><p>真实备注图片；中间为原导出，右侧为新导出。裁剪位置一致，按原图像素放大两倍。</p>',
             '<p>仅本地验收，未部署，未改写业务数据。耗时为本机离线生成，不包含网络、排队和下载。</p>',
             '<p><a href="before.xlsx">修改前 Excel</a> · <a href="after.xlsx">修改后 Excel</a></p>',
             '<table><tr><th>版本</th><th>Excel KB</th><th>冷缓存 ms（3 次中位数）</th><th>热缓存 ms（3 次中位数）</th></tr>']
    for name in ('before', 'after'):
        run = runs[name]
        lines.append(f'<tr><td>{name}</td><td>{run["xlsxBytes"]/1024:.1f}</td><td>{run["coldLocalMsMedian"]}</td><td>{run["warmLocalMsMedian"]}</td></tr>')
    lines.append('</table><p>商品缩略图：修改前后嵌入字节完全一致。</p>')
    for row in rows:
        before, after = row['before'], row['after']
        lines.append(f'<article><h2>样图 {row["sample"]} · {row["sourceFormat"]} {row["sourceSize"]}</h2><p>嵌入尺寸 {before["size"]} → {after["size"]}；体积 {before["bytes"]/1024:.1f} → {after["bytes"]/1024:.1f} KB；PNG 原字节保留：{row["pngExactBytesPreserved"]}</p><img loading="lazy" src="sample-{row["sample"]:02}-2x.png"></article>')
    (output / 'index.html').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'passed': True, 'realImages': len(manifest), 'runs': runs, 'productThumbnailsByteIdentical': True,
                      'pngPreserved': sum(row['pngExactBytesPreserved'] for row in rows),
                      'highResolution': [row for row in rows if max(row['sourceSize']) > 1600]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
