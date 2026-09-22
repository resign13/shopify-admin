from __future__ import annotations

import module_permissions

import os
import re
import hashlib
import zipfile
from copy import copy
from concurrent.futures import ThreadPoolExecutor
import secrets
import sys
import mimetypes
from base64 import b64encode
from io import BytesIO
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib import error as urllib_error
from urllib import request as urllib_request

BASE_DIR = Path(__file__).resolve().parent
LOCAL_VENDOR_DIR = BASE_DIR / "_vendor"
if LOCAL_VENDOR_DIR.exists():
    sys.path.insert(0, str(LOCAL_VENDOR_DIR))

import inventory_policy

from flask import Flask, g, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter, column_index_from_string
from PIL import Image as PILImage
from psycopg.errors import ForeignKeyViolation
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

from db import (
    category_key_exists,
    count_active_admin_users,
    count_admin_users,
    count_orders,
    count_products,
    count_store_users,
    count_units_in_stock,
    create_admin_session,
    create_admin_user,
    create_banner,
    create_category,
    create_order,
    delete_orders,
    create_product,
    create_products_batch,
    create_store_user,
    delete_admin_session,
    delete_admin_sessions_for_user,
    delete_admin_user,
    delete_banner,
    delete_category,
    delete_product,
    delete_store_user,
    ensure_database_ready,
    get_admin_user_by_email,
    get_admin_user_by_id,
    get_category_by_id,
    get_admin_user_by_session_token,
    get_banner_by_id,
    get_homepage_config,
    get_order_by_id,
    get_product_by_id,
    get_product_by_slug,
    get_store_user_by_email,
    get_store_user_by_id,
    list_admin_users,
    list_banners,
    list_categories,
    list_category_labels,
    list_orders,
    list_products,
    list_store_users,
    product_code_exists,
    product_sku_exists,
    product_slug_exists,
    save_homepage_config,
    update_admin_user,
    update_banner,
    update_category,
    update_order_status,
    update_product,
    apply_inventory_import,
    update_product_inventory,
    update_store_user,
)

import workbench

app = Flask(__name__)
CORS(app)
UPLOAD_DIR = BASE_DIR / "uploads"
ADMIN_FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
mimetypes.add_type("image/webp", ".webp")

F = TypeVar("F", bound=Callable[..., Any])
SERVICE_TOKEN = os.environ.get("LUMIERE_SERVICE_TOKEN", "lumiere-service-token")
PASSWORD_HASH_METHOD = "pbkdf2:sha256:600000"
SUPPORTED_LANGS = {"zh", "en"}
DEFAULT_LANG = "zh"
ORDER_STATUSES = {"pending_payment", "allocated", "paid", "shipped", "completed", "cancelled"}
ORDER_STATUS_LABELS = {
    "pending_payment": "待付款",
    "allocated": "已配货",
    "paid": "已付款",
    "shipped": "已发货",
    "completed": "已完成",
    "cancelled": "已取消",
}


def parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def matches_time_range(value: str, range_key: str) -> bool:
    if range_key == "all":
        return True
    try:
        target = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.now(UTC)
    if range_key == "today":
        target_local = target.astimezone(UTC)
        return target_local.date() == now.date()
    if range_key == "yesterday":
        target_local = target.astimezone(UTC)
        return target_local.date() == (now.date()).fromordinal(now.date().toordinal() - 1)
    diff_days = (now - target.astimezone(UTC)).total_seconds() / 86400
    if range_key == "7d":
        return diff_days <= 7
    if range_key == "30d":
        return diff_days <= 30
    if range_key == "90d":
        return diff_days <= 90
    if range_key == "year":
        return target.astimezone(UTC).year == now.year
    return True


def filter_orders(
    orders: list[dict[str, Any]],
    *,
    time_range: str = "all",
    status: str = "all",
    category: str = "all",
    keyword: str = "",
) -> list[dict[str, Any]]:
    normalized_keyword = str(keyword or "").strip().lower()
    items: list[dict[str, Any]] = []
    for order in orders:
        status_match = status == "all" or order.get("status") == status
        time_match = matches_time_range(str(order.get("createdAt") or ""), time_range)
        category_match = category == "all" or any(
            str(item.get("categoryKey") or "") == category for item in (order.get("items") or [])
        )
        keyword_match = not normalized_keyword or normalized_keyword in " ".join(
            [
                str(order.get("orderNo") or "").lower(),
                str(order.get("userName") or "").lower(),
            ]
        )
        if status_match and time_match and category_match and keyword_match:
            items.append(order)
    return items


def _parse_dashboard_date(value: str) -> datetime.date | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _parse_dashboard_datetime(value: str) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None


def _dashboard_style_value(item: dict[str, Any]) -> str:
    raw = (
        item.get('productCode')
        or item.get('sku')
        or item.get('productName')
        or item.get('colorGroup')
        or item.get('familyCode')
        or ''
    )
    return re.sub(r'\s+', '', str(raw or '').strip())


def _dashboard_style_label(item: dict[str, Any]) -> str:
    return _dashboard_style_value(item)


