# Order quotes and native USD/CNY orders

## Operator workflow

- The quantity/stock matrix has one small **统一改价** button next to 添加商品.
  No prices or per-SKU editing links are added below SKU labels.
- Its modal stages independent prices for every color SKU: a uniform row price
  applies to all actual sizes, including zero-quantity sizes; expanded rows allow
  individual sizes. Blank is not zero. Cancel never changes the order draft.
- Restore catalog prices explicitly uses USD catalog prices and this order's FX.
  Ordinary price edits affect only the order, never products or finance costs.
- New orders default to USD. CNY requires a positive, at-most-six-decimal rate,
  expressed as 1 USD = CNY. The public finance rate is only a default; changing
  the order's rate does not save or change that public setting.
- Currency changes preview unit prices, freight and total before application.
  Unit prices/freight round half-up to cents before quantity multiplication.
  Draft conversion anchors prevent repeated currency toggles accumulating loss.
- Rate-only changes reprice catalog-mode new-draft items after confirmation.
  Negotiated prices, freight and existing saved order prices remain unchanged.

## API and persistence

- Additive, idempotent migrations in both repositories add orders.currency
  (USD default), orders.exchange_rate (nullable for USD), and item price_source
  plus reference_price_usd. Historical amounts/numbers are never rewritten.
- Existing order creation/detail/draft/reorder contracts accept currency,
  exchangeRate, and items[].priceSource/referencePriceUsd. Totals are always
  calculated server-side with Decimal and existing money/range validation.
- `GET /api/admin/orders/pricing-settings` requires order-edit operation access
  and returns supported currencies/default FX only, not costs or finance writes.
- Catalog quote conflicts return the existing `reorder_price_changed` 409 code,
  including native unitPrice and referencePriceUsd for explicit reconfirmation.
  Manual prices are not compared against catalog prices. Editing an unchanged
  saved line does not silently refresh its historical quote.
- Explicit catalog/manual draft quotes survive reopening. Older drafts without
  pricing metadata retain the previous current-catalog restore behavior.
- Reorder inherits native currency/freight, but uses current catalog prices and
  the current public FX default. Old negotiated prices are not inherited.
- Paid orders lock currency/FX but allow price edits before shipment. Shipped,
  completed and cancelled orders retain their existing item-edit lock.
- Changing native total or currency clears the saved payment link in both full
  editing and compatibility freight updates. The external payment page is not
  revoked and payment status/refunds are not automated.
- Price-only edits never adjust stock. Quantity deltas, ownership, optimistic
  versions, transaction rollback and requestId replay keep their prior rules.
- Warehouse order responses/history strip all monetary/quote fields. Explicit
  order grants remain authoritative for other internal departments.
- Store checkout still selects USD catalog prices server-side and ignores
  supplied currency/prices. Customer order responses expose native currency and
  actual amounts, never FX/reference price/source metadata or finance costs.

## Reports and exports

- Finance reports preserve their separate report FX: USD line sales are rounded
  to CNY per line and added to native CNY sales. Original USD and native CNY
  totals stay separate. Freight is excluded and historical cost matching is
  unchanged. Known/complete profit and missing-cost semantics are preserved.
- Workbench money/rankings normalize CNY using the order's saved rate to USD;
  finance's report rate is deliberately not the workbench normalization rate.
- Order lists/details and the English customer orders page display native money.
- Packing Excel exports preserve price-specific rows, numeric unit/line amounts,
  native currency and existing size columns. Nonstandard sizes get their own
  labeled PI line and retain their actual quantity.
- Per the confirmed export requirement, PI always uses USD and the existing
  USD template/bank details. For CNY orders, saved unit prices and freight are
  divided by the order's saved exchange rate and rounded half-up to cents
  before multiplying quantities and summing invoice totals. Different size
  prices are preserved after conversion. The current catalog/public rate is
  never used; a missing/invalid saved rate rejects export. Export does not
  change the native CNY order, transaction prices, totals or stock. Other order
  Excel exports and finance reports retain their existing native-currency rules.
  PI deposit rounds half of the total to cents; balance is total minus deposit,
  so an odd-cent total never creates a one-cent overpayment in displayed parts.
- Finance Excel retains native amounts, currencies, both rate contexts and
  complete unpaginated results under the same export snapshot.

## Local acceptance and future rollout

- Run the fixed read-only production sync before development; keep the script,
  backup and daily automation in their existing locations.
- Manual services use 127.0.0.1:55439 / lumiere_admin and existing real accounts.
  All automated fixtures/writes require a separate local database ending _test.
- `scripts/order-pricing-browser-fixture.py` provides isolated browser services
  on 5408/5409. It rejects a mirror/production DB target. Never use fixture login
  credentials or seed operations in the manual mirror.
- Admin business regression uses verify-security-regression.py: real default
  quotas run in security tests, high synthetic quotas only in business tests.
- Before any future release: explicit migration/backup preflight, compatible
  backend plus BOTH sites' currency display first, then enable CNY order entry.
  No runtime auto-DDL, credential rotation or private-attachment switch is needed.
- This change does not deploy itself. Production maintenance requires fresh
  user confirmation; existing production availability must be preserved.
