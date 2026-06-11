from __future__ import annotations

import json
import os
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from psycopg import connect
from psycopg.errors import InvalidCatalogName
from psycopg.rows import dict_row
from psycopg.sql import Identifier, SQL

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
SCHEMA_SQL_FILE = REPO_DIR / "db" / "postgres" / "init_lumiere_admin.sql"
DEFAULT_LANG = "zh"
SUPPORTED_LANGS = ("zh", "en")
HOME_SECTION_KEYS = ("bestSeller", "newArrival", "specialPrice")
ORDER_STATUSES = ("pending_payment", "paid", "shipped", "completed", "cancelled")


def _safe_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(BASE_DIR / ".env")

DB_HOST = os.environ.get("PGHOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PGPORT", "5432"))
DB_NAME = os.environ.get("PGDATABASE", "lumiere_admin")
DB_USER = os.environ.get("PGUSER", "postgres")
DB_PASSWORD = os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD") or ""


def _connect(dbname: str | None = None, *, autocommit: bool = False):
    kwargs: dict[str, Any] = {
        "host": DB_HOST,
        "port": DB_PORT,
        "dbname": dbname or DB_NAME,
        "user": DB_USER,
        "row_factory": dict_row,
        "autocommit": autocommit,
    }
    if DB_PASSWORD:
        kwargs["password"] = DB_PASSWORD
    return connect(**kwargs)


@contextmanager
def get_connection() -> Iterator[Any]:
    with _connect() as conn:
        yield conn


def _fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


def _fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()


def _sync_order_status_constraint(cur: Any) -> None:
    cur.execute(
        """
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = con.connamespace
        WHERE nsp.nspname = 'public'
          AND rel.relname = 'orders'
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) ILIKE '%status%'
        """
    )
    rows = cur.fetchall()
    for row in rows:
        cur.execute(SQL("ALTER TABLE orders DROP CONSTRAINT IF EXISTS {}").format(Identifier(row["conname"])))
    cur.execute(
        """
        ALTER TABLE orders
        ADD CONSTRAINT orders_status_check
        CHECK (status IN ('pending_payment', 'paid', 'shipped', 'completed', 'cancelled'))
        """
    )


def _migrate_order_status_values(cur: Any) -> None:
    cur.execute(
        """
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = con.connamespace
        WHERE nsp.nspname = 'public'
          AND rel.relname = 'orders'
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) ILIKE '%status%'
        """
    )
    rows = cur.fetchall()
    for row in rows:
        cur.execute(SQL("ALTER TABLE orders DROP CONSTRAINT IF EXISTS {}").format(Identifier(row["conname"])))

    cur.execute("UPDATE orders SET status = 'pending_payment' WHERE status = 'pending'")
    cur.execute("UPDATE orders SET status = 'paid' WHERE status = 'packed'")
    _sync_order_status_constraint(cur)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _num(value: Any) -> int | float:
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if value == as_int else float(value)
    return value


def _empty_bundle() -> dict[str, str]:
    return {lang: "" for lang in SUPPORTED_LANGS}


