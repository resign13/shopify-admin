"""Selected-SKU operations only; fixtures require the existing local *_test guard."""
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import test_workbench as fixtures
import workbench

db = fixtures.db


class InventoryBatchTest(unittest.TestCase):
    setUp = fixtures.WorkbenchTest.setUp
    call = fixtures.WorkbenchTest.call

    def detail(self, product_id=1):
        return self.call(f'inventory/{product_id}').json['product']

    def inventory_state(self, product_id):
        product = self.detail(product_id)
        # Family-wide color summaries legitimately reflect received sibling SKUs.
        return {key: product[key] for key in ('stock', 'version', 'sizePrices')}

    def preview(self, ids=(1, 2), source='normal', role='admin'):
        return self.call(f'inventory/batch/preview?ids={",".join(map(str, ids))}&source={source}', role=role)

    def body(self, ids=(1, 2), source='normal'):
        return {'requestId': str(uuid.uuid4()), 'items': [
            {'productId': p['id'], 'version': p['version']} for p in self.preview(ids, source).json['items']]}

    def execute(self, body, source='normal', role='admin'):
        suffix = {'normal': 'receive', 'temporary': 'temporary/receive', 'defective': 'defective/return'}[source]
        return self.call('inventory/batch/' + suffix, 'POST', body, role)

    def register(self, product_id, **values):
        response = self.call(f'inventory/{product_id}', 'PUT', {'version': self.detail(product_id)['version'], 'sizeStocks': {}, **values})
        self.assertEqual(response.status_code, 200, response.json)

    def test_preview_and_receive_only_selected_products(self):
        before = self.inventory_state(3)
        preview = self.preview((2, 1)).json
        self.assertEqual([p['id'] for p in preview['items']], [1, 2])
        self.assertEqual(preview['units'], 12)
        result = self.execute(self.body((2, 1)))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['processedProducts'], 2)
        self.assertEqual(result.json['units'], 12)
        self.assertEqual(self.inventory_state(3), before)
        for product_id in (1, 2):
            sizes = {s['sizeCode']: s for s in self.detail(product_id)['sizePrices']}
            self.assertEqual(sizes['M']['stock'], 14)
            self.assertEqual(sizes['M']['pendingInbound'], 0)
            self.assertEqual(sizes['M']['pendingInspection'], 6)

    def test_temporary_and_defective_sources_do_not_mix(self):
        for i in (1, 2):
            self.register(i, defectivePendingBySize={'M': 3}, temporaryInboundBySize={'L': 4})
        before_stock = self.detail()['stock']
        result = self.execute(self.body(source='defective'), 'defective')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['units'], 6)
        for i in (1, 2):
            sizes = {s['sizeCode']: s for s in self.detail(i)['sizePrices']}
            self.assertEqual(sizes['M']['contractPending'], 15)
            self.assertEqual(sizes['M']['pendingInspection'], 3)
            self.assertEqual(sizes['M']['defectivePending'], 0)
            self.assertEqual(sizes['M']['pendingInbound'], 4)
            self.assertEqual(sizes['L']['temporaryInbound'], 4)
            self.assertEqual(self.detail(i)['stock'], before_stock)
            logs = self.call(f'inventory/{i}/operations').json
            self.assertEqual(logs['total'], 2)
        result = self.execute(self.body(source='temporary'), 'temporary')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['units'], 8)
        self.assertEqual(self.detail()['stock'], before_stock + 4)
        self.assertEqual(sum(s['pendingInbound'] for s in self.detail()['sizePrices']), 6)

    def test_zero_quantities_skip_and_empty_selection_does_not_write(self):
        self.register(2, pendingInboundBySize={'M': 0, 'L': 0})
        before = self.inventory_state(2)
        result = self.execute(self.body())
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['skippedProductIds'], [2])
        self.assertEqual(self.inventory_state(2), before)
        count = db._fetch_one('SELECT COUNT(*) AS n FROM inventory_receipts')['n']
        response = self.execute(self.body((1, 2)))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM inventory_receipts')['n'], count)

    def test_stale_one_product_rolls_back_entire_selection(self):
        body = self.body()
        self.register(2, temporaryInboundBySize={'M': 1})
        before = [self.detail(i) for i in (1, 2)]
        response = self.execute(body)
        self.assertEqual(response.status_code, 409, response.json)
        self.assertEqual([self.detail(i) for i in (1, 2)], before)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM inventory_receipts')['n'], 0)

    def test_overflow_in_later_product_rolls_back_prior_product_and_receipts(self):
        self.register(2, sizeStocks={'M': 2147483647, 'L': -20})
        before = [self.detail(i) for i in (1, 2)]
        response = self.execute(self.body())
        self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual([self.detail(i) for i in (1, 2)], before)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM inventory_receipts')['n'], 0)

    def test_duplicate_replay_and_request_namespace(self):
        body = self.body()
        first = self.execute(body)
        self.assertEqual(first.status_code, 200, first.json)
        after = [self.detail(i) for i in (1, 2)]
        count = db._fetch_one('SELECT COUNT(*) AS n FROM inventory_receipts')['n']
        repeat = self.execute(body)
        self.assertEqual(repeat.status_code, 200, repeat.json)
        self.assertTrue(repeat.json['replayed'])
        self.assertEqual([self.detail(i) for i in (1, 2)], after)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM inventory_receipts')['n'], count)
        self.assertEqual(self.execute(body, 'temporary').status_code, 400)
        self.assertEqual(self.execute(body, role='warehouse').status_code, 400)
        changed = {**body, 'items': body['items'][:1]}
        self.assertEqual(self.execute(changed).status_code, 400)

    def test_concurrent_same_request_commits_once(self):
        body = self.body()
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.execute(body), range(2)))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 200])
        self.assertEqual(sum(bool(r.json.get('replayed')) for r in responses), 1)
        self.assertEqual(self.detail()['stock'], 36)

    def test_defect_log_failure_rolls_back_entire_selection(self):
        for i in (1, 2): self.register(i, defectivePendingBySize={'M': 2})
        body = self.body(source='defective')
        before = [self.detail(i) for i in (1, 2)]
        original = workbench.record_inventory_registration
        def fail_second(old, new, **kwargs):
            if old['id'] == 2: raise ValueError('日志暂不可写入')
            return original(old, new, **kwargs)
        with patch.object(workbench, 'record_inventory_registration', side_effect=fail_second):
            response = self.execute(body, 'defective')
        self.assertEqual(response.status_code, 400)
        self.assertEqual([self.detail(i) for i in (1, 2)], before)
        for i in (1, 2): self.assertEqual(self.call(f'inventory/{i}/operations').json['total'], 1)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM inventory_receipts')['n'], 0)

    def test_validation_permissions_and_inactive_products(self):
        for role in ('admin', 'sales', 'warehouse'):
            self.assertEqual(self.preview(role=role).status_code, 200)
        self.assertEqual(self.preview(role='customer').status_code, 403)
        body = self.body()
        self.assertEqual(self.execute(body, role='customer').status_code, 403)
        for invalid in [[], [{'productId': 1}], [{'productId': True, 'version': 'x'}], body['items'] * 2,
                        [{'productId': 999999, 'version': 'x'}]]:
            self.assertIn(self.execute({**body, 'items': invalid}).status_code, (400, 409))
        for ids in ((1, 1), (999999,), (0,)):
            self.assertEqual(self.preview(ids).status_code, 400)
        db._fetch_one('UPDATE products SET is_active=FALSE WHERE id=1 RETURNING id')
        self.assertEqual(self.execute(self.body((1,))).status_code, 200)
        user = db._fetch_one("SELECT id FROM admin_users WHERE role='warehouse'")
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE id=%s RETURNING id", (user['id'],))
        self.assertEqual(self.preview(role='warehouse').status_code, 403)


if __name__ == '__main__': unittest.main()
