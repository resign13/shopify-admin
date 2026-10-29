"""Chinese user-facing feedback at the admin HTTP boundary.

The shared security, image, and inventory modules also serve other channels.
Keep their messages and protocols intact and translate only admin responses.
"""
from __future__ import annotations

import re

from flask import request


MESSAGES = {
    # Authentication, request validation, and security middleware.
    'ok': '操作成功',
    'Forbidden': '没有执行此操作的权限',
    'Forbidden.': '没有执行此操作的权限',
    'Not found': '请求的内容不存在',
    'Not found.': '请求的内容不存在',
    'Invalid request': '请求内容无效',
    'Invalid request.': '请求内容无效',
    'Request failed.': '请求失败，请重试',
    'Please sign in again.': '登录已失效，请重新登录',
    'Invalid email or password': '邮箱或密码错误',
    'Invalid account or password.': '账号或密码错误',
    'Too many sign-in attempts. Try again later.': '登录尝试过于频繁，请稍后重试',
    'Too many requests. Try again later.': '请求过于频繁，请稍后重试',
    'Too many reports.': '报告提交过于频繁，请稍后重试',
    'Report is too large.': '报告内容过大',
    'Search text must be 200 characters or fewer.': '搜索内容不能超过 200 个字符',
    'Request is too large.': '请求内容过大',
    'A JSON object is required.': '请求内容必须为 JSON 对象',
    'The signed-in account changed. Reload this page.': '登录账号已改变，请刷新页面',
    'Reload this page before trying again.': '请刷新页面后重试',
    'Use HTTPS.': '请使用 HTTPS 访问',
    'Use at least 12 characters and avoid common passwords.': '密码至少需要 12 个字符，且不能使用常见密码',
    'requestId 必须为 UUID': '请求编号必须为 UUID',
    'eventIds 最多包含 100 个有效事件编号': '事件编号列表最多包含 100 个有效编号',
    'The service is temporarily unavailable. Try again later.': '服务暂时不可用，请稍后重试',
    'The service is busy. Please try again later.': '服务繁忙，请稍后重试',
    # Export, upload, and image validation.
    'Export is queued.': '导出正在排队，请稍后重试',
    'Export service is busy. Try again shortly.': '导出服务繁忙，请稍后重试',
    'Another export is in progress. Try again later.': '已有导出任务正在进行，请稍后重试',
    'Please enter shipping fee before exporting PI': '导出 PI 前请填写运费',
    'Invalid invoice data': 'PI 数据无效，请检查后重试',
    'Unsupported warehouse export type': '不支持此仓库导出类型',
    'Select one PDF file': '请选择一个 PDF 文件',
    'Invalid file count': '文件数量不符合要求',
    'Empty file': '文件为空',
    'Only supported images and PDF files are allowed': '仅支持上传指定格式的图片和 PDF 文件',
    'Attachment size exceeds the limit': '附件大小超过限制',
    'File content is invalid or unsupported': '文件内容无效或格式不受支持',
    'Attachment access denied': '无权访问此附件',
    'Unregistered private attachment': '私有附件未登记，请重新上传',
    'Attachment is not owned or accessible; upload it again': '附件不属于当前账号或无权访问，请重新上传',
    'A private attachment cannot be published as a product image': '私有附件不能发布为商品图片',
    'Invalid legacy upload key': '历史上传文件标识无效',
    'Invalid legacy upload path': '历史上传文件路径无效',
    'Invalid legacy upload': '历史上传文件无效',
    'Legacy upload exceeds size limit': '历史上传文件超过大小限制',
    'Invalid storage key': '文件存储标识无效',
    'Attachment size mismatch': '附件大小与记录不一致',
    'Attachment integrity mismatch': '附件完整性校验失败',
    'Invalid historical office document': '历史办公文档无效',
    'Invalid PDF content': 'PDF 文件内容无效',
    'Encrypted or oversized PDF is not supported': '不支持加密或超过大小限制的 PDF 文件',
    'PDF structure is too complex': 'PDF 文件结构过于复杂',
    'Active PDF content is not supported': '不支持包含活动内容的 PDF 文件',
    'Image origin is not allowed': '图片来源不在允许范围内',
    'Image destination is not public': '图片地址无法公开访问',
    'Invalid image size': '图片大小无效',
    'Image dimensions are too large': '图片尺寸过大',
    'Image content does not match its extension': '图片内容与文件扩展名不匹配',
    'Too many image redirects': '图片地址重定向次数过多',
    'Image retrieval failed': '图片读取失败',
    'Image is too large': '图片文件过大',
    'Unsupported image width': '不支持此图片宽度',
    'Image exceeds processing limits': '图片超出处理限制',
    'Image storage temporarily unavailable': '图片存储服务暂时不可用，请稍后重试',
    # Admin CRUD feedback.
    'Inventory updated': '库存已更新',
    'Product not found': '商品不存在',
    'Product created': '商品已创建',
    'Product updated': '商品已更新',
    'Product deleted': '商品已删除',
    'Product slug already exists': '商品链接标识已存在',
    'Product SKU already exists': '商品 SKU 已存在',
    'Product code already exists': '商品编码已存在',
    'Product has related orders, so it was hidden instead of deleted': '商品存在关联订单，已隐藏而非删除',
    'Category key already exists': '分类标识已存在',
    'Category created': '分类已创建',
    'Category updated': '分类已更新',
    'Category deleted': '分类已删除',
    'Category not found': '分类不存在',
    'Category has related products and cannot be deleted': '分类存在关联商品，不能删除',
    'Banner created': '横幅已创建',
    'Banner updated': '横幅已更新',
    'Banner deleted': '横幅已删除',
    'Banner not found': '横幅不存在',
    'Store account email already exists': '商城账号邮箱已存在',
    'Store account created': '商城账号已创建',
    'Store account updated': '商城账号已更新',
    'Store account deleted': '商城账号已删除',
    'Store account not found': '商城账号不存在',
    'Store account has related orders and cannot be deleted': '商城账号存在关联订单，不能删除',
    'Admin account email already exists': '后台账号邮箱已存在',
    'Admin account created': '后台账号已创建',
    'Admin account updated': '后台账号已更新',
    'Admin account deleted': '后台账号已删除',
    'Admin account not found': '后台账号不存在',
    'At least one active administrator is required': '至少需要保留一个启用的管理员',
    'You cannot disable the current signed-in admin': '不能停用当前登录的管理员账号',
    'You cannot delete the current signed-in admin': '不能删除当前登录的管理员账号',
    'Order not found': '订单不存在',
    'Order updated': '订单已更新',
    'Orders deleted': '订单已删除',
    'Invalid role': '角色无效',
    'Invalid status': '状态无效',
    'Missing status': '请填写状态',
    'Missing trackingNo': '请填写物流单号',
    'Missing orderIds': '请选择订单',
    'orderIds must be a list': '订单编号必须为列表',
    'Invalid event filter': '事件筛选条件无效',
    'Invalid categoryKey': '分类标识无效',
    'Missing sizeCode in sizePrices': '尺码价格中缺少尺码',
    'Product has no size inventory': '商品没有尺码库存',
    'contractPendingBySize must be an object': '各尺码合同未送数量必须为对象',
    'pendingInboundBySize must be an object': '各尺码合格数量必须为对象',
    'Display categories cannot exceed 5': '展示分类不能超过 5 个',
    'Admin frontend build not found': '后台页面构建文件不存在',
}