def _apply_schema_migrations(cur: Any) -> None:
    cur.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'admin'")
    cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS size_chart_image_url TEXT")
    cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS description_image_url TEXT")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS product_size_prices (
          id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          size_code VARCHAR(32) NOT NULL,
          price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
          sort_order INTEGER NOT NULL DEFAULT 0,
          UNIQUE (product_id, size_code)
        )
        """
    )
    cur.execute("ALTER TABLE product_size_prices ADD COLUMN IF NOT EXISTS stock INTEGER NOT NULL DEFAULT 0")
    cur.execute(
        """
        WITH grouped AS (
          SELECT product_id, COUNT(*)::INTEGER AS row_count, COALESCE(SUM(stock), 0)::INTEGER AS current_stock
          FROM product_size_prices
          GROUP BY product_id
        ),
        ranked AS (
          SELECT id, product_id, ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY sort_order, id) AS row_index
          FROM product_size_prices
        )
        UPDATE product_size_prices psp
        SET stock = CASE
          WHEN ranked.row_index = 1
            THEN (products.stock / grouped.row_count) + (products.stock % grouped.row_count)
          ELSE products.stock / grouped.row_count
        END
        FROM ranked
        JOIN grouped ON grouped.product_id = ranked.product_id
        JOIN products ON products.id = ranked.product_id
        WHERE psp.id = ranked.id
          AND grouped.row_count > 0
          AND grouped.current_stock = 0
          AND products.stock > 0
        """
    )
    cur.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS size_code VARCHAR(32)")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS contact_email VARCHAR(190)")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS first_name VARCHAR(120)")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS last_name VARCHAR(120)")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS address_line1 TEXT")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS apartment VARCHAR(190)")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS city VARCHAR(120)")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS state VARCHAR(120)")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS postal_code VARCHAR(40)")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS tracking_no VARCHAR(120)")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_link TEXT")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_fee NUMERIC(12, 2) NOT NULL DEFAULT 0")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS label_pdf_url TEXT")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS label_image_urls TEXT NOT NULL DEFAULT '[]'")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at TIMESTAMPTZ")
    cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
    _migrate_order_status_values(cur)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS homepage_configs (
          id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          hero_banner_ids TEXT NOT NULL DEFAULT '{}',
          hero_banner_images TEXT NOT NULL DEFAULT '{}',
          section_product_ids TEXT NOT NULL DEFAULT '{}',
          collection_product_ids TEXT NOT NULL DEFAULT '{}',
          display_category_keys TEXT NOT NULL DEFAULT '[]',
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute("ALTER TABLE homepage_configs ADD COLUMN IF NOT EXISTS hero_banner_images TEXT NOT NULL DEFAULT '{}'")
    cur.execute("ALTER TABLE homepage_configs ADD COLUMN IF NOT EXISTS collection_product_ids TEXT NOT NULL DEFAULT '{}'")



def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return [value.strip()]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item or "").strip()]
        if isinstance(parsed, str) and parsed.strip():
            return [parsed.strip()]
    return []


def _serialize_label_image_urls(value: Any, fallback: str = "") -> str:
    urls = _json_list(value)[:5]
    if not urls and fallback:
        urls = [str(fallback).strip()]
    return json.dumps(urls[:5], ensure_ascii=False)


def _parse_label_image_urls(row: dict[str, Any]) -> list[str]:
    urls = _json_list(row.get("label_image_urls"))[:5]
    if not urls and str(row.get("label_pdf_url") or "").strip():
        urls = [str(row.get("label_pdf_url") or "").strip()]
    return urls

def ensure_database_ready() -> None:
    try:
        with _connect():
            pass
    except InvalidCatalogName:
        with _connect("postgres", autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(SQL("CREATE DATABASE {}").format(Identifier(DB_NAME)))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='admin_users') AS exists"
            )
            row = cur.fetchone()
            if not row or not row["exists"]:
                if not SCHEMA_SQL_FILE.exists():
                    raise FileNotFoundError(f"Database schema file not found: {SCHEMA_SQL_FILE}")
                schema_sql = SCHEMA_SQL_FILE.read_text(encoding="utf-8-sig")
                cur.execute(schema_sql)
            _apply_schema_migrations(cur)
        conn.commit()


def _build_product_bundles(product_ids: list[int]) -> tuple[
    dict[int, dict[str, str]],
    dict[int, dict[str, str]],
    dict[int, dict[str, str]],
    dict[int, list[str]],
    dict[int, list[str]],
    dict[int, list[dict[str, Any]]],
]:
    translation_rows = _fetch_all(
        """
        SELECT product_id, lang_code, name, summary, description
        FROM product_translations
        WHERE product_id = ANY(%s)
        ORDER BY product_id, lang_code
        """,
        (product_ids,),
    )
    image_rows = _fetch_all(
        """
        SELECT product_id, image_url
        FROM product_images
        WHERE product_id = ANY(%s)
        ORDER BY product_id, sort_order, id
        """,
        (product_ids,),
    )
    size_rows = _fetch_all(
        """
        SELECT product_id, size_code
        FROM product_sizes
        WHERE product_id = ANY(%s)
        ORDER BY product_id, sort_order, id
        """,
        (product_ids,),
    )
    size_price_rows = _fetch_all(
        """
        SELECT product_id, size_code, price, stock, sort_order
        FROM product_size_prices
        WHERE product_id = ANY(%s)
        ORDER BY product_id, sort_order, id
        """,
        (product_ids,),
    )

    names = {product_id: _empty_bundle() for product_id in product_ids}
    summaries = {product_id: _empty_bundle() for product_id in product_ids}
    descriptions = {product_id: _empty_bundle() for product_id in product_ids}
    galleries = {product_id: [] for product_id in product_ids}
    sizes = {product_id: [] for product_id in product_ids}
    size_prices = {product_id: [] for product_id in product_ids}

    for row in translation_rows:
        product_id = int(row["product_id"])
        lang = row["lang_code"]
        names[product_id][lang] = row["name"] or ""
        summaries[product_id][lang] = row["summary"] or ""
        descriptions[product_id][lang] = row["description"] or ""
    for row in image_rows:
        galleries[int(row["product_id"])].append(row["image_url"])
    for row in size_rows:
        sizes[int(row["product_id"])].append(row["size_code"])
    for row in size_price_rows:
        size_prices[int(row["product_id"])].append(
            {
                "sizeCode": row["size_code"],
                "price": _num(row["price"]),
                "stock": int(row["stock"]),
                "sortOrder": int(row["sort_order"]),
            }
        )
    return names, summaries, descriptions, galleries, sizes, size_prices


def _build_product_result(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    product_ids = [int(row["id"]) for row in rows]
    names, summaries, descriptions, galleries, sizes, size_prices = _build_product_bundles(product_ids)
    items: list[dict[str, Any]] = []
    for row in rows:
        product_id = int(row["id"])
        size_price_list = size_prices[product_id]
        default_price = size_price_list[0]["price"] if size_price_list else _num(row["price"])
        items.append(
            {
                "id": product_id,
                "slug": row["slug"],
                "sku": row["sku"],
                "productCode": row.get("product_code") or "",
                "colorGroup": row.get("color_group") or "",
                "colorName": row.get("color_name") or "",
                "colorHex": row.get("color_hex") or "",
                "categoryKey": row["category_key"],
                "categoryLabel": row.get("category_label", ""),
                "price": default_price,
                "formattedPrice": f"${default_price}",
                "stock": int(row["stock"]),
                "featured": bool(row["featured"]),
                "origin": row["origin"] or "",
                "sizes": sizes[product_id],
                "sizePrices": size_price_list,
                "image": row["main_image_url"],
                "gallery": galleries[product_id],
                "sizeChartImage": row.get("size_chart_image_url") or "",
                "descriptionImage": row.get("description_image_url") or "",
                "name": names[product_id],
                "summary": summaries[product_id],
                "description": descriptions[product_id],
            }
        )
    return items


def _product_base_query() -> str:
    return """
        SELECT
          p.id,
          p.slug,
          p.sku,
          p.product_code,
          p.color_group,
          p.color_name,
          p.color_hex,
          p.price,
          p.stock,
          p.featured,
          p.origin,
          p.main_image_url,
          p.size_chart_image_url,
          p.description_image_url,
          pc.category_key,
          pct.label AS category_label
        FROM products p
        JOIN product_categories pc ON pc.id = p.category_id
        LEFT JOIN product_category_translations pct
          ON pct.category_id = pc.id AND pct.lang_code = %s
    """


def _format_color_options(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": int(row["id"]),
            "slug": row["slug"],
            "productCode": row.get("product_code") or "",
            "colorName": row.get("color_name") or "",
            "colorHex": row.get("color_hex") or "",
            "image": row["main_image_url"],
            "stock": int(row["stock"]),
        }
        for row in rows
    ]


def _product_code_family_prefix(product_code: str) -> str:
    code = str(product_code or "").strip()
    for separator in ("-", "－", "_"):
        if separator in code:
            prefix = code.split(separator, 1)[0].strip()
            if len(prefix) >= 3 and prefix.lower() != code.lower():
                return prefix
    return ""


def _list_color_options(
    color_group: str,
    product_code: str = "",
    category_key: str = "",
    names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if color_group:
        rows = _fetch_all(
            """
            SELECT id, slug, product_code, color_name, color_hex, main_image_url, stock
            FROM products
            WHERE is_active = TRUE AND color_group = %s
            ORDER BY id
            """,
            (color_group,),
        )

    # Backward compatibility: older edits could accidentally overwrite color_group
    # with each color variant's own product_code. In that case the query above
    # only returns itself, so recover sibling colors by the shared product-code
    # prefix such as CS2010-Black / CS2010-White.
    family_prefix = _product_code_family_prefix(product_code)
    if family_prefix and len(rows) <= 1:
        fallback_rows = _fetch_all(
            """
            SELECT id, slug, product_code, color_name, color_hex, main_image_url, stock
            FROM products
            WHERE is_active = TRUE
              AND (color_group = %s OR product_code = %s OR product_code ILIKE %s)
            ORDER BY id
            """,
            (family_prefix, family_prefix, f"{family_prefix}-%"),
        )
        if len(fallback_rows) > len(rows):
            rows = fallback_rows

    # Some products use plain codes such as ZM4757 for each color, so there is no
    # reliable code prefix to recover from. For those, use the product title
    # inside the same category as the grouping fallback. Different color variants
    # are created with the same title and category but different color_name/images.
    name_values = list(
        dict.fromkeys(
            str(value or "").strip()
            for value in (names or {}).values()
            if str(value or "").strip()
        )
    )
    if category_key and name_values and len(rows) <= 1:
        title_rows = _fetch_all(
            """
            SELECT DISTINCT p.id, p.slug, p.product_code, p.color_name, p.color_hex, p.main_image_url, p.stock
            FROM products p
            JOIN product_categories pc ON pc.id = p.category_id
            JOIN product_translations pt ON pt.product_id = p.id
            WHERE p.is_active = TRUE
              AND pc.category_key = %s
              AND pt.name = ANY(%s)
            ORDER BY p.id
            """,
            (category_key, name_values),
        )
        if len(title_rows) > len(rows):
            rows = title_rows

    return _format_color_options(rows)


def _attach_color_options(product: dict[str, Any] | None) -> dict[str, Any] | None:
    if not product:
        return None
    product["colorOptions"] = _list_color_options(
        product.get("colorGroup", ""),
        product.get("productCode", ""),
        product.get("categoryKey", ""),
        product.get("name") or {},
    )
    return product



def list_products() -> list[dict[str, Any]]:
    rows = _fetch_all(
        _product_base_query() + """
        WHERE p.is_active = TRUE
        ORDER BY p.id
        """,
        (DEFAULT_LANG,),
    )
    return _build_product_result(rows)


def get_product_by_id(product_id: int) -> dict[str, Any] | None:
    rows = _fetch_all(
        _product_base_query() + """
        WHERE p.id = %s AND p.is_active = TRUE
        """,
        (DEFAULT_LANG, product_id),
    )
    items = _build_product_result(rows)
    return _attach_color_options(items[0] if items else None)


def get_product_by_slug(slug: str) -> dict[str, Any] | None:
    rows = _fetch_all(
        _product_base_query() + """
        WHERE p.slug = %s AND p.is_active = TRUE
        """,
        (DEFAULT_LANG, slug),
    )
    items = _build_product_result(rows)
    return _attach_color_options(items[0] if items else None)


def product_slug_exists(slug: str, *, exclude_id: int | None = None) -> bool:
    query = "SELECT 1 FROM products WHERE slug = %s AND is_active = TRUE"
    params: list[Any] = [slug]
    if exclude_id is not None:
        query += " AND id <> %s"
        params.append(exclude_id)
    return _fetch_one(query, tuple(params)) is not None

def product_sku_exists(sku: str, *, exclude_id: int | None = None) -> bool:
    query = "SELECT 1 FROM products WHERE sku = %s AND is_active = TRUE"
    params: list[Any] = [sku]
    if exclude_id is not None:
        query += " AND id <> %s"
        params.append(exclude_id)
    return _fetch_one(query, tuple(params)) is not None



def product_code_exists(product_code: str, *, exclude_id: int | None = None) -> bool:
    query = "SELECT 1 FROM products WHERE LOWER(product_code) = LOWER(%s) AND is_active = TRUE"
    params: list[Any] = [product_code]
    if exclude_id is not None:
        query += " AND id <> %s"
        params.append(exclude_id)
    return _fetch_one(query, tuple(params)) is not None


def _build_archived_identifier(
    value: str | None, product_id: int, *, max_length: int, label: str
) -> str:
    base = str(value or "").strip()
    suffix = f"__deleted__{label}_{product_id}"
    if len(suffix) >= max_length:
        return suffix[:max_length]
    remaining = max_length - len(suffix)
    return f"{base[:remaining]}{suffix}"

def _get_category_id(cur: Any, category_key: str) -> int:
    cur.execute("SELECT id FROM product_categories WHERE category_key = %s", (category_key,))
    row = cur.fetchone()
    if not row:
        raise ValueError("Invalid categoryKey")
    return int(row["id"])



def _normalize_size_prices(size_prices: list[dict[str, Any]] | None, sizes: list[str]) -> list[dict[str, Any]]:
    rows = size_prices or []
    if not rows:
        rows = [{"sizeCode": size, "price": 0, "stock": 0, "sortOrder": index} for index, size in enumerate(sizes, start=1)]
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        size_code = str(row.get("sizeCode") or row.get("size_code") or "").strip()
        if not size_code:
            raise ValueError("Missing sizeCode in sizePrices")
        try:
            price = Decimal(str(row.get("price") or 0))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid size price for {size_code}") from exc
        try:
            stock = int(row.get("stock") if row.get("stock") not in (None, "") else 0)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid size stock for {size_code}") from exc
        if stock < 0:
            raise ValueError(f"Invalid size stock for {size_code}")
        normalized.append({"sizeCode": size_code, "price": price, "stock": stock, "sortOrder": int(row.get("sortOrder") or index)})
    return normalized


def _sum_size_stock(size_prices: list[dict[str, Any]]) -> int:
    return sum(int(item.get("stock") or 0) for item in size_prices)


def _normalize_localized_bundle(value: Any, fallback: Any = "") -> dict[str, str]:
    source = value if value not in (None, "") else fallback
    if isinstance(source, dict):
        return {lang: str(source.get(lang, "")).strip() for lang in SUPPORTED_LANGS}
    text = str(source or "").strip()
    return {lang: text for lang in SUPPORTED_LANGS}


def _normalize_product_details(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title", "")).strip()
    normalized_sizes = [str(item).strip() for item in payload.get("sizes", []) if str(item).strip()]
    if not normalized_sizes:
        raise ValueError("Missing field: sizes")
    if not title:
        raise ValueError("Missing field: title")
    normalized_name = _normalize_localized_bundle(title)
    if not any(normalized_name.values()):
        raise ValueError("Missing field: title")
    return {
        "name": normalized_name,
        "summary": _normalize_localized_bundle(title, normalized_name),
        "description": _normalize_localized_bundle(title, normalized_name),
        "sizes": normalized_sizes,
        "sizeChartImage": str(payload.get("sizeChartImage", "")).strip(),
        "descriptionImage": str(payload.get("descriptionImage", "")).strip(),
    }


def _write_product_details(cur: Any, product_id: int, payload: dict[str, Any]) -> None:
    cur.execute("DELETE FROM product_translations WHERE product_id = %s", (product_id,))
    for lang in SUPPORTED_LANGS:
        cur.execute(
            """
            INSERT INTO product_translations (product_id, lang_code, name, summary, description)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                product_id,
                lang,
                payload["name"][lang],
                payload["summary"][lang],
                payload["description"][lang],
            ),
        )

    cur.execute("DELETE FROM product_images WHERE product_id = %s", (product_id,))
    gallery = payload.get("gallery") or [payload["image"]]
    for index, image_url in enumerate(gallery, start=1):
        cur.execute(
            "INSERT INTO product_images (product_id, image_url, sort_order) VALUES (%s, %s, %s)",
            (product_id, image_url, index),
        )

    cur.execute("DELETE FROM product_sizes WHERE product_id = %s", (product_id,))
    for index, size_code in enumerate(payload.get("sizes", []), start=1):
        cur.execute(
            "INSERT INTO product_sizes (product_id, size_code, sort_order) VALUES (%s, %s, %s)",
            (product_id, size_code, index),
        )

    cur.execute("DELETE FROM product_size_prices WHERE product_id = %s", (product_id,))
    for item in _normalize_size_prices(payload.get("sizePrices"), payload.get("sizes", [])):
        cur.execute(
            """
            INSERT INTO product_size_prices (product_id, size_code, price, stock, sort_order)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (product_id, item["sizeCode"], item["price"], item["stock"], item["sortOrder"]),
        )


    cur.execute(
        """
        UPDATE products
        SET size_chart_image_url = %s,
            description_image_url = %s,
            updated_at = NOW()
        WHERE id = %s
        """,
        (payload.get("sizeChartImage", ""), payload.get("descriptionImage", ""), product_id),
    )


def _insert_product_row(cur: Any, payload: dict[str, Any]) -> int:
    category_id = _get_category_id(cur, payload["categoryKey"])
    size_prices = _normalize_size_prices(payload.get("sizePrices"), payload.get("sizes", []))
    price = size_prices[0]["price"] if size_prices else Decimal(str(payload.get("price", 0) or 0))
    stock = _sum_size_stock(size_prices) if size_prices else int(payload.get("stock", 0))
    cur.execute(
        """
        INSERT INTO products (
          category_id, slug, sku, product_code, color_group, color_name, color_hex,
          price, stock, featured, origin, main_image_url, size_chart_image_url, description_image_url,
          is_active, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
        RETURNING id
        """,
        (
            category_id,
            payload["slug"],
            payload["sku"],
            payload["productCode"],
            payload.get("colorGroup") or payload.get("familyCode") or payload["productCode"],
            payload.get("colorName", ""),
            payload.get("colorHex", ""),
            price,
            stock,
            bool(payload.get("featured")),
            payload.get("origin", ""),
            payload["image"],
            payload.get("sizeChartImage", ""),
            payload.get("descriptionImage", ""),
        ),
    )
    product_id = int(cur.fetchone()["id"])
    _write_product_details(cur, product_id, {**payload, "price": price, "sizePrices": size_prices})
    return product_id


def create_products_batch(payload: dict[str, Any]) -> list[dict[str, Any]]:
    details = _normalize_product_details(payload)
    variants = payload.get("variants") or []
    if not variants:
        raise ValueError("Missing field: variants")
    family_code = str(payload.get("familyCode") or payload.get("colorGroup") or payload.get("productCode") or "").strip()
    if not family_code:
        raise ValueError("Missing field: familyCode")

    created_ids: list[int] = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            for index, raw_variant in enumerate(variants, start=1):
                variant = raw_variant or {}
                variant_product_code = str(variant.get("productCode") or "").strip() or f"{family_code}-{index:02d}"
                variant_slug = str(variant.get("slug") or variant_product_code).strip().lower().replace(" ", "-")
                image_urls = [str(item).strip() for item in (variant.get("imageUrls") or variant.get("gallery") or []) if str(item).strip()]
                if not image_urls:
                    raise ValueError(f"Missing field: variants[{index}].imageUrls")
                size_prices = _normalize_size_prices(variant.get("sizePrices"), details["sizes"])
                if len(size_prices) != len(details["sizes"]):
                    raise ValueError(f"Missing field: variants[{index}].sizePrices")
                stock = _sum_size_stock(size_prices)
                payload_row = {
                    "categoryKey": payload["categoryKey"],
                    "slug": variant_slug,
                    "sku": str(variant.get("sku") or variant_product_code).strip(),
                    "productCode": variant_product_code,
                    "colorGroup": family_code,
                    "colorName": str(variant.get("colorName") or "").strip(),
                    "colorHex": str(variant.get("colorHex") or "").strip(),
                    "stock": stock,
                    "featured": bool(payload.get("featured")),
                    "origin": str(payload.get("origin") or "").strip(),
                    "image": image_urls[0],
                    "gallery": image_urls,
                    "sizes": details["sizes"],
                    "sizePrices": size_prices,
                    "name": details["name"],
                    "summary": details["summary"],
                    "description": details["description"],
                    "sizeChartImage": details["sizeChartImage"],
                    "descriptionImage": details["descriptionImage"],
                }
                created_ids.append(_insert_product_row(cur, payload_row))
        conn.commit()
    return [product for product in (get_product_by_id(product_id) for product_id in created_ids) if product]


def create_product(payload: dict[str, Any]) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            product_id = _insert_product_row(cur, payload)
        conn.commit()
    return get_product_by_id(product_id)  # type: ignore[return-value]


def update_product(product_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    details = _normalize_product_details(payload)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, color_group FROM products WHERE id = %s AND is_active = TRUE", (product_id,))
            existing_product = cur.fetchone()
            if not existing_product:
                return None
            category_id = _get_category_id(cur, payload["categoryKey"])
            next_color_group = str(
                payload.get("colorGroup")
                or payload.get("familyCode")
                or existing_product.get("color_group")
                or payload["productCode"]
            ).strip()
            size_prices = _normalize_size_prices(payload.get("sizePrices"), details["sizes"])
            price = size_prices[0]["price"] if size_prices else Decimal(str(payload.get("price", 0) or 0))
            stock = _sum_size_stock(size_prices) if size_prices else int(payload.get("stock", 0))
            cur.execute(
                """
                UPDATE products
                SET category_id = %s,
                    slug = %s,
                    sku = %s,
                    product_code = %s,
                    color_group = %s,
                    color_name = %s,
                    color_hex = %s,
                    price = %s,
                    stock = %s,
                    featured = %s,
                    origin = %s,
                    main_image_url = %s,
                    size_chart_image_url = %s,
                    description_image_url = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    category_id,
                    payload["slug"],
                    payload["sku"],
                    payload["productCode"],
                    next_color_group,
                    payload.get("colorName", ""),
                    payload.get("colorHex", ""),
                    price,
                    stock,
                    bool(payload.get("featured")),
                    payload.get("origin", ""),
                    payload["image"],
                    details["sizeChartImage"],
                    details["descriptionImage"],
                    product_id,
                ),
            )
            _write_product_details(cur, product_id, {**payload, **details, "price": price, "sizePrices": size_prices})
        conn.commit()
    return get_product_by_id(product_id)