def build_dashboard_order_filters(orders: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    style_map: dict[str, str] = {}
    countries: set[str] = set()
    for order in orders:
        country = str(order.get('country') or '').strip()
        if country:
            countries.add(country)
        for item in order.get('items') or []:
            value = _dashboard_style_value(item)
            label = _dashboard_style_label(item)
            if value and value not in style_map:
                style_map[value] = label
    return {
        'styles': [{'value': key, 'label': style_map[key]} for key in sorted(style_map, key=str.lower)],
        'countries': [{'value': key, 'label': key} for key in sorted(countries, key=str.lower)],
    }


def filter_dashboard_orders(orders: list[dict[str, Any]], *, style: str = 'all', country: str = 'all', date_from: str = '', date_to: str = '') -> list[dict[str, Any]]:
    style_value = str(style or 'all').strip()
    country_value = str(country or 'all').strip()
    start_date = _parse_dashboard_date(date_from)
    end_date = _parse_dashboard_date(date_to)
    filtered: list[dict[str, Any]] = []
    for order in orders:
        created_at = _parse_dashboard_datetime(str(order.get('createdAt') or ''))
        created_date = created_at.date() if created_at else None
        if start_date and created_date and created_date < start_date:
            continue
        if end_date and created_date and created_date > end_date:
            continue
        if country_value != 'all' and str(order.get('country') or '').strip() != country_value:
            continue
        if style_value != 'all' and not any(_dashboard_style_value(item) == style_value for item in (order.get('items') or [])):
            continue
        filtered.append(order)
    return filtered


def build_dashboard_style_summary(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for order in orders:
        order_styles: set[str] = set()
        for item in order.get('items') or []:
            style_code = _dashboard_style_value(item)
            if not style_code:
                continue
            entry = summary.setdefault(
                style_code,
                {
                    'style': style_code,
                    'label': style_code,
                    'quantity': 0,
                    'orderCount': 0,
                    'totalAmount': 0.0,
                },
            )
            quantity = int(item.get('quantity') or 0)
            entry['quantity'] += quantity
            entry['totalAmount'] += float(item.get('totalPrice') or 0)
            order_styles.add(style_code)
        for style_code in order_styles:
            summary[style_code]['orderCount'] += 1
    rows = list(summary.values())
    rows.sort(key=lambda item: (-int(item['quantity']), str(item['style']).lower()))
    for row in rows:
        row['totalAmount'] = round(float(row.get('totalAmount') or 0), 2)
    return rows


def _dashboard_trend_granularity(start_date: Any, end_date: Any) -> str:
    day_span = max(1, (end_date - start_date).days + 1)
    if day_span <= 120:
        return 'day'
    if day_span <= 730:
        return 'week'
    return 'month'


def _dashboard_bucket_start(value: Any, granularity: str) -> Any:
    if granularity == 'month':
        return value.replace(day=1)
    if granularity == 'week':
        return value - timedelta(days=value.weekday())
    return value


def _dashboard_next_bucket(value: Any, granularity: str) -> Any:
    if granularity == 'month':
        year = value.year + (1 if value.month == 12 else 0)
        month = 1 if value.month == 12 else value.month + 1
        return value.replace(year=year, month=month, day=1)
    if granularity == 'week':
        return value + timedelta(days=7)
    return value + timedelta(days=1)


def _dashboard_bucket_label(value: Any, granularity: str) -> str:
    if granularity == 'month':
        return value.strftime('%Y-%m')
    if granularity == 'week':
        week_end = value + timedelta(days=6)
        return f"{value.strftime('%Y-%m-%d')}~{week_end.strftime('%m-%d')}"
    return value.isoformat()


def build_dashboard_trend(orders: list[dict[str, Any]], *, date_from: str = '', date_to: str = '') -> dict[str, Any]:
    today = datetime.now(UTC).date()
    start_date = _parse_dashboard_date(date_from)
    end_date = _parse_dashboard_date(date_to)
    parsed_dates = [
        value.date()
        for value in (_parse_dashboard_datetime(str(order.get('createdAt') or '')) for order in orders)
        if value is not None
    ]
    if not end_date:
        end_date = max(parsed_dates) if parsed_dates else today
    if not start_date:
        start_date = min(parsed_dates) if parsed_dates else end_date - timedelta(days=29)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    granularity = _dashboard_trend_granularity(start_date, end_date)
    buckets: dict[str, dict[str, Any]] = {}
    cursor = _dashboard_bucket_start(start_date, granularity)
    while cursor <= end_date:
        key = cursor.isoformat()
        buckets[key] = {
            'date': _dashboard_bucket_label(cursor, granularity),
            'bucketStart': key,
            'orderCount': 0,
            'itemCount': 0,
            'totalAmount': 0.0,
        }
        cursor = _dashboard_next_bucket(cursor, granularity)

    total_orders = 0
    total_items = 0
    total_amount = 0.0
    for order in orders:
        created_at = _parse_dashboard_datetime(str(order.get('createdAt') or ''))
        if not created_at:
            continue
        bucket_start = _dashboard_bucket_start(created_at.date(), granularity)
        key = bucket_start.isoformat()
        if key not in buckets:
            continue
        item_count = int(order.get('itemCount') or 0)
        amount = float(order.get('totalAmount') or 0)
        buckets[key]['orderCount'] += 1
        buckets[key]['itemCount'] += item_count
        buckets[key]['totalAmount'] += amount
        total_orders += 1
        total_items += item_count
        total_amount += amount

    points = list(buckets.values())
    for point in points:
        point['totalAmount'] = round(float(point.get('totalAmount') or 0), 2)
    max_order_count = max((int(point['orderCount']) for point in points), default=0)
    return {
        'points': points,
        'granularity': granularity,
        'summary': {
            'orderCount': total_orders,
            'itemCount': total_items,
            'totalAmount': round(total_amount, 2),
            'dateFrom': start_date.isoformat(),
            'dateTo': end_date.isoformat(),
            'maxOrderCount': max_order_count,
        },
    }


def fetch_image_bytes(url: str, *, attachment: bool = False) -> bytes | None:
    from urllib.parse import urlsplit, unquote
    from flask import has_request_context
    from image_delivery import deliver_image, MAX_SOURCE_BYTES
    value = str(url or "").strip()
    if not value:
        return None
    cache_key = (value, 1600) if attachment else value
    cache = None
    if has_request_context():
        cache = g.setdefault('export_image_cache', {})
        if cache_key in cache:
            return cache[cache_key]
    result = None
    try:
        parsed = urlsplit(value)
        owned_hosts = {'img.smawell.shop', 'smawell.shop', 'admin.smawell.shop',
                       'gingtto.store', 'admin.gingtto.store', 'img.gingtto.store'}
        if parsed.path.startswith('/uploads/') and (not parsed.netloc or parsed.hostname in owned_hosts):
            # Read the same local/R2 cache as image delivery, without an HTTP
            # round trip through Cloudflare or another Gunicorn worker.
            with app.test_request_context('/uploads/export?w=' + ('1600' if attachment else '640')):
                response = deliver_image(UPLOAD_DIR, BASE_DIR / 'data' / 'image-cache',
                                         unquote(parsed.path[len('/uploads/'):]), app.logger)
                try:
                    if response.status_code == 200 and response.mimetype.startswith('image/'):
                        response.direct_passthrough = False
                        result = response.get_data()
                finally:
                    response.close()
        elif parsed.scheme in {'https', 'http'}:
            # Cache the original once across requests and quality variants.
            # URL hashes avoid persisting signed URLs or credentials in filenames.
            import time
            from filelock import FileLock
            from image_delivery import atomic_write, prune_cache, SOURCE_TTL
            cache_dir = BASE_DIR / 'data' / 'export-image-cache'
            cache_dir.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha256(value.encode()).hexdigest()
            source = cache_dir / (key + '.source')
            with FileLock(str(cache_dir / f'stripe-{int(key[:2], 16) % 64}.lock'), timeout=20):
                if source.exists() and time.time() - source.stat().st_mtime < SOURCE_TTL:
                    if source.stat().st_size <= MAX_SOURCE_BYTES:
                        result = source.read_bytes()
                else:
                    req = urllib_request.Request(value, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'image/*'})
                    with urllib_request.urlopen(req, timeout=10) as response:
                        if str(response.headers.get('Content-Type', '')).lower().startswith('image/'):
                            data = response.read(MAX_SOURCE_BYTES + 1)
                            if len(data) <= MAX_SOURCE_BYTES:
                                result = data
                                atomic_write(source, lambda output: output.write(data))
                    if result:
                        try:
                            prune_cache(cache_dir, {source})
                        except Exception:
                            app.logger.warning('Export image cache cleanup deferred')
    except Exception:
        app.logger.warning('Order export image retrieval failed')
    if cache is not None and sum(len(data) for data in cache.values() if data) + len(result or b'') <= MAX_SOURCE_BYTES:
        cache[cache_key] = result
    return result


def prefetch_export_images(orders: list[dict[str, Any]]) -> None:
    """Fetch each URL at the highest required quality, with bounded concurrency."""
    from flask import has_request_context
    if not has_request_context():
        return
    wanted = {}
    for order in orders:
        for item in order.get('items', []):
            if item.get('image'):
                wanted.setdefault(str(item['image']), False)
        for url in split_order_attachments(order)[0]:
            wanted[str(url)] = True
    cache = g.setdefault('export_image_cache', {})
    pending = [(url, attachment) for url, attachment in wanted.items()
               if ((url, 1600) if attachment else url) not in cache][:128]
    def read(pair):
        url, attachment = pair
        with app.test_request_context('/api/admin/orders/export'):
            return fetch_image_bytes(url, attachment=attachment)
    budget = sum(len(data) for data in cache.values() if data)
    with ThreadPoolExecutor(max_workers=6) as pool:
        for (url, attachment), data in zip(pending, pool.map(read, pending)):
            cost = len(data or b'') * (2 if attachment else 1)
            if budget + cost <= 32 * 1024 * 1024:
                cache[url] = data
                if attachment:
                    cache[(url, 1600)] = data
                budget += cost


def build_excel_image(image_bytes: bytes, *, width: int = 54, height: int = 70, pixels: int = 640) -> OpenpyxlImage | None:
    try:
        from PIL import ImageOps
        with PILImage.open(BytesIO(image_bytes)) as img:
            converted = ImageOps.exif_transpose(img).convert("RGBA")
            converted.thumbnail((pixels, pixels), PILImage.Resampling.LANCZOS)
            output = BytesIO()
            if converted.getextrema()[3][0] == 255:
                converted.convert("RGB").save(output, format="JPEG", quality=94, subsampling=0)
            else:
                converted.save(output, format="PNG")
            output.seek(0)
            excel_image = OpenpyxlImage(output)
            ratio = min(1, width / converted.width, height / converted.height)
            excel_image.width = converted.width * ratio
            excel_image.height = converted.height * ratio
            return excel_image
    except Exception:
        return None


def autosize_columns(worksheet: Any) -> None:
    widths: dict[int, int] = {}
    for row in worksheet.iter_rows():
        for cell in row:
            if cell.value in (None, ""):
                continue
            widths[cell.column] = max(widths.get(cell.column, 0), len(str(cell.value)))
    for column_index, width in widths.items():
        worksheet.column_dimensions[get_column_letter(column_index)].width = min(max(width + 2, 12), 42)


def set_fixed_column_widths(worksheet: Any, widths: dict[str, float]) -> None:
    for column, width in widths.items():
        worksheet.column_dimensions[str(column).upper()].width = float(width)


def estimate_text_row_height(
    value: Any,
    *,
    line_width: int = 28,
    min_height: float = 24.0,
    line_height: float = 18.0,
    max_height: float = 120.0,
) -> float:
    text = str(value or "").strip()
    if not text:
        return min_height

    visual_lines = 0
    for raw_line in text.splitlines() or [""]:
        line = raw_line.strip()
        if not line:
            visual_lines += 1
            continue
        visual_lines += max(1, (len(line) + line_width - 1) // line_width)

    return min(max_height, max(min_height, visual_lines * line_height))


def is_image_attachment(url: str) -> bool:
    value = str(url or "").strip().lower()
    return bool(re.search(r"\.(?:jpg|jpeg|png|webp|gif|avif|bmp)(?:$|[?#])", value))


def split_order_attachments(order: dict[str, Any]) -> tuple[list[str], list[str]]:
    raw = order.get("labelImageUrls") or ([order.get("labelPdfUrl")] if order.get("labelPdfUrl") else [])
    image_urls: list[str] = []
    file_urls: list[str] = []
    for item in raw:
        url = str(item or "").strip()
        if not url:
            continue
        if is_image_attachment(url):
            image_urls.append(url)
        else:
            file_urls.append(url)
    return image_urls[:9], file_urls[:5]


def build_orders_export(orders: list[dict[str, Any]], *, include_images: bool = True) -> BytesIO:
    from order_matrix_export import build
    if include_images:
        prefetch_export_images(orders)
    return build(orders, split=False, include_images=include_images,
                 fetch_image=fetch_image_bytes, make_image=build_excel_image,
                 attachments=split_order_attachments,
                 fetch_attachment=lambda url: fetch_image_bytes(url, attachment=True))


PROFORMA_TEMPLATE_PATH = Path(
    os.environ.get("PROFORMA_TEMPLATE_PATH", str(BASE_DIR / "data" / "proforma_invoice_template.xlsx"))
).expanduser()


def copy_row_style(worksheet: Any, source_row: int, target_row: int, max_col: int = 6) -> None:
    worksheet.row_dimensions[target_row].height = worksheet.row_dimensions[source_row].height
    for column in range(1, max_col + 1):
        source = worksheet.cell(source_row, column)
        target = worksheet.cell(target_row, column)
        if source.has_style:
            target._style = copy(source._style)
        target.font = copy(source.font)
        target.fill = copy(source.fill)
        target.border = copy(source.border)
        target.alignment = copy(source.alignment)
        target.number_format = source.number_format
        target.protection = copy(source.protection)


def prepare_invoice_item_row(worksheet: Any, row: int, *, source_row: int, max_col: int = 10) -> None:
    copy_row_style(worksheet, source_row, row, max_col=max_col)
    worksheet.row_dimensions[row].height = 44
    for column in range(1, max_col + 1):
        cell = worksheet.cell(row, column)
        cell.value = None
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    worksheet[f"A{row}"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    worksheet[f"B{row}"].alignment = Alignment(horizontal="center", vertical="center")


def insert_invoice_rows(worksheet: Any, insert_at: int, amount: int) -> None:
    """Unmerge before moving cells, then rebuild merges at their new positions.

    openpyxl.insert_rows moves cells but leaves merged range metadata unchanged.
    Unmerging afterwards can delete shifted content or raise KeyError.
    """
    if amount <= 0:
        return
    ranges = [copy(area) for area in worksheet.merged_cells.ranges if area.max_row >= insert_at]
    for area in ranges:
        worksheet.unmerge_cells(str(area))
    worksheet.insert_rows(insert_at, amount)
    for area in ranges:
        if area.min_row >= insert_at:
            area.shift(row_shift=amount)
        else:
            area.max_row += amount
        worksheet.merge_cells(str(area))


def normalize_order_shipping_fee(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_invoice_party_name(order: dict[str, Any]) -> str:
    return (
        str(order.get("companyName") or "").strip()
        or str(order.get("contactName") or "").strip()
        or str(order.get("userName") or "").strip()
        or "--"
    )


def build_invoice_email(order: dict[str, Any]) -> str:
    return str(order.get("contactValue") or "").strip() or str(order.get("userEmail") or "").strip()


def build_invoice_address(order: dict[str, Any]) -> str:
    explicit = str(order.get("shippingAddress") or "").strip()
    if explicit:
        return explicit
    parts = [
        str(order.get("address") or "").strip(),
        str(order.get("apartment") or "").strip(),
        str(order.get("city") or "").strip(),
        str(order.get("state") or "").strip(),
        str(order.get("zip") or "").strip(),
        str(order.get("country") or "").strip(),
    ]
    return ", ".join(part for part in parts if part)


def build_invoice_item_description(item: dict[str, Any]) -> str:
    sku = str(item.get("sku") or "").strip()
    return sku or "--"


INVOICE_SIZE_COLUMNS = {
    "28": "C",
    "S": "C",
    "30": "D",
    "M": "D",
    "32": "E",
    "L": "E",
    "34": "F",
    "XL": "F",
    "36": "G",
    "XXL": "G",
    "2XL": "G",
}


def normalize_invoice_size_code(value: Any) -> str:
    text = str(value or "").strip().upper().replace(" ", "")
    aliases = {
        "2XL": "XXL",
        "XXL": "XXL",
        "XXXL": "XXXL",
        "3XL": "XXXL",
    }
    return aliases.get(text, text)


def invoice_size_column(size_code: Any) -> str:
    raw_text = str(size_code or "").strip().upper().replace(" ", "")
    if not raw_text:
        return ""

    # Order items may store either the pure size (S / 28 / 2XL) or the display
    # label used by the template (28/S, S/28, 36/2XL, etc.). The PI template
    # already lists the size labels in C:G; item rows should only fill the
    # quantity under the matching label, never write the size text itself.
    candidates = [raw_text]
    candidates.extend(part for part in re.split(r"[^A-Z0-9]+", raw_text) if part)

    for candidate in candidates:
        normalized = normalize_invoice_size_code(candidate)
        column = INVOICE_SIZE_COLUMNS.get(normalized)
        if column:
            return column
    return ""


def build_invoice_line_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, float], dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        description = build_invoice_item_description(item)
        image = str(item.get("image") or "").strip()
        unit_price = float(item.get("unitPrice") or 0)
        key = (description, image, unit_price)
        row = grouped.setdefault(
            key,
            {
                "description": description,
                "image": image,
                "unitPrice": unit_price,
                "sizes": {},
                "quantity": 0,
            },
        )
        quantity = int(item.get("quantity") or 0)
        row["quantity"] += quantity
        column = invoice_size_column(item.get("sizeCode"))
        if column:
            row["sizes"][column] = int(row["sizes"].get(column, 0)) + quantity
    return list(grouped.values()) or [{"description": "--", "image": "", "unitPrice": 0, "sizes": {}, "quantity": 0}]


def safe_sheet_title(value: Any, fallback: str = "Sheet") -> str:
    text = str(value or "").strip() or fallback
    text = text.translate({ord(ch): "_" for ch in "[]:*?/\\"})
    return text[:31]


def build_orders_sheet_export(orders: list[dict[str, Any]], *, include_images: bool = True) -> BytesIO:
    from order_matrix_export import build
    if include_images:
        prefetch_export_images(orders)
    return build(orders, split=True, include_images=include_images,
                 fetch_image=fetch_image_bytes, make_image=build_excel_image,
                 attachments=split_order_attachments,
                 fetch_attachment=lambda url: fetch_image_bytes(url, attachment=True))


def reset_invoice_summary_merges(
    worksheet: Any,
    item_start_row: int,
    balance_row: int,
    shipping_row: int,
    total_row: int,
    deposit_row: int,
) -> None:
    # openpyxl does not reliably move every merged range when rows are inserted.
    # The PI template only needs merges in the summary/deposit rows below the
    # item table, so clear stale merges from the dynamic A:J block first. This
    # prevents old Shipping/Total merges from landing inside the red-box size
    # rows and swallowing C:G/H formulas. Header merges (rows 11-12) and the
    # remarks/bank/signature area are left untouched.
    for merged_range in list(worksheet.merged_cells.ranges):
        overlaps_dynamic_rows = not (merged_range.max_row < item_start_row or merged_range.min_row > balance_row)
        overlaps_table_columns = not (merged_range.max_col < 1 or merged_range.min_col > 10)
        if overlaps_dynamic_rows and overlaps_table_columns:
            worksheet.unmerge_cells(str(merged_range))

    for row in (shipping_row, total_row):
        worksheet.merge_cells(start_row=row, start_column=3, end_row=row, end_column=9)
    for row in (deposit_row, balance_row):
        worksheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        worksheet.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)


def rebuild_invoice_fixed_footer(worksheet: Any, *, footer_start_row: int) -> None:
    """Recreate the template footer after dynamic item rows."""
    remarks_row = footer_start_row
    packing_row = footer_start_row + 1
    partial_row = footer_start_row + 2
    shipment_row = footer_start_row + 3
    payment_row = footer_start_row + 4
    bank_title_row = footer_start_row + 5
    bank_row = footer_start_row + 6
    seller_name_row = footer_start_row + 9
    seller_label_row = footer_start_row + 10

    for merged_range in list(worksheet.merged_cells.ranges):
        overlaps_footer = not (merged_range.max_row < remarks_row or merged_range.min_row > seller_label_row)
        overlaps_table_columns = not (merged_range.max_col < 1 or merged_range.min_col > 10)
        if overlaps_footer and overlaps_table_columns:
            worksheet.unmerge_cells(str(merged_range))

    worksheet.merge_cells(start_row=bank_row, start_column=1, end_row=bank_row, end_column=10)
    worksheet.merge_cells(start_row=seller_name_row, start_column=9, end_row=seller_name_row, end_column=10)
    worksheet.merge_cells(start_row=seller_label_row, start_column=9, end_row=seller_label_row, end_column=10)

    # Values are normally shifted from the template by insert_rows(); keep those
    # exact template strings.  The fallback values only protect a damaged/empty
    # template, while the row heights/merges below fix the squeezed layout.
    fallback_values = {
        remarks_row: "REMARKS:",
        packing_row: "1. Packing: Single package in Carton",
        partial_row: "2.Partial shipments: ALLOWED       3.Transhipment: ALLOWED",
        shipment_row: "4.Time of shipment: In  Jun. 2026",
        payment_row: "5. Terms of payment: 100% payment for T/T sample.",
        bank_title_row: "6.Beneficiary bank information:",
    }

    for row, value in fallback_values.items():
        if worksheet[f"A{row}"].value in (None, ""):
            worksheet[f"A{row}"] = value
        worksheet[f"A{row}"].font = Font(name="Arial", size=8, bold=True)
        worksheet[f"A{row}"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    if worksheet[f"B{seller_name_row}"].value in (None, ""):
        worksheet[f"B{seller_name_row}"] = "QUANZHOU CHENSHENG Trading Co., Ltd."
    if worksheet[f"I{seller_name_row}"].value in (None, ""):
        worksheet[f"I{seller_name_row}"] = "=B6"
    if worksheet[f"B{seller_label_row}"].value in (None, ""):
        worksheet[f"B{seller_label_row}"] = "SELLER"
    if worksheet[f"I{seller_label_row}"].value in (None, ""):
        worksheet[f"I{seller_label_row}"] = "BUYER"
    for cell_ref in (f"B{seller_name_row}", f"I{seller_name_row}", f"B{seller_label_row}", f"I{seller_label_row}"):
        worksheet[cell_ref].font = Font(name="Arial", size=8, bold=True)
        worksheet[cell_ref].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row in range(remarks_row, bank_title_row + 1):
        worksheet.row_dimensions[row].height = 25
    worksheet.row_dimensions[bank_row].height = 175
    worksheet.row_dimensions[footer_start_row + 7].height = 15.35
    worksheet.row_dimensions[footer_start_row + 8].height = 15.35
    worksheet.row_dimensions[seller_name_row].height = 15.35
    worksheet.row_dimensions[seller_label_row].height = 24

    bank_cell = worksheet[f"A{bank_row}"]
    bank_cell.font = Font(name="Arial", size=8, bold=True)
    bank_cell.fill = PatternFill(fill_type="solid", fgColor="DDEBF0")
    bank_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    for column in range(1, 11):
        worksheet.cell(bank_row, column).fill = copy(bank_cell.fill)


def build_order_invoice_export(order: dict[str, Any]) -> BytesIO:
    if not PROFORMA_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Proforma invoice template not found: {PROFORMA_TEMPLATE_PATH}")

    shipping_fee = normalize_order_shipping_fee(order.get("shippingFee"))
    if shipping_fee <= 0:
        raise ValueError("Please enter shipping fee before exporting PI")

    prefetch_export_images([order])
    workbook = load_workbook(PROFORMA_TEMPLATE_PATH)
    worksheet = workbook["PI"] if "PI" in workbook.sheetnames else workbook.active
    worksheet.sheet_view.showGridLines = False
    # The inherited PI template styles empty cells through XFC. Remove only
    # unused columns before insert_rows, which otherwise visits ~1M cells.
    for key, cell in list(worksheet._cells.items()):
        if key[1] > 10 and cell.value is None:
            del worksheet._cells[key]
    for name, dimension in list(worksheet.column_dimensions.items()):
        if (dimension.min or column_index_from_string(name)) > 10:
            del worksheet.column_dimensions[name]

    raw_items = [item for item in (order.get("items") or []) if isinstance(item, dict)]
    invoice_items = build_invoice_line_items(raw_items)

    item_start_row = 13
    template_item_rows = 3
    reserved_item_rows = 8
    template_last_item_row = item_start_row + template_item_rows - 1
    required_item_rows = max(len(invoice_items), reserved_item_rows)
    extra_rows = required_item_rows - template_item_rows

    if extra_rows > 0:
        insert_at = template_last_item_row + 1
        insert_invoice_rows(worksheet, insert_at, extra_rows)
        for offset in range(extra_rows):
            prepare_invoice_item_row(worksheet, insert_at + offset, source_row=template_last_item_row, max_col=10)

    product_total_row = 16 + extra_rows
    shipping_row = 17 + extra_rows
    total_row = 18 + extra_rows
    spacer_row = 19 + extra_rows
    deposit_row = 20 + extra_rows
    balance_row = 21 + extra_rows
    pre_footer_spacer_row = 22 + extra_rows
    remarks_row = 23 + extra_rows
    last_item_row = product_total_row - 1

    reset_invoice_summary_merges(worksheet, item_start_row, balance_row, shipping_row, total_row, deposit_row)
    attachment_images, attachment_files = split_order_attachments(order)
    note_text = str(order.get("note") or "").strip()
    has_attachments = bool(note_text or attachment_files or attachment_images)
    if has_attachments:
        insert_invoice_rows(worksheet, remarks_row, 5)
    rebuild_invoice_fixed_footer(worksheet, footer_start_row=remarks_row + (5 if has_attachments else 0))
    worksheet.column_dimensions["B"].width = 22
    worksheet.sheet_view.zoomScale = 90
    worksheet.sheet_view.zoomScaleNormal = 90

    # Header/customer fields: keep all original template formatting.
    worksheet["B5"] = str(order.get("orderNo") or "")
    worksheet["I5"] = datetime.now().strftime("%Y.%m.%d")
    worksheet["B6"] = build_invoice_party_name(order)
    worksheet["I6"] = build_invoice_email(order)
    worksheet["I7"] = str(order.get("phone") or "").strip()
    worksheet["B9"] = build_invoice_address(order)
    worksheet["B9"].alignment = copy(worksheet["B6"].alignment)
    worksheet.row_dimensions[9].height = estimate_text_row_height(
        worksheet["B9"].value,
        line_width=72,
        min_height=float(worksheet.row_dimensions[9].height or 34),
        line_height=18,
        max_height=72,
    )

    # Preserve the paired-size columns while giving product pictures more room.
    for row in range(item_start_row, product_total_row):
        prepare_invoice_item_row(worksheet, row, source_row=template_last_item_row, max_col=10)

    for index, item in enumerate(invoice_items):
        row = item_start_row + index
        worksheet.row_dimensions[row].height = 132
        worksheet[f"A{row}"] = item.get("description") or "--"
        worksheet[f"H{row}"] = f"=SUM(C{row}:G{row})"
        worksheet[f"I{row}"] = float(item.get("unitPrice") or 0)
        worksheet[f"J{row}"] = f"=H{row}*I{row}"

        for column, quantity in (item.get("sizes") or {}).items():
            worksheet[f"{column}{row}"] = quantity

        image_bytes = fetch_image_bytes(str(item.get("image") or ""))
        if image_bytes:
            excel_image = build_excel_image(image_bytes, width=140, height=160)
            if excel_image:
                worksheet.add_image(excel_image, f"B{row}")

    # Summary and formulas. These are the only formula positions that move when
    # more than three item rows are inserted.
    worksheet[f"B{product_total_row}"] = "Product Total"
    worksheet[f"H{product_total_row}"] = f"=SUM(H{item_start_row}:H{last_item_row})"
    worksheet[f"J{product_total_row}"] = f"=SUM(J{item_start_row}:J{last_item_row})"

    worksheet[f"B{shipping_row}"] = "Shipping Cost"
    worksheet[f"C{shipping_row}"] = "(DDP) Air freight: Delivery time is approximately 10-16 days."
    worksheet[f"J{shipping_row}"] = shipping_fee

    worksheet[f"B{total_row}"] = "Total"
    worksheet[f"J{total_row}"] = f"=J{product_total_row}+J{shipping_row}"

    worksheet[f"A{deposit_row}"] = "50% DEPOSITE:"
    worksheet[f"C{deposit_row}"] = f"=J{total_row}*0.5"
    worksheet[f"A{balance_row}"] = "50% BALANCE:"
    worksheet[f"C{balance_row}"] = f"=J{total_row}*0.5"

    # Keep the moving summary/footer rows visually identical to the one-item
    # template, so Shipping Cost and the blue bank area never get squeezed.
    worksheet.row_dimensions[product_total_row].height = 30
    worksheet.row_dimensions[shipping_row].height = 30
    worksheet.row_dimensions[total_row].height = 30
    worksheet.row_dimensions[spacer_row].height = 20.1
    worksheet.row_dimensions[deposit_row].height = 20.1
    worksheet.row_dimensions[balance_row].height = 20.1
    worksheet.row_dimensions[pre_footer_spacer_row].height = 11

    for row in (product_total_row, shipping_row, total_row):
        for column in range(1, 11):
            worksheet.cell(row, column).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    worksheet[f"C{shipping_row}"].font = Font(name="Arial", size=8, bold=True)
    worksheet[f"C{shipping_row}"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for cell_ref in (f"J{product_total_row}", f"J{shipping_row}", f"J{total_row}", f"C{deposit_row}", f"C{balance_row}"):
        worksheet[cell_ref].number_format = '$#,##0.00'

    # Show order-specific remarks directly below totals, before the fixed terms.
    if has_attachments:
        append_row = remarks_row
        worksheet[f"A{append_row}"] = f"订单备注 / 附件图片（{len(attachment_images)} 张） / ORDER NOTE / ATTACHMENTS"
        worksheet[f"A{append_row}"].font = Font(bold=True)
        worksheet[f"A{append_row + 1}"] = "\n".join(
            [part for part in [f"Note: {note_text}" if note_text else "", "Attachments: " + ", ".join(attachment_files) if attachment_files else ""] if part]
        )
        worksheet[f"A{append_row + 1}"].alignment = Alignment(wrap_text=True, vertical="top")
        worksheet.merge_cells(start_row=append_row + 1, start_column=1, end_row=append_row + 1, end_column=10)
        worksheet.row_dimensions[append_row + 1].height = estimate_text_row_height(
            worksheet[f"A{append_row + 1}"].value,
            line_width=100,
            min_height=26,
            line_height=18,
            max_height=409,
        )

        from order_matrix_export import add_attachment_strip
        pictures = []
        for attachment_url in attachment_images[:9]:
            attachment_bytes = fetch_image_bytes(attachment_url, attachment=True)
            attachment_image = build_excel_image(attachment_bytes, width=480, height=480, pixels=1600) if attachment_bytes else None
            if attachment_image:
                pictures.append(attachment_image)
        add_attachment_strip(worksheet, append_row + 3, pictures)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


INVENTORY_TEMPLATE_VERSION = "inventory-v3"
INVENTORY_HEADERS = [
    "模板版本",
    "商品ID",
    "商品标题",
    "颜色 SKU",
    "颜色",
    "分类",
    "尺码",
    "当前库存",
    "合同未送",
    "原始库存",
    "原始合同未送",
    "导出指纹",
    "待入库",
    "原始待入库",
    "待验货",
    "原始待验货",
]
INVENTORY_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
INVENTORY_MAX_ROWS = 20_000
INVENTORY_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


def inventory_item_title(item: dict[str, Any]) -> str:
    names = item.get("name")
    if isinstance(names, dict):
        return str(names.get("zh") or names.get("en") or next(iter(names.values()), "") or "").strip()
    return str(names or item.get("productCode") or item.get("sku") or "").strip()


def filter_inventory_items(
    items: list[dict[str, Any]], *, category: str = "", keyword: str = ""
) -> list[dict[str, Any]]:
    category_value = str(category or "").strip()
    keyword_value = str(keyword or "").strip().lower()
    filtered: list[dict[str, Any]] = []
    for item in items:
        if category_value and str(item.get("categoryKey") or "") != category_value:
            continue
        if keyword_value:
            haystack = " ".join(
                str(value or "")
                for value in (
                    inventory_item_title(item),
                    (item.get("name") or {}).get("en") if isinstance(item.get("name"), dict) else "",
                    item.get("sku"),
                    item.get("productCode"),
                    item.get("colorName"),
                    item.get("categoryLabel"),
                )
            ).lower()
            if keyword_value not in haystack:
                continue
        filtered.append(item)
    return filtered


def inventory_export_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        for size in item.get("sizePrices") or []:
            size_code = str(size.get("sizeCode") or "").strip()
            if not size_code:
                continue
            product_id = int(item.get("id") or 0)
            rows.append(
                {
                    "productId": product_id,
                    "title": inventory_item_title(item),
                    "sku": str(item.get("sku") or item.get("productCode") or "").strip(),
                    "colorName": str(item.get("colorName") or "").strip(),
                    "categoryKey": str(item.get("categoryKey") or "").strip(),
                    "categoryLabel": str(item.get("categoryLabel") or "").strip(),
                    "sizeCode": size_code,
                    "stock": int(size.get("stock") or 0),
                    "contractPending": int(size.get("contractPending") or 0),
                    "pendingInbound": int(size.get("pendingInbound") or 0),
                    "pendingInspection": int(size.get("pendingInspection") or 0),
                }
            )
    return rows


def build_inventory_export(items: list[dict[str, Any]]) -> BytesIO:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "库存数据"
    worksheet.sheet_view.showGridLines = False
    worksheet.freeze_panes = "B2"
    worksheet.append(INVENTORY_HEADERS)
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="6F4E37")
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in inventory_export_rows(items):
        worksheet.append(
            [
                INVENTORY_TEMPLATE_VERSION,
                str(row["productId"]),
                row["title"],
                row["sku"],
                row["colorName"],
                row["categoryKey"],
                row["sizeCode"],
                row["stock"],
                row["contractPending"],
                row["stock"],
                row["contractPending"],
                f"{row['productId']}:{row['sizeCode']}",
                row["pendingInbound"],
                row["pendingInbound"],
                row["pendingInspection"],
                row["pendingInspection"],
            ]
        )

    from openpyxl.comments import Comment
    worksheet['I1'].comment = Comment('转移待验货或待入库时可保持此列原值，系统会自动按阶段差额计算合同未送；若同时填写此列，须与自动计算结果一致。', 'GINGTTO')
    worksheet['M1'].comment = Comment('填写待入库目标数量。增加量从待验货扣减；单独修改此列时系统自动计算待验货余额，一键入库另行操作。', 'GINGTTO')
    worksheet['O1'].comment = Comment('填写待验货目标数量。单独增加时从合同未送扣减；与待入库同时修改时，两列均填写转移后的最终余额。', 'GINGTTO')
    worksheet.column_dimensions['M'].width = 16
    worksheet.column_dimensions['O'].width = 16
    widths = {"A": 16, "B": 12, "C": 36, "D": 22, "E": 16, "F": 20, "G": 14, "H": 14, "I": 14, "J": 14, "K": 18, "L": 24}
    for column, width in widths.items():
        worksheet.column_dimensions[column].width = width
    for column in ("A", "J", "K", "L", "N", "P"):
        worksheet.column_dimensions[column].hidden = True
    for row in worksheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=cell.column in (3, 4, 5, 6))
    if worksheet.max_row > 1:
        worksheet.auto_filter.ref = f"B1:O{worksheet.max_row}"

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def _excel_text(cell: Any) -> str:
    value = cell.value
    if value is None:
        return ""
    return str(value).strip()


def _excel_quantity(cell: Any, label: str, *, signed: bool = False) -> int:
    if cell.value is None or (isinstance(cell.value, str) and not cell.value.strip()):
        raise ValueError(f"{label}不能为空")
    if cell.data_type == "f" or (isinstance(cell.value, str) and cell.value.startswith("=")):
        raise ValueError(f"{label}不能使用公式")
    value = cell.value
    if signed:
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return inventory_policy.parse_stock(value, label)
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是非负整数")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{label}必须是非负整数")
    raw = str(value).strip()
    if not re.fullmatch(r"\d+", raw):
        raise ValueError(f"{label}必须是非负整数")
    if int(raw) > 2147483647:
        raise ValueError(f"{label}超出允许范围")
    return int(raw)


def parse_inventory_workbook(raw: bytes, snapshot: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(raw) > INVENTORY_MAX_UPLOAD_BYTES:
        raise ValueError("导入文件不能超过 10 MB")
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            total_uncompressed = sum(max(0, int(info.file_size)) for info in archive.infolist())
            if total_uncompressed > INVENTORY_MAX_UNCOMPRESSED_BYTES:
                raise ValueError("导入文件解压后体积过大")
    except zipfile.BadZipFile as exc:
        raise ValueError("请上传有效的 .xlsx 文件") from exc

    try:
        workbook = load_workbook(BytesIO(raw), read_only=True, data_only=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("请上传有效的 .xlsx 文件") from exc
    try:
        if not workbook.worksheets:
            raise ValueError("工作簿中没有库存数据表")
        worksheet = workbook.worksheets[0]
        if worksheet.max_row > INVENTORY_MAX_ROWS + 1:
            raise ValueError("数据行不能超过 20,000 行")
        header = [_excel_text(cell) for cell in next(worksheet.iter_rows(min_row=1, max_row=1, max_col=len(INVENTORY_HEADERS)))]
        if header != INVENTORY_HEADERS:
            raise ValueError("库存模板版本或列名不匹配，请使用库存页面导出的文件")

        lookup: dict[tuple[int, str], dict[str, Any]] = {}
        for item in snapshot:
            for size in item.get("sizePrices") or []:
                size_code = str(size.get("sizeCode") or "").strip()
                if size_code:
                    lookup[(int(item["id"]), size_code)] = {"item": item, "size": size}

        parsed: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for row_number, cells in enumerate(
            worksheet.iter_rows(min_row=2, max_col=len(INVENTORY_HEADERS)), start=2
        ):
            if not any(cell.value not in (None, "") for cell in cells):
                continue
            try:
                for cell in cells:
                    if cell.data_type == "f" or (isinstance(cell.value, str) and cell.value.startswith("=")):
                        raise ValueError("不支持公式，请填写固定值")
                version = _excel_text(cells[0])
                if version != INVENTORY_TEMPLATE_VERSION:
                    raise ValueError("模板版本不匹配")
                product_id_raw = _excel_text(cells[1])
                if not re.fullmatch(r"\d+", product_id_raw) or int(product_id_raw) <= 0:
                    raise ValueError("商品ID必须是正整数")
                product_id = int(product_id_raw)
                title = _excel_text(cells[2])
                sku = _excel_text(cells[3])
                color_name = _excel_text(cells[4])
                category_key = _excel_text(cells[5])
                size_code = _excel_text(cells[6])
                if not all((title, sku, category_key, size_code)):
                    raise ValueError("商品ID、标题、SKU、分类和尺码不能为空")
                key = (product_id, size_code)
                if key in seen:
                    raise ValueError("商品与尺码重复")
                seen.add(key)
                fingerprint = _excel_text(cells[11])
                if fingerprint != f"{product_id}:{size_code}":
                    raise ValueError("商品ID与尺码指纹不匹配")
                target = lookup.get(key)
                if not target:
                    raise ValueError("商品或尺码不存在")
                item = target["item"]
                actual_identity = {
                    "标题": inventory_item_title(item),
                    "SKU": str(item.get("sku") or item.get("productCode") or "").strip(),
                    "颜色": str(item.get("colorName") or "").strip(),
                    "分类": str(item.get("categoryKey") or "").strip(),
                }
                imported_identity = {"标题": title, "SKU": sku, "颜色": color_name, "分类": category_key}
                mismatches = [label for label in actual_identity if actual_identity[label] != imported_identity[label]]
                if mismatches:
                    raise ValueError("身份字段不匹配：" + ", ".join(mismatches))
                original_stock = _excel_quantity(cells[9], "原始库存", signed=True)
                original_pending = _excel_quantity(cells[10], "原始合同未送")
                stock = _excel_quantity(cells[7], "当前库存", signed=True)
                contract_pending = _excel_quantity(cells[8], "合同未送")
                inbound_fields = {}
                if version == INVENTORY_TEMPLATE_VERSION:
                    inbound_fields = {"pendingInbound": _excel_quantity(cells[12], "待入库"), "originalPendingInbound": _excel_quantity(cells[13], "原始待入库"), "pendingInspection": _excel_quantity(cells[14], "待验货"), "originalPendingInspection": _excel_quantity(cells[15], "原始待验货")}
                parsed.append(
                    {
                        **inbound_fields,
                        "rowNumber": row_number,
                        "productId": product_id,
                        "title": title,
                        "sku": sku,
                        "colorName": color_name,
                        "categoryKey": category_key,
                        "sizeCode": size_code,
                        "stock": stock,
                        "contractPending": contract_pending,
                        "originalStock": original_stock,
                        "originalContractPending": original_pending,
                    }
                )
            except ValueError as exc:
                errors.append({"row": row_number, "message": str(exc)})
        if not parsed and not errors:
            raise ValueError("库存文件没有可处理的数据行")
        return parsed, errors
    finally:
        workbook.close()


def inventory_import_payload(raw: bytes) -> dict[str, Any]:
    snapshot = list_products(include_contract_pending=True, include_inactive=True)
    parsed, errors = parse_inventory_workbook(raw, snapshot)
    current = {(int(item['id']), str(size['sizeCode'])): size for item in snapshot for size in item.get('sizePrices', [])}
    for index, row in enumerate(parsed, start=2):
        size = current[(row['productId'], row['sizeCode'])]
        effective = dict(size)
        for field, original in [('stock','originalStock'),('contractPending','originalContractPending'),('pendingInbound','originalPendingInbound'),('pendingInspection','originalPendingInspection')]:
            if field in row and row[field] != row[original]:
                if size[field] not in (row[original], row[field]):
                    errors.append({'row':row.get('rowNumber',index),'message':f"{row['sku']} / {row['sizeCode']}：{field} 已在线上变更"})
                effective[field] = row[field]
        try:
            import db as inventory_db
            inventory_db.prepare_inventory_import(row)
            moving = any(row[k] != row[o] for k,o in [('contractPending','originalContractPending'),('pendingInspection','originalPendingInspection'),('pendingInbound','originalPendingInbound')])
            if moving and any(size[k] != row[o] for k,o in [('contractPending','originalContractPending'),('pendingInspection','originalPendingInspection'),('pendingInbound','originalPendingInbound')]):
                if any(size[k] != row[k] for k in ['contractPending','pendingInspection','pendingInbound']): raise ValueError('库存阶段数量已变化，请重新导出')
        except ValueError as exc:
            errors.append({'row':row.get('rowNumber',index),'message':str(exc)})
    changed_rows = [
        row
        for row in parsed
        if row["stock"] != row["originalStock"]
        or row["contractPending"] != row["originalContractPending"]
        or row.get("pendingInbound") != row.get("originalPendingInbound")
        or row.get("pendingInspection") != row.get("originalPendingInspection")
    ]
    return {
        "fileHash": hashlib.sha256(raw).hexdigest(),
        "rows": [
            {
                **row,
                "stockChanged": row["stock"] != row["originalStock"],
                "contractPendingChanged": row["contractPending"] != row["originalContractPending"],
                "pendingInboundChanged": row.get("pendingInbound") != row.get("originalPendingInbound"),
                "pendingInspectionChanged": row.get("pendingInspection") != row.get("originalPendingInspection"),
            }
            for row in parsed
        ],
        "errors": errors,
        "summary": {
            "rowCount": len(parsed),
            "changedRowCount": len(changed_rows),
            "changedFieldCount": sum(
                int(row["stock"] != row["originalStock"])
                + int(row["contractPending"] != row["originalContractPending"])
                + int(row.get("pendingInbound") != row.get("originalPendingInbound"))
                + int(row.get("pendingInspection") != row.get("originalPendingInspection"))
                for row in changed_rows
            ),
            "productCount": len({int(row["productId"]) for row in parsed}),
        },
    }


HOME_SECTION_KEYS = ("bestSeller", "newArrival", "specialPrice")
ADMIN_USER_ROLES = {"admin", "sales", "warehouse", "customer"}
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
CLOUDINARY_FOLDER = os.environ.get("CLOUDINARY_UPLOAD_FOLDER", "gingtto").strip() or "gingtto"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def pick_language() -> str:
    lang = request.args.get("lang", request.headers.get("X-Lang", DEFAULT_LANG))
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def localize(value: Any, lang: str) -> Any:
    if isinstance(value, dict) and SUPPORTED_LANGS & set(value.keys()):
        return value.get(lang) or value.get(DEFAULT_LANG) or next(iter(value.values()))
    if isinstance(value, list):
        return [localize(item, lang) for item in value]
    if isinstance(value, dict):
        return {key: localize(item, lang) for key, item in value.items()}
    return value


def serialize_product(product: dict[str, Any], lang: str) -> dict[str, Any]:
    product = inventory_policy.public_inventory(product)
    category_label = product.get("categoryLabel") or product.get("categoryKey", "")
    name = localize(product["name"], lang)
    summary = localize(product["summary"], lang)
    return {
        "id": product["id"],
        "slug": product["slug"],
        "sku": product["sku"],
        "productCode": product.get("productCode", ""),
        "colorGroup": product.get("colorGroup", ""),
        "colorName": product.get("colorName", ""),
        "colorHex": product.get("colorHex", ""),
        "categoryKey": product["categoryKey"],
        "categoryLabel": category_label,
        "price": product["price"],
        "formattedPrice": f"${product['price']}",
        "stock": product["stock"],
        "featured": bool(product.get("featured")),
        "origin": product.get("origin", ""),
        "sizes": product.get("sizes", []),
        "sizePrices": product.get("sizePrices", []),
        "image": product["image"],
        "gallery": product.get("gallery", []),
        "sizeChartImage": product.get("sizeChartImage", ""),
        "descriptionImage": product.get("descriptionImage", ""),
        "colorOptions": product.get("colorOptions", []),
        "name": name,
        "summary": summary,
        "description": localize(product["description"], lang),
        "searchText": " ".join([name, summary, category_label, product["sku"], product.get("productCode", ""), product.get("colorName", "")]).lower(),
    }

def serialize_banner(banner: dict[str, Any], lang: str) -> dict[str, Any]:
    return {
        "id": banner["id"],
        "image": banner["image"],
        "ctaPath": banner.get("ctaPath", "/shop"),
        "title": localize(banner["title"], lang),
        "subtitle": localize(banner["subtitle"], lang),
        "ctaLabel": localize(banner["ctaLabel"], lang),
    }


def sanitize_admin_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user.get("role", "admin"),
        "permissions": module_permissions.effective(user),
        "status": user["status"],
        "createdAt": user["createdAt"],
    }


def sanitize_store_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "name": user["name"],
        "companyName": user.get("companyName", ""),
        "email": user["email"],
        "status": user["status"],
        "createdAt": user["createdAt"],
    }


def extract_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.replace("Bearer ", "", 1).strip()
    return ""


def require_auth(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        token = extract_token()
        user = get_admin_user_by_session_token(token)
        if not user:
            return jsonify({"message": "Unauthorized"}), 401
        g.current_user = user
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def require_roles(*roles: str) -> Callable[[F], F]:
    allowed_roles = {role.strip().lower() for role in roles if role.strip()}

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_role = str(g.current_user.get("role", "admin")).strip().lower()
            if current_role not in allowed_roles or not module_permissions.allows_request(g.current_user, request.path, request.method):
                return jsonify({"message": "Forbidden"}), 403
            if request.path.startswith('/api/admin/') and request.method in {'POST', 'PUT', 'DELETE', 'PATCH'} and not request.path.endswith(('/uploads', '/preview')):
                return workbench.atomic_admin_call(func, args, kwargs)
            if request.method == "GET":
                return workbench.snapshot_admin_call(func, args, kwargs)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def require_service_auth(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if request.headers.get("X-Service-Token", "") != SERVICE_TOKEN:
            return jsonify({"message": "Unauthorized service"}), 401
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def normalize_admin_role(raw_value: Any, default: str = "admin") -> str:
    role = str(raw_value or default).strip().lower() or default
    if role not in ADMIN_USER_ROLES:
        raise ValueError("Invalid role")
    return role


def validate_product_payload(payload: dict[str, Any]) -> str | None:
    if not str(payload.get("categoryKey", "")).strip():
        return "Missing field: categoryKey"
    if not str(payload.get("title", "")).strip():
        return "Missing field: title"

    if not str(payload.get("sizeChartImage", "")).strip():
        return "Missing field: sizeChartImage"
    if not str(payload.get("descriptionImage", "")).strip():
        return "Missing field: descriptionImage"

    sizes = [str(item).strip() for item in payload.get("sizes", []) if str(item).strip()]
    if not sizes:
        return "Missing field: sizes"


    variants = payload.get("variants")
    if variants is None:
        for field in ["productCode", "slug", "sku", "image"]:
            if not str(payload.get(field, "")).strip():
                return f"Missing field: {field}"
        size_prices = payload.get("sizePrices") or []
        if len(size_prices) != len(sizes):
            return "Missing field: sizePrices"
        for index, item in enumerate(size_prices, start=1):
            if not str(item.get("sizeCode", "")).strip() or item.get("price") in (None, "") or item.get("stock") in (None, ""):
                return f"Invalid sizePrices row at index {index}"
        return None

    if not isinstance(variants, list) or not variants:
        return "Missing field: variants"
    if not str(payload.get("familyCode", "")).strip() and not str(payload.get("colorGroup", "")).strip():
        return "Missing field: familyCode"

    for index, variant in enumerate(variants, start=1):
        if not isinstance(variant, dict):
            return f"Invalid variant at index {index}"
        if not str(variant.get("colorName", "")).strip():
            return f"Missing field: variants[{index}].colorName"
        if not str(variant.get("colorHex", "")).strip():
            return f"Missing field: variants[{index}].colorHex"
        image_urls = variant.get("imageUrls") or variant.get("gallery") or []
        if not isinstance(image_urls, list) or not image_urls or len(image_urls) > 10:
            return f"Invalid field: variants[{index}].imageUrls"
        size_prices = variant.get("sizePrices") or []
        if not isinstance(size_prices, list) or len(size_prices) != len(sizes):
            return f"Missing field: variants[{index}].sizePrices"
        for size_index, size_price in enumerate(size_prices, start=1):
            if (
                not str(size_price.get("sizeCode", "")).strip()
                or size_price.get("price") in (None, "")
                or size_price.get("stock") in (None, "")
            ):
                return f"Invalid sizePrices row at index {index}-{size_index}"
    return None


def apply_default_category(payload: dict[str, Any]) -> None:
    if str(payload.get("categoryKey", "")).strip():
        return
    categories = list_categories()
    if categories:
        payload["categoryKey"] = categories[0]["key"]

def validate_banner_payload(payload: dict[str, Any]) -> str | None:
    if not str(payload.get("image", "")).strip():
        return "Missing field: image"
    for field in ["title", "subtitle", "ctaLabel"]:
        bundle = payload.get(field, {})
        if not isinstance(bundle, dict):
            return f"Invalid field: {field}"
        for lang in ["zh", "en"]:
            if not str(bundle.get(lang, "")).strip():
                return f"Missing field: {field}.{lang}"
    return None


def validate_category_payload(payload: dict[str, Any]) -> str | None:
    key = str(payload.get("key") or payload.get("categoryKey") or "").strip().lower()
    if not key:
        return "Missing field: key"
    labels = payload.get("labels") or payload.get("name")
    if not isinstance(labels, dict):
        return "Invalid field: labels"
    for lang in ("zh", "en"):
        if not str(labels.get(lang, "")).strip():
            return f"Missing field: labels.{lang}"
    try:
        int(payload.get("sortOrder") or 0)
    except (TypeError, ValueError):
        return "Invalid field: sortOrder"
    return None


def validate_homepage_config_payload(payload: dict[str, Any]) -> str | None:
    hero_banners = payload.get("heroBanners")
    section_product_ids = payload.get("sectionProductIds")
    collection_product_ids = payload.get("collectionProductIds")
    display_category_keys = payload.get("displayCategoryKeys")

    if not isinstance(hero_banners, dict):
        return "Invalid field: heroBanners"
    if not isinstance(section_product_ids, dict):
        return "Invalid field: sectionProductIds"
    if not isinstance(collection_product_ids, dict):
        return "Invalid field: collectionProductIds"
    if not isinstance(display_category_keys, list):
        return "Invalid field: displayCategoryKeys"
    if len(display_category_keys) > 5:
        return "Display categories cannot exceed 5"

    valid_product_ids = {row["id"] for row in workbench.db._fetch_all("SELECT id FROM products WHERE is_active=TRUE")}
    valid_category_keys = {str(item["key"]) for item in list_categories()}

    for key in HOME_SECTION_KEYS:
        hero_image = str(hero_banners.get(key, "") or "").strip()
        if not hero_image:
            return f"Missing field: heroBanners.{key}"

        product_ids = section_product_ids.get(key)
        if not isinstance(product_ids, list):
            return f"Invalid field: sectionProductIds.{key}"
        if len(product_ids) > 5:
            return f"{key} home products cannot exceed 5"
        for product_id in product_ids:
            try:
                normalized_product_id = int(product_id)
            except (TypeError, ValueError):
                return f"Invalid product id for {key}"
            if normalized_product_id not in valid_product_ids:
                return f"Product not found for {key}"

        collection_ids = collection_product_ids.get(key)
        if not isinstance(collection_ids, list):
            return f"Invalid field: collectionProductIds.{key}"
        for product_id in collection_ids:
            try:
                normalized_product_id = int(product_id)
            except (TypeError, ValueError):
                return f"Invalid collection product id for {key}"
            if normalized_product_id not in valid_product_ids:
                return f"Collection product not found for {key}"

    for key in display_category_keys:
        normalized_key = str(key or "").strip().lower()
        if normalized_key not in valid_category_keys:
            return f"Category not found: {normalized_key}"

    return None


def build_homepage_payload(lang: str) -> dict[str, Any]:
    config = get_homepage_config()
    products = list_products()
    product_map = {int(item["id"]): item for item in products}
    category_map = {item["key"]: item["label"] for item in list_category_labels(lang)}

    selected_banners = []
    for key in HOME_SECTION_KEYS:
        image_url = str(config["heroBanners"].get(key, "") or "").strip()
        if not image_url:
            continue
        selected_banners.append(
            {
                "id": 0,
                "slotKey": key,
                "image": image_url,
                "ctaPath": "/shop",
                "title": "",
                "subtitle": "",
                "ctaLabel": "",
            }
        )

    sections = {}
    for key in HOME_SECTION_KEYS:
        section_items = []
        for product_id in config["sectionProductIds"].get(key, []):
            product = product_map.get(int(product_id))
            if product:
                section_items.append(serialize_product(product, lang))
        sections[key] = section_items[:5]

    categories = [
        {"key": key, "label": category_map[key]}
        for key in config["displayCategoryKeys"]
        if key in category_map
    ]

    stats = [
        {"label": {"zh": "在线 SKU", "en": "Live SKUs"}[lang], "value": str(count_products())},
        {"label": {"zh": "现货库存", "en": "Units in stock"}[lang], "value": str(count_units_in_stock())},
    ]

    return {
        "banners": selected_banners,
        "sections": sections,
        "categories": categories,
        "stats": stats,
        "featured": sections.get("bestSeller", []),
    }


def build_upload_url(filename: str) -> str:
    return f"{request.host_url.rstrip('/')}/uploads/{filename}"


def cloudinary_enabled() -> bool:
    return bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)


def build_multipart_form_data(fields: dict[str, str], file_name: str, file_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----CloudinaryBoundary{secrets.token_hex(12)}"
    body = bytearray()

    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8")
    )
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    return bytes(body), boundary


def upload_file_to_cloudinary(file_storage: Any) -> str:
    if not cloudinary_enabled():
        raise RuntimeError("Cloudinary is not configured")

    file_name = secure_filename(file_storage.filename or "") or f"upload-{secrets.token_hex(4)}.jpg"
    content_type = file_storage.mimetype or "application/octet-stream"
    file_bytes = file_storage.read()
    file_storage.stream.seek(0)
    if not file_bytes:
        raise ValueError("Empty file")

    endpoint = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"
    fields = {
        "folder": CLOUDINARY_FOLDER,
        "use_filename": "true",
        "unique_filename": "true",
        "overwrite": "false",
    }
    payload, boundary = build_multipart_form_data(fields, file_name, file_bytes, content_type)
    auth_token = b64encode(f"{CLOUDINARY_API_KEY}:{CLOUDINARY_API_SECRET}".encode("utf-8")).decode("ascii")
    request_obj = urllib_request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Basic {auth_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request_obj, timeout=60) as response:
            data = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Cloudinary upload failed: {detail or exc.reason}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Cloudinary upload failed: {exc.reason}") from exc

    try:
        import json

        parsed = json.loads(data)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Cloudinary upload failed: invalid response") from exc

    secure_url = str(parsed.get("secure_url", "")).strip()
    if not secure_url:
        raise RuntimeError("Cloudinary upload failed: missing secure_url")
    return secure_url


def save_file_locally(file_storage: Any) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stem = secure_filename(Path(file_storage.filename or "").stem) or "upload"
    suffix = Path(file_storage.filename or "").suffix.lower() or ".jpg"
    unique_name = f"{stem}-{secrets.token_hex(6)}{suffix}"
    file_storage.save(UPLOAD_DIR / unique_name)
    return build_upload_url(unique_name)


def admin_frontend_ready() -> bool:
    return (ADMIN_FRONTEND_DIST / "index.html").exists()


@app.get("/uploads/<path:filename>")
def serve_upload(filename: str) -> Any:
    from image_delivery import deliver_image
    return deliver_image(UPLOAD_DIR, BASE_DIR / "data" / "image-cache", filename, app.logger)


@app.post("/api/admin/uploads")
@require_auth
@require_roles("admin", "sales")
def upload_files() -> Any:
    files = request.files.getlist("files")
    if not files:
        return jsonify({"message": "Missing files"}), 400
    valid_files = [file for file in files if file.filename]
    if not valid_files:
        return jsonify({"message": "Missing files"}), 400

    uploader = upload_file_to_cloudinary if cloudinary_enabled() else save_file_locally
    if len(valid_files) == 1:
        urls = [uploader(valid_files[0])]
    else:
        max_workers = min(4, len(valid_files))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            urls = list(executor.map(uploader, valid_files))
    return jsonify({"urls": urls})


@app.get("/api/health")
def health() -> Any:
    return jsonify({"status": "ok", "timestamp": utc_now()})


@app.post("/api/auth/admin/login")
def admin_login() -> Any:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", "")).strip()
    user = get_admin_user_by_email(email, include_password_hash=True)
    password_ok = user is not None and check_password_hash(user["passwordHash"], password)
    if not user or user["status"] != "active" or not password_ok:
        return jsonify({"message": "Invalid email or password"}), 401
    token = create_admin_session(user["id"])
    return jsonify({"token": token, "user": sanitize_admin_user(user)})


@app.get("/api/auth/me")
@require_auth
def auth_me() -> Any:
    return jsonify({"role": "admin", "user": sanitize_admin_user(g.current_user)})


@app.post("/api/auth/logout")
@require_auth
def logout() -> Any:
    token = extract_token()
    if token:
        delete_admin_session(token)
    return jsonify({"message": "ok"})


@app.get("/api/public/home")
def public_home() -> Any:
    lang = pick_language()
    return jsonify(build_homepage_payload(lang))


@app.get("/api/public/products")
def public_products() -> Any:
    lang = pick_language()
    category = request.args.get("category", "").strip().lower()
    keyword = request.args.get("keyword", "").strip().lower()
    items = [serialize_product(item, lang) for item in list_products()]
    if category:
        items = [item for item in items if item["categoryKey"] == category]
    if keyword:
        items = [item for item in items if keyword in item["searchText"]]
    return jsonify({"items": items, "total": len(items)})


@app.get("/api/public/products/<slug>")
def public_product_detail(slug: str) -> Any:
    lang = pick_language()
    product = get_product_by_slug(slug)
    if not product:
        return jsonify({"message": "Product not found"}), 404
    related = [
        serialize_product(item, lang)
        for item in list_products()
        if item["categoryKey"] == product["categoryKey"] and item["id"] != product["id"]
    ][:3]
    return jsonify({"product": serialize_product(product, lang), "related": related})


@app.post("/api/internal/store-users/authenticate")
@require_service_auth
def service_auth_store_user() -> Any:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", "")).strip()
    user = get_store_user_by_email(email, include_password_hash=True)
    password_ok = user is not None and check_password_hash(user["passwordHash"], password)
    if not user or user["status"] != "active" or not password_ok:
        return jsonify({"message": "Invalid email or password"}), 401
    return jsonify({"user": sanitize_store_user(user)})


@app.get("/api/internal/store-users/<int:user_id>")
@require_service_auth
def service_get_store_user(user_id: int) -> Any:
    user = get_store_user_by_id(user_id, include_password_hash=False)
    if not user or user["status"] != "active":
        return jsonify({"message": "Store user not found"}), 404
    return jsonify({"user": sanitize_store_user(user)})


@app.get("/api/internal/orders")
@require_service_auth
def service_get_orders() -> Any:
    user_id = request.args.get("userId", "").strip()
    if user_id:
        try:
            target_user_id = int(user_id)
        except ValueError:
            return jsonify({"message": "Invalid userId"}), 400
        return jsonify({"items": list_orders(user_id=target_user_id)})
    if 'page' in request.args:
        return jsonify(workbench.orders_page(request.args))
    return jsonify({"items": list_orders()})


@app.post("/api/internal/orders")
@require_service_auth
def service_create_order() -> Any:
    payload = request.get_json(silent=True) or {}
    required = ["userId", "productId", "quantity", "contactName", "phone", "shippingAddress"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"message": f"Missing field: {', '.join(missing)}"}), 400
    try:
        user_id = int(payload["userId"])
        product_id = int(payload["productId"])
        quantity = int(payload["quantity"])
    except (TypeError, ValueError):
        return jsonify({"message": "Invalid order payload"}), 400
    try:
        order = create_order(
            {
                "userId": user_id,
                "productId": product_id,
                "quantity": quantity,
                "sizeCode": str(payload.get("sizeCode", "")).strip(),
                "contactName": str(payload["contactName"]).strip(),
                "phone": str(payload["phone"]).strip(),
                "country": str(payload.get("country", "")).strip(),
                "shippingAddress": str(payload["shippingAddress"]).strip(),
                "note": str(payload.get("note", "")).strip(),
                "labelImageUrls": payload.get("labelImageUrls") or payload.get("labelImageUrl") or [],
                "labelPdfUrl": str(payload.get("labelPdfUrl", "")).strip(),
            }
        )
    except ValueError as error:
        return jsonify({"message": str(error)}), 404
    except LookupError as error:
        return jsonify({"message": str(error)}), 404
    except RuntimeError as error:
        return jsonify({"message": str(error)}), 400
    return jsonify({"message": "Order submitted to admin system", "order": order}), 201


@app.get("/api/admin/dashboard")
@require_auth
@require_roles("admin", "sales")
def dashboard() -> Any:
    view = request.args.get('view')
    if view == 'workbench':
        return jsonify(workbench.dashboard(request.args))
    if view == 'style-performance':
        return jsonify(workbench.style_performance(request.args))
    if view == 'style-detail':
        try:
            return jsonify(workbench.style_detail(request.args))
        except LookupError as error:
            return jsonify({'message': str(error)}), 404
    if view == 'style-size-detail':
        return jsonify(workbench.style_size_detail(request.args))
    hero_count = len(
        [item for item in get_homepage_config().get("heroBanners", {}).values() if str(item or "").strip()]
    )
    style = request.args.get('style', 'all')
    country = request.args.get('country', 'all')
    date_from = request.args.get('dateFrom', '')
    date_to = request.args.get('dateTo', '')
    all_orders = list_orders()
    filtered_orders = filter_dashboard_orders(
        all_orders,
        style=style,
        country=country,
        date_from=date_from,
        date_to=date_to,
    )
    return jsonify(
        {
            "stats": [
                {"label": "Products", "value": count_products()},
                {"label": "Hero banners", "value": hero_count},
                {"label": "Store accounts", "value": count_store_users()},
                {"label": "Admin accounts", "value": count_admin_users()},
                {"label": "Orders", "value": count_orders()},
            ],
            "filters": build_dashboard_order_filters(all_orders),
            "appliedFilters": {
                'style': str(style or 'all'),
                'country': str(country or 'all'),
                'dateFrom': str(date_from or ''),
                'dateTo': str(date_to or ''),
            },
            "trend": build_dashboard_trend(filtered_orders, date_from=date_from, date_to=date_to),
            "styleSummary": build_dashboard_style_summary(filtered_orders),
            "recentOrders": filtered_orders[:5],
        }
    )


@app.get("/api/admin/products")
@require_auth
@require_roles("admin", "sales")
def products() -> Any:
    if 'page' in request.args:
        return jsonify(workbench.products_page(request.args))
    return jsonify({"items": list_products()})


@app.get("/api/admin/inventory")
@require_auth
@require_roles("admin", "sales", "warehouse", "customer")
def inventory_products() -> Any:
    include_contract_pending = str(g.current_user.get("role") or "").lower() != "customer"
    if 'page' in request.args or request.args.get('stock'):
        return jsonify(workbench.products_page(request.args, pending=include_contract_pending))
    return jsonify({"items": workbench.products_for_export(request.args) if include_contract_pending else list_products()})


@app.get("/api/admin/inventory/export")
@require_auth
@require_roles("admin", "sales", "warehouse")
def export_inventory() -> Any:
    category = str(request.args.get("category", "")).strip()
    keyword = str(request.args.get("keyword", "")).strip()
    items = (workbench.products_for_export(request.args) if request.args.get('view') == 'workbench'
             else workbench.products_for_export(request.args))
    file_stream = build_inventory_export(items)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=f"inventory_export_{timestamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _inventory_upload_bytes() -> bytes:
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        raise ValueError("请选择库存 .xlsx 文件")
    raw = uploaded.read(INVENTORY_MAX_UPLOAD_BYTES + 1)
    if len(raw) > INVENTORY_MAX_UPLOAD_BYTES:
        raise ValueError("导入文件不能超过 10 MB")
    return raw


@app.post("/api/admin/inventory/import/preview")
@require_auth
@require_roles("admin", "sales", "warehouse")
def preview_inventory_import() -> Any:
    try:
        raw = _inventory_upload_bytes()
        payload = inventory_import_payload(raw)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    return jsonify(payload)


@app.post("/api/admin/inventory/import/confirm")
@require_auth
@require_roles("admin", "sales", "warehouse")
def confirm_inventory_import() -> Any:
    try:
        raw = _inventory_upload_bytes()
        expected_hash = str(request.form.get("fileHash", "")).strip().lower()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if not expected_hash or expected_hash != actual_hash:
            return jsonify({"message": "导入文件与预览文件不一致，请重新预览"}), 409
        workbench.db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (actual_hash,))
        processed = workbench.db._fetch_one('SELECT result FROM inventory_import_receipts WHERE file_hash=%s', (actual_hash,))
        if processed:
            return jsonify({'message':'此文件已经导入，不会重复修改','updatedProducts':0,'updatedRows':0,'updatedFields':0,'fileHash':actual_hash,'alreadyProcessed':True})
        payload = inventory_import_payload(raw)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    if payload["errors"]:
        return jsonify({"message": "导入文件存在错误，请修正后重新预览", **payload}), 400
    try:
        result = apply_inventory_import(payload["rows"])
        workbench.db._fetch_one('INSERT INTO inventory_import_receipts(file_hash,result) VALUES(%s,%s) RETURNING file_hash',(actual_hash,workbench.Jsonb(result)))
    except ValueError as error:
        return jsonify({"message": str(error)}), 409
    return jsonify({"message": "库存导入完成", **result, "fileHash": actual_hash})


