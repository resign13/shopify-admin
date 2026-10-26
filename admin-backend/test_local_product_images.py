import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from local_product_image_cache import install


class LocalProductImageCacheTest(unittest.TestCase):
    def test_original_bytes_and_unmapped_fallback(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ,{'APP_ENV':'test','PGHOST':'127.0.0.1','PGPORT':'55439','PGDATABASE':'local_images_test'}):
            root=Path(folder);data=io.BytesIO();Image.new('RGB',(20,30),'navy').save(data,'JPEG')
            (root/'image.jpg').write_bytes(data.getvalue())
            (root/'local-product-images.json').write_text(json.dumps({'https://res.cloudinary.com/example.jpg':'image.jpg'}))
            fallback=Mock(return_value=b'fallback');app=SimpleNamespace(media=SimpleNamespace(uploads={'admin':root}),_read_export_image=fallback)
            self.assertEqual(install(app),1)
            self.assertEqual(app._read_export_image('https://res.cloudinary.com/example.jpg',None),data.getvalue())
            fallback.assert_not_called()
            self.assertEqual(app._read_export_image('other',None),b'fallback')

    def test_production_and_path_escape_are_rejected(self):
        with patch.dict(os.environ,{'APP_ENV':'production'}):
            with self.assertRaises(RuntimeError):install(None)
        with TemporaryDirectory() as folder,patch.dict(os.environ,{'APP_ENV':'test','PGHOST':'127.0.0.1','PGPORT':'55439','PGDATABASE':'local_images_test'}):
            root=Path(folder);(root/'local-product-images.json').write_text(json.dumps({'https://example.test/p':'../outside.jpg'}))
            app=SimpleNamespace(media=SimpleNamespace(uploads={'admin':root}),_read_export_image=Mock())
            with self.assertRaises(ValueError):install(app)

if __name__=='__main__':unittest.main()
