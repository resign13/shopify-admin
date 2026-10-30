"""Filtered style performance XLSX; shares the dashboard query and access scope."""
from datetime import datetime
from io import BytesIO

from flask import send_file
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import db
import safe_excel
import sales_ownership
import workbench


RISK_NAMES = {
    'backordered': '欠货', 'out_of_stock': '无库存', 'no_sales': '周转期无销量',
    'critical': '7 天内售罄', 'warning': '7–30 天售罄', 'healthy': '库存健康',
}
SORT_NAMES = {
    'units': '销量', 'amount': '商品金额', 'stock': '现货余额',
    'estimatedDays': '预计可售天数', 'lastSoldAt': '最近销售时间',
    'styleCode': '款号', 'velocityUnits': '周转期销量',
}
BASE_COLUMNS = [
    ('styleCode', '款号', 24, '@'), ('name', '商品名称', 48, '@'),
    ('units', '销量（件）', 16, '#,##0'),
    ('amount', '商品金额（USD，不含运费）', 24, '#,##0.00'),
    ('colorSkuCount', '颜色 SKU 数', 16, '#,##0'),
]
STOCK_COLUMNS = [
    ('stock', '现货余额', 16, '#,##0'), ('availableStock', '可用现货', 16, '#,##0'),
    ('shortageUnits', '欠货件数', 16, '#,##0'), ('shortageSizeCount', '欠货尺码数', 16, '#,##0'),
    ('contractPending', '合同未送', 16, '#,##0'), ('pendingInspection', '待验货', 16, '#,##0'),
    ('pendingInbound', '合格', 16, '#,##0'), ('defectivePending', '待打回次品', 16, '#,##0'),
    ('temporaryInbound', '临时待入库', 16, '#,##0'),
]
HEADER_ROW = 7


def _local_time(value):
    if not value:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.astimezone(workbench.SHANGHAI).replace(tzinfo=None)


def _days(item):
    if item['shortageUnits'] > 0:
        return '欠货待补'
    if item['availableStock'] <= 0:
        return '无库存'
    if not item['velocityUnits'] or item['estimatedDays'] is None:
        return '暂无销量'
    return item['estimatedDays']


