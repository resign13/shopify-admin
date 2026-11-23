import unittest
from unittest.mock import patch

import inventory_policy
import order_stock_cutover as cutover
from test_workbench import db, seed


class OrderStockCutoverTest(unittest.TestCase):
    def setUp(self):
        seed()
        self.clear_marker()
        self.addCleanup(self.clear_marker)

    def clear_marker(self):
        with db.get_connection() as conn:
            conn.execute('DELETE FROM inventory_policy_versions WHERE version=%s',
                         (inventory_policy.ORDER_STOCK_ON_PAYMENT_VERSION,))

    def sizes(self):
        return {row['product_id']: row['stock'] for row in db._fetch_all(
            "SELECT product_id,stock FROM product_size_prices WHERE size_code='M'"
        )}

    def test_read_only_review_then_release_only_pending_once(self):
        initial = self.sizes()
        report = cutover.preview()
        self.assertEqual(self.sizes(), initial)
        self.assertFalse(report['alreadyApplied'])
        self.assertEqual(report['needsReview'], [])
        self.assertEqual([order['orderNo'] for order in report['orders']], ['GT202609180002'])
        self.assertEqual([(r['before'],r['release'],r['after']) for r in report['balances']],
                         [(initial[1], 2, initial[1]+2), (initial[2], 1, initial[2]+1)])

        expected = {**initial, 1: initial[1]+2, 2: initial[2]+1}
        self.assertEqual(cutover.apply(report),
                         {'alreadyApplied':False, 'ordersReleased':1, 'unitsReleased':3})
        self.assertEqual(self.sizes(), expected)
        self.assertTrue(cutover.preview()['alreadyApplied'])
        self.assertTrue(cutover.apply(report)['alreadyApplied'])
        self.assertEqual(self.sizes(), expected)
        for order_id, returns_stock in [(1,True), (2,False), (3,False), (4,True)]:
            row = db.get_order_by_id(order_id)
            self.assertTrue(row['stockOnPaymentEnabled'])
            self.assertEqual(row['cancelReturnsStock'], returns_stock)

    def test_changed_order_and_unmapped_size_block_entire_cutover(self):
        initial = self.sizes()
        before = cutover.preview()
        with db.get_connection() as conn:
            conn.execute("UPDATE orders SET status='partially_allocated' WHERE id=2")
        with self.assertRaisesRegex(ValueError, '清单不一致'):
            cutover.apply(before)
        with db.get_connection() as conn:
            conn.execute("UPDATE orders SET status='pending_payment' WHERE id=2")
            conn.execute("UPDATE order_items SET size_code='archived' WHERE order_id=2 AND product_id=1")
        needs_review = cutover.preview()
        self.assertEqual(needs_review['needsReview'][0]['sizeCode'], 'archived')
        with self.assertRaisesRegex(ValueError, '需要核对'):
            cutover.apply(needs_review)
        self.assertEqual(self.sizes(), initial)
        self.assertFalse(cutover.preview()['alreadyApplied'])

    def test_empty_preview_still_activates_both_applications(self):
        initial = self.sizes()
        with db.get_connection() as conn:
            conn.execute("UPDATE orders SET status='paid' WHERE status='pending_payment'")
        review = cutover.preview()
        self.assertEqual(review['orders'], [])
        self.assertEqual(cutover.apply(review)['unitsReleased'], 0)
        self.assertEqual(self.sizes(), initial)
        self.assertTrue(cutover.preview()['alreadyApplied'])

    def test_post_apply_mismatch_never_sets_marker(self):
        initial = self.sizes()
        review = cutover.preview()
        with patch.object(inventory_policy, 'adjust_stock'):
            with self.assertRaisesRegex(ValueError, '实际回补后的尺码库存'):
                cutover.apply(review)
        self.assertFalse(cutover.preview()['alreadyApplied'])
        self.assertEqual(self.sizes(), initial)