@app.put("/api/admin/inventory/<int:product_id>")
@require_auth
@require_roles("admin", "sales", "warehouse")
def update_inventory_route(product_id: int) -> Any:
    payload = request.get_json(silent=True) or {}
    size_stocks = payload.get("sizeStocks")
    if not isinstance(size_stocks, dict) or (not size_stocks and not payload.get("contractPendingBySize") and not payload.get("pendingInboundBySize") and not payload.get("pendingInspectionBySize")):
        return jsonify({"message": "Missing field: sizeStocks"}), 400
    contract_pending_by_size = payload.get("contractPendingBySize")
    if contract_pending_by_size is not None and not isinstance(contract_pending_by_size, dict):
        return jsonify({"message": "contractPendingBySize must be an object"}), 400
    try:
        inbound = payload.get('pendingInboundBySize')
        if inbound is not None and not isinstance(inbound, dict):
            raise ValueError('pendingInboundBySize must be an object')
        inspection = payload.get('pendingInspectionBySize')
        if inspection is not None and not isinstance(inspection,dict): raise ValueError('待验货数量格式错误')
        product = update_product_inventory(product_id, size_stocks, contract_pending_by_size, inbound, inspection)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    if not product:
        return jsonify({"message": "Product not found"}), 404
    return jsonify({"message": "Inventory updated", "product": product})


