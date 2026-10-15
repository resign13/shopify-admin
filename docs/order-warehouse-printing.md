# Warehouse export / printed mark

- A successful warehouse-role export adds a small green printer beside the main
  order number in the admin list and detail header. Hover/focus says 仓库已打单.
- All backend accounts authorized to view an order see the same mark in its
  list and detail, including admin, sales, warehouse and explicitly authorized
  finance accounts. Existing ownership and module permissions still apply.
- The mark means the export file was generated, not a physical-printer receipt.
  Only the actual authorized/filtered orders in the file are marked, across all
  export pages. Admin/sales exports do not mark orders. Previous exports are not
  guessed or backfilled. Repeated exports preserve the first timestamp/actor.
- First timestamp, actor ID/name and export kind persist in
  `order_warehouse_prints`. No order status/version, stock, amount, payment link,
  notification or original order audit is changed. There is no automatic reset.
- Both order Excel routes support POST with the existing query parameters.
  The UI uses the existing cookie/Origin/CSRF transport. Warehouse GET/HEAD is
  rejected with 405/Allow: POST to avoid a state-changing GET; nonwarehouse GET
  compatibility stays read-only. Export quota/concurrency and module permissions
  remain in force. No separate client-writable mark endpoint is exposed.
- Build the complete workbook and response before recording the batch. An export
  or mark-transaction failure does not return a successful download; all marks in
  that batch roll back. A client disconnect after a prepared response cannot prove
  the file reached disk. Retry safely downloads again without duplicating marks.
- Admin list/detail read one joined mark per order, not one query per item. The
  customer order API does not expose internal print metadata. Warehouse amounts
  stay redacted in both API responses and Excel.
- Incremental migration and both initialization SQL files create the table
  idempotently. Admin runtime needs SELECT/INSERT; existing migrator default
  grants cover it. Store runtime gets no access to the print table. Run migration
  before switching the admin application. No production work is performed during
  local acceptance; all automated writes stay in a guarded local `*_test` DB.