FIELDS = {
    'name': '名称', 'email': '邮箱', 'password': '密码', 'role': '角色',
    'categoryKey': '分类', 'category': '分类', 'key': '分类标识',
    'title': '标题', 'subtitle': '副标题', 'ctaLabel': '按钮文字',
    'labels': '分类名称', 'sortOrder': '排序', 'image': '图片',
    'sizeChartImage': '尺码表图片', 'descriptionImage': '详情图片',
    'sizes': '尺码', 'sizeCode': '尺码', 'sizePrices': '尺码价格',
    'sizeStocks': '尺码库存', 'variants': '颜色款式', 'imageUrls': '图片',
    'productCode': '商品编码', 'slug': '商品链接标识', 'sku': 'SKU',
    'familyCode': '款号', 'colorGroup': '颜色组', 'colorName': '颜色名称',
    'colorHex': '颜色代码', 'color': '颜色', 'stock': '库存',
    'contractPending': '合同未送', 'pendingInbound': '合格',
    'pendingInspection': '待验货', 'temporaryInbound': '临时待入库',
    'heroBanners': '首页横幅', 'sectionProductIds': '首页分区商品',
    'collectionProductIds': '合集商品', 'displayCategoryKeys': '展示分类',
    'contactName': '收货人', 'phone': '联系电话', 'country': '国家',
    'contactValue': '联系方式', 'address': '收货地址', 'apartment': '地址补充',
    'city': '城市', 'state': '州或省', 'zip': '邮政编码', 'note': '备注',
}