@app.post("/api/admin/products")
@require_auth
@require_roles("admin", "sales")
def create_product_route() -> Any:
    payload = request.get_json(silent=True) or {}
    apply_default_category(payload)
    error = validate_product_payload(payload)
    if error:
        return jsonify({"message": error}), 400
    try:
        if payload.get("variants"):
            family_code = str(payload.get("familyCode") or payload.get("colorGroup") or payload.get("productCode") or "").strip()
            for index, variant in enumerate(payload.get("variants") or [], start=1):
                variant_code = str(variant.get("productCode") or "").strip() or f"{family_code}-{index:02d}"
                variant_slug = str(variant.get("slug") or variant_code).strip()
                variant_sku = str(variant.get("sku") or variant_code).strip()
                if product_slug_exists(variant_slug):
                    return jsonify({"message": f"Product slug already exists: {variant_slug}"}), 400
                if product_sku_exists(variant_sku):
                    return jsonify({"message": f"Product SKU already exists: {variant_sku}"}), 400
                if product_code_exists(variant_code):
                    return jsonify({"message": f"Product code already exists: {variant_code}"}), 400
            product = create_products_batch(payload)
        else:
            if product_slug_exists(str(payload["slug"]).strip()):
                return jsonify({"message": "Product slug already exists"}), 400
            if product_sku_exists(str(payload["sku"]).strip()):
                return jsonify({"message": "Product SKU already exists"}), 400
            if product_code_exists(str(payload["productCode"]).strip()):
                return jsonify({"message": "Product code already exists"}), 400
            product = create_product(payload)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    return jsonify({"message": "Product created", "product": product}), 201


