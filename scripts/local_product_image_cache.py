"""Explicit local-manual bootstrap only; production import paths are unchanged."""
import json
import os
from pathlib import Path


def install(application):
    mode=os.environ.get('APP_ENV')
    database=os.environ.get('PGDATABASE','')
    if os.environ.get('PGHOST')!='127.0.0.1' or os.environ.get('PGPORT')!='55439' or not (
        mode=='local' and database=='lumiere_admin' or mode=='test' and database.endswith('_test')):
        raise RuntimeError('Local product image cache is restricted to local development')
    root=Path(application.media.uploads['admin']).resolve()
    manifest=root/'local-product-images.json'
    mapping=json.loads(manifest.read_text('utf-8')) if manifest.exists() else {}
    paths={}
    for url,key in mapping.items():
        path=(root/key).resolve()
        if not path.is_relative_to(root):raise ValueError('Invalid local image cache path')
        paths[url]=path
    original=application._read_export_image
    def read(value,source):
        path=paths.get(value)
        if path and path.is_file():
            from safe_images import check_image,MAX_BYTES
            with path.open('rb') as stream:data=stream.read(MAX_BYTES+1)
            check_image(data)
            return data
        return original(value,source)
    application._read_export_image=read
    return len(paths)
