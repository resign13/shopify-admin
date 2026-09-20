"""Order packing exports: one color SKU per row, paired sizes across columns."""
from io import BytesIO
import re
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
from openpyxl.utils import get_column_letter

SIZES = ['28/S', '30/M', '32/L', '34/XL', '36/2XL']
ALIASES = {alias: label for label, aliases in zip(SIZES, [
    ['28', 'S'], ['30', 'M'], ['32', 'L'], ['34', 'XL'], ['36', '2XL', 'XXL']
]) for alias in aliases}


def size_label(value):
    raw = str(value or '').strip() or '未标注尺码'
    normalized = raw.upper().replace(' ', '')
    if normalized in ALIASES:
        return ALIASES[normalized]
    parts = normalized.split('/')
    matches = {ALIASES.get(part) for part in parts}
    # Only map unambiguous paired labels; never silently lose special sizes.
    if len(matches) == 1 and None not in matches:
        return matches.pop()
    return raw


def group_items(items):
    groups = {}
    for item in items:
        identity = item.get('productId') or item.get('sku') or item.get('productName')
        key = (identity, item.get('sku'), item.get('colorName'))
        group = groups.setdefault(key, {'sku': item.get('sku') or item.get('productName') or '--',
            'color': item.get('colorName') or '', 'image': item.get('image') or '', 'sizes': {}})
        if not group['image']:
            group['image'] = item.get('image') or ''
        label = size_label(item.get('sizeCode'))
        group['sizes'][label] = group['sizes'].get(label, 0) + int(item.get('quantity') or 0)
    return list(groups.values())


def text_cell(ws, row, col, value):
    cell = ws.cell(row, col, str(value or ''))
    cell.data_type = 's'  # SKU, notes and account text must not become Excel formulas.
    cell.alignment = Alignment(vertical='center', wrap_text=True)
    return cell


def add_attachment_strip(ws, row, images):
    """Place full-resolution images side by side without changing table columns."""
    from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    from openpyxl.utils.units import pixels_to_EMU
    left = 0
    max_height = 0
    for image in images:
        # Keep the embedded pixels; only scale the Excel display dimensions.
        scale = min(1, 320 / image.width, 400 / image.height)
        image.width *= scale
        image.height *= scale
        column, offset = 0, left
        while True:
            letter = get_column_letter(column + 1)
            dimension = ws.column_dimensions.get(letter)
            width = (dimension.width if dimension else ws.sheet_format.defaultColWidth or 8.43)
            pixels = max(1, int(width * 7 + 5))
            if offset < pixels:
                break
            offset -= pixels
            column += 1
        image.anchor = OneCellAnchor(
            _from=AnchorMarker(col=column, colOff=pixels_to_EMU(offset), row=row - 1),
            ext=XDRPositiveSize2D(pixels_to_EMU(image.width), pixels_to_EMU(image.height)))
        ws.add_image(image)
        left += image.width + 20
        max_height = max(max_height, image.height)
    if images:
        ws.row_dimensions[row].height = max_height * 0.75 + 12
    return row + (1 if images else 0)


def build(orders, *, split=False, include_images=True, fetch_image, make_image, attachments, fetch_attachment=None):
    book = Workbook()
    book.remove(book.active)
    shared = None if split else book.create_sheet('Orders')
    cursor = 1
    image_cache = {}
    cache_bytes = 0
    def image_bytes(url, attachment=False):
        nonlocal cache_bytes
        key = (url, attachment)
        if key not in image_cache:
            data = (fetch_attachment if attachment and fetch_attachment else fetch_image)(url)
            if cache_bytes + len(data or b'') > 32 * 1024 * 1024:
                return data
            image_cache[key] = data
            cache_bytes += len(data or b'')
        return image_cache[key]
    for index, order in enumerate(orders, 1):
        name = re.sub(r'[\[\]:*?/\\]', '_', str(order.get('orderNo') or f'Order {index}'))[:31]
        ws = book.create_sheet(name) if split else shared
        start = 1 if split else cursor
        rows = group_items(order.get('items') or [])
        labels = SIZES + list(dict.fromkeys(label for row in rows for label in row['sizes'] if label not in SIZES))
        end_col = 3 + len(labels)
        # All blocks on the combined sheet share the same dimensions.
        ws.column_dimensions['A'].width = 29
        ws.column_dimensions['B'].width = 19
        for col in range(3, end_col + 1):
            ws.column_dimensions[get_column_letter(col)].width = 13
        ws.sheet_view.showGridLines = False

        def full_line(row, value, height=28):
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_col)
            text_cell(ws, row, 1, value)
            lines = sum(max(1, (len(part) + 69) // 70) for part in str(value).splitlines())
            ws.row_dimensions[row].height = min(409, max(height, lines * 18))

        full_line(start, f"订单：{order.get('orderNo', '')}    业务员：{order.get('userName', '')}")
        ws.cell(start, 1).font = Font(bold=True, size=14)
        full_line(start + 1, f"联系人：{order.get('contactName', '')}    电话：{order.get('phone', '')}    邮箱：{order.get('userEmail', '')}", 34)
        full_line(start + 2, '收货地址：' + str(order.get('shippingAddress') or ''), 42)
        header = start + 4
        for col, label in enumerate(['型号 / 颜色 SKU', '图片', *labels, '合计 pcs'], 1):
            cell = text_cell(ws, header, col, label)
            cell.fill = PatternFill('solid', fgColor='FFF36A')
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.row_dimensions[header].height = 30
        row_no = header + 1
        side = Side(style='thin', color='D1D5DB')
        border = Border(left=side, right=side, top=side, bottom=side)
        for item in rows:
            text_cell(ws, row_no, 1, str(item['sku']) + ('\n' + item['color'] if item['color'] else ''))
            for col, label in enumerate(labels, 3):
                ws.cell(row_no, col, item['sizes'].get(label))
            ws.cell(row_no, end_col, sum(item['sizes'].values()))
            for cell in ws[row_no][:end_col]:
                cell.border = border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            ws.row_dimensions[row_no].height = 88 if include_images else 36
            if include_images and item['image']:
                data = image_bytes(item['image'])
                image = make_image(data, width=110, height=104) if data else None
                if image:
                    ws.add_image(image, f'B{row_no}')
            row_no += 1
        text_cell(ws, row_no, 1, '总件数')
        for col, label in enumerate(labels, 3):
            ws.cell(row_no, col, sum(item['sizes'].get(label, 0) for item in rows))
        ws.cell(row_no, end_col, sum(sum(item['sizes'].values()) for item in rows))
        for cell in ws[row_no][:end_col]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill('solid', fgColor='F1F5F9')
        image_urls, file_urls = attachments(order)
        full_line(row_no + 2, '备注：' + str(order.get('note') or ''), 48)
        urls = file_urls
        if urls:
            full_line(row_no + 3, '附件：' + '\n'.join(urls), min(180, 24 * len(urls) + 24))
        cursor = row_no + 5
        if include_images:
            attachment_images = []
            for url in image_urls:
                data = image_bytes(url, attachment=True)
                image = make_image(data, width=480, height=480, pixels=1600) if data else None
                if image:
                    attachment_images.append(image)
            cursor = add_attachment_strip(ws, cursor, attachment_images)
        cursor += 2
        ws.freeze_panes = 'A6'
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
    if not book.worksheets:
        book.create_sheet('Orders')
    if not orders:
        book.active['A1'] = '暂无订单'
    out = BytesIO()
    book.save(out)
    out.seek(0)
    return out
