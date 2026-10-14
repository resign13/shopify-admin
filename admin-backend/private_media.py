"""Shared file registry and independent business references. No URL-based upload trust."""
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import tempfile
import uuid
from urllib.parse import urlsplit, unquote
from flask import abort, g, has_request_context, request, send_file, current_app
from werkzeug.utils import secure_filename
from safe_images import check_image, fetch_image, MAX_BYTES
from security_settings import attachment_mode


def migrate(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS security_files (
      id UUID PRIMARY KEY, storage_channel TEXT NOT NULL CHECK(storage_channel IN ('admin','store')),
      storage_key TEXT NOT NULL, filename TEXT NOT NULL, mime_type TEXT NOT NULL,
      byte_size BIGINT NOT NULL CHECK(byte_size>=0), sha256 VARCHAR(64) NOT NULL,
      owner_channel TEXT NOT NULL, owner_id BIGINT, purpose TEXT NOT NULL,
      visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','public')),
      origin_hash VARCHAR(64), created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      UNIQUE(storage_channel,storage_key), UNIQUE(origin_hash,purpose));
    CREATE TABLE IF NOT EXISTS security_file_refs (
      file_id UUID NOT NULL REFERENCES security_files(id), entity_type TEXT NOT NULL,
      entity_id BIGINT NOT NULL, PRIMARY KEY(file_id,entity_type,entity_id));
    CREATE INDEX IF NOT EXISTS security_file_entities ON security_file_refs(entity_type,entity_id);
    CREATE INDEX IF NOT EXISTS security_file_origins ON security_files(origin_hash);
    CREATE TABLE IF NOT EXISTS security_media_migrations (
      name TEXT PRIMARY KEY, completed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());''')


def origin_hash(url):
    return hashlib.sha256(str(url).strip().encode()).hexdigest()


def file_id(url):
    try:
        parts = unquote(urlsplit(str(url)).path).split('/')
        if parts[1:3] in (['api','attachments'], ['media','products']):
            return str(uuid.UUID(parts[3]))
    except (ValueError, IndexError):
        pass
    return None


def url_for(row):
    prefix = '/media/products/' if row['purpose'] == 'product' else '/api/attachments/'
    tail = '/' if row['purpose'] == 'product' else '/content/'
    return prefix + str(row['id']) + tail + row['filename']


def attachment_urls(document):
    result = []
    for key in ('labelImageUrls', 'inheritedAttachmentUrls', 'attachments'):
        value = document.get(key, [])
        if isinstance(value, str):
            try: value = json.loads(value)
            except ValueError: value = [value]
        if isinstance(value, list): result += [v for v in value if isinstance(v, str) and v]
    value = document.get('labelPdfUrl', '')
    if value: result.append(value)
    return list(dict.fromkeys(result))


class Media:
    def __init__(self, app, db, channel, base_dir):
        self.app, self.db, self.channel, self.base = app, db, channel, Path(base_dir)
        self.mode = attachment_mode()
        # Both applications must use these same absolute directories in production.
        sibling = self.base.parent.parent
        defaults = {'admin': sibling / 'shopify-admin' / 'admin-backend', 'store': sibling / 'shopify' / 'storefront-backend'}
        defaults[channel] = self.base
        self.roots = {c: Path(os.environ.get('SECURITY_' + c.upper() + '_FILE_ROOT', str(root / 'data' / 'private-files'))).resolve() for c, root in defaults.items()}
        self.uploads = {c: Path(os.environ.get('SECURITY_' + c.upper() + '_LEGACY_UPLOADS', str(root / 'uploads'))).resolve() for c, root in defaults.items()}
        self.cache = self.base / 'data' / 'image-cache'
        if os.environ.get('APP_ENV') == 'test':
            # Fixture database isolation also implies file isolation. Tests must
            # never populate a manual service's upload directory or private
            # cache merely because they share the same checkout.
            namespace = hashlib.sha256(os.environ.get('PGDATABASE', '').encode()).hexdigest()[:20]
            test_root = Path(tempfile.gettempdir()) / 'gingtto-security-test-files' / namespace
            self.roots = {c: test_root / c / 'private' for c in ('admin', 'store')}
            self.uploads = {c: test_root / c / 'uploads' for c in ('admin', 'store')}
            self.cache = test_root / channel / 'image-cache'
        app.extensions['media'] = self
        app.add_url_rule('/api/attachments/<uuid:attachment_id>/content', 'attachment_content', self.content)
        app.add_url_rule('/api/attachments/<uuid:attachment_id>/content/<filename>', 'attachment_named_content', self.content)
        app.add_url_rule('/media/products/<uuid:attachment_id>/<filename>', 'public_product_content', self.content)

    def find(self, url):
        identity = file_id(url)
        with self.db.get_connection() as conn:
            if identity:
                return conn.execute('SELECT * FROM security_files WHERE id=%s', (identity,)).fetchone()
            return conn.execute("SELECT * FROM security_files WHERE origin_hash=%s ORDER BY (visibility='private') DESC LIMIT 1", (origin_hash(url),)).fetchone()

    def legacy_export_source(self, value):
        """Read owned legacy uploads by a bounded storage key, never by HTTP.

        Other HTTPS images still pass safe_images' exact-origin, public-DNS and
        redirect checks. A similar-looking hostname is not a local file origin.
        """
        parts = urlsplit(str(value))
        path = unquote(parts.path)
        if not path.startswith('/uploads/') or '\\' in path:
            return None
        channel = self.channel if not parts.netloc and not parts.scheme else None
        for candidate in ('admin', 'store'):
            origins = {v.strip().rstrip('/') for v in os.environ.get('SECURITY_' + candidate.upper() + '_LEGACY_ORIGINS', '').split(',') if v.strip()}
            if parts.scheme == 'https' and not parts.username and not parts.password and ('https://' + parts.netloc.lower()) in origins:
                channel = candidate
        if has_request_context() and parts.netloc == request.host and parts.scheme == request.scheme:
            channel = self.channel
        if not channel:
            return None
        key = path[len('/uploads/'):]
        if not key or any(p in {'', '.', '..'} for p in key.split('/')):
            raise ValueError('Invalid legacy upload key')
        root = self.uploads[channel]
        source = (root / key).resolve()
        if root not in source.parents:
            raise ValueError('Invalid legacy upload path')
        if source.is_file():
            return {'legacy_path': str(source), 'legacy_channel': channel}
        if channel == 'admin':
            return {'legacy_key': key, 'legacy_channel': channel}
        raise FileNotFoundError('Legacy upload is missing')

    def read_legacy_source(self, source):
        if source.get('legacy_path'):
            path = Path(source['legacy_path']).resolve()
            root = self.uploads[source['legacy_channel']]
            if root not in path.parents or path.stat().st_size > MAX_BYTES:
                raise ValueError('Invalid legacy upload')
            with path.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
        else:
            # This is the existing owned upload bucket, not a user-provided
            # endpoint. The SDK has bounded timeouts and credentials stay local.
            from image_delivery import r2_client
            obj = r2_client().get_object(Bucket=os.environ['R2_BUCKET'], Key=source['legacy_key'])
            body = obj['Body']
            try:
                if obj.get('ContentLength', 0) > MAX_BYTES:
                    raise ValueError('Legacy upload exceeds size limit')
                data = body.read(MAX_BYTES + 1)
            finally:
                body.close()
        if not data or len(data) > MAX_BYTES:
            raise ValueError('Legacy upload exceeds size limit')
        return data

    def can_read(self, row, user=None):
        if row['visibility'] == 'public': return True
        if user is None:
            identity = current_app.extensions['security'].current() if has_request_context() else None
            user = current_app.extensions['security'].user(identity) if identity else None
        if not user: return False
        with self.db.get_connection() as conn:
            refs = conn.execute('SELECT entity_type,entity_id FROM security_file_refs WHERE file_id=%s', (row['id'],)).fetchall()
            if not refs:
                return row['owner_channel'] == self.channel and row['owner_id'] == user['id']
            if self.channel == 'store':
                ids = [r['entity_id'] for r in refs if r['entity_type'] == 'order']
                return bool(ids and conn.execute('SELECT 1 FROM orders WHERE id=ANY(%s) AND store_user_id=%s LIMIT 1', (ids,user['id'])).fetchone())
            import module_permissions
            allowed = set(module_permissions.effective(user))
            role = user.get('role')
            order_ids = [r['entity_id'] for r in refs if r['entity_type'] == 'order']
            if 'orders' in allowed and role in {'admin','sales','warehouse'} and order_ids:
                if role != 'sales' and conn.execute('SELECT 1 FROM orders WHERE id=ANY(%s) LIMIT 1',(order_ids,)).fetchone(): return True
                if conn.execute('SELECT 1 FROM orders WHERE id=ANY(%s) AND owner_admin_id=%s LIMIT 1', (order_ids,user['id'])).fetchone(): return True
            draft_ids = [r['entity_id'] for r in refs if r['entity_type'] == 'draft']
            if 'orders' in allowed and role in {'admin','sales'} and draft_ids:
                clause, args = ("", (draft_ids,)) if role == 'admin' else (' AND creator_id=%s',(draft_ids,user['id']))
                if conn.execute("SELECT 1 FROM admin_order_drafts WHERE id=ANY(%s) AND state='active'" + clause + ' LIMIT 1', args).fetchone(): return True
            if 'contracts' in allowed and role in {'admin','sales'} and any(r['entity_type']=='contract' for r in refs): return True
            templates = [r['entity_id'] for r in refs if r['entity_type'] == 'template']
            if templates and 'orders' in allowed and role in {'admin','sales'}:
                if role=='admin': return True
                if conn.execute('SELECT 1 FROM order_customer_templates WHERE id=ANY(%s) AND created_by_admin_id=%s LIMIT 1',(templates,user['id'])).fetchone(): return True
        return False

    def upload(self, storage, *, purpose='order', max_bytes=MAX_BYTES):
        identity = current_app.extensions['security'].current()
        if not identity: abort(401)
        suffix = Path(storage.filename or '').suffix.lower()
        allowed = {'.jpg','.jpeg','.png','.webp','.avif','.gif','.bmp'}
        if purpose != 'product': allowed.add('.pdf')
        if suffix not in allowed: raise ValueError('Only supported images and PDF files are allowed')
        raw = storage.read(max_bytes + 1)
        if not raw or len(raw)>max_bytes: raise ValueError('Attachment size exceeds the limit')
        try: mime = validate_content(raw, suffix)
        except Exception as exc: raise ValueError('File content is invalid or unsupported') from exc
        if self.mode == 'legacy':
            # Validate new uploads without changing their storage provider,
            # legacy URLs, historical references or anonymous-access policy.
            uploader = self.app.extensions.get('legacy_media_uploader')
            if uploader:
                from werkzeug.datastructures import FileStorage
                return uploader(FileStorage(stream=io.BytesIO(raw), filename=storage.filename, content_type=mime))
            root = self.uploads[self.channel]
            root.mkdir(parents=True, exist_ok=True)
            name = secrets.token_hex(16) + suffix
            target = root / name
            with target.open('xb') as output:
                output.write(raw)
            target.chmod(0o640)
            return request.url_root.rstrip('/') + '/uploads/' + name
        identity_id = uuid.uuid4()
        name = (secure_filename(Path(storage.filename).stem) or 'attachment')[:80] + suffix
        key = str(identity_id) + suffix
        root = self.roots[self.channel]; root.mkdir(parents=True,exist_ok=True)
        target = root / key
        with target.open('xb') as output: output.write(raw)
        target.chmod(0o640)
        try:
            from private_storage import replicate
            replicate(self.channel,key,raw,mime)
            with self.db.get_connection() as conn:
                row=conn.execute('''INSERT INTO security_files(id,storage_channel,storage_key,filename,mime_type,byte_size,sha256,owner_channel,owner_id,purpose)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                  (identity_id,self.channel,key,name,mime,len(raw),hashlib.sha256(raw).hexdigest(),self.channel,identity['id'],purpose)).fetchone()
            return url_for(row)
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def read(self, row):
        root = self.roots[row['storage_channel']]
        path = (root / row['storage_key']).resolve()
        if root not in path.parents: raise ValueError('Invalid storage key')
        if path.is_file():
            if path.stat().st_size != row['byte_size'] or path.stat().st_size > MAX_BYTES: raise ValueError('Attachment size mismatch')
            data=path.read_bytes()
        else:
            from private_storage import retrieve
            data=retrieve(row['storage_channel'],row['storage_key'],MAX_BYTES)
            if len(data)!=row['byte_size']: raise ValueError('Attachment size mismatch')
        if hashlib.sha256(data).hexdigest() != row['sha256']: raise ValueError('Attachment integrity mismatch')
        return data

    def register_legacy(self, url, raw, *, purpose, entity_type, entity_id, storage_channel='admin'):
        """Explicit migration only; URL comes from a saved database reference.
        A public product image and private business attachment always get two
        independent storage objects, even when their legacy URL was identical.
        """
        suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
        if suffix in {'.doc','.docx','.xls','.xlsx'}:
            if not (raw.startswith(bytes.fromhex('d0cf11e0a1b11ae1')) or raw.startswith(b'PK')): raise ValueError('Invalid historical office document')
            mime = 'application/octet-stream'
        elif suffix == '.pdf':
            mime = validate_content(raw, suffix)
        else:
            # Legacy CDNs can negotiate WebP/AVIF for a .jpg URL. Validate the
            # actual image, then give its protected copy a matching extension;
            # new uploads still require exact extension/content agreement.
            mime = check_image(raw)
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as picture:
                suffix = {'JPEG':'.jpg','MPO':'.jpg','PNG':'.png','WEBP':'.webp','AVIF':'.avif','GIF':'.gif','BMP':'.bmp'}[picture.format]
        key_hash = origin_hash(url)
        with self.db.get_connection() as conn:
            row = conn.execute('SELECT * FROM security_files WHERE origin_hash=%s AND purpose=%s', (key_hash,purpose)).fetchone()
            if not row:
                identity = uuid.uuid4()
                key = str(identity) + suffix
                root = self.roots[storage_channel]; root.mkdir(parents=True,exist_ok=True)
                with (root / key).open('xb') as output: output.write(raw)
                (root / key).chmod(0o640)
                from private_storage import replicate
                replicate(storage_channel,key,raw,mime)
                row = conn.execute('''INSERT INTO security_files(id,storage_channel,storage_key,filename,mime_type,byte_size,sha256,owner_channel,purpose,visibility,origin_hash)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                  (identity,storage_channel,key,'attachment'+suffix,mime,len(raw),hashlib.sha256(raw).hexdigest(),storage_channel,purpose,'public' if purpose=='product' else 'private',key_hash)).fetchone()
            conn.execute('INSERT INTO security_file_refs(file_id,entity_type,entity_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(row['id'],entity_type,entity_id))
        return row

    def legacy_alias(self, *urls):
        with self.db.get_connection() as conn:
            return conn.execute("SELECT * FROM security_files WHERE origin_hash=ANY(%s) ORDER BY (visibility='public') DESC LIMIT 1",([origin_hash(url) for url in urls],)).fetchone()

    def content(self, attachment_id, filename=None):
        row=self.find('/api/attachments/' + str(attachment_id) + '/content')
        if not row or not self.can_read(row): abort(404)
        try: raw=self.read(row)
        except (FileNotFoundError,ValueError): abort(404)
        response=send_file(io.BytesIO(raw),mimetype=row['mime_type'],download_name=row['filename'],as_attachment=not row['mime_type'].startswith('image/'))
        response.headers['Cache-Control']='public, max-age=86400' if row['visibility']=='public' else 'no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        origin=request.headers.get('Origin','')
        public_origins={v.strip() for v in os.environ.get('PUBLIC_IMAGE_CORS_ORIGINS','').split(',') if v.strip()}
        if row['visibility']=='public' and origin in public_origins:
            response.headers['Access-Control-Allow-Origin']=origin
            response.headers['Vary']='Origin'
        return response

    def bind(self, entity_type, entity_id, urls):
        """Called inside the order/draft/contract transaction, after validation.

        Replacing one reference list never removes another business object's files.
        """
        if self.mode == 'legacy':
            return
        urls=list(dict.fromkeys(str(v) for v in urls if v))
        rows=[]
        for url in urls:
            row=self.find(url)
            if not row or not self.can_read(row): raise ValueError('Attachment is not owned or accessible; upload it again')
            if entity_type=='product' and row['purpose']!='product': raise ValueError('A private attachment cannot be published as a product image')
            if entity_type != 'product' and row['visibility']=='public':
                row=self.register_legacy(url,self.read(row),purpose='legacy-private',entity_type=entity_type,entity_id=entity_id,storage_channel=self.channel)
            rows.append(row)
        with self.db.get_connection() as conn:
            conn.execute('DELETE FROM security_file_refs WHERE entity_type=%s AND entity_id=%s',(entity_type,entity_id))
            for row in rows:
                conn.execute('INSERT INTO security_file_refs(file_id,entity_type,entity_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(row['id'],entity_type,entity_id))
                if entity_type=='product': conn.execute("UPDATE security_files SET visibility='public' WHERE id=%s",(row['id'],))

    def canonical(self, value):
        if self.mode == 'legacy':
            return value
        row=self.find(value) if value else None
        return url_for(row) if row else value

    def rewrite(self, payload):
        """Translate only private business fields; product images remain public.
        Batch lookup, so serializing a list does not issue a query per attachment.
        """
        if self.mode == 'legacy':
            return payload
        keys={'labelImageUrls','labelPdfUrl','inheritedAttachmentUrls','attachments','styleImage'}
        if has_request_context() and '/contracts' in request.path:
            keys.update({'sizeChartImage','image'})
        wanted=set()
        def collect(value,key=''):
            if isinstance(value,dict):
                for k,v in value.items(): collect(v,k)
            elif isinstance(value,list):
                for v in value: collect(v,key)
            elif key in keys and isinstance(value,str) and value: wanted.add(value)
        collect(payload)
        if not wanted: return payload
        with self.db.get_connection() as conn:
            rows=conn.execute("SELECT * FROM security_files WHERE origin_hash=ANY(%s) OR id=ANY(%s::uuid[])",([origin_hash(v) for v in wanted],[file_id(v) for v in wanted if file_id(v)])).fetchall()
        mapping={}
        for row in sorted(rows,key=lambda row:row['visibility']=='private'):
            for value in wanted:
                if str(row['id'])==file_id(value) or row['origin_hash']==origin_hash(value): mapping[value]=url_for(row)
        def transform(value,key=''):
            if isinstance(value,dict): return {k:transform(v,k) for k,v in value.items()}
            if isinstance(value,list): return [transform(v,key) for v in value]
            if key in keys and isinstance(value,str) and value:
                suffix=Path(urlsplit(value).path).suffix.lower()
                if suffix not in {'.jpg','.jpeg','.png','.webp','.avif','.gif','.bmp','.pdf','.doc','.docx','.xls','.xlsx'}:suffix='.bin'
                return mapping.get(value, '/api/attachments/00000000-0000-0000-0000-000000000000/content/missing'+suffix)
            return value
        return transform(payload)


def validate_content(raw, suffix):
    if suffix != '.pdf': return check_image(raw,suffix)
    if not raw.startswith(b'%PDF-'): raise ValueError('Invalid PDF content')
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(raw),strict=True)
    if reader.is_encrypted or len(reader.pages)>500: raise ValueError('Encrypted or oversized PDF is not supported')
    forbidden={'/JavaScript','/JS','/Launch','/RichMedia','/EmbeddedFiles','/OpenAction','/AA','/XFA','/SubmitForm','/ImportData'}
    seen=set()
    def inspect(obj,depth=0):
        if depth>50 or len(seen)>100000: raise ValueError('PDF structure is too complex')
        if hasattr(obj,'get_object'): obj=obj.get_object()
        marker=id(obj)
        if marker in seen: return
        seen.add(marker)
        if isinstance(obj,dict):
            if forbidden.intersection(str(k) for k in obj): raise ValueError('Active PDF content is not supported')
            if str(obj.get('/S','')) in forbidden: raise ValueError('Active PDF content is not supported')
            for value in obj.values(): inspect(value,depth+1)
        elif isinstance(obj,(list,tuple)):
            for value in obj: inspect(value,depth+1)
    inspect(reader.trailer)
    return 'application/pdf'


def bind_current(entity_type, entity_id, urls):
    if has_request_context(): current_app.extensions['media'].bind(entity_type,entity_id,urls)
