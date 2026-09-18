"""Synthetic invoice export regression tests; no real order writes."""
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from unittest.mock import patch
from openpyxl import load_workbook
from PIL import Image
from test_workbench import application


class InvoiceExportTest(unittest.TestCase):
    def test_both_exports_embed_small_images_and_reuse_downloads(self):
        with TemporaryDirectory() as directory:
            Image.new('RGB', (2400, 3200), '#335577').save(Path(directory) / 'fixture.jpg')
            order = {'orderNo': 'IMAGE-FIXTURE', 'items': [
                {'sku': 'SKU-1', 'productName': 'Fixture', 'image': 'https://img.smawell.shop/uploads/fixture.jpg',
                 'sizeCode': size, 'quantity': 1, 'unitPrice': 20}
                for size in ['S', 'M', 'L']
            ]}
            for builder in (application.build_orders_export, application.build_orders_sheet_export):
                with self.subTest(export=builder.__name__), patch.object(application, 'UPLOAD_DIR', Path(directory)), \
                        application.app.test_request_context('/api/admin/orders/export'):
                    from image_delivery import deliver_image
                    with patch('image_delivery.deliver_image', wraps=deliver_image) as read:
                        stream = builder([order])
                        self.assertEqual(read.call_count, 1)
                    with ZipFile(stream) as archive:
                        media = [name for name in archive.namelist() if name.startswith('xl/media/')]
                        self.assertEqual(len(media), 1)
                        for name in media:
                            content = archive.read(name)
                            self.assertLess(len(content), 50000)
                            with Image.open(BytesIO(content)) as image:
                                self.assertLessEqual(image.width, 172)
                                self.assertLessEqual(image.height, 224)

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
                last_item = 12 + max(count, 8)
                self.assertEqual(sheet['B5'].value, 'SYNTHETIC-INVOICE')
                self.assertEqual(sheet.cell(last_item + 1, 10).value, f'=SUM(J13:J{last_item})')
                self.assertEqual(sheet.cell(last_item + 2, 10).value, 15)
                for index in range(count):
                    row = 13 + index
                    self.assertEqual(sheet.cell(row, 8).value, f'=SUM(C{row}:G{row})')
                    self.assertEqual(sheet.cell(row, 10).value, f'=H{row}*I{row}')
                    self.assertIn(f'SKU-{index}', str(sheet.cell(row, 1).value))
                self.assertTrue(any('BANK' in str(cell.value).upper() for row in sheet for cell in row))
                book.close()


if __name__ == '__main__':
    unittest.main()
