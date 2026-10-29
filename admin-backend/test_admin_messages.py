"""Admin feedback at the actual Flask response boundary; no database is used."""
import ast
import os
from pathlib import Path
import re
import unittest
from unittest.mock import Mock, patch

from flask import Flask, Response, g, jsonify

import admin_messages
import request_telemetry
from security_core import Security


CHINESE = re.compile(r'[\u3400-\u9fff]')


class AdminMessagesTest(unittest.TestCase):
    def setUp(self):
        # Instantiate the real Security.after in the same registration order as
        # app.py, while replacing authentication, metrics, and all DB access.
        self.env = patch.dict(os.environ, {
            'APP_ENV': 'local',
            'SECURITY_SECRET': 'fixture-security-key-0123456789-abcdef',
            'SECURITY_ATTACHMENT_MODE': 'legacy',
            'SECURITY_ADMIN_CAPTCHA_ENABLED': '0',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.enterContext(patch('request_telemetry.record'))
        self.db = Mock()
        self.app = Flask('admin-message-fixture')
        admin_messages.register(self.app)
        security = Security(self.app, self.db, 'admin')
        security.record = Mock()
        self.app.before_request_funcs[None].clear()
        self.app.before_request(request_telemetry.start)
        self.payload = {}
        self.status = 200
        self.headers = {}
        self.flags = {}
        self.binary = None
        self.content_type = None

        def fixture():
            for key, value in self.flags.items():
                setattr(g, key, value)
            response = (Response(self.binary, content_type=self.content_type)
                        if self.binary is not None else jsonify(self.payload))
            response.status_code = self.status
            response.headers.update(self.headers)
            return response

        paths = (
            '/api/admin/probe',
            '/api/admin/uploads',
            '/api/admin/inventory/import/preview',
            '/api/admin/size-charts/import/preview',
            '/api/admin/finance/costs/import/preview',
            '/api/admin/orders/export-results/fixture',
            '/api/admin/orders/1/invoice',
            '/api/auth/admin/login',
            '/api/auth/me',
            '/api/auth/csrf',
            '/api/attachments/fixture',
            '/api/security/probe',
            '/api/external/probe',
            '/api/internal/probe',
            '/api/public/probe',
            '/api/store/probe',
            '/api/administer/probe',
            '/uploads/fixture',
            '/media/products/fixture',
        )
        for index, path in enumerate(paths):
            self.app.add_url_rule(path, f'fixture_{index}', fixture)
        # Security already registers this route before the fixture rule.
        self.app.view_functions['security_csrf'] = fixture
        self.client = self.app.test_client()

    def tearDown(self):
        self.assertEqual(self.db.mock_calls, [], 'The response tests must not access a database')

    def test_http_error_statuses_keep_code_headers_and_business_values(self):
        cases = (
            (400, 'Invalid file count', {}),
            (401, 'Invalid email or password', {}),
            (403, 'Forbidden', {}),
            (409, 'The signed-in account changed. Reload this page.', {}),
            (410, 'Not found', {}),
            (413, 'Request is too large.', {}),
            (429, 'Too many requests. Try again later.', {}),
            (502, '图片读取失败，请重试导出。', {'security_export_image_failure': True}),
            (503, 'The service is busy. Please try again later.', {'security_database_busy': True}),
            (504, '导出超时，请减少订单数量后重试。', {'security_export_timeout': True}),
        )
        business_data = {'name': 'Slim Fit', 'message': 'Forbidden', 'sku': 'ST-42'}
        for status, message, flags in cases:
            with self.subTest(status=status):
                self.status, self.flags = status, flags
                self.headers = {'Retry-After': '17', 'X-Fixture': 'unchanged'}
                code = {502: 'export_image_unavailable', 504: 'export_timeout'}.get(status, 'fixture_code')
                self.payload = {'message': message, 'code': code, 'data': business_data, 'position': 2}
                response = self.client.get('/api/admin/probe')
                self.assertEqual(response.status_code, status)
                self.assertRegex(response.json['message'], CHINESE)
                self.assertEqual(response.json['code'], code)
                self.assertEqual(response.json['data'], business_data)
                self.assertEqual(response.json['position'], 2)
                self.assertEqual(response.headers['Retry-After'], '17')
                self.assertEqual(response.headers['X-Fixture'], 'unchanged')

    def test_translation_runs_after_security_masks_unexpected_5xx(self):
        self.status = 500
        self.payload = {'code': 'private', 'message': 'a private failure'}
        response = self.client.get('/api/admin/probe')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json['code'], 'service_error')
        self.assertRegex(response.json['message'], CHINESE)
        self.assertNotIn('private', str(response.json))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_dynamic_identifiers_survive_translation(self):
        cases = (
            ('Product SKU already exists: ST-42', 'ST-42', '商品'),
            ('Product slug already exists: slim-jean', 'slim-jean', '商品'),
            ('Product code already exists: GT-123', 'GT-123', '商品'),
            ('Invalid size price for Tall XL', 'Tall XL', '价格'),
            ('Duplicate sizeCode: XXL', 'XXL', '尺码'),
            ('Unknown sizes: XS, Tall XL', 'XS, Tall XL', '尺码'),
            ('Product or size not found: 42 / Tall XL', '42 / Tall XL', '尺码'),
            ('Inventory conflict for 42 / XXL', '42 / XXL', '库存'),
            ('Contract pending conflict for 42 / XXL', '42 / XXL', '合同'),
            ('Identity changed for 42 / XXL: sku, stock', '42 / XXL', '变化'),
            ('Missing field: variants[1].imageUrls', 'variants[1]', '图片'),
        )
        for original, value, meaning in cases:
            with self.subTest(original=original):
                self.status = 400
                self.payload = {'message': original}
                message = self.client.get('/api/admin/probe').json['message']
                self.assertIn(value, message)
                self.assertIn(meaning, message)

    def test_attachment_rejections_remain_distinct_and_specific(self):
        cases = (
            ('Select one PDF file', 'PDF'),
            ('Only supported images and PDF files are allowed', 'PDF'),
            ('Attachment size exceeds the limit', '大小'),
            ('File content is invalid or unsupported', '内容'),
        )
        self.status = 400
        messages = []
        for original, meaning in cases:
            with self.subTest(original=original):
                self.payload = {'message': original}
                message = self.client.get('/api/admin/uploads').json['message']
                self.assertRegex(message, CHINESE)
                self.assertIn(meaning, message)
                messages.append(message)
        self.assertEqual(len(set(messages)), len(cases))

    def test_image_delivery_errors_keep_specific_reasons(self):
        for path in ('/uploads/fixture', '/media/products/fixture'):
            for status, original, meaning in (
                (413, 'Image dimensions are too large', '尺寸'),
                (503, 'Image storage temporarily unavailable', '存储'),
            ):
                with self.subTest(path=path, status=status):
                    self.status, self.payload = status, {'message': original}
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, status)
                    self.assertIn(meaning, response.json['message'])

    def test_mixed_technical_field_labels_in_validation_are_readable(self):
        cases = (
            ('requestId 必须为 UUID', '请求编号', 'UUID'),
            ('eventIds 最多包含 100 个有效事件编号', '事件编号', '100'),
            ('ST-42 / Tall XL：contractPending 已在线上变更', '合同未送', 'ST-42 / Tall XL'),
        )
        self.status = 400
        for original, meaning, value in cases:
            with self.subTest(original=original):
                self.payload = {'message': original}
                message = self.client.get('/api/admin/probe').json['message']
                self.assertIn(meaning, message)
                self.assertIn(value, message)

    def test_preview_errors_preserve_rows_and_nested_business_objects(self):
        self.payload = {
            'errors': [
                {'row': 7, 'styleCode': 'ST-42', 'sheet': 'Slim Fit', 'message': 'Duplicate sizeCode: Tall XL'},
                'Product not found',
            ],
            'warnings': [{'row': 8, 'message': 'Unknown sizes: XS, Tall XL', 'customer': {'name': 'Alex'}}],
            'items': [{'name': 'Slim Fit', 'message': 'Forbidden', 'errors': ['Product not found']}],
        }
        for path in ('/api/admin/inventory/import/preview', '/api/admin/size-charts/import/preview'):
            with self.subTest(path=path):
                data = self.client.get(path).json
                self.assertEqual((data['errors'][0]['row'], data['errors'][0]['styleCode'], data['errors'][0]['sheet']), (7, 'ST-42', 'Slim Fit'))
                self.assertIn('Tall XL', data['errors'][0]['message'])
                self.assertRegex(data['errors'][0]['message'], CHINESE)
                self.assertRegex(data['errors'][1], CHINESE)
                self.assertIn('XS, Tall XL', data['warnings'][0]['message'])
                self.assertEqual(data['warnings'][0]['customer'], {'name': 'Alex'})
                self.assertEqual(data['items'], self.payload['items'])

    def test_finance_preview_only_changes_error_feedback(self):
        self.payload = {'rows': [
            {'rowNumber': 2, 'styleCode': 'Slim Fit', 'status': 'error', 'message': 'Invalid file count'},
            {'rowNumber': 3, 'styleCode': 'ST-42', 'status': 'same', 'message': '相同跳过'},
        ]}
        data = self.client.get('/api/admin/finance/costs/import/preview').json
        self.assertIn('文件', data['rows'][0]['message'])
        self.assertEqual(data['rows'][0]['styleCode'], 'Slim Fit')
        self.assertEqual(data['rows'][1], self.payload['rows'][1])

    def test_success_feedback_is_translated_but_values_and_pdf_are_unchanged(self):
        self.payload = {
            'message': 'Product created',
            'status': 'ok',
            'product': {'name': 'Slim Fit', 'message': 'Forbidden'},
            'customer': {'name': 'Alex Morgan', 'companyName': 'Northline Apparel'},
        }
        self.status = 201
        response = self.client.get('/api/admin/probe')
        self.assertEqual(response.json['message'], '商品已创建')
        self.assertEqual(response.json['status'], 'ok')
        self.assertEqual(response.json['product'], self.payload['product'])
        self.assertEqual(response.json['customer'], self.payload['customer'])
        self.binary = b'%PDF-1.4\nInvoice: Slim Fit / Alex Morgan\n%%EOF'
        self.content_type = 'application/pdf'
        self.status = 200
        self.headers = {'Content-Disposition': 'attachment; filename=invoice.pdf'}
        response = self.client.get('/api/admin/orders/1/invoice')
        self.assertEqual(response.data, self.binary)
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertEqual(response.headers['Content-Disposition'], self.headers['Content-Disposition'])

    def test_failed_result_in_200_response_is_error_not_success(self):
        self.payload = {'status': 'failed', 'code': 'export_failed', 'message': 'Another export is in progress. Try again later.'}
        data = self.client.get('/api/admin/orders/export-results/fixture').json
        self.assertEqual((data['status'], data['code']), ('failed', 'export_failed'))
        self.assertRegex(data['message'], CHINESE)

    def test_non_admin_channels_are_untouched(self):
        self.status = 403
        self.payload = {'code': 'fixture_code', 'message': 'Forbidden', 'product': {'name': 'Slim Fit'}}
        for path in ('/api/external/probe', '/api/internal/probe', '/api/public/probe', '/api/store/probe', '/api/administer/probe'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json, self.payload)

    def test_admin_security_and_attachment_paths_translate(self):
        self.status = 403
        self.payload = {'message': 'Forbidden', 'code': 'fixture_code'}
        for path in ('/api/admin/probe', '/api/auth/admin/login', '/api/auth/me', '/api/auth/csrf', '/api/attachments/fixture', '/api/security/probe'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertRegex(response.json['message'], CHINESE)
                self.assertEqual(response.json['code'], 'fixture_code')

    def test_known_chinese_and_unknown_error_fallback(self):
        self.status = 400
        chinese = '商品 SKU-01 已在线上变更，请核对'
        self.payload = {'message': chinese}
        self.assertEqual(self.client.get('/api/admin/probe').json['message'], chinese)
        self.payload = {'message': 'An unmapped English fixture error', 'code': 'fixture'}
        response = self.client.get('/api/admin/probe')
        self.assertRegex(response.json['message'], CHINESE)
        self.assertEqual(response.json['code'], 'fixture')

    def test_direct_admin_error_literals_have_specific_mappings(self):
        """Audit only literal error responses in admin routes, not all English code.

        Dynamic validations and messages carried in exceptions are covered by
        the representative cases above; external API and internal exception
        contracts deliberately remain outside this static inventory.
        """
        tree = ast.parse((Path(__file__).parent / 'app.py').read_text(encoding='utf-8'))
        fallback = admin_messages.translate_message('An unmapped English fixture error', is_error=True)
        audited = set()
        for function in tree.body:
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes = [decorator.args[0].value for decorator in function.decorator_list
                      if isinstance(decorator, ast.Call) and decorator.args
                      and isinstance(decorator.args[0], ast.Constant)
                      and isinstance(decorator.args[0].value, str)
                      and decorator.args[0].value.startswith(('/api/admin/', '/api/auth/admin/', '/api/attachments/', '/api/security/'))]
            if not routes:
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Tuple) or len(node.value.elts) < 2:
                    continue
                body, status = node.value.elts[:2]
                if not isinstance(status, ast.Constant) or not isinstance(status.value, int) or status.value < 400:
                    continue
                if not (isinstance(body, ast.Call) and isinstance(body.func, ast.Name) and body.func.id == 'jsonify'
                        and body.args and isinstance(body.args[0], ast.Dict)):
                    continue
                for key, value in zip(body.args[0].keys, body.args[0].values):
                    if not (isinstance(key, ast.Constant) and key.value == 'message'
                            and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                        continue
                    original = value.value
                    if not re.search(r'[A-Za-z]{3}', original) or CHINESE.search(original):
                        continue
                    audited.add(original)
                    with self.subTest(route=routes[0], line=node.lineno, message=original):
                        translated = admin_messages.translate_message(original, is_error=True)
                        self.assertRegex(translated, CHINESE)
                        self.assertNotEqual(translated, fallback)
        self.assertIn('Invalid file count', audited)
        self.assertIn('Product not found', audited)


if __name__ == '__main__':
    unittest.main()