@app.put("/api/admin/products/<int:product_id>")
@require_auth
@require_roles("admin", "sales")
def update_product_route(product_id: int) -> Any:
    payload = request.get_json(silent=True) or {}
    apply_default_category(payload)
    error = validate_product_payload(payload)
    if error:
        return jsonify({"message": error}), 400
    if product_slug_exists(str(payload["slug"]).strip(), exclude_id=product_id):
        return jsonify({"message": "Product slug already exists"}), 400
    if product_sku_exists(str(payload["sku"]).strip(), exclude_id=product_id):
        return jsonify({"message": "Product SKU already exists"}), 400
    if product_code_exists(str(payload["productCode"]).strip(), exclude_id=product_id):
        return jsonify({"message": "Product code already exists"}), 400
    try:
        product = update_product(product_id, payload)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    if not product:
        return jsonify({"message": "Product not found"}), 404
    return jsonify({"message": "Product updated", "product": product})


@app.get("/api/admin/categories")
@require_auth
@require_roles("admin", "sales")
def categories() -> Any:
    items = list_categories()
    return jsonify({"items": items})


@app.post("/api/admin/categories")
@require_auth
@require_roles("admin", "sales")
def create_category_route() -> Any:
    payload = request.get_json(silent=True) or {}
    error = validate_category_payload(payload)
    if error:
        return jsonify({"message": error}), 400
    key = str(payload.get("key") or payload.get("categoryKey") or "").strip().lower()
    if category_key_exists(key):
        return jsonify({"message": "Category key already exists"}), 400
    try:
        category = create_category(payload)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    return jsonify({"message": "Category created", "category": category}), 201


