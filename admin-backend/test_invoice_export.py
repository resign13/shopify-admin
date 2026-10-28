"""Synthetic invoice export regression tests; no real order writes."""
import unittest
import os
from copy import copy, deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from unittest.mock import patch
from openpyxl import load_workbook
from PIL import Image
from flask.testing import FlaskClient
from test_workbench import application, db, seed


class InvoiceExportTest(unittest.TestCase):
    def setUp(self):
        # Registered/private storage tests remain for the later media phase.
        self.media_mode = patch.object(application.media, 'mode', 'private')
        self.media_mode.start(); self.addCleanup(self.media_mode.stop)
        self.cache_directory = TemporaryDirectory(prefix='invoice-export-cache-test-')
        self.addCleanup(self.cache_directory.cleanup)
        self.cache_settings = patch.dict(os.environ, {'ORDER_EXPORT_IMAGE_CACHE_DIR': self.cache_directory.name})
        self.cache_settings.start(); self.addCleanup(self.cache_settings.stop)
    def test_invoice_route_formats_file_without_changing_stock_or_access(self):
        tokens, _ = seed()
        owner_id = db.get_admin_user_by_email('sales@gingtto.test')['id']
        db._fetch_one('UPDATE orders SET owner_admin_id=%s,shipping_fee=15 WHERE id=1 RETURNING id', (owner_id,))
        before = db._fetch_all('SELECT product_id,size_code,stock FROM product_size_prices ORDER BY product_id,size_code')
        with application.app.test_client() as client, \
                patch.object(application, 'prefetch_export_images'), \
                patch.object(application, 'fetch_image_bytes', return_value=None):
            for role in ('admin', 'sales'):
                response = client.get('/api/admin/orders/1/invoice', headers={'Authorization': 'Bearer ' + tokens[role]})
                self.assertEqual(response.status_code, 200)
                self.assertIn('.xlsx', response.headers['Content-Disposition'])
                sheet = load_workbook(BytesIO(response.data)).active
                self.assertEqual(copy(sheet['I13'].font), copy(sheet['J13'].font))
                self.assertIn('$', sheet['I13'].number_format)
                self.assertEqual(sheet['A31'].value, '3.Transhipment: ALLOWED')
            for role in ('warehouse', 'customer'):
                self.assertEqual(client.get('/api/admin/orders/1/invoice', headers={'Authorization': 'Bearer ' + tokens[role]}).status_code, 403)
            self.assertEqual(client.get('/api/admin/orders/2/invoice', headers={'Authorization': 'Bearer ' + tokens['sales']}).status_code, 404)
            anonymous = FlaskClient(application.app, application.app.response_class)
            self.assertEqual(anonymous.get('/api/admin/orders/1/invoice').status_code, 401)
        self.assertEqual(db._fetch_all('SELECT product_id,size_code,stock FROM product_size_prices ORDER BY product_id,size_code'), before)

    def test_all_exports_include_note_and_all_nine_attachments(self):
        photo = BytesIO(); Image.new('RGB', (40, 60), '#335577').save(photo, format='PNG')
        order = {'orderNo': 'NINE-ATTACHMENTS', 'shippingFee': 10, 'note': 'Nine photo packing instructions',
                 'labelImageUrls': [f'/uploads/attachment-{i}.png' for i in range(9)],
                 'items': [{'productId': 1, 'sku': 'BLUE', 'sizeCode': 'M', 'quantity': 1, 'unitPrice': 20}]}
        for builder in [application.build_orders_export, application.build_orders_sheet_export, application.build_order_invoice_export]:
            with self.subTest(builder=builder.__name__), patch.object(application, 'fetch_image_bytes', side_effect=lambda url, **kwargs: photo.getvalue() if url else None):
                stream = builder(order if builder == application.build_order_invoice_export else [order])
                book = load_workbook(stream)
                baseline_order = {**order, 'labelImageUrls': []}
                baseline = load_workbook(builder(baseline_order if builder == application.build_order_invoice_export else [baseline_order]))
                self.assertEqual(sum(len(ws._images) for ws in book) - sum(len(ws._images) for ws in baseline), 9)
                self.assertTrue(any(order['note'] in str(c.value) for ws in book for row in ws for c in row))
                self.assertFalse(any('/uploads/attachment-' in str(c.value) for ws in book for row in ws for c in row))
                attachment_pictures = [pic for ws in book for pic in ws._images if pic.width == 40 and pic.height == 60]
                self.assertEqual(len(attachment_pictures), 9)
                self.assertEqual(len({pic.anchor._from.row for pic in attachment_pictures}), 1)
                positions = [(pic.anchor._from.col, pic.anchor._from.colOff) for pic in attachment_pictures]
                self.assertEqual(positions, sorted(set(positions)))


    def test_both_exports_embed_clear_images_and_reuse_downloads(self):
        seed()
        with TemporaryDirectory() as directory:
            Image.new('RGB', (2400, 3200), '#335577').save(Path(directory) / 'fixture.jpg')
            application.media.register_legacy('https://img.smawell.shop/uploads/fixture.jpg',
                (Path(directory) / 'fixture.jpg').read_bytes(), purpose='product', entity_type='product', entity_id=1)
            order = {'orderNo': 'IMAGE-FIXTURE', 'items': [
                {'sku': 'SKU-1', 'productName': 'Fixture', 'image': 'https://img.smawell.shop/uploads/fixture.jpg',
                 'sizeCode': size, 'quantity': 1, 'unitPrice': 20}
                for size in ['S', 'M', 'L']
            ]}
            for index, builder in enumerate((application.build_orders_export, application.build_orders_sheet_export)):
                with self.subTest(export=builder.__name__), patch.object(application, 'UPLOAD_DIR', Path(directory)), \
                        application.app.test_request_context('/api/admin/orders/export'):
                    with patch.object(application.media, 'read', wraps=application.media.read) as read:
                        stream = builder([order])
                        self.assertEqual(read.call_count, 1 if index == 0 else 0)
                    with ZipFile(stream) as archive:
                        media = [name for name in archive.namelist() if name.startswith('xl/media/')]
                        self.assertEqual(len(media), 1)
                        for name in media:
                            content = archive.read(name)
                            self.assertLess(len(content), 50000)
                            with Image.open(BytesIO(content)) as image:
                                self.assertEqual(image.width, 480)
                                self.assertEqual(image.height, 640)

    def test_attachment_quality_is_independent_of_product_thumbnail(self):
        tokens, _ = seed()
        with TemporaryDirectory() as directory:
            Image.new('RGB', (2400, 3200), '#335577').save(Path(directory) / 'large.jpg')
            url = '/uploads/large.jpg'
            raw = (Path(directory) / 'large.jpg').read_bytes()
            application.media.register_legacy(url, raw, purpose='product', entity_type='product', entity_id=1)
            application.media.register_legacy(url, raw, purpose='legacy-private', entity_type='order', entity_id=1)
            order = {'orderNo': 'CLEAR-ATTACHMENT', 'shippingFee': 10, 'labelImageUrls': [url, url],
                     'items': [{'sku': 'ONE', 'image': url, 'quantity': 1, 'unitPrice': 20}]}
            for builder in (application.build_orders_export, application.build_orders_sheet_export, application.build_order_invoice_export):
                with self.subTest(export=builder.__name__), application.app.test_request_context('/',
                        headers={'Cookie': application.security.cookie + '=' + tokens['admin']}):
                    stream = builder(order if builder == application.build_order_invoice_export else [order])
                    book = load_workbook(stream)
                    with ZipFile(stream) as archive:
                        dimensions = []
                        for name in archive.namelist():
                            if name.startswith('xl/media/'):
                                with Image.open(BytesIO(archive.read(name))) as picture:
                                    dimensions.append(picture.size)
                        self.assertIn((1200, 1600), dimensions)
                    pictures = [pic for ws in book for pic in ws._images if pic.width == 1200]
                    self.assertEqual(len(pictures), 2)
                    self.assertEqual(pictures[0].anchor._from.row, pictures[1].anchor._from.row)
                    self.assertGreater(pictures[1].anchor._from.col, pictures[0].anchor._from.col)
                    for ws in book:
                        for picture in ws._images:
                            if picture.width == 1200:
                                self.assertGreaterEqual(ws.row_dimensions[picture.anchor._from.row + 1].height, 300)

    def test_invoice_attachments_follow_totals_and_product_pictures_are_large(self):
        photo = BytesIO(); Image.new('RGB', (1200, 1600), '#335577').save(photo, format='PNG')
        order = {'orderNo': 'VISIBLE-PHOTOS', 'shippingFee': 10, 'note': 'Packing note',
                 'labelImageUrls': ['/uploads/attachment.png'], 'items': [
                     {'sku': 'ONE', 'image': '/uploads/product.png', 'sizeCode': 'M', 'quantity': 2, 'unitPrice': 20}]}
        with patch.object(application, 'fetch_image_bytes', return_value=photo.getvalue()):
            sheet = load_workbook(application.build_order_invoice_export(order)).active
        self.assertEqual(sheet.column_dimensions['B'].width, 22)
        self.assertEqual(sheet.row_dimensions[13].height, 132)
        self.assertIn('ATTACHMENTS', sheet['A28'].value)
        self.assertIn('Packing note', sheet['A29'].value)
        self.assertEqual(sheet['A33'].value, 'REMARKS:')
        self.assertEqual(sheet['J23'].value, '=J21+J22')
        product = next(pic for pic in sheet._images if pic.anchor._from.row == 12)
        self.assertEqual(product.anchor.ext.cy, 160 * 9525)
        self.assertTrue(any(pic.anchor._from.row == 30 for pic in sheet._images))
        self.assertTrue(any('BANK' in str(c.value).upper() for row in sheet.iter_rows(max_col=10) for c in row))

    def test_invoice_product_picture_keeps_640_pixels(self):
        photo = BytesIO(); Image.new('RGB', (1800, 1800), '#335577').save(photo, format='PNG')
        order = {'orderNo': 'CLEAR-PI', 'shippingFee': 10, 'items': [
            {'sku': 'ONE', 'image': 'https://example.test/product.png', 'quantity': 1, 'unitPrice': 20}]}
        with patch.object(application, 'fetch_image_bytes', return_value=photo.getvalue()):
            book = load_workbook(application.build_order_invoice_export(order))
        self.assertTrue(any(pic.width == 640 and pic.height == 640 for pic in book.active._images))

    def test_parallel_prefetch_reuses_authorized_private_storage(self):
        from threading import Barrier
        from private_media import url_for
        tokens, _ = seed()
        barrier = Barrier(2)
        photo = BytesIO(); Image.new('RGB', (1800, 1800), '#335577').save(photo, format='PNG')
        urls = [url_for(application.media.register_legacy('/uploads/prefetch-' + name + '.png',
            photo.getvalue(), purpose='legacy-private', entity_type='order', entity_id=1)) for name in ['one','two']]
        order = {'items': [], 'labelImageUrls': urls}
        original_read = application.media.read
        def read(row):
            barrier.wait(timeout=10)
            return original_read(row)
        with patch.object(application.media, 'read', side_effect=read) as storage, \
                patch('safe_images.fetch_image', side_effect=AssertionError('Private images must not use the network')) as network:
            for repeat in range(2):
                with application.app.test_request_context('/', headers={'Cookie': application.security.cookie + '=' + tokens['admin']}):
                    application.prefetch_export_images([order])
                    for url in urls:
                        self.assertEqual(application.fetch_image_bytes(url, attachment=True), photo.getvalue())
            self.assertEqual(storage.call_count, 2)
            network.assert_not_called()
        # A different sales account is denied before any worker reads a file.
        with application.app.test_request_context('/', headers={'Cookie': application.security.cookie + '=' + tokens['sales']}), \
                patch.object(application.media, 'read') as denied:
            from export_image_cache import ExportImageError
            with self.assertRaises(ExportImageError):
                application.prefetch_export_images([order])
            with self.assertRaises(ExportImageError):
                application.fetch_image_bytes(urls[0], attachment=True)
            denied.assert_not_called()

    def test_invoice_with_few_and_many_product_rows(self):
        for count in (1, 8, 20, 60):
            with self.subTest(products=count), patch.object(application, 'fetch_image_bytes', return_value=None):
                order = {
                    'orderNo': 'SYNTHETIC-INVOICE', 'shippingFee': 15,
                    'contactName': 'Fixture', 'items': [
                        {'productName': f'Product {index}', 'sku': f'SKU-{index}',
                         'sizeCode': 'M', 'quantity': index + 1, 'unitPrice': 20}
                        for index in range(count)
                    ],
                }
                output = application.build_order_invoice_export(order)
                book = load_workbook(output)
                sheet = book['PI']
                self.assertEqual(sheet.max_column, 10)
                self.assertTrue(all((d.max or d.min or 0) <= 10 for d in sheet.column_dimensions.values()))
                last_item = 12 + max(count, 8)
                self.assertEqual(sheet['B5'].value, 'SYNTHETIC-INVOICE')
                self.assertEqual(sheet.cell(last_item + 1, 10).value, f'=SUM(J13:J{last_item})')
                self.assertEqual(sheet.cell(last_item + 2, 10).value, 15)
                for index in range(count):
                    row = 13 + index
                    self.assertEqual(sheet.cell(row, 8).value, f'=SUM(C{row}:G{row})')
                    self.assertEqual(sheet.cell(row, 10).value, f'=H{row}*I{row}')
                    self.assertIn(f'SKU-{index}', str(sheet.cell(row, 1).value))
                    self.assertEqual(copy(sheet.cell(row, 9).font), copy(sheet.cell(row, 10).font))
                    self.assertEqual(sheet.cell(row, 9).number_format, sheet.cell(row, 10).number_format)
                    self.assertIsInstance(sheet.cell(row, 9).value, (int, float))
                footer = last_item + 8
                for offset in range(1, 7):
                    cell = sheet.cell(footer + offset, 1)
                    self.assertTrue(str(cell.value).startswith(str(offset) + '.'))
                    self.assertFalse(cell.alignment.wrap_text)
                    self.assertIn(f'A{footer + offset}:J{footer + offset}', sheet.merged_cells)
                self.assertEqual(str(sheet.print_area), f"'PI'!$A$1:$J${footer + 11}")
                self.assertTrue(any('BANK' in str(cell.value).upper() for row in sheet for cell in row))
                book.close()

    def test_readable_terms_notes_and_signature_layout_preserves_bank_content(self):
        source = load_workbook(application.PROFORMA_TEMPLATE_PATH)['PI']
        expected_bank = source['A29'].value
        with patch.object(application, 'fetch_image_bytes', return_value=None):
            sheet = load_workbook(application.build_order_invoice_export({
                'orderNo': 'READABLE-FOOTER', 'shippingFee': 15, 'contactName': 'Layout Buyer',
                'note': '请按尺码分包。' * 40 + '\nPacking instructions',
                'items': [{'sku': 'FIXTURE', 'sizeCode': 'M', 'quantity': 2, 'unitPrice': 12.35}],
            })).active
        # Notes reserve five rows before the fixed terms; all six terms have
        # their own full-width merged row and use the same Arial as the address.
        for row in range(33, 40):
            cell = sheet[f'A{row}']
            self.assertEqual((cell.font.name, cell.font.size), ('Arial', source['A2'].font.size))
            self.assertFalse(cell.alignment.wrap_text)
            self.assertIn(f'A{row}:J{row}', sheet.merged_cells)
            self.assertNotIn('\n', cell.value)
        self.assertEqual(sheet['A35'].value, '2.Partial shipments: ALLOWED')
        self.assertEqual(sheet['A36'].value, '3.Transhipment: ALLOWED')
        self.assertEqual(sheet['A40'].value, expected_bank)
        self.assertEqual(sheet['A40'].font.name, 'Arial')
        self.assertEqual(sheet['A40'].font.size, source['A2'].font.size)
        self.assertEqual(sheet['A40'].fill.fgColor.rgb, '00DDEBF0')
        self.assertEqual(sheet['A43'].value, source['B32'].value)
        self.assertEqual(sheet['G43'].value, '=B6')
        self.assertEqual((sheet['A44'].value, sheet['G44'].value), ('SELLER', 'BUYER'))
        for cell_ref in ('A43', 'G43', 'A44', 'G44', 'C22', 'A28', 'A29'):
            self.assertEqual(sheet[cell_ref].font.name, 'Arial')
            self.assertEqual(sheet[cell_ref].font.size, source['A2'].font.size)
        for cell_ref in ('A43', 'G43', 'C22'):
            self.assertFalse(sheet[cell_ref].alignment.wrap_text)
        self.assertEqual(sheet['A43'].border.bottom.style, 'thin')
        self.assertEqual(sheet['G43'].border.bottom.style, 'thin')
        self.assertGreaterEqual(sheet.row_dimensions[29].height, 6 * 18)
        self.assertEqual(str(sheet.print_area), "'PI'!$A$1:$J$44")
        self.assertEqual(sheet['I13'].value, 12.35)
        self.assertEqual(copy(sheet['I13'].font), copy(sheet['J13'].font))
        self.assertIn('$', sheet['I13'].number_format)
        self.assertEqual(sheet['J13'].value, '=H13*I13')
        self.assertEqual(sheet['J23'].value, '=J21+J22')
        self.assertEqual(sheet['C25'].value, '=ROUND(J23*0.5,2)')
        self.assertEqual(sheet['C26'].value, '=ROUND(J23-C25,2)')

    def test_cny_pi_rounds_units_and_freight_before_totals_without_mutating_order(self):
        order = {'orderNo': 'CNY-USD-PI', 'currency': 'CNY', 'exchangeRate': '6',
                 'shippingFee': 1, 'totalAmount': 4,
                 'items': [{'sku': 'FIXTURE', 'sizeCode': 'M', 'quantity': 3, 'unitPrice': 1}]}
        original = deepcopy(order)
        with patch.object(application, 'fetch_image_bytes', return_value=None):
            sheet = load_workbook(application.build_order_invoice_export(order)).active
        self.assertEqual(order, original)
        self.assertEqual(sheet['I12'].value, '(USD)')
        self.assertEqual(sheet['I13'].value, 0.17)
        self.assertEqual(sheet['J22'].value, 0.17)
        self.assertEqual(sheet['D13'].value, 3)
        self.assertEqual(sheet['J13'].value, '=H13*I13')
        self.assertEqual(sheet['J23'].value, '=J21+J22')
        self.assertEqual(sheet['C25'].value, '=ROUND(J23*0.5,2)')
        self.assertEqual(sheet['C26'].value, '=ROUND(J23-C25,2)')
        self.assertIn('USD', sheet['I13'].number_format)
        self.assertIn('USD', sheet['J22'].number_format)
        source = load_workbook(application.PROFORMA_TEMPLATE_PATH)['PI']
        self.assertEqual(sheet['A35'].value, source['A29'].value)
        for rate in (None, 0, -1, 'NaN', '7.1234567'):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                application.build_order_invoice_export({**order, 'exchangeRate': rate})

    def test_custom_terms_are_preserved_and_footer_rebuild_is_idempotent(self):
        with TemporaryDirectory() as directory:
            book = load_workbook(application.PROFORMA_TEMPLATE_PATH)
            source = book['PI']
            source['A25'] = '2.Partial shipments: NOT ALLOWED       3. Transhipment: NOT ALLOWED'
            source['A26'] = '4.Time of shipment: In Oct. 2026'
            source['A27'] = '5. Terms of payment: Custom payment terms.'
            source['A29'] = 'Custom bank instructions\nAccount details unchanged'
            path = Path(directory) / 'custom-template.xlsx'
            book.save(path)
            with patch.object(application, 'PROFORMA_TEMPLATE_PATH', path), patch.object(application, 'fetch_image_bytes', return_value=None):
                sheet = load_workbook(application.build_order_invoice_export({
                    'orderNo': 'CUSTOM-TERMS', 'shippingFee': 15,
                    'items': [{'sku': 'FIXTURE', 'sizeCode': 'M', 'quantity': 1, 'unitPrice': 21}],
                })).active
            expected = [sheet[f'A{row}'].value for row in range(28, 40)]
            self.assertEqual(sheet['A30'].value, '2.Partial shipments: NOT ALLOWED')
            self.assertEqual(sheet['A31'].value, '3. Transhipment: NOT ALLOWED')
            self.assertEqual(sheet['A32'].value, '4.Time of shipment: In Oct. 2026')
            self.assertEqual(sheet['A33'].value, '5. Terms of payment: Custom payment terms.')
            self.assertEqual(sheet['A35'].value, 'Custom bank instructions\nAccount details unchanged')
            application.rebuild_invoice_fixed_footer(sheet, footer_start_row=28)
            self.assertEqual([sheet[f'A{row}'].value for row in range(28, 40)], expected)
            self.assertEqual(sheet['G38'].value, '=B6')
            self.assertEqual(sheet['G38'].border.bottom.style, 'thin')
            self.assertEqual(str(sheet.print_area), "'PI'!$A$1:$J$39")


if __name__ == '__main__':
    unittest.main()