def update_product_inventory(product_id: int, size_stocks: dict[str, Any]) -> dict[str, Any] | None:
    normalized: dict[str, int] = {}
    for size_code, stock_value in (size_stocks or {}).items():
        size_key = str(size_code or "").strip()
        if not size_key:
            continue
        try:
            stock = int(stock_value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid size stock for {size_key}") from exc
        if stock < 0:
            raise ValueError(f"Invalid size stock for {size_key}")
        normalized[size_key] = stock

    if not normalized:
        raise ValueError("Missing field: sizeStocks")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM products WHERE id = %s AND is_active = TRUE", (product_id,))
            if not cur.fetchone():
                return None

            cur.execute(
                """
                SELECT size_code
                FROM product_size_prices
                WHERE product_id = %s
                ORDER BY sort_order, id
                """,
                (product_id,),
            )
            rows = cur.fetchall()
            if not rows:
                raise ValueError("Product has no size inventory")

            existing_sizes = [str(row["size_code"]) for row in rows]
            unknown_sizes = [size for size in normalized if size not in existing_sizes]
            if unknown_sizes:
                raise ValueError(f"Unknown sizes: {', '.join(unknown_sizes)}")

            for size_code, stock in normalized.items():
                cur.execute(
                    """
                    UPDATE product_size_prices
                    SET stock = %s
                    WHERE product_id = %s AND size_code = %s
                    """,
                    (stock, product_id, size_code),
                )

            cur.execute(
                "SELECT COALESCE(SUM(stock), 0) AS total_stock FROM product_size_prices WHERE product_id = %s",
                (product_id,),
            )
            total_stock = int((cur.fetchone() or {}).get("total_stock") or 0)
            cur.execute(
                """
                UPDATE products
                SET stock = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (total_stock, product_id),
            )
        conn.commit()

    return get_product_by_id(product_id)


def delete_product(product_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM products
                WHERE id = %s AND is_active = TRUE
                """,
                (product_id,),
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return None

            has_related_orders = False
            action = "deleted"
            if row is not None:
                cur.execute("SELECT COUNT(*) AS total FROM order_items WHERE product_id = %s", (product_id,))
                order_row = cur.fetchone()
                if order_row and int(order_row["total"]) > 0:
                    has_related_orders = True

                if has_related_orders:
                    cur.execute(
                        """
                        UPDATE products
                        SET is_active = FALSE,
                            updated_at = NOW()
                        WHERE id = %s AND is_active = TRUE
                        """,
                        (product_id,),
                    )
                    action = "hidden"
                else:
                    cur.execute(
                        """
                        DELETE FROM products
                        WHERE id = %s AND is_active = TRUE
                        """,
                        (product_id,),
                    )

                cur.execute(
                    """
                    SELECT section_product_ids, collection_product_ids
                    FROM homepage_configs
                    WHERE id = 1
                    """
                )
                row = cur.fetchone()
                if row:
                    cur.execute("SELECT id FROM products WHERE is_active = TRUE ORDER BY id")
                    valid_product_ids = {int(item["id"]) for item in cur.fetchall()}
                    defaults = _default_homepage_config()
                    section_product_ids = _filter_section_product_map(
                        _normalize_home_section_products(
                            _parse_json_text(row.get("section_product_ids"), defaults["sectionProductIds"])
                        ),
                        valid_product_ids,
                        limit=5,
                    )
                    collection_product_ids = _filter_section_product_map(
                        _normalize_collection_section_products(
                            _parse_json_text(
                                row.get("collection_product_ids"), defaults["collectionProductIds"]
                            )
                        ),
                        valid_product_ids,
                        limit=None,
                    )
                    cur.execute(
                        """
                        UPDATE homepage_configs
                        SET section_product_ids = %s,
                            collection_product_ids = %s,
                            updated_at = NOW()
                        WHERE id = 1
                        """,
                        (
                            json.dumps(section_product_ids, ensure_ascii=False),
                            json.dumps(collection_product_ids, ensure_ascii=False),
                        ),
                    )
        conn.commit()
    return {"action": action, "hasRelatedOrders": has_related_orders}


def count_products() -> int:
    row = _fetch_one("SELECT COUNT(*) AS total FROM products WHERE is_active = TRUE")
    return int(row["total"]) if row else 0


def count_units_in_stock() -> int:
    row = _fetch_one("SELECT COALESCE(SUM(stock), 0) AS total FROM products WHERE is_active = TRUE")
    return int(row["total"]) if row else 0


def _build_banner_result(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    banner_ids = [int(row["id"]) for row in rows]
    translation_rows = _fetch_all(
        """
        SELECT banner_id, lang_code, title, subtitle, cta_label
        FROM banner_translations
        WHERE banner_id = ANY(%s)
        ORDER BY banner_id, lang_code
        """,
        (banner_ids,),
    )
    titles = {banner_id: _empty_bundle() for banner_id in banner_ids}
    subtitles = {banner_id: _empty_bundle() for banner_id in banner_ids}
    cta_labels = {banner_id: _empty_bundle() for banner_id in banner_ids}
    for row in translation_rows:
        banner_id = int(row["banner_id"])
        lang = row["lang_code"]
        titles[banner_id][lang] = row["title"] or ""
        subtitles[banner_id][lang] = row["subtitle"] or ""
        cta_labels[banner_id][lang] = row["cta_label"] or ""
    return [
        {
            "id": int(row["id"]),
            "image": row["image_url"],
            "ctaPath": row["cta_path"],
            "title": titles[int(row["id"])],
            "subtitle": subtitles[int(row["id"])],
            "ctaLabel": cta_labels[int(row["id"])],
        }
        for row in rows
    ]


def list_banners() -> list[dict[str, Any]]:
    rows = _fetch_all(
        """
        SELECT id, image_url, cta_path
        FROM banners
        WHERE is_active = TRUE
        ORDER BY sort_order, id
        """
    )
    return _build_banner_result(rows)


def get_banner_by_id(banner_id: int) -> dict[str, Any] | None:
    rows = _fetch_all(
        "SELECT id, image_url, cta_path FROM banners WHERE id = %s AND is_active = TRUE",
        (banner_id,),
    )
    items = _build_banner_result(rows)
    return items[0] if items else None


def _write_banner_details(cur: Any, banner_id: int, payload: dict[str, Any]) -> None:
    cur.execute("DELETE FROM banner_translations WHERE banner_id = %s", (banner_id,))
    for lang in SUPPORTED_LANGS:
        cur.execute(
            """
            INSERT INTO banner_translations (banner_id, lang_code, title, subtitle, cta_label)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                banner_id,
                lang,
                payload["title"][lang],
                payload["subtitle"][lang],
                payload["ctaLabel"][lang],
            ),
        )


def create_banner(payload: dict[str, Any]) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO banners (image_url, cta_path, sort_order, is_active, created_at, updated_at)
                VALUES (%s, %s, COALESCE((SELECT MAX(sort_order) + 1 FROM banners), 1), TRUE, NOW(), NOW())
                RETURNING id
                """,
                (payload["image"], payload.get("ctaPath", "/shop")),
            )
            banner_id = int(cur.fetchone()["id"])
            _write_banner_details(cur, banner_id, payload)
        conn.commit()
    return get_banner_by_id(banner_id)  # type: ignore[return-value]


def update_banner(banner_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM banners WHERE id = %s AND is_active = TRUE", (banner_id,))
            if not cur.fetchone():
                return None
            cur.execute(
                """
                UPDATE banners
                SET image_url = %s,
                    cta_path = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (payload["image"], payload.get("ctaPath", "/shop"), banner_id),
            )
            _write_banner_details(cur, banner_id, payload)
        conn.commit()
    return get_banner_by_id(banner_id)


def delete_banner(banner_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE banners SET is_active = FALSE, updated_at = NOW() WHERE id = %s AND is_active = TRUE RETURNING id",
                (banner_id,),
            )
            deleted = cur.fetchone() is not None
        conn.commit()
    return deleted


def count_banners() -> int:
    row = _fetch_one("SELECT COUNT(*) AS total FROM banners WHERE is_active = TRUE")
    return int(row["total"]) if row else 0


def _parse_json_text(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _normalize_home_banner_ids(value: Any) -> dict[str, int]:
    result = {key: 0 for key in HOME_SECTION_KEYS}
    if not isinstance(value, dict):
        return result
    for key in HOME_SECTION_KEYS:
        raw = value.get(key)
        try:
            banner_id = int(raw)
        except (TypeError, ValueError):
            banner_id = 0
        result[key] = banner_id if banner_id > 0 else 0
    return result


def _normalize_home_banner_images(value: Any) -> dict[str, str]:
    result = {key: "" for key in HOME_SECTION_KEYS}
    if not isinstance(value, dict):
        return result
    for key in HOME_SECTION_KEYS:
        result[key] = str(value.get(key, "") or "").strip()
    return result


def _normalize_section_product_map(value: Any, *, limit: int | None = None) -> dict[str, list[int]]:
    result = {key: [] for key in HOME_SECTION_KEYS}
    if not isinstance(value, dict):
        return result
    for key in HOME_SECTION_KEYS:
        rows = value.get(key)
        if not isinstance(rows, list):
            continue
        seen: set[int] = set()
        normalized: list[int] = []
        for item in rows:
            try:
                product_id = int(item)
            except (TypeError, ValueError):
                continue
            if product_id < 1 or product_id in seen:
                continue
            seen.add(product_id)
            normalized.append(product_id)
        result[key] = normalized[:limit] if limit is not None else normalized
    return result


def _normalize_home_section_products(value: Any) -> dict[str, list[int]]:
    return _normalize_section_product_map(value, limit=5)


def _normalize_collection_section_products(value: Any) -> dict[str, list[int]]:
    return _normalize_section_product_map(value, limit=None)


def _filter_section_product_map(
    value: dict[str, list[int]], valid_product_ids: set[int], *, limit: int | None = None
) -> dict[str, list[int]]:
    result = {key: [] for key in HOME_SECTION_KEYS}
    for key in HOME_SECTION_KEYS:
        rows = value.get(key) or []
        filtered = [product_id for product_id in rows if product_id in valid_product_ids]
        result[key] = filtered[:limit] if limit is not None else filtered
    return result


def _normalize_home_category_keys(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        key = str(item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result[:5]


def _default_homepage_config() -> dict[str, Any]:
    banners = list_banners()
    return {
        "heroBanners": {
            "bestSeller": str(banners[0]["image"]) if len(banners) > 0 else "",
            "newArrival": str(banners[1]["image"]) if len(banners) > 1 else "",
            "specialPrice": str(banners[2]["image"]) if len(banners) > 2 else "",
        },
        "sectionProductIds": {
            "bestSeller": [],
            "newArrival": [],
            "specialPrice": [],
        },
        "collectionProductIds": {
            "bestSeller": [],
            "newArrival": [],
            "specialPrice": [],
        },
        "displayCategoryKeys": [],
    }


def get_homepage_config() -> dict[str, Any]:
    row = _fetch_one(
        """
        SELECT hero_banner_ids, hero_banner_images, section_product_ids, collection_product_ids, display_category_keys
        FROM homepage_configs
        WHERE id = 1
        """
    )
    defaults = _default_homepage_config()
    if not row:
        return defaults

    hero_banners = _normalize_home_banner_images(
        _parse_json_text(row.get("hero_banner_images"), defaults["heroBanners"])
    )
    legacy_banner_images = {}
    for key, banner_id in _normalize_home_banner_ids(_parse_json_text(row.get("hero_banner_ids"), {})).items():
        banner = get_banner_by_id(banner_id) if banner_id else None
        legacy_banner_images[key] = str(banner["image"]) if banner else ""
    section_product_ids = _normalize_home_section_products(
        _parse_json_text(row.get("section_product_ids"), defaults["sectionProductIds"])
    )
    collection_product_ids = _normalize_collection_section_products(
        _parse_json_text(row.get("collection_product_ids"), defaults["collectionProductIds"])
    )
    display_category_keys = _normalize_home_category_keys(
        _parse_json_text(row.get("display_category_keys"), defaults["displayCategoryKeys"])
    )
    valid_product_rows = _fetch_all("SELECT id FROM products WHERE is_active = TRUE ORDER BY id")
    valid_product_ids = {int(item["id"]) for item in valid_product_rows}
    section_product_ids = _filter_section_product_map(section_product_ids, valid_product_ids, limit=5)
    collection_product_ids = _filter_section_product_map(
        collection_product_ids, valid_product_ids, limit=None
    )

    for key in HOME_SECTION_KEYS:
        if not hero_banners[key]:
            hero_banners[key] = legacy_banner_images.get(key) or defaults["heroBanners"][key]

    return {
        "heroBanners": hero_banners,
        "sectionProductIds": section_product_ids,
        "collectionProductIds": collection_product_ids,
        "displayCategoryKeys": display_category_keys,
    }


def save_homepage_config(payload: dict[str, Any]) -> dict[str, Any]:
    hero_banners = _normalize_home_banner_images(payload.get("heroBanners"))
    section_product_ids = _normalize_home_section_products(payload.get("sectionProductIds"))
    collection_product_ids = _normalize_collection_section_products(payload.get("collectionProductIds"))
    display_category_keys = _normalize_home_category_keys(payload.get("displayCategoryKeys"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO homepage_configs (
                    id, hero_banner_ids, hero_banner_images, section_product_ids,
                    collection_product_ids, display_category_keys, updated_at
                )
                VALUES (1, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE
                SET hero_banner_ids = EXCLUDED.hero_banner_ids,
                    hero_banner_images = EXCLUDED.hero_banner_images,
                    section_product_ids = EXCLUDED.section_product_ids,
                    collection_product_ids = EXCLUDED.collection_product_ids,
                    display_category_keys = EXCLUDED.display_category_keys,
                    updated_at = NOW()
                """,
                (
                    json.dumps({}, ensure_ascii=False),
                    json.dumps(hero_banners, ensure_ascii=False),
                    json.dumps(section_product_ids, ensure_ascii=False),
                    json.dumps(collection_product_ids, ensure_ascii=False),
                    json.dumps(display_category_keys, ensure_ascii=False),
                ),
            )
        conn.commit()
    return get_homepage_config()


def _build_category_result(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    category_ids = [int(row["id"]) for row in rows]
    translation_rows = _fetch_all(
        """
        SELECT category_id, lang_code, label
        FROM product_category_translations
        WHERE category_id = ANY(%s)
        ORDER BY category_id, lang_code
        """,
        (category_ids,),
    )
    product_count_rows = _fetch_all(
        """
        SELECT category_id, COUNT(*) AS total
        FROM products
        WHERE category_id = ANY(%s) AND is_active = TRUE
        GROUP BY category_id
        """,
        (category_ids,),
    )

    labels = {category_id: _empty_bundle() for category_id in category_ids}
    product_counts = {category_id: 0 for category_id in category_ids}

    for row in translation_rows:
        labels[int(row["category_id"])][row["lang_code"]] = row["label"] or ""
    for row in product_count_rows:
        product_counts[int(row["category_id"])] = int(row["total"])

    return [
        {
            "id": int(row["id"]),
            "key": row["category_key"],
            "label": labels[int(row["id"])].get(DEFAULT_LANG, ""),
            "labels": labels[int(row["id"])],
            "sortOrder": int(row["sort_order"]),
            "isActive": bool(row["is_active"]),
            "productCount": product_counts[int(row["id"])],
            "createdAt": _iso(row["created_at"]),
        }
        for row in rows
    ]


def list_categories(*, include_inactive: bool = False) -> list[dict[str, Any]]:
    query = """
        SELECT id, category_key, sort_order, is_active, created_at
        FROM product_categories
    """
    params: tuple[Any, ...] = ()
    if not include_inactive:
        query += " WHERE is_active = TRUE"
    query += " ORDER BY sort_order, id"
    return _build_category_result(_fetch_all(query, params))


def get_category_by_id(category_id: int) -> dict[str, Any] | None:
    rows = _fetch_all(
        """
        SELECT id, category_key, sort_order, is_active, created_at
        FROM product_categories
        WHERE id = %s
        """,
        (category_id,),
    )
    items = _build_category_result(rows)
    return items[0] if items else None


def category_key_exists(category_key: str, *, exclude_id: int | None = None) -> bool:
    query = "SELECT 1 FROM product_categories WHERE LOWER(category_key) = LOWER(%s)"
    params: list[Any] = [category_key]
    if exclude_id is not None:
        query += " AND id <> %s"
        params.append(exclude_id)
    return _fetch_one(query, tuple(params)) is not None


def _normalize_category_payload(payload: dict[str, Any]) -> dict[str, Any]:
    labels = payload.get("labels") or payload.get("name") or {}
    if not isinstance(labels, dict):
        raise ValueError("Invalid field: labels")
    category_key = str(payload.get("key") or payload.get("categoryKey") or "").strip().lower()
    if not category_key:
        raise ValueError("Missing field: key")
    normalized_labels = {lang: str(labels.get(lang, "")).strip() for lang in SUPPORTED_LANGS}
    if any(not normalized_labels[lang] for lang in SUPPORTED_LANGS):
        raise ValueError("Missing field: labels")
    sort_order = int(payload.get("sortOrder") or 0)
    return {
        "key": category_key,
        "labels": normalized_labels,
        "sortOrder": sort_order,
    }


def _write_category_translations(cur: Any, category_id: int, labels: dict[str, str]) -> None:
    cur.execute("DELETE FROM product_category_translations WHERE category_id = %s", (category_id,))
    for lang in SUPPORTED_LANGS:
        cur.execute(
            """
            INSERT INTO product_category_translations (category_id, lang_code, label)
            VALUES (%s, %s, %s)
            """,
            (category_id, lang, labels[lang]),
        )


def create_category(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_category_payload(payload)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO product_categories (category_key, sort_order, is_active, created_at)
                VALUES (%s, %s, TRUE, NOW())
                RETURNING id
                """,
                (normalized["key"], normalized["sortOrder"]),
            )
            category_id = int(cur.fetchone()["id"])
            _write_category_translations(cur, category_id, normalized["labels"])
        conn.commit()
    return get_category_by_id(category_id)  # type: ignore[return-value]


def update_category(category_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    normalized = _normalize_category_payload(payload)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM product_categories WHERE id = %s", (category_id,))
            if not cur.fetchone():
                return None
            cur.execute(
                """
                UPDATE product_categories
                SET category_key = %s,
                    sort_order = %s,
                    is_active = TRUE
                WHERE id = %s
                """,
                (normalized["key"], normalized["sortOrder"], category_id),
            )
            _write_category_translations(cur, category_id, normalized["labels"])
        conn.commit()
    return get_category_by_id(category_id)


def delete_category(category_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM products WHERE category_id = %s AND is_active = TRUE",
                (category_id,),
            )
            row = cur.fetchone()
            if row and int(row["total"]) > 0:
                raise ValueError("Category has related products and cannot be deleted")
            cur.execute(
                """
                UPDATE product_categories
                SET is_active = FALSE
                WHERE id = %s AND is_active = TRUE
                RETURNING id
                """,
                (category_id,),
            )
            deleted = cur.fetchone() is not None
        conn.commit()
    return deleted


def list_category_labels(lang: str) -> list[dict[str, str]]:
    rows = _fetch_all(
        """
        SELECT pc.category_key, pct.label
        FROM product_categories pc
        JOIN product_category_translations pct
          ON pct.category_id = pc.id AND pct.lang_code = %s
        WHERE pc.is_active = TRUE
        ORDER BY pc.sort_order, pc.id
        """,
        (lang,),
    )
    return [{"key": row["category_key"], "label": row["label"]} for row in rows]


def _build_user_dict(row: dict[str, Any], *, include_password_hash: bool, company_name: bool) -> dict[str, Any]:
    item = {
        "id": int(row["id"]),
        "name": row["name"],
        "email": row["email"],
        "status": row["status"],
        "createdAt": _iso(row["created_at"]),
    }
    if "role" in row:
        item["role"] = row["role"] or "admin"
    if include_password_hash:
        item["passwordHash"] = row["password_hash"]
    if company_name:
        item["companyName"] = row["company_name"] or ""
    return item


def list_admin_users(*, include_password_hash: bool = True) -> list[dict[str, Any]]:
    rows = _fetch_all(
        "SELECT id, name, email, password_hash, role, status, created_at FROM admin_users ORDER BY id"
    )
    return [_build_user_dict(row, include_password_hash=include_password_hash, company_name=False) for row in rows]


def get_admin_user_by_id(user_id: int, *, include_password_hash: bool = True) -> dict[str, Any] | None:
    row = _fetch_one(
        "SELECT id, name, email, password_hash, role, status, created_at FROM admin_users WHERE id = %s",
        (user_id,),
    )
    return _build_user_dict(row, include_password_hash=include_password_hash, company_name=False) if row else None


def get_admin_user_by_email(email: str, *, include_password_hash: bool = True) -> dict[str, Any] | None:
    row = _fetch_one(
        "SELECT id, name, email, password_hash, role, status, created_at FROM admin_users WHERE LOWER(email) = LOWER(%s)",
        (email,),
    )
    return _build_user_dict(row, include_password_hash=include_password_hash, company_name=False) if row else None


def count_admin_users() -> int:
    row = _fetch_one("SELECT COUNT(*) AS total FROM admin_users")
    return int(row["total"]) if row else 0


def count_active_admin_users(role: str | None = None) -> int:
    if role:
        row = _fetch_one(
            "SELECT COUNT(*) AS total FROM admin_users WHERE status = 'active' AND role = %s",
            (role,),
        )
    else:
        row = _fetch_one("SELECT COUNT(*) AS total FROM admin_users WHERE status = 'active'")
    return int(row["total"]) if row else 0


def create_admin_user(payload: dict[str, Any]) -> dict[str, Any]:
    row = _fetch_one(
        """
        INSERT INTO admin_users (name, email, password_hash, role, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        RETURNING id
        """,
        (
            payload["name"],
            payload["email"],
            payload["passwordHash"],
            payload.get("role", "admin"),
            payload.get("status", "active"),
        ),
    )
    return get_admin_user_by_id(int(row["id"]), include_password_hash=True)  # type: ignore[arg-type]


def update_admin_user(user_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM admin_users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                return None
            fields = ["name = %s", "email = %s", "role = %s", "status = %s", "updated_at = NOW()"]
            params: list[Any] = [payload["name"], payload["email"], payload["role"], payload["status"]]
            if payload.get("passwordHash"):
                fields.insert(4, "password_hash = %s")
                params.append(payload["passwordHash"])
            params.append(user_id)
            cur.execute(f"UPDATE admin_users SET {', '.join(fields)} WHERE id = %s", tuple(params))
        conn.commit()
    return get_admin_user_by_id(user_id, include_password_hash=True)


def delete_admin_user(user_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_users WHERE id = %s RETURNING id", (user_id,))
            deleted = cur.fetchone() is not None
        conn.commit()
    return deleted


def list_store_users(*, include_password_hash: bool = True) -> list[dict[str, Any]]:
    rows = _fetch_all(
        "SELECT id, name, company_name, email, password_hash, status, created_at FROM store_users ORDER BY id"
    )
    return [_build_user_dict(row, include_password_hash=include_password_hash, company_name=True) for row in rows]


def get_store_user_by_id(user_id: int, *, include_password_hash: bool = True) -> dict[str, Any] | None:
    row = _fetch_one(
        "SELECT id, name, company_name, email, password_hash, status, created_at FROM store_users WHERE id = %s",
        (user_id,),
    )
    return _build_user_dict(row, include_password_hash=include_password_hash, company_name=True) if row else None


def get_store_user_by_email(email: str, *, include_password_hash: bool = True) -> dict[str, Any] | None:
    row = _fetch_one(
        "SELECT id, name, company_name, email, password_hash, status, created_at FROM store_users WHERE LOWER(email) = LOWER(%s)",
        (email,),
    )
    return _build_user_dict(row, include_password_hash=include_password_hash, company_name=True) if row else None


def count_store_users() -> int:
    row = _fetch_one("SELECT COUNT(*) AS total FROM store_users")
    return int(row["total"]) if row else 0


def create_store_user(payload: dict[str, Any]) -> dict[str, Any]:
    row = _fetch_one(
        """
        INSERT INTO store_users (name, company_name, email, password_hash, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        RETURNING id
        """,
        (
            payload["name"],
            payload.get("companyName", ""),
            payload["email"],
            payload["passwordHash"],
            payload.get("status", "active"),
        ),
    )
    return get_store_user_by_id(int(row["id"]), include_password_hash=True)  # type: ignore[arg-type]


def update_store_user(user_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM store_users WHERE id = %s", (user_id,))
            if not cur.fetchone():
                return None
            fields = [
                "name = %s",
                "company_name = %s",
                "email = %s",
                "status = %s",
                "updated_at = NOW()",
            ]
            params: list[Any] = [
                payload["name"],
                payload.get("companyName", ""),
                payload["email"],
                payload["status"],
            ]
            if payload.get("passwordHash"):
                fields.insert(4, "password_hash = %s")
                params.append(payload["passwordHash"])
            params.append(user_id)
            cur.execute(f"UPDATE store_users SET {', '.join(fields)} WHERE id = %s", tuple(params))
        conn.commit()
    return get_store_user_by_id(user_id, include_password_hash=True)


def delete_store_user(user_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM store_users WHERE id = %s RETURNING id", (user_id,))
            deleted = cur.fetchone() is not None
        conn.commit()
    return deleted


def create_admin_session(user_id: int) -> str:
    token = secrets.token_urlsafe(24)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_sessions WHERE admin_user_id = %s", (user_id,))
            cur.execute(
                """
                INSERT INTO admin_sessions (admin_user_id, token, created_at)
                VALUES (%s, %s, NOW())
                """,
                (user_id, token),
            )
        conn.commit()
    return token


def get_admin_user_by_session_token(token: str) -> dict[str, Any] | None:
    row = _fetch_one(
        """
        SELECT au.id, au.name, au.email, au.password_hash, au.role, au.status, au.created_at
        FROM admin_sessions s
        JOIN admin_users au ON au.id = s.admin_user_id
        WHERE s.token = %s AND au.status = 'active'
        """,
        (token,),
    )
    return _build_user_dict(row, include_password_hash=True, company_name=False) if row else None


def delete_admin_session(token: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_sessions WHERE token = %s", (token,))
        conn.commit()


def delete_admin_sessions_for_user(user_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_sessions WHERE admin_user_id = %s", (user_id,))
        conn.commit()


def list_orders(*, user_id: int | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT
          o.id,
          o.order_no,
          o.created_at,
          o.updated_at,
          o.status,
          o.store_user_id,
          su.name AS user_name,
          su.company_name,
          su.email AS user_email,
          o.contact_email,
          o.marketing_opt_in,
          o.first_name,
          o.last_name,
          oi.product_id,
          oi.product_name,
          oi.sku,
          oi.size_code,
          oi.quantity,
          oi.unit_price,
          oi.total_price,
          pc.category_key,
          pct.label AS category_label,
          o.total_amount,
          o.contact_name,
          o.phone,
          o.country,
          o.address_line1,
          o.apartment,
          o.city,
          o.state,
          o.postal_code,
          o.tracking_no,
          o.payment_link,
          o.shipping_fee,
          o.label_pdf_url,
          o.label_image_urls,
          o.shipped_at,
          o.completed_at,
          o.shipping_address,
          o.note,
          p.main_image_url
        FROM orders o
        JOIN store_users su ON su.id = o.store_user_id
        LEFT JOIN order_items oi ON oi.order_id = o.id
        LEFT JOIN products p ON p.id = oi.product_id
        LEFT JOIN product_categories pc ON pc.id = p.category_id
        LEFT JOIN product_category_translations pct ON pct.category_id = pc.id AND pct.lang_code = %s
    """
    params: list[Any] = [DEFAULT_LANG]
    where = []
    if user_id is not None:
        where.append("o.store_user_id = %s")
        params.append(user_id)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY o.id DESC, oi.id ASC"
    rows = _fetch_all(query, tuple(params))
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        order_id = int(row["id"])
        if order_id not in grouped:
            grouped[order_id] = {
                "id": order_id,
                "orderNo": row["order_no"],
                "createdAt": _iso(row["created_at"]),
                "updatedAt": _iso(row["updated_at"]),
                "status": row["status"],
                "userId": int(row["store_user_id"]),
                "userName": row["user_name"],
                "companyName": row["company_name"] or "",
                "userEmail": row["user_email"],
                "contactName": row["contact_name"],
                "contactValue": row.get("contact_email") or "",
                "phone": row["phone"],
                "country": row["country"] or "",
                "address": row.get("address_line1") or "",
                "apartment": row.get("apartment") or "",
                "city": row.get("city") or "",
                "state": row.get("state") or "",
                "zip": row.get("postal_code") or "",
                "shippingAddress": row["shipping_address"],
                "note": row["note"] or "",
                "totalAmount": _num(row["total_amount"]),
                "trackingNo": row.get("tracking_no") or "",
                "paymentLink": row.get("payment_link") or "",
                "shippingFee": _num(row.get("shipping_fee") or 0),
                "labelPdfUrl": row.get("label_pdf_url") or "",
                "labelImageUrls": _parse_label_image_urls(row),
                "shippedAt": _iso(row["shipped_at"]) if row.get("shipped_at") else "",
                "completedAt": _iso(row["completed_at"]) if row.get("completed_at") else "",
                "marketingOptIn": bool(row.get("marketing_opt_in")),
                "itemCount": 0,
                "items": [],
            }
        if row["product_id"] is not None:
            quantity = int(row["quantity"])
            grouped[order_id]["itemCount"] += quantity
            grouped[order_id]["items"].append(
                {
                    "productId": int(row["product_id"]),
                    "productName": row["product_name"] or "",
                    "sku": row["sku"] or "",
                    "categoryKey": row.get("category_key") or "",
                    "categoryLabel": row.get("category_label") or "",
                    "sizeCode": row["size_code"] or "",
                    "quantity": quantity,
                    "unitPrice": _num(row["unit_price"]) if row["unit_price"] is not None else 0,
                    "totalPrice": _num(row["total_price"]) if row["total_price"] is not None else 0,
                    "image": row.get("main_image_url") or "",
                }
            )
    items = list(grouped.values())
    if limit is not None:
        items = items[:limit]
    return items


def get_order_by_id(order_id: int) -> dict[str, Any] | None:
    items = list_orders()
    return next((item for item in items if item["id"] == order_id), None)


def create_order(payload: dict[str, Any]) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, company_name, email, status
                FROM store_users
                WHERE id = %s
                """,
                (payload["userId"],),
            )
            user = cur.fetchone()
            if not user or user["status"] != "active":
                raise ValueError("Store user not found")

            size_code = str(payload.get("sizeCode", "")).strip()
            cur.execute(
                """
                SELECT p.id, p.sku, p.price, p.stock, pt.name
                FROM products p
                JOIN product_translations pt
                  ON pt.product_id = p.id AND pt.lang_code = %s
                WHERE p.id = %s AND p.is_active = TRUE
                FOR UPDATE
                """,
                (DEFAULT_LANG, payload["productId"]),
            )
            product = cur.fetchone()
            if not product:
                raise LookupError("Product not found")
            if int(payload["quantity"]) > int(product["stock"]):
                raise RuntimeError("Insufficient stock")

            if size_code:
                cur.execute(
                    """
                    SELECT price, stock
                    FROM product_size_prices
                    WHERE product_id = %s AND size_code = %s
                    FOR UPDATE
                    """,
                    (payload["productId"], size_code),
                )
                size_row = cur.fetchone()
                if not size_row:
                    raise LookupError("Size price not found")
                if int(payload["quantity"]) > int(size_row["stock"]):
                    raise RuntimeError("Insufficient stock")
                base_price = size_row["price"]
            else:
                base_price = product["price"]

            quantity = int(payload["quantity"])
            unit_price = base_price
            total_price = unit_price * quantity

            cur.execute(
                "UPDATE products SET stock = stock - %s, updated_at = NOW() WHERE id = %s",
                (quantity, payload["productId"]),
            )
            if size_code:
                cur.execute(
                    """
                    UPDATE product_size_prices
                    SET stock = stock - %s
                    WHERE product_id = %s AND size_code = %s
                    """,
                    (quantity, payload["productId"], size_code),
                )
            cur.execute(
                """
                INSERT INTO orders (
                  order_no, store_user_id, status, contact_name, phone, country,
                  shipping_address, note, label_pdf_url, label_image_urls, total_amount, created_at, updated_at
                )
                VALUES (
                  %s, %s, 'pending_payment', %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                )
                RETURNING id
                """,
                (
                    f"TEMP-{secrets.token_hex(6)}",
                    payload["userId"],
                    payload["contactName"],
                    payload["phone"],
                    payload.get("country", ""),
                    payload["shippingAddress"],
                    payload.get("note", ""),
                    payload.get("labelPdfUrl", ""),
                    _serialize_label_image_urls(payload.get("labelImageUrls"), payload.get("labelPdfUrl", "")),
                    total_price,
                ),
            )
            order_row = cur.fetchone()
            order_id = int(order_row["id"])
            cur.execute(
                "UPDATE orders SET order_no = %s WHERE id = %s",
                (f"LM-{order_id:06d}", order_id),
            )
            cur.execute(
                """
                INSERT INTO order_items (order_id, product_id, product_name, sku, size_code, quantity, unit_price, total_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    payload["productId"],
                    product["name"],
                    product["sku"],
                    size_code,
                    quantity,
                    unit_price,
                    total_price,
                ),
            )
        conn.commit()
    return get_order_by_id(order_id)  # type: ignore[return-value]


def update_order_status(
    order_id: int, status: str, tracking_no: str = "", payment_link: str = "", shipping_fee: Any = 0
) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            shipping_fee_decimal = _safe_decimal(shipping_fee)
            cur.execute("SELECT COALESCE(SUM(total_price), 0) AS subtotal FROM order_items WHERE order_id = %s", (order_id,))
            subtotal_row = cur.fetchone()
            subtotal = _safe_decimal(subtotal_row["subtotal"] if subtotal_row else 0)
            next_total = subtotal + shipping_fee_decimal
            if status == "shipped":
                cur.execute(
                    """
                    UPDATE orders
                    SET status = %s,
                        tracking_no = %s,
                        payment_link = %s,
                        shipping_fee = %s,
                        total_amount = %s,
                        shipped_at = COALESCE(shipped_at, NOW()),
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (status, tracking_no, payment_link, shipping_fee_decimal, next_total, order_id),
                )
            elif status == "completed":
                cur.execute(
                    """
                    UPDATE orders
                    SET status = %s,
                        tracking_no = CASE WHEN %s <> '' THEN %s ELSE tracking_no END,
                        payment_link = %s,
                        shipping_fee = %s,
                        total_amount = %s,
                        completed_at = COALESCE(completed_at, NOW()),
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (status, tracking_no, tracking_no, payment_link, shipping_fee_decimal, next_total, order_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE orders
                    SET status = %s,
                        tracking_no = CASE WHEN %s <> '' THEN %s ELSE tracking_no END,
                        payment_link = %s,
                        shipping_fee = %s,
                        total_amount = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (status, tracking_no, tracking_no, payment_link, shipping_fee_decimal, next_total, order_id),
                )
            if not cur.fetchone():
                return None
        conn.commit()
    return get_order_by_id(order_id)


def delete_orders(order_ids: list[int]) -> dict[str, Any]:
    normalized_ids = sorted({int(order_id) for order_id in order_ids if int(order_id) > 0})
    if not normalized_ids:
        return {"deletedIds": [], "deletedCount": 0}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM orders WHERE id = ANY(%s) FOR UPDATE", (normalized_ids,))
            existing_order_ids = [int(row["id"]) for row in cur.fetchall()]
            if not existing_order_ids:
                return {"deletedIds": [], "deletedCount": 0}

            cur.execute(
                """
                SELECT product_id, COALESCE(size_code, '') AS size_code, SUM(quantity)::INTEGER AS quantity
                FROM order_items
                WHERE order_id = ANY(%s)
                GROUP BY product_id, COALESCE(size_code, '')
                """,
                (existing_order_ids,),
            )
            for row in cur.fetchall():
                product_id = int(row.get("product_id") or 0)
                quantity = int(row.get("quantity") or 0)
                size_code = str(row.get("size_code") or "").strip()
                if product_id <= 0 or quantity <= 0:
                    continue
                cur.execute(
                    "UPDATE products SET stock = stock + %s, updated_at = NOW() WHERE id = %s",
                    (quantity, product_id),
                )
                if size_code:
                    cur.execute(
                        "UPDATE product_size_prices SET stock = stock + %s WHERE product_id = %s AND size_code = %s",
                        (quantity, product_id, size_code),
                    )

            cur.execute("DELETE FROM orders WHERE id = ANY(%s) RETURNING id", (existing_order_ids,))
            deleted_ids = [int(row["id"]) for row in cur.fetchall()]
        conn.commit()

    return {"deletedIds": deleted_ids, "deletedCount": len(deleted_ids)}


def count_orders() -> int:
    row = _fetch_one("SELECT COUNT(*) AS total FROM orders")
    return int(row["total"]) if row else 0