@app.put("/api/admin/categories/<int:category_id>")
@require_auth
@require_roles("admin", "sales")
def update_category_route(category_id: int) -> Any:
    payload = request.get_json(silent=True) or {}
    error = validate_category_payload(payload)
    if error:
        return jsonify({"message": error}), 400
    key = str(payload.get("key") or payload.get("categoryKey") or "").strip().lower()
    if category_key_exists(key, exclude_id=category_id):
        return jsonify({"message": "Category key already exists"}), 400
    try:
        category = update_category(category_id, payload)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    if not category:
        return jsonify({"message": "Category not found"}), 404
    return jsonify({"message": "Category updated", "category": category})


@app.delete("/api/admin/categories/<int:category_id>")
@require_auth
@require_roles("admin", "sales")
def delete_category_route(category_id: int) -> Any:
    try:
        deleted = delete_category(category_id)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    if not deleted:
        return jsonify({"message": "Category not found"}), 404
    return jsonify({"message": "Category deleted"})


@app.delete("/api/admin/products/<int:product_id>")
@require_auth
@require_roles("admin", "sales")
def delete_product_route(product_id: int) -> Any:
    result = delete_product(product_id)
    if not result:
        return jsonify({"message": "Product not found"}), 404
    if result.get("action") == "hidden":
        return jsonify(
            {
                "message": "Product has related orders, so it was hidden instead of deleted",
                "action": "hidden",
            }
        )
    return jsonify({"message": "Product deleted", "action": "deleted"})