SECTIONS = {'bestSeller': '畅销', 'newArrival': '新品', 'specialPrice': '特价'}
_CHINESE = re.compile(r'[\u3400-\u9fff]')
_VARIANT_FIELD = re.compile(r'variants\[(\d+)\]\.(\w+)')
_CUSTOMER_FIELD = re.compile(r'(' + '|'.join(re.escape(k) for k in (
    'contactName', 'phone', 'country', 'contactValue', 'address', 'apartment', 'city', 'state', 'zip', 'note'
)) + r')格式或长度无效')
_PREVIEW_ONLINE_FIELD = re.compile(
    r'(.+：)(stock|contractPending|pendingInbound|pendingInspection|temporaryInbound)( 已在线上变更)',
    re.DOTALL,
)


def field_label(field: str) -> str:
    """Render known validation field paths without losing their indexes or values."""
    match = _VARIANT_FIELD.fullmatch(field)
    if match:
        index, name = match.groups()
        return f'颜色款式 variants[{index}] 的{FIELDS.get(name, name)}'
    head, dot, tail = field.partition('.')
    label = FIELDS.get(head, head)
    if dot and tail in ('zh', 'en'):
        return ('中文' if tail == 'zh' else '英文') + label
    if dot:
        return f'{label}（{SECTIONS.get(tail, tail)}）'
    return label


def translate_message(message: str, *, is_error: bool = False) -> str:
    """Translate a user-facing message; never inspect arbitrary business values."""
    if not message:
        return message
    if message in MESSAGES:
        return MESSAGES[message]

    match = _CUSTOMER_FIELD.fullmatch(message)
    if match:
        return FIELDS[match[1]] + '格式或长度无效'
    match = _PREVIEW_ONLINE_FIELD.fullmatch(message)
    if match:
        return match[1] + FIELDS[match[2]] + match[3]

    for prefix, template in (
        ('Missing field: ', '请填写：{}'),
        ('Invalid field: ', '字段无效：{}'),
    ):
        if message.startswith(prefix):
            fields = [field_label(value.strip()) for value in message[len(prefix):].split(',')]
            return template.format('、'.join(fields))

    dynamic = (
        (r'Invalid sizePrices row at index (.+)', '尺码价格第 {} 行无效'),
        (r'Invalid variant at index (.+)', '颜色款式第 {} 项无效'),
        (r'Product slug already exists: (.+)', '商品链接标识已存在：{}'),
        (r'Product SKU already exists: (.+)', '商品 SKU 已存在：{}'),
        (r'Product code already exists: (.+)', '商品编码已存在：{}'),
        (r'Invalid size price for (.+)', '尺码 {} 的价格无效'),
        (r'Duplicate sizeCode: (.+)', '尺码重复：{}'),
        (r'Unknown sizes: (.+)', '以下尺码不存在：{}'),
        (r'Product or size not found: (.+)', '商品或尺码不存在：{}'),
        (r'Inventory conflict for (.+)', '库存发生冲突：{}'),
        (r'Contract pending conflict for (.+)', '合同未送数量发生冲突：{}'),
        (r'Cannot remove sizes with contract pending quantities: (.+)', '存在合同未送数量的尺码不能删除：{}'),
        (r'Invalid contract pending for (.+)', '尺码 {} 的合同未送数量无效'),
        (r'Invalid pending inbound for (.+)', '尺码 {} 的合格数量无效'),
        (r'Category not found: (.+)', '分类不存在：{}'),
    )
    for pattern, template in dynamic:
        match = re.fullmatch(pattern, message, flags=re.DOTALL)
        if match:
            return template.format(match[1])

    match = re.fullmatch(r'Identity changed for (.+): (.+)', message, flags=re.DOTALL)
    if match:
        labels = '、'.join(field_label(value.strip()) for value in match[2].split(','))
        return f'商品或尺码身份信息已变化：{match[1]}；变化字段：{labels}'
    match = re.fullmatch(r'size stock for (.+?)(必须是整数|超出允许范围)', message, flags=re.DOTALL)
    if match:
        return f'尺码 {match[1]} 的库存{match[2]}'
    match = re.fullmatch(r'Invalid ([\u3400-\u9fff]+)', message)
    if match:
        return match[1] + '无效'
    match = re.fullmatch(r'(bestSeller|newArrival|specialPrice) home products cannot exceed 5', message)
    if match:
        return f'{SECTIONS[match[1]]}首页商品不能超过 5 个'
    match = re.fullmatch(r'(Invalid product id|Product not found|Invalid collection product id|Collection product not found) for (bestSeller|newArrival|specialPrice)', message)
    if match:
        reason = {'Invalid product id': '商品编号无效', 'Product not found': '商品不存在',
                  'Invalid collection product id': '合集商品编号无效', 'Collection product not found': '合集商品不存在'}[match[1]]
        return f'{SECTIONS[match[2]]}：{reason}'

    if _CHINESE.search(message):
        return message
    return '请求未完成，请检查后重试' if is_error else '操作成功'


