"""Payment-time inventory lifecycle, using the guarded local *_test database."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_orders as helpers
from test_workbench import db
import test_order_cancellation_approval as approval_helpers
import test_order_drafts as draft_helpers


class PaymentStockTest(unittest.TestCase):
    call = helpers.AdminOrdersTest.call
    payload = helpers.AdminOrdersTest.payload
    create = helpers.AdminOrdersTest.create
    stock = helpers.AdminOrdersTest.stock
    stage = approval_helpers.CancellationApprovalTest.stage
    detail = approval_helpers.CancellationApprovalTest.detail
    submit = approval_helpers.CancellationApprovalTest.submit
    decision = approval_helpers.CancellationApprovalTest.decision
    save_draft = draft_helpers.OrderDraftsTest.save
    draft_submit_body = draft_helpers.OrderDraftsTest.submit_body

    def setUp(self):
        helpers.AdminOrdersTest.setUp(self)
        db._fetch_one("INSERT INTO inventory_policy_versions(version) VALUES('order-stock-on-payment-v1') ON CONFLICT DO NOTHING RETURNING version")

    def tearDown(self):
        db._fetch_one("DELETE FROM inventory_policy_versions WHERE version='order-stock-on-payment-v1' RETURNING version")

    def balances(self):
        return {r['sizeCode']: r['stock'] for r in self.stock()['sizePrices']}

    def edit(self, order, **updates):
        body = copy.deepcopy(order)
        body.update(updates)
        response = self.call(f"orders/{order['id']}/details", 'PUT', body)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json['order']

    def test_new_pending_and_pending_edit_do_not_reserve(self):
        self.assertTrue(self.call('catalog-options').json['stockOnPaymentEnabled'])
        order = self.create()
        self.assertEqual(self.stock()['stock'], 30)
        lines = copy.deepcopy(order['items'])
        lines[0]['quantity'] = 8
        order = self.edit(order, items=lines)
        self.assertEqual(self.stock()['stock'], 30)
        order = self.stage(order, 'paid')
        self.assertEqual(self.balances(), {'M': 2, 'L': 7, 'Tall XL': 10})
        for status in ('paid', 'partially_allocated', 'allocated', 'shipped', 'completed'):
            order = self.stage(order, status)
            self.assertEqual(self.balances(), {'M': 2, 'L': 7, 'Tall XL': 10})

    def test_draft_conversion_and_replay_do_not_reserve_until_payment(self):
        before = self.balances()
        saved, _ = self.save_draft(self.payload())
        self.assertEqual(self.balances(), before)
        body = self.draft_submit_body(saved)
        first = self.call('orders', 'POST', body, 'sales')
        retry = self.call('orders', 'POST', body, 'sales')
        self.assertEqual((first.status_code, retry.status_code), (200, 200), (first.json, retry.json))
        self.assertEqual(first.json['order']['status'], 'pending_payment')
        self.assertTrue(retry.json['replayed'])
        self.assertEqual(self.balances(), before)
        self.stage(first.json['order'], 'paid')
        self.assertEqual(self.stock()['stock'], sum(before.values())-5)

    def test_direct_status_jumps_each_deduct_once(self):
        for status in ('paid', 'partially_allocated', 'allocated', 'shipped', 'completed'):
            with self.subTest(status=status):
                before = self.stock()['stock']
                order = self.create()
                self.assertEqual(self.stock()['stock'], before)
                order = self.stage(order, status)
                self.assertEqual(self.stock()['stock'], before - 5)
                self.stage(order, status)
                self.assertEqual(self.stock()['stock'], before - 5)

    def test_combined_status_and_item_edit_uses_final_quantity_once(self):
        order = self.create()
        lines = copy.deepcopy(order['items'])
        lines[0]['quantity'] = 4
        lines[1]['quantity'] = 1
        order = self.edit(order, status='partially_allocated', items=lines)
        self.assertEqual(self.balances(), {'M': 6, 'L': 9, 'Tall XL': 10})
        lines[0]['quantity'] = 7
        lines[1]['quantity'] = 2
        order = self.edit(order, items=lines)
        self.assertEqual(self.balances(), {'M': 3, 'L': 8, 'Tall XL': 10})
        order = self.edit(order, note='no stock change', address='Another address')
        self.assertEqual(self.balances(), {'M': 3, 'L': 8, 'Tall XL': 10})
        order = self.edit(order, status='pending_payment')
        self.assertEqual(self.balances(), {'M': 10, 'L': 10, 'Tall XL': 10})
        order = self.stage(order, 'partially_allocated')
        self.assertEqual(self.balances(), {'M': 3, 'L': 8, 'Tall XL': 10})

    def test_paid_item_size_change_returns_old_and_deducts_new(self):
        order = self.stage(self.create(), 'paid')
        lines = copy.deepcopy(order['items'])
        lines[0]['sizeCode'] = 'Tall XL'
        order = self.edit(order, items=lines)
        self.assertEqual(self.balances(), {'M': 10, 'L': 7, 'Tall XL': 8})

    def test_cancel_pending_restore_and_delete_never_returns_unspent_stock(self):
        order = self.stage(self.create(), 'cancelled')
        self.assertEqual(self.stock()['stock'], 30)
        order = self.stage(order, 'pending_payment')
        self.assertEqual(self.stock()['stock'], 30)
        response = self.call('orders', 'DELETE', {'orderIds': [order['id']]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.stock()['stock'], 30)

    def test_mixed_delete_only_returns_partial_and_cancelled_restores_once(self):
        pending = self.create()
        partial = self.stage(self.create(), 'partially_allocated')
        cancelled = self.stage(self.stage(self.create(), 'partially_allocated'), 'cancelled')
        self.assertEqual(self.stock()['stock'], 25)
        cancelled = self.stage(cancelled, 'partially_allocated')
        self.assertEqual(self.stock()['stock'], 20)
        cancelled = self.stage(cancelled, 'cancelled')
        response = self.call('orders', 'DELETE', {'orderIds': [pending['id'], partial['id'], cancelled['id']]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.stock()['stock'], 30)

    def test_approval_defers_stock_and_only_returns_once(self):
        order = self.stage(self.create(), 'paid')
        item = self.submit(order)
        self.assertEqual(self.stock()['stock'], 25)
        response = self.decision(item)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.stock()['stock'], 30)
        self.assertEqual(self.decision(item).status_code, 409)
        self.assertEqual(self.stock()['stock'], 30)
        self.stage(self.detail(order['id']), 'paid')
        self.assertEqual(self.stock()['stock'], 25)

    def test_concurrent_payment_only_one_transition_and_no_double_deduction(self):
        order = self.create()
        def pay(_):
            return self.call(f"orders/{order['id']}", 'PUT', {'version': order['version'], 'status': 'paid'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(pay, range(2)))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        self.assertEqual(self.stock()['stock'], 25)

    def test_competing_orders_record_negative_stock_as_shortage(self):
        orders = []
        for quantity in (8, 6):
            payload = self.payload()
            payload['items'] = [{'productId': 1, 'sizeCode': 'M', 'quantity': quantity, 'unitPrice': 20}]
            response = self.call('orders', 'POST', payload)
            self.assertEqual(response.status_code, 200, response.json)
            orders.append(response.json['order'])
        self.assertEqual(self.balances()['M'], 10)
        for order in orders:
            self.stage(order, 'paid')
        self.assertEqual(self.balances()['M'], -4)


if __name__ == '__main__':
    unittest.main()