@app.get("/api/admin/banners")
@require_auth
@require_roles("admin", "sales")
def banners() -> Any:
    return jsonify({"items": list_banners()})


@app.post("/api/admin/banners")
@require_auth
@require_roles("admin", "sales")
def create_banner_route() -> Any:
    payload = request.get_json(silent=True) or {}
    error = validate_banner_payload(payload)
    if error:
        return jsonify({"message": error}), 400
    banner = create_banner(payload)
    return jsonify({"message": "Banner created", "banner": banner}), 201


@app.put("/api/admin/banners/<int:banner_id>")
@require_auth
@require_roles("admin", "sales")
def update_banner_route(banner_id: int) -> Any:
    payload = request.get_json(silent=True) or {}
    error = validate_banner_payload(payload)
    if error:
        return jsonify({"message": error}), 400
    banner = update_banner(banner_id, payload)
    if not banner:
        return jsonify({"message": "Banner not found"}), 404
    return jsonify({"message": "Banner updated", "banner": banner})


@app.delete("/api/admin/banners/<int:banner_id>")
@require_auth
@require_roles("admin", "sales")
def delete_banner_route(banner_id: int) -> Any:
    if not delete_banner(banner_id):
        return jsonify({"message": "Banner not found"}), 404
    return jsonify({"message": "Banner deleted"})


@app.get("/api/admin/activity-config")
@app.get("/api/admin/home-config")
@require_auth
@require_roles("admin", "sales")
def get_home_config_route() -> Any:
    return jsonify({"config": {**get_homepage_config(), "version": workbench.version("homepage_configs", 1)}})


@app.put("/api/admin/activity-config")
@app.put("/api/admin/home-config")
@require_auth
@require_roles("admin", "sales")
def update_home_config_route() -> Any:
    payload = request.get_json(silent=True) or {}
    if request.path.endswith("/activity-config"):
        if set(payload) - {"collectionProductIds", "version"}:
            return jsonify({"message": "活动接口仅支持修改活动商品"}), 400
        payload = {**get_homepage_config(), **payload}
    elif not set(module_permissions.effective(g.current_user)) & {'activity-zone/apply', 'activity-zone/manage'}:
        if payload.get('collectionProductIds') != get_homepage_config()['collectionProductIds']:
            return jsonify({'message': '未分配活动模块权限，不能修改活动商品'}), 403
    error = validate_homepage_config_payload(payload)
    if error:
        return jsonify({"message": error}), 400
    config = save_homepage_config(payload)
    return jsonify({"message": "Home config updated", "config": {**config, "version": workbench.version("homepage_configs", 1)}})


@app.get("/api/admin/store-users")
@require_auth
@require_roles("admin")
def store_users() -> Any:
    if 'page' in request.args:
        return jsonify(workbench.users_page(request.args))
    return jsonify({"items": [sanitize_store_user(item) for item in list_store_users(include_password_hash=False)]})


@app.post("/api/admin/store-users")
@require_auth
@require_roles("admin")
def create_store_user_route() -> Any:
    payload = request.get_json(silent=True) or {}
    required = ["name", "email", "password"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"message": f"Missing field: {', '.join(missing)}"}), 400
    email = str(payload["email"]).strip().lower()
    if get_store_user_by_email(email, include_password_hash=False):
        return jsonify({"message": "Store account email already exists"}), 400
    user = create_store_user(
        {
            "name": str(payload["name"]).strip(),
            "companyName": str(payload.get("companyName", "")).strip(),
            "email": email,
            "passwordHash": generate_password_hash(str(payload["password"]).strip(), method=PASSWORD_HASH_METHOD),
            "status": str(payload.get("status", "active")).strip() or "active",
        }
    )
    return jsonify({"message": "Store account created", "user": sanitize_store_user(user)}), 201


@app.put("/api/admin/store-users/<int:user_id>")
@require_auth
@require_roles("admin")
def update_store_user_route(user_id: int) -> Any:
    payload = request.get_json(silent=True) or {}
    user = get_store_user_by_id(user_id, include_password_hash=True)
    if not user:
        return jsonify({"message": "Store account not found"}), 404
    email = str(payload.get("email", user["email"])).strip().lower()
    existing = get_store_user_by_email(email, include_password_hash=False)
    if existing and existing["id"] != user_id:
        return jsonify({"message": "Store account email already exists"}), 400
    updated = update_store_user(
        user_id,
        {
            "name": str(payload.get("name", user["name"])).strip(),
            "companyName": str(payload.get("companyName", user.get("companyName", ""))).strip(),
            "email": email,
            "status": str(payload.get("status", user["status"])).strip() or user["status"],
            "passwordHash": generate_password_hash(str(payload["password"]).strip(), method=PASSWORD_HASH_METHOD)
            if str(payload.get("password", "")).strip()
            else None,
        },
    )
    return jsonify({"message": "Store account updated", "user": sanitize_store_user(updated)})  # type: ignore[arg-type]


@app.delete("/api/admin/store-users/<int:user_id>")
@require_auth
@require_roles("admin")
def delete_store_user_route(user_id: int) -> Any:
    try:
        deleted = delete_store_user(user_id)
    except ForeignKeyViolation:
        return jsonify({"message": "Store account has related orders and cannot be deleted"}), 400
    if not deleted:
        return jsonify({"message": "Store account not found"}), 404
    return jsonify({"message": "Store account deleted"})


@app.get("/api/admin/admin-users")
@require_auth
@require_roles("admin")
def admin_users() -> Any:
    if 'page' in request.args:
        return jsonify(workbench.users_page(request.args, admin=True))
    return jsonify({"items": [sanitize_admin_user(item) for item in list_admin_users(include_password_hash=False)]})


@app.post("/api/admin/admin-users")
@require_auth
@require_roles("admin")
def create_admin_user_route() -> Any:
    payload = request.get_json(silent=True) or {}
    required = ["name", "email", "password"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"message": f"Missing field: {', '.join(missing)}"}), 400
    email = str(payload["email"]).strip().lower()
    if get_admin_user_by_email(email, include_password_hash=False):
        return jsonify({"message": "Admin account email already exists"}), 400
    try:
        role = normalize_admin_role(payload.get("role"), default="sales")
        permissions = module_permissions.validate(payload.get("permissions", module_permissions.DEFAULTS[role]), role)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    user = create_admin_user(
        {
            "name": str(payload["name"]).strip(),
            "email": email,
            "passwordHash": generate_password_hash(str(payload["password"]).strip(), method=PASSWORD_HASH_METHOD),
            "role": role,
            "permissions": permissions,
            "status": str(payload.get("status", "active")).strip() or "active",
        }
    )
    return jsonify({"message": "Admin account created", "user": sanitize_admin_user(user)}), 201


@app.put("/api/admin/admin-users/<int:user_id>")
@require_auth
@require_roles("admin")
def update_admin_user_route(user_id: int) -> Any:
    user = get_admin_user_by_id(user_id, include_password_hash=True)
    if not user:
        return jsonify({"message": "Admin account not found"}), 404
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", user["email"])).strip().lower()
    existing = get_admin_user_by_email(email, include_password_hash=False)
    if existing and existing["id"] != user_id:
        return jsonify({"message": "Admin account email already exists"}), 400

    try:
        next_role = normalize_admin_role(payload.get("role", user.get("role", "admin")))
        permissions = module_permissions.validate(payload.get("permissions", [p for p in user["permissions"] if p in module_permissions.DEFAULTS[next_role]]), next_role)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    next_status = str(payload.get("status", user["status"])).strip() or user["status"]
    if (
        user["status"] == "active"
        and user.get("role", "admin") == "admin"
        and (next_status != "active" or next_role != "admin")
        and count_active_admin_users("admin") <= 1
    ):
        return jsonify({"message": "At least one active administrator is required"}), 400
    if user_id == g.current_user["id"] and next_status != "active":
        return jsonify({"message": "You cannot disable the current signed-in admin"}), 400

    candidate = {**user, "role": next_role, "status": next_status, "permissions": permissions}
    if module_permissions.can_administer(user) and not module_permissions.can_administer(candidate):
        if not any(u["id"] != user_id and module_permissions.can_administer(u) for u in list_admin_users(include_password_hash=False)):
            return jsonify({"message": "至少保留一名启用且拥有后台账号权限的管理员"}), 400

    updated = update_admin_user(
        user_id,
        {
            "name": str(payload.get("name", user["name"])).strip(),
            "email": email,
            "role": next_role,
            "permissions": permissions,
            "status": next_status,
            "passwordHash": generate_password_hash(str(payload["password"]).strip(), method=PASSWORD_HASH_METHOD)
            if str(payload.get("password", "")).strip()
            else None,
        },
    )
    if next_status != "active":
        delete_admin_sessions_for_user(user_id)
    return jsonify({"message": "Admin account updated", "user": sanitize_admin_user(updated)})  # type: ignore[arg-type]


@app.delete("/api/admin/admin-users/<int:user_id>")
@require_auth
@require_roles("admin")
def delete_admin_user_route(user_id: int) -> Any:
    user = get_admin_user_by_id(user_id, include_password_hash=False)
    if not user:
        return jsonify({"message": "Admin account not found"}), 404
    if user_id == g.current_user["id"]:
        return jsonify({"message": "You cannot delete the current signed-in admin"}), 400
    if user["status"] == "active" and user.get("role", "admin") == "admin" and count_active_admin_users("admin") <= 1:
        return jsonify({"message": "At least one active administrator is required"}), 400
    if module_permissions.can_administer(user) and not any(u["id"] != user_id and module_permissions.can_administer(u) for u in list_admin_users(include_password_hash=False)):
        return jsonify({"message": "至少保留一名启用且拥有后台账号权限的管理员"}), 400
    delete_admin_sessions_for_user(user_id)
    if not delete_admin_user(user_id):
        return jsonify({"message": "Admin account not found"}), 404
    return jsonify({"message": "Admin account deleted"})


@app.get("/api/admin/orders")
@require_auth
@require_roles("admin", "sales", "warehouse")
def orders() -> Any:
    owner_id = g.current_user['id'] if g.current_user.get('role') == 'sales' else None
    if 'page' in request.args:
        return jsonify(workbench.orders_page(request.args, owner_id=owner_id))
    return jsonify({"items": list_orders(order_ids=workbench.order_ids(request.args, owner_id=owner_id))})


@app.get("/api/admin/orders/export")
@require_auth
@require_roles("admin", "sales", "warehouse")
def export_orders() -> Any:
    time_range = str(request.args.get("timeRange", "all")).strip() or "all"
    status = str(request.args.get("status", "all")).strip() or "all"
    category = str(request.args.get("category", "all")).strip() or "all"
    keyword = str(request.args.get("keyword", "")).strip()
    include_images = parse_bool(request.args.get("includeImages", "1"))
    order_ids_raw = str(request.args.get("orderIds", "")).strip()
    selected_order_ids = {
        int(item)
        for item in order_ids_raw.split(",")
        if str(item).strip().isdigit()
    }
    if request.args.get('view') == 'workbench':
        owner_id = g.current_user['id'] if g.current_user.get('role') == 'sales' else None
        orders = workbench.db.list_orders(order_ids=workbench.order_ids(request.args, owner_id=owner_id))
    else:
        orders = filter_orders(list_orders(), time_range=time_range, status=status,
                               category=category, keyword=keyword)
    if selected_order_ids:
        orders = [order for order in orders if int(order.get("id") or 0) in selected_order_ids]
    file_stream = build_orders_export(orders, include_images=include_images)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=f"orders_export_{timestamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/admin/orders/export-by-sheet")
