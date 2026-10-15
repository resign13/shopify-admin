# Order pricing (local main: USD only)

- New admin orders and drafts use USD. The order editor has no currency selector,
  per-order FX editor, currency conversion preview or conversion dialog.
- The small unified-price dialog remains: manual color/size quotes, zero prices,
  catalog-price refresh confirmation and per-order totals are unchanged.
- The server rejects new CNY orders and per-order FX changes, including direct
  API calls and drafts. Saved order currency/FX stays frozen for every status.
- Reorders use current USD catalog prices and no public FX snapshot. If a saved
  source is CNY, only its freight is converted using its saved FX, never relabeled.
- Existing native-currency records retain their currency and saved values for
  compatible reads, reports, exports and USD PI rendering. No schema columns,
  historical records or finance shared FX settings are removed or rewritten.
- Currency-switch development is retained in both repositories at local branch
  `feature/order-currency-switch-saved` (admin e7b157a, storefront 710db4d).
  The original feature/order-pricing-currency branch is retained as well.
- Release the USD-only main version through the normal reviewed CI/deployment
  flow. Keep the currency feature branch separate. Automated writes require a
  local *_test database; production acceptance is read-only.