def build_workbook(data, args, scope_label, category_label):
    personal = data.get('scope', {}).get('personal', False)
    columns = [*BASE_COLUMNS, *([] if personal else STOCK_COLUMNS),
               ('averageDailyUnits', '日均销量（件）', 18, '#,##0.00')]
    if not personal:
        columns += [('estimatedDays', '预计可售（天）', 18, '0.0'), ('risk', '库存状态', 20, '@')]
    columns += [('lastSoldAt', '最近销售时间（北京时间）', 27, 'yyyy-mm-dd hh:mm:ss')]
    book = Workbook()
    sheet = book.active
    sheet.title = '款号商品表现'
    sheet.sheet_view.showGridLines = False
    sales, velocity = data['salesWindow'], data['velocityWindow']
    sort = args.get('sort') or 'units'
    if personal and sort in {'stock', 'estimatedDays'}:
        sort = 'units'
    criteria = [f"关键词：{args.get('keyword') or '全部'}", f'分类：{category_label}',
                f"国家：{args.get('country') or '全部'}", f"款号：{args.get('style') or '全部'}"]
    if not personal:
        criteria.append(f"库存状态：{RISK_NAMES.get(args.get('risk'), '全部')}")
    criteria.append(f"排序：{SORT_NAMES.get(sort, '销量')} · {'从低到高' if args.get('direction') == 'asc' else '从高到低'}")
    notes = [
        '款号商品表现',
        f"销售日期：{sales['dateFrom']} 至 {sales['dateTo']}（北京时间）｜数据范围：{scope_label}",
        '；'.join(criteria),
        f"日均销量窗口：{velocity['dateFrom']} 至 {velocity['dateTo']}（{velocity['days']} 天）；与销量使用相同国家和业务员范围。",
        '排除已取消订单，金额不含运费，按订单保存汇率折合 USD。'
        + ('' if personal else '库存各阶段为当前余额；预计可售按未舍入日均销量计算，欠货或无销量时不估算。'),
        f"读取时间：{_local_time(data['updatedAt']):%Y-%m-%d %H:%M:%S}（北京时间）｜共 {data['total']} 个款号，导出全部筛选结果。",
    ]
    for row, text in enumerate(notes, 1):
        sheet.cell(row, 1, text)
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(columns))
        sheet.row_dimensions[row].height = 34 if row == 1 else 30
        sheet.cell(row, 1).font = Font(name='Microsoft YaHei', size=16 if row == 1 else 11,
                                      bold=row == 1, color='17324D' if row == 1 else '475569')
        sheet.cell(row, 1).alignment = Alignment(vertical='center', wrap_text=True)
    sheet.append([label for _, label, _, _ in columns])
    for item in data['items']:
        values = {**item, 'lastSoldAt': _local_time(item.get('lastSoldAt'))}
        if not personal:
            values.update(estimatedDays=_days(item), risk=RISK_NAMES[item['risk']])
        sheet.append([values.get(key) for key, _, _, _ in columns])
    last_data_row = sheet.max_row
    # Only additive metrics are totalled. Turnover and per-style SKU counts are not sums.
    summary = data['summary']
    sheet.append(['合计' if key == 'styleCode' else f"{data['total']} 个款号" if key == 'name'
                  else summary.get(key) for key, _, _, _ in columns])
    total_row = sheet.max_row
    for col, (key, _, width, number_format) in enumerate(columns, 1):
        sheet.column_dimensions[get_column_letter(col)].width = width
        for row in range(HEADER_ROW, total_row + 1):
            cell = sheet.cell(row, col)
            heading = row in {HEADER_ROW, total_row}
            cell.font = Font(name='Microsoft YaHei', size=11, bold=heading,
                             color='FFFFFF' if row == HEADER_ROW else '1E293B')
            cell.alignment = Alignment(vertical='center', wrap_text=True,
                                       horizontal='left' if key in {'styleCode', 'name', 'risk'} else 'right')
            if row > HEADER_ROW:
                cell.number_format = number_format
                if key == 'styleCode':
                    cell.data_type = 's'
            if row == HEADER_ROW:
                cell.fill = PatternFill('solid', fgColor='243850')
            elif row == total_row or row % 2 == 0:
                cell.fill = PatternFill('solid', fgColor='EFF6FF' if row == total_row else 'F8FAFC')
    for row in range(HEADER_ROW, total_row + 1):
        sheet.row_dimensions[row].height = 40 if row == HEADER_ROW else 42
    sheet.freeze_panes = f'C{HEADER_ROW + 1}'
    sheet.auto_filter.ref = f'A{HEADER_ROW}:{get_column_letter(len(columns))}{last_data_row}'
    sheet.print_title_rows = f'1:{HEADER_ROW}'
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    return safe_excel.prepare(book)


def export(args, user):
    # The route's existing snapshot_admin_call supplies one read-only MVCC snapshot.
    owner_id = sales_ownership.scope(args, user)
    scoped = {**args, '_ownerId': owner_id}
    data = sales_ownership.personalize(workbench.style_performance(scoped, paginate=False), owner_id)
    if owner_id is None:
        scope_label = '全公司'
    elif owner_id == 0:
        scope_label = '未分配订单'
    else:
        owner = db._fetch_one('SELECT name FROM admin_users WHERE id=%s', (owner_id,))
        scope_label = owner['name'] if owner else '本人数据'
    category = args.get('category')
    category_row = db._fetch_one('''SELECT COALESCE(t.label,c.category_key) AS label
        FROM product_categories c LEFT JOIN product_category_translations t
        ON t.category_id=c.id AND t.lang_code='zh' WHERE c.category_key=%s''', (category,)) if category and category != 'all' else None
    category_label = category_row['label'] if category_row else '全部' if category in (None, '', 'all') else category
    book = build_workbook(data, scoped, scope_label, category_label)
    out = BytesIO()
    book.save(out)
    book.close()
    out.seek(0)
    stamp = datetime.now(workbench.SHANGHAI).strftime('%Y%m%d-%H%M%S')
    return send_file(out, as_attachment=True, download_name=f'款号商品表现-{stamp}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