def _feedback_items(value):
    """Translate direct error/warning text and message nodes, not row data."""
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                item = translate_message(item, is_error=True)
            elif isinstance(item, dict) and isinstance(item.get('message'), str):
                item = {**item, 'message': translate_message(item['message'], is_error=True)}
            result.append(item)
        return result
    return value


def _admin_path(path: str) -> bool:
    return (path == '/api/admin' or path.startswith('/api/admin/')
            or path.startswith('/api/auth/admin/')
            or path in {'/api/auth/me', '/api/auth/logout', '/api/auth/csrf'}
            or path.startswith(('/api/attachments/', '/api/security/', '/uploads/', '/media/products/'))
            or (not path.startswith('/api/') and request.endpoint in {
                'serve_admin_index', 'serve_admin_spa', 'serve_admin_assets', 'serve_admin_favicon'
            }))


def register(app):
    # Register before Security.after: Flask invokes after_request handlers in
    # reverse registration order, so this sees its final 5xx response as well.
    @app.after_request
    def localize_admin_feedback(response):
        if not _admin_path(request.path) or not response.is_json:
            return response
        data = response.get_json(silent=True)
        if not isinstance(data, dict):
            return response
        localized = dict(data)
        message = data.get('message')
        if isinstance(message, str):
            if response.status_code >= 500 and message not in MESSAGES and not (
                data.get('code') == 'export_image_unavailable' and message == '图片读取失败，请重试导出。'
                or data.get('code') == 'export_timeout' and message == '导出超时，请减少订单数量后重试。'
            ):
                localized['message'] = '服务暂时不可用，请稍后重试'
            else:
                export_failed = (request.path.startswith('/api/admin/orders/export-results/')
                                 and data.get('status') in {'failed', 'expired'})
                localized['message'] = translate_message(message, is_error=response.status_code >= 400 or export_failed)
        for key in ('errors', 'warnings'):
            if key in data:
                localized[key] = _feedback_items(data[key])
        if request.path == '/api/admin/finance/costs/import/preview' and isinstance(data.get('rows'), list):
            rows = []
            for row in data['rows']:
                if isinstance(row, dict) and isinstance(row.get('message'), str):
                    row = {**row, 'message': translate_message(row['message'], is_error=row.get('status') == 'error')}
                rows.append(row)
            localized['rows'] = rows
        if localized != data:
            response.set_data(app.json.dumps(localized))
        return response
