"""Dashboard API regressions; test_workbench guards the isolated local *_test database."""
import unittest
from urllib.parse import urlencode

from test_workbench import seed, application, db


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tokens, self.products = seed()
        application.app.config['TESTING'] = True

    def call(self, view='style-performance', role='admin', **params):
        query = {'view': view, 'dateFrom': '2026-09-18', 'dateTo': '2026-09-18', **params}
        with application.app.test_client() as client:
            headers = {'Authorization': 'Bearer ' + self.tokens[role]} if role else {}
            return client.get('/api/admin/dashboard?' + urlencode(query), headers=headers)

    def data(self, view='style-performance', **params):
        response = self.call(view, **params)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def product(self, code, stock=10, category='outerwear', **extra):
        product = db.create_product({
            'categoryKey': category, 'productCode': code + '-BLUE', 'sku': code + '-BLUE',
            'slug': code.lower(), 'familyCode': code, 'colorGroup': code, 'colorName': '蓝色',
            'title': code, 'sizes': ['M'], 'sizePrices': [{'sizeCode': 'M', 'price': 10, 'stock': stock}],
            'image': '/uploads/fixture.jpg',
            **extra,
        })
        return product

    def order(self, product, quantity, created='2026-09-18 10:00:00+00', country='Germany',
              status='paid', price=10, size='M'):
        order = db._fetch_one(
            'INSERT INTO orders(order_no,store_user_id,status,contact_name,phone,country,'
            'shipping_address,total_amount,shipping_fee,created_at) '
            "VALUES('DASH-' || nextval('orders_id_seq'),1,%s,'Fixture','123',%s,'Fixture',%s,0,%s) RETURNING id",
            (status, country, price * quantity, created),
        )
        self.line(order['id'], product, quantity, price, size)
        return order['id']

    def line(self, order_id, product, quantity, price=10, size='M'):
        db._fetch_one(
            'INSERT INTO order_items(order_id,product_id,product_name,sku,size_code,quantity,unit_price,total_price) '
            'VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (order_id, product['id'], product['sku'], product['sku'], size, quantity, price, price * quantity),
        )

    def test_period_country_timezone_and_cancelled_sales(self):
        data = self.data()
        row = data['items'][0]
        self.assertEqual((row['styleCode'], row['units'], row['orders'], row['customers']), ('GT-2026', 6, 2, 1))
        self.assertAlmostEqual(row['amount'], 179.4)
        self.assertEqual((row['velocityUnits'], row['stock'], row['colorSkuCount'], row['sizeCount']), (9, 90, 3, 9))
        self.assertEqual((row['contractPending'], row['pendingInspection'], row['pendingInbound']), (63, 27, 18))
        self.assertEqual((row['averageDailyUnits'], row['estimatedDays']), (1.29, 70))
        self.assertEqual(data['velocityWindow'], {'dateFrom': '2026-09-12', 'dateTo': '2026-09-18', 'days': 7})
        german = self.data(country='Germany')['items'][0]
        self.assertEqual((german['units'], german['velocityUnits'], german['orders']), (3, 3, 1))
        self.assertEqual(german['stock'], 90)
        self.assertEqual(self.data(country='all')['items'], data['items'])

    def test_style_color_size_totals_and_turnover_reconcile(self):
        style = self.data()['items'][0]
        detail = self.data('style-detail', styleCode='GT-2026')
        for key in ['units', 'amount', 'velocityUnits', 'stock', 'contractPending', 'pendingInspection', 'pendingInbound']:
            self.assertAlmostEqual(sum(color[key] for color in detail['items']), style[key], msg=key)
            for color in detail['items']:
                self.assertAlmostEqual(sum(size[key] for size in color['sizes']), color[key], msg=key)
        for color in detail['items']:
            result = self.data('style-size-detail', styleCode='GT-2026', productId=color['productId'])
            self.assertEqual(result['items'], color['sizes'])
            for size in color['sizes']:
                if size['velocityUnits']:
                    self.assertEqual(size['estimatedDays'], round(size['stock'] * 7 / size['velocityUnits'], 1))
                else:
                    self.assertIsNone(size['estimatedDays'])
                    self.assertEqual(size['risk'], 'no_sales')

    def test_global_style_sku_category_and_active_filter_options(self):
        coat = self.product('COAT', stock=7)
        self.product('UNSOLD', stock=12)
        hidden = self.product('HIDDEN')
        db._fetch_one('UPDATE products SET is_active=FALSE WHERE id=%s RETURNING id', (hidden['id'],))
        order_id = self.order(coat, 4)
        self.line(order_id, self.products[0], 2)
        all_data = self.data('workbench', country='all')
        self.assertEqual(all_data['filters']['styles'], ['COAT', 'GT-2026', 'UNSOLD'])
        self.assertEqual(all_data['metrics']['units'], 12)
        for style, units, amount in [('GT-2026', 8, 199.4), ('GT-2026-1', 6, 139.6), ('COAT', 4, 40)]:
            with self.subTest(style=style):
                data = self.data('workbench', style=style)
                self.assertEqual(data['metrics']['units'], units)
                self.assertAlmostEqual(data['metrics']['amount'], amount)
                self.assertEqual(self.data(style=style)['summary']['units'], units)
                self.assertTrue(all(any(item['productId'] in ([coat['id']] if style == 'COAT' else [1, 2])
                                        for item in order['items']) for order in data['recentOrders']))
        self.assertEqual(self.data('workbench', category='outerwear')['metrics']['units'], 4)
        self.assertEqual(self.data('workbench', category='denim')['metrics']['units'], 8)
        unmatched = self.data('workbench', style='COAT', category='denim')
        self.assertEqual(unmatched['metrics']['units'], 0)
        self.assertEqual(unmatched['recentOrders'], [])

    def test_category_keyword_and_country_persist_in_drilldown(self):
        params = {'category': 'denim', 'keyword': '水洗灰', 'country': 'Germany'}
        style = self.data(**params)['items'][0]
        detail = self.data('style-detail', styleCode='GT-2026', **params)
        self.assertEqual((style['colorSkuCount'], style['units'], style['stock']), (1, 1, 30))
        self.assertEqual([color['productId'] for color in detail['items']], [2])
        self.assertEqual((detail['items'][0]['units'], detail['items'][0]['velocityUnits']), (1, 1))
        self.assertEqual(self.data('style-size-detail', styleCode='GT-2026', productId=2, **params)['items'], detail['items'][0]['sizes'])
        self.assertEqual(self.data('style-size-detail', styleCode='GT-2026', productId=1, **params)['items'], [])
        self.assertEqual(self.data(category='outerwear')['total'], 0)

    def test_all_sort_columns_directions_and_nulls_last(self):
        coat = self.product('COAT', stock=7)
        self.order(coat, 4, price=100)
        self.product('ZERO', stock=0)
        self.product('UNSOLD', stock=12)
        for key in ['units', 'amount', 'stock', 'estimatedDays', 'lastSoldAt', 'styleCode', 'velocityUnits']:
            for direction in ['asc', 'desc']:
                with self.subTest(sort=key, direction=direction):
                    rows = self.data(sort=key, direction=direction)['items']
                    values = [row[key] for row in rows if row[key] is not None]
                    self.assertEqual(values, sorted(values, reverse=direction == 'desc'))
                    self.assertTrue(all(row[key] is None for row in rows[len(values):]))
                    for value in set(values):
                        tied = [row['styleCode'] for row in rows if row[key] == value]
                        self.assertEqual(tied, sorted(tied))

    def test_pagination_clamping_and_whole_filter_summary(self):
        for index in range(12):
            self.product(f'EXTRA-{index:02}', stock=index)
        first = self.data(page=1, pageSize=10, sort='styleCode', direction='asc')
        last = self.data(page=999, pageSize=10, sort='styleCode', direction='asc')
        self.assertEqual((first['total'], first['page'], len(first['items'])), (13, 1, 10))
        self.assertEqual((last['page'], len(last['items'])), (2, 3))
        self.assertEqual(first['summary'], last['summary'])
        self.assertEqual(first['summary'], {'styleCount': 13, 'units': 6, 'amount': 179.4, 'stock': 156,
                                           'availableStock': 156, 'shortageUnits': 0, 'shortageSizeCount': 0,
                                           'contractPending': 63, 'pendingInspection': 27, 'pendingInbound': 18})
        self.assertEqual(len({row['styleCode'] for row in first['items'] + last['items']}), 13)
        empty = self.data(keyword='does-not-exist', page=999)
        self.assertEqual((empty['page'], empty['total'], empty['items'], empty['summary']['stock']), (1, 0, [], 0))
        for size in [25, 50]:
            self.assertEqual(len(self.data(pageSize=size)['items']), 13)

    def test_zero_stock_no_sales_and_risk_filter_summary(self):
        zero = self.product('ZERO', stock=0)
        self.product('UNSOLD', stock=12)
        critical = self.product('CRITICAL', stock=1)
        self.order(critical, 7)
        warning = self.product('WARNING', stock=14)
        self.order(warning, 7)
        rows = {row['styleCode']: row for row in self.data()['items']}
        self.assertEqual(rows['ZERO']['risk'], 'out_of_stock')
        self.assertEqual(rows['UNSOLD']['risk'], 'no_sales')
        self.assertIsNone(rows['ZERO']['estimatedDays'])
        self.assertIsNone(rows['UNSOLD']['estimatedDays'])
        for risk in ['out_of_stock', 'no_sales', 'critical', 'warning', 'healthy']:
            data = self.data(risk=risk)
            self.assertEqual(data['total'], 1)
            self.assertTrue(all(row['risk'] == risk for row in data['items']))
            self.assertEqual(data['summary']['stock'], data['items'][0]['stock'])
        self.order(zero, 2)
        self.assertEqual(self.data(style='ZERO')['items'][0]['risk'], 'out_of_stock')

    def test_beijing_day_boundaries_and_velocity_end_date(self):
        p = self.products[0]
        for created, units in [('2026-09-17 15:59:59+00', 7), ('2026-09-17 16:00:00+00', 5),
                               ('2026-09-18 15:59:59+00', 11), ('2026-09-18 16:00:00+00', 13)]:
            self.order(p, units, created)
        self.order(p, 100, status='cancelled')
        data = self.data()
        self.assertEqual(data['items'][0]['units'], 22)
        self.assertEqual(data['items'][0]['velocityUnits'], 32)
        self.assertEqual(self.data('workbench')['metrics']['units'], 22)
        thirty = self.data(velocityWindow=30)
        self.assertEqual(thirty['velocityWindow']['dateFrom'], '2026-08-20')
        self.assertEqual(thirty['items'][0]['averageDailyUnits'], 1.07)
        self.assertEqual(thirty['items'][0]['estimatedDays'], 84.4)
        future = self.data(dateFrom='2026-10-01', dateTo='2026-10-01')['items'][0]
        self.assertEqual((future['units'], future['velocityUnits'], future['risk']), (0, 0, 'no_sales'))

    def test_style_precedence_and_legacy_fallback(self):
        explicit = self.product('PREFIX')
        legacy = self.product('LEGACY')
        db._fetch_one("UPDATE products SET style_code='  EXPLICIT  ',color_group='OTHER' WHERE id=%s RETURNING id", (explicit['id'],))
        db._fetch_one("UPDATE products SET style_code='',color_group=product_code WHERE id=%s RETURNING id", (legacy['id'],))
        self.order(explicit, 2)
        self.order(legacy, 3)
        styles = self.data('workbench')['filters']['styles']
        self.assertEqual(styles, ['EXPLICIT', 'GT-2026', 'LEGACY'])
        self.assertEqual(self.data('workbench', style='EXPLICIT')['metrics']['units'], 2)
        self.assertEqual(self.data(style='LEGACY')['items'][0]['units'], 3)
        self.assertEqual(self.data('style-detail', styleCode='EXPLICIT')['items'][0]['productId'], explicit['id'])

    def test_permissions_and_invalid_parameters(self):
        views = ['workbench', 'style-performance', 'style-detail', 'style-size-detail']
        for view in views:
            params = {'styleCode': 'GT-2026', 'productId': 1}
            self.assertEqual(self.call(view, role=None, **params).status_code, 401)
            self.assertEqual(self.call(view, role='sales', **params).status_code, 200)
            for role in ['warehouse', 'customer']:
                self.assertEqual(self.call(view, role=role, **params).status_code, 403)
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE role='sales' RETURNING id")
        self.assertEqual(self.call(role='sales').status_code, 403)
        for params in [{'page': 0}, {'page': 'x'}, {'pageSize': 11}, {'velocityWindow': 14},
                       {'velocityWindow': 'bad'}, {'risk': 'bad'}, {'dateFrom': 'bad'},
                       {'dateFrom': '2026-09-20'}, {'dateFrom': '2020-01-01'}]:
            with self.subTest(params=params):
                self.assertEqual(self.call(**params).status_code, 400)
        self.assertEqual(self.call('style-detail').status_code, 400)
        self.assertEqual(self.call('style-detail', styleCode='missing').status_code, 404)
        self.assertEqual(self.call('style-size-detail', styleCode='GT-2026', productId=-1).status_code, 400)
        self.assertEqual(self.call('style-size-detail', styleCode='GT-2026', productId='bad').status_code, 400)


if __name__ == '__main__':
    unittest.main()