@require_auth
@require_roles("admin", "sales", "warehouse")
def export_orders_by_sheet() -> Any:
    time_range = str(request.args.get("timeRange", "all")).strip() or "all"
    status = str(request.args.get("status", "all")).strip() or "all"
    category = str(request.args.get("category", "all")).strip() or "all"
    keyword = str(request.args.get("keyword", "")).strip()
    include_images = parse_bool(request.args.get("includeImages", "1"))
    order_ids_raw = str(request.args.get("orderIds", "")).strip()
    selected_order_ids = {
        int(item)
        for item in order_ids_raw.split(",")
        if str(item).strip().isdigit()
    }
    if request.args.get('view') == 'workbench':
        orders = workbench.db.list_orders(order_ids=workbench.order_ids(request.args))
    else:
        orders = filter_orders(list_orders(), time_range=time_range, status=status,
                               category=category, keyword=keyword)
    if selected_order_ids:
        orders = [order for order in orders if int(order.get("id") or 0) in selected_order_ids]
    file_stream = build_orders_sheet_export(orders, include_images=include_images)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=f"orders_by_sheet_{timestamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/admin/orders/<int:order_id>/invoice")
@require_auth
@require_roles("admin", "sales", "warehouse")
def export_order_invoice(order_id: int) -> Any:
    order = get_order_by_id(order_id)
    if not order:
        return jsonify({"message": "Order not found"}), 404
    try:
        file_stream = build_order_invoice_export(order)
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    except FileNotFoundError as error:
        return jsonify({"message": str(error)}), 500
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    order_no = secure_filename(str(order.get("orderNo") or order_id)) or f"order_{order_id}"
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=f"proforma_{order_no}_{timestamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.put("/api/admin/orders/<int:order_id>")
@require_auth
@require_roles("admin", "sales", "warehouse")
def update_order_route(order_id: int) -> Any:
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status", "")).strip()
    tracking_no = str(payload.get("trackingNo", "")).strip()
    payment_link = str(payload.get("paymentLink", "")).strip()
    from order_management import amount
    shipping_fee = amount(payload.get("shippingFee", 0), "运费")
    if not status:
        return jsonify({"message": "Missing status"}), 400
    if status not in ORDER_STATUSES:
        return jsonify({"message": "Invalid status"}), 400
    if status == "shipped" and not tracking_no:
        return jsonify({"message": "Missing trackingNo"}), 400
    order = update_order_status(order_id, status, tracking_no, payment_link, shipping_fee)
    if not order:
        return jsonify({"message": "Order not found"}), 404
    return jsonify({"message": "Order updated", "order": order})


@app.delete("/api/admin/orders")
@require_auth
@require_roles("admin")
def delete_orders_route() -> Any:
    payload = request.get_json(silent=True) or {}
    raw_order_ids = payload.get("orderIds") or []
    if not isinstance(raw_order_ids, list):
        return jsonify({"message": "orderIds must be a list"}), 400

    order_ids: list[int] = []
    for item in raw_order_ids:
        try:
            order_id = int(item)
        except (TypeError, ValueError):
            continue
        if order_id > 0:
            order_ids.append(order_id)

    if not order_ids:
        return jsonify({"message": "Missing orderIds"}), 400

    result = delete_orders(order_ids)
    if not result["deletedCount"]:
        return jsonify({"message": "Order not found"}), 404
    return jsonify(
        {
            "message": "Orders deleted",
            "deletedCount": result["deletedCount"],
            "deletedIds": result["deletedIds"],
        }
    )


@app.get("/favicon.svg")
def serve_admin_favicon() -> Any:
    if admin_frontend_ready():
        favicon_path = ADMIN_FRONTEND_DIST / "favicon.svg"
        if favicon_path.exists():
            return send_from_directory(ADMIN_FRONTEND_DIST, "favicon.svg")
    return jsonify({"message": "Not found"}), 404


@app.get("/assets/<path:filename>")
def serve_admin_assets(filename: str) -> Any:
    if admin_frontend_ready():
        assets_dir = ADMIN_FRONTEND_DIST / "assets"
        file_path = assets_dir / filename
        if file_path.exists():
            return send_from_directory(assets_dir, filename)
    return jsonify({"message": "Not found"}), 404


@app.get("/")
def serve_admin_index() -> Any:
    if admin_frontend_ready():
        return send_from_directory(ADMIN_FRONTEND_DIST, "index.html")
    return jsonify({"message": "Admin frontend build not found"}), 404


@app.get("/<path:path>")
def serve_admin_spa(path: str) -> Any:
    if path.startswith("api/") or path.startswith("uploads/"):
        return jsonify({"message": "Not found"}), 404
    if admin_frontend_ready():
        target = ADMIN_FRONTEND_DIST / path
        if target.exists() and target.is_file():
            return send_from_directory(ADMIN_FRONTEND_DIST, path)
        return send_from_directory(ADMIN_FRONTEND_DIST, "index.html")
    return jsonify({"message": "Admin frontend build not found"}), 404


@app.get('/api/admin/orders/customers')
@require_auth
@require_roles('admin', 'sales')
def order_customer_options():
    page, size = workbench.paging(request.args)
    keyword = '%' + request.args.get('keyword', '').strip() + '%'
    params = (keyword,)
    where = "status='active' AND concat_ws(' ',name,company_name,email) ILIKE %s"
    total = workbench.db._fetch_one('SELECT COUNT(*) AS total FROM store_users WHERE '+where, params)['total']
    rows = workbench.db._fetch_all('SELECT id,name,email,company_name AS "companyName" FROM store_users WHERE '+where+' ORDER BY id DESC LIMIT %s OFFSET %s', (*params,size,(page-1)*size))
    return jsonify({'items':rows,'total':total,'page':page,'pageSize':size})


@app.post('/api/admin/orders')
@require_auth
@require_roles('admin', 'sales')
def create_admin_order():
    from order_management import save_order
    return jsonify(save_order(request.get_json(silent=True) or {}))


@app.put('/api/admin/orders/<int:order_id>/details')
@require_auth
@require_roles('admin', 'sales')
def edit_admin_order(order_id):
    from order_management import save_order
    return jsonify(save_order(request.get_json(silent=True) or {}, order_id))


@app.get('/api/admin/catalog-options')
@require_auth
@require_roles('admin','sales','warehouse','customer')
def catalog_options_route():
    return jsonify({'items': [{'key': c['key'], 'labels': c['labels']} for c in list_categories()]})


@app.post('/api/admin/inventory/<int:product_id>/receive')
@require_auth
@require_roles('admin','sales','warehouse')
def receive_inventory_route(product_id):
    return jsonify(workbench.receive_inventory(product_id, request.get_json() or {}))


@app.errorhandler(ValueError)
def invalid_workbench_input(error):
    return jsonify({"message": str(error)}), 400


@app.get('/api/admin/products/<int:product_id>')
@require_auth
@require_roles('admin', 'sales')
def product_detail_route(product_id):
    item = workbench.product_detail(product_id)
    return (jsonify({'product': item}) if item else (jsonify({'message': '商品不存在'}), 404))


@app.get('/api/admin/products/<int:product_id>/family')
@require_auth
@require_roles('admin', 'sales')
def product_family_route(product_id):
    item = workbench.product_detail(product_id)
    if not item:
        return jsonify({'message': '商品不存在'}), 404
    ids = workbench.db._fetch_all("SELECT id FROM products WHERE is_active=TRUE AND (id=%s OR (color_group<>'' AND color_group=%s)) ORDER BY id", (product_id, item['colorGroup']))
    return jsonify({'items': [workbench.product_detail(row['id']) for row in ids]})


@app.post('/api/admin/products/save-group')
@require_auth
@require_roles('admin', 'sales')
def save_product_group():
    body = request.get_json() or {}
    rows = body.get('products')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError('请提交 1–100 个颜色商品')
    versions = body.get('versions') or {}
    existing_ids = [int(row['id']) for row in rows if row.get('id')]
    if len(existing_ids) != len(set(existing_ids)):
        raise ValueError('同一商品不能重复提交')
    saved = []
    for payload in rows:
        error = validate_product_payload(payload)
        if error:
            raise ValueError(error)
        product_id = payload.get('id')
        if product_id and str(product_id) not in versions:
            raise ValueError('缺少商品版本，请重新读取商品')
        for field, check in [('slug', product_slug_exists), ('sku', product_sku_exists), ('productCode', product_code_exists)]:
            if check(str(payload[field]).strip(), exclude_id=product_id):
                label = {"slug": "商品链接标识", "sku": "SKU", "productCode": "商品编码"}[field]
                raise ValueError(f"{label}重复：{payload[field]}")
        product = update_product(int(product_id), payload) if product_id else create_product(payload)
        if not product:
            raise ValueError('商品不存在')
        saved.append(product)
    return jsonify({'items': saved})


@app.post('/api/admin/products/batch')
@require_auth
@require_roles('admin', 'sales')
def batch_products_route():
    body = request.get_json() or {}
    ids = sorted(set(int(value) for value in body.get('ids', [])))
    if not ids or len(ids) > 500:
        raise ValueError('请选择 1–500 个商品')
    if any(str(value) not in (body.get('versions') or {}) for value in ids):
        raise ValueError('缺少商品版本，请重新选择商品')
    rows = workbench.db._fetch_all('SELECT id FROM products WHERE is_active=TRUE AND id=ANY(%s) ORDER BY id FOR UPDATE', (ids,))
    if len(rows) != len(ids):
        raise ValueError('选择的商品包含已删除记录')
    assignments, params = [], []
    if body.get('categoryKey'):
        category = workbench.db._fetch_one('SELECT id FROM product_categories WHERE category_key=%s AND is_active=TRUE', (body['categoryKey'],))
        if not category: raise ValueError('分类不存在')
        assignments.append('category_id=%s'); params.append(category['id'])
    if 'featured' in body:
        if not isinstance(body['featured'], bool): raise ValueError('推荐状态无效')
        assignments.append('featured=%s'); params.append(body['featured'])
    if not assignments: raise ValueError('请选择要修改的字段')
    workbench.db._fetch_all('UPDATE products SET '+','.join(assignments)+',updated_at=NOW() WHERE id=ANY(%s) RETURNING id', tuple([*params, ids]))
    return jsonify({'updatedCount': len(ids)})


@app.get('/api/admin/inventory/<int:product_id>')
@require_auth
@require_roles('admin', 'sales', 'warehouse', 'customer')
def inventory_detail_route(product_id):
    item = workbench.product_detail(product_id, pending=g.current_user.get('role') != 'customer')
    return jsonify({'product': item}) if item else (jsonify({'message': '商品不存在'}),404)


@app.get('/api/admin/orders/<int:order_id>')
@require_auth
@require_roles('admin', 'sales', 'warehouse')
def order_detail_route(order_id):
    item = get_order_by_id(order_id)
    if not item: return jsonify({'message':'订单不存在'}),404
    item['version'] = workbench.version('orders', order_id)
    item['goodsAmount'] = round(sum(float(row['totalPrice']) for row in item['items']),2)
    return jsonify({'order': item})


@app.get('/api/admin/audit-logs')
@require_auth
@require_roles('admin')
def audit_logs_route():
    return jsonify(workbench.audit_page(request.args))


@app.get('/api/admin/audit-logs/<int:log_id>')
@require_auth
@require_roles('admin')
def audit_detail_route(log_id):
    row = workbench.db._fetch_one('SELECT * FROM admin_audit_logs WHERE id=%s',(log_id,))
    return jsonify({'item':workbench.serialize_audit(row)}) if row else (jsonify({'message':'记录不存在'}),404)



@app.route('/api/admin/contracts', methods=['GET', 'POST'])
@require_auth
@require_roles('admin', 'sales')
def contracts_route():
    import contracts
    return jsonify(contracts.create(request.get_json() or {}) if request.method == 'POST' else contracts.listing(request.args))


@app.get('/api/admin/contracts/<int:contract_id>')
@require_auth
@require_roles('admin', 'sales')
def contract_detail_route(contract_id):
    import contracts
    item = contracts.detail(contract_id)
    return jsonify({'item': item}) if item else (jsonify({'message': '合同不存在'}), 404)


@app.put('/api/admin/contracts/<int:contract_id>')
@require_auth
@require_roles('admin', 'sales')
def contract_update_route(contract_id):
    import contracts
    return jsonify({'item': contracts.update(contract_id, request.get_json() or {})})


@app.post('/api/admin/contracts/<int:contract_id>/cancel')
@require_auth
@require_roles('admin', 'sales')
def contract_cancel_route(contract_id):
    import contracts
    return jsonify({'item': contracts.cancel(contract_id, request.get_json() or {})})


@app.get('/api/admin/contracts/<int:contract_id>/export')
@require_auth
@require_roles('admin', 'sales')
def contract_export_route(contract_id):
    import contracts
    item = contracts.detail(contract_id)
    if not item: return jsonify({'message': '合同不存在'}), 404
    result = contracts.export(item, lambda url: fetch_image_bytes(url, attachment=True), build_excel_image)
    return send_file(result, download_name=f"购买合同-{item['contractNo']}.xlsx", as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.after_request
def sanitize_customer_inventory(response):
    user = getattr(g, 'current_user', None) or {}
    if user.get('role') == 'customer' and request.path.startswith('/api/admin/inventory') and response.is_json:
        response.set_data(app.json.dumps(inventory_policy.public_inventory(response.get_json())))
    return response


ensure_database_ready()


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False, host="0.0.0.0", port=5002)
