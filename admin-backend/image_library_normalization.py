"""Legacy-only, reference-scoped image migration. No application startup or DDL.

The private manifest and per-image journals are the resume/rollback record.
Images are never overwritten or deleted. All provider work precedes DB locks.
"""
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shutil
import uuid
from urllib.parse import urlsplit

from image_normalization import MAX_OUTPUT_BYTES, normalize_image
from safe_images import MAX_BYTES, check_image

TOOL = 'legacy-image-library-normalization-v1'


# These are actual persisted image fields, not every string in a business JSON.
FIELDS = {
    'products': {'main_image_url':'scalar','size_chart_image_url':'scalar','description_image_url':'scalar'},
    'product_images': {'image_url':'scalar'},
    'banners': {'image_url':'scalar'},
    'orders': {'label_image_urls':'json_text','label_pdf_url':'scalar'},
    'admin_order_drafts': {'document':'json'},
    'order_customer_templates': {'customer_info':'json'},
    'purchase_contracts': {'snapshot':'json'},
    'homepage_configs': {'hero_banner_images':'json_text_all'},
}
JSON_IMAGE_FIELDS = {'image','imageUrl','imageUrls','gallery','styleImage','sizeChartImage',
                     'descriptionImage','labelImageUrls','labelPdfUrl','inheritedAttachmentUrls','attachments'}
IMAGE_EXTENSIONS = {'.jpg','.jpeg','.png','.webp','.avif','.gif','.bmp','.mpo'}


class Conflict(ValueError):
    pass


class Unsupported(ValueError):
    pass


def image_url(value):
    return (isinstance(value,str) and bool(value) and
            Path(urlsplit(value).path).suffix.lower() in IMAGE_EXTENSIONS)


def _tree(value, old=None, new=None, enabled=False, all_strings=False):
    """Collect/replace only full image strings under named image fields."""
    found=[]
    if isinstance(value,dict):
        output={}
        for key,item in value.items():
            # A named image field enables its list values, not unrelated siblings.
            output[key], values=_tree(item,old,new,all_strings or key in JSON_IMAGE_FIELDS or (enabled and key=='url'),all_strings)
            found.extend(values)
        return output,found
    if isinstance(value,list):
        output=[]
        for item in value:
            result,values=_tree(item,old,new,enabled,all_strings)
            output.append(result); found.extend(values)
        return output,found
    if enabled and image_url(value):
        found.append(value)
        return (new if old is not None and value==old else value),found
    return value,found


def field_images(value, kind, old=None, new=None):
    if kind=='scalar':
        return (new if old is not None and value==old else value),([value] if image_url(value) else [])
    text=kind.startswith('json_text')
    document=json.loads(value) if text and value else ([] if text else value)
    changed,found=_tree(document,old,new,enabled=(kind=='json_text_all' or isinstance(document,list)),all_strings=kind=='json_text_all')
    if text:
        return (json.dumps(changed,ensure_ascii=False) if changed!=document else value),found
    return changed,found


def row_key(row):
    return row['table'],row['id']


def references(rows, url=None):
    result={}
    for row in rows:
        for column,value in row['values'].items():
            _,urls=field_images(value,FIELDS[row['table']][column])
            for candidate in urls:
                if url is None or candidate==url:
                    result.setdefault(candidate,[]).append(row_key(row)+(column,))
    return result


def replace_row(row, old, new):
    result=copy.deepcopy(row)
    for column,value in row['values'].items():
        result['values'][column],_=field_images(value,FIELDS[row['table']][column],old,new)
    return result


def prepare_changes(rows, old, new):
    """Exact image-only deltas plus explicitly required optimistic versions."""
    moment=datetime.now(timezone.utc)
    for row in rows:
        if row.get('updated_at'):
            moment=max(moment,datetime.fromisoformat(row['updated_at'])+timedelta(microseconds=1))
    stamp=moment.isoformat()
    changes={}
    parents=set()
    for row in rows:
        after=replace_row(row,old,new)
        if after['values']==row['values']: continue
        if row.get('updated_at') is not None: after['updated_at']=stamp
        if row.get('revision') is not None: after['revision']=row['revision']+1
        if row['table']=='purchase_contracts':
            snapshot=after['values']['snapshot']
            snapshot['revision']=snapshot.get('revision',1)+1
        changes[row_key(row)]={'before':copy.deepcopy(row),'after':after}
        if row['table']=='product_images': parents.add(row['product_id'])
    for row in rows:
        if row['table']=='products' and row['id'] in parents and row_key(row) not in changes:
            after=copy.deepcopy(row)
            if row.get('updated_at') is None: raise Unsupported('Product version timestamp is absent')
            after['updated_at']=stamp
            changes[row_key(row)]={'before':copy.deepcopy(row),'after':after}
    if parents-set(r['id'] for r in rows if r['table']=='products'):
        raise Conflict('Gallery parent is absent')
    return [changes[key] for key in sorted(changes)]


def rebase(rows,changes):
    after={row_key(change['after']):change['after'] for change in changes}
    return [copy.deepcopy(after.get(row_key(row),row)) for row in rows]


class ReferenceDatabase:
    def __init__(self, connect, name, mode, target=None):
        self.connect,self.name,self.mode=connect,name,mode
        self.target=target or name
        self.columns={}

    def guard(self,conn):
        if self.mode!='legacy': raise Unsupported('Only legacy attachment mode is supported')
        if conn.execute('SELECT current_database() AS name').fetchone()['name']!=self.name:
            raise Unsupported('Database identity changed')
        if conn.execute('SELECT count(*) AS n FROM security_files').fetchone()['n']:
            raise Unsupported('Registered/private media requires a different migration')

    def schema(self,conn):
        columns={table:{} for table in FIELDS}
        for row in conn.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='public'"):
            if row['table_name'] in columns:
                columns[row['table_name']][row['column_name']]=row['data_type']
        for table,fields in FIELDS.items():
            if not (set(fields)|{'id'}).issubset(columns[table]):
                raise Unsupported('Image reference schema is incomplete: '+table)
        for table,column in [('products','updated_at'),('orders','updated_at'),('banners','updated_at'),
                             ('homepage_configs','updated_at'),('admin_order_drafts','revision'),
                             ('order_customer_templates','revision')]:
            if column not in columns[table]: raise Unsupported('Optimistic version is absent: '+table)
        self.columns=columns

    def read_rows(self,conn):
        result=[]
        for table,fields in FIELDS.items():
            columns=['id',*fields]
            columns += [name for name in ('updated_at','revision') if name in self.columns[table]]
            if table=='product_images': columns.append('product_id')
            for data in conn.execute('SELECT '+','.join(columns)+' FROM '+table+' ORDER BY id'):
                row={'table':table,'id':data['id'],'values':{name:data[name] for name in fields}}
                for name in columns:
                    if name not in {'id',*fields}:
                        value=data[name]
                        row[name]=value.astimezone(timezone.utc).isoformat() if name=='updated_at' and value else value
                result.append(row)
        return result

    def snapshot(self):
        with self.connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            self.guard(conn); self.schema(conn)
            rows=self.read_rows(conn)
            baseline={table:conn.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']
                      for table in ('products','orders','order_items')}
            return rows,baseline

    def switch(self,old,new,changes):
        """One URL, one short transaction. No provider/filesystem calls inside."""
        from psycopg.types.json import Jsonb
        with self.connect() as conn:
            conn.execute("SET LOCAL lock_timeout='1500ms'")
            conn.execute("SET LOCAL statement_timeout='15000ms'")
            # NOWAIT prevents waiting behind active business edits; these locks
            # also close the insertion/phantom gap while all old refs are checked.
            conn.execute('LOCK TABLE '+','.join(sorted([*FIELDS,'security_files']))+' IN SHARE ROW EXCLUSIVE MODE NOWAIT')
            self.guard(conn)
            current=self.read_rows(conn)
            before={row_key(c['before']):c['before'] for c in changes}
            after={row_key(c['after']):c['after'] for c in changes}
            actual={row_key(row):row for row in current}
            if all(actual.get(key)==row for key,row in after.items()) and not references(current,old):
                return 'recovered_commit'
            if any(actual.get(key)!=row for key,row in before.items()):
                raise Conflict('A referenced row or its version changed')
            expected=references(list(before.values()),old).get(old,[])
            if sorted(references(current,old).get(old,[]))!=sorted(expected):
                raise Conflict('The set of references changed')
            for change in changes:
                previous,target=change['before'],change['after']
                assignments=[]; params=[]
                for column,value in target['values'].items():
                    if value==previous['values'][column]: continue
                    assignments.append(column+'=%s')
                    params.append(Jsonb(value) if FIELDS[target['table']][column]=='json' else value)
                for name in ('updated_at','revision'):
                    if target.get(name)!=previous.get(name):
                        assignments.append(name+'=%s'); params.append(target[name])
                if not assignments: continue
                row=conn.execute('UPDATE '+target['table']+' SET '+','.join(assignments)+' WHERE id=%s RETURNING id',(*params,target['id'])).fetchone()
                if not row: raise Conflict('A reference disappeared')
            actual={row_key(row):row for row in self.read_rows(conn)}
            if any(actual.get(key)!=row for key,row in after.items()):
                raise Conflict('Stored values differ from the prepared journal')
            return 'committed'


def private_json(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(path.name+'.tmp')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as output:
        json.dump(value,output,ensure_ascii=False,indent=2)
        output.flush(); os.fsync(output.fileno())
    os.replace(temporary,path)
    path.chmod(0o600)


def private_bytes(path,raw):
    path=Path(path)
    if path.exists():
        if path.read_bytes()!=raw: raise Conflict('Existing backup differs')
        return
    temporary=path.with_name(path.name+'.tmp')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'wb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    os.replace(temporary,path)
    path.chmod(0o600)
    if path.read_bytes()!=raw: raise OSError('Backup read-back differs')


class LibraryMigration:
    def __init__(self,database,provider,state_dir):
        self.database,self.provider=database,provider
        self.root=Path(state_dir).resolve()
        self.manifest_path=self.root/'manifest.json'
        if self.root.exists() and any(self.root.iterdir()):
            if not self.manifest_path.is_file(): raise Unsupported('State directory is not a dedicated migration directory')
            previous=json.loads(self.manifest_path.read_text(encoding='utf-8'))
            if previous.get('tool')!=TOOL: raise Unsupported('State directory belongs to another tool')
        # This existing helper applies an actual private ACL on Windows as well.
        from export_image_cache import _private_directory
        _private_directory(self.root)

    @contextmanager
    def run_lock(self):
        with (self.root/'run.lock').open('a+b') as stream:
            if os.name!='nt': (self.root/'run.lock').chmod(0o600)
            if stream.seek(0,2)==0: stream.write(b'0'); stream.flush()
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            try: yield
            finally:
                stream.seek(0)
                if os.name=='nt': msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else: fcntl.flock(stream.fileno(),fcntl.LOCK_UN)

    def save(self):
        private_json(self.manifest_path,self.manifest)

    def load(self):
        self.manifest=json.loads(self.manifest_path.read_text(encoding='utf-8'))
        if self.manifest['database']!=self.database.name: raise Unsupported('Manifest belongs to another database')
        if self.manifest.get('target')!=self.database.target: raise Unsupported('Manifest belongs to another database endpoint')
        return self.manifest

    def audit(self):
        if self.manifest_path.exists():
            self.load()
            rows,_=self.database.snapshot()
            current=references(rows)
            known=set(references(self.manifest['rows']))
            reintroduced=[entry['original_url'] for entry in self.manifest['entries']
                          if (self.journal(entry) or {}).get('status')=='applied' and entry['original_url'] in current]
            self.manifest['last_audit']={'new_unplanned_image_urls':len(set(current)-known),
                                         'reintroduced_original_urls':len(reintroduced),
                                         'reference_rows_differ':rows!=self.manifest['rows']}
            self.save(); return self.manifest
        rows,baseline=self.database.snapshot()
        urls=references(rows)
        metadata=self.provider.metadata(urls)
        entries=[]
        for url,refs in sorted(urls.items()):
            item={'id':str(uuid.uuid4()),'original_url':url,'references':len(refs),**metadata[url]}
            entries.append(item)
        budget=sum((entry.get('bytes') if entry.get('bytes') is not None else MAX_BYTES)+MAX_OUTPUT_BYTES
                   for entry in entries if entry.get('status')=='candidate' and (entry.get('bytes') is None or entry['bytes']>MAX_OUTPUT_BYTES))
        free=shutil.disk_usage(self.root).free
        self.manifest={'tool':TOOL,'version':1,'database':self.database.name,'target':self.database.target,'mode':'legacy','created_at':datetime.now(timezone.utc).isoformat(),
                       'baseline':baseline,'rows':rows,'entries':entries,'metadata_scope':self.provider.scope,
                       'disk':{'free_bytes':free,'estimated_backup_and_output_bytes':budget,'reserved_headroom_bytes':64*1024*1024}}
        self.save(); return self.manifest

    def journal_path(self,entry):
        return self.root/(str(uuid.UUID(entry['id']))+'.json')

    def journal(self,entry):
        path=self.journal_path(entry)
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def stage(self):
        self.load()
        disk=self.manifest['disk']
        remaining=sum((entry.get('bytes') if entry.get('bytes') is not None else MAX_BYTES)+MAX_OUTPUT_BYTES
                      for entry in self.manifest['entries'] if entry['status']=='candidate'
                      and (self.journal(entry) or {}).get('status','error')=='error'
                      and (entry.get('bytes') is None or entry['bytes']>MAX_OUTPUT_BYTES))
        if shutil.disk_usage(self.root).free < remaining+disk['reserved_headroom_bytes']:
            raise OSError('Insufficient backup disk reserve')
        for entry in self.manifest['entries']:
            previous=self.journal(entry)
            if entry['status']!='candidate' or (previous and previous['status']!='error'): continue
            journal={'id':entry['id'],'original_url':entry['original_url'],'status':'staging'}
            try:
                if entry.get('verified_original_image') and isinstance(entry.get('bytes'),int) and 0<entry['bytes']<=MAX_OUTPUT_BYTES:
                    journal.update(status='unchanged',original_bytes=entry['bytes'],metadata_only=True)
                    private_json(self.journal_path(entry),journal)
                    continue
                raw=self.provider.read_original(entry)
                check_image(raw)
                if len(raw)<=MAX_OUTPUT_BYTES:
                    journal.update(status='unchanged',original_bytes=len(raw))
                else:
                    if shutil.disk_usage(self.root).free < len(raw)+MAX_OUTPUT_BYTES+disk['reserved_headroom_bytes']:
                        raise OSError('Insufficient per-image backup reserve')
                    original_path=self.root/(entry['id']+'.original')
                    private_bytes(original_path,raw)
                    # Shared URLs used in a contract/order keep the larger detail floor.
                    locations=references(self.manifest['rows'],entry['original_url'])[entry['original_url']]
                    purpose='product' if all(t in {'products','product_images','banners','homepage_configs'} for t,_,_ in locations) else 'document'
                    result=normalize_image(raw,purpose=purpose)
                    derivative=self.root/(entry['id']+result.suffix)
                    private_bytes(derivative,result.data)
                    journal.update(status='staged',original_bytes=len(raw),output_bytes=len(result.data),
                                   original_file=original_path.name,output_file=derivative.name,mime=result.mime,suffix=result.suffix,
                                   backup_verified=True)
            except Exception as error:
                journal.update(status='error',error_type=type(error).__name__)
            private_json(self.journal_path(entry),journal)
        return self.summary()

    def apply(self):
        self.load()
        # A fresh read-only guard prevents accidentally applying against a cutover.
        self.database.snapshot()
        if any(entry['status']=='candidate' and self.journal(entry) is None for entry in self.manifest['entries']):
            raise Unsupported('Dry-run must stage every candidate before apply')
        for entry in self.manifest['entries']:
            journal=self.journal(entry)
            if not journal or journal['status'] in {'unchanged','error','rolled_back'}: continue
            try:
                if journal['status']=='applied':
                    self.manifest['rows']=rebase(self.manifest['rows'],journal['changes']); self.save(); continue
                raw=(self.root/journal['output_file']).read_bytes()
                original=(self.root/journal['original_file']).read_bytes()
                if len(original)!=journal['original_bytes'] or check_image(original) is None:
                    raise Conflict('Backup is incomplete')
                if len(raw)>MAX_OUTPUT_BYTES or len(raw)!=journal['output_bytes'] or check_image(raw)!=journal['mime']:
                    raise Conflict('Staged derivative is invalid')
                if not journal.get('new_url'):
                    # Deterministic unique destination from the private journal ID.
                    # A crash after upload retries the same never-overwrite resource.
                    journal['new_url']=self.provider.publish(entry,raw,journal['mime'],journal['suffix'])
                    journal['status']='uploaded'; private_json(self.journal_path(entry),journal)
                delivered,mime=self.provider.read_published(entry,journal['new_url'])
                if delivered!=raw or mime!=journal['mime'] or check_image(delivered)!=mime:
                    raise Conflict('New object read-back differs')
                if not journal.get('changes'):
                    journal['changes']=prepare_changes(self.manifest['rows'],entry['original_url'],journal['new_url'])
                    if not journal['changes']: raise Conflict('The source has no planned references')
                    journal['status']='switching'; private_json(self.journal_path(entry),journal)
                self.database.switch(entry['original_url'],journal['new_url'],journal['changes'])
                journal['status']='applied'; journal.pop('last_error_type',None); private_json(self.journal_path(entry),journal)
                self.manifest['rows']=rebase(self.manifest['rows'],journal['changes']); self.save()
            except Exception as error:
                # Keep uploaded objects, the backup and prepared deltas for retry.
                journal['last_error_type']=type(error).__name__
                private_json(self.journal_path(entry),journal)
        return self.summary()

    def rollback(self):
        self.load(); self.database.snapshot()
        for entry in reversed(self.manifest['entries']):
            journal=self.journal(entry)
            if not journal or journal['status'] not in {'applied','rolling_back'}: continue
            try:
                # Use the known latest migration state; never absorb external edits.
                if not journal.get('rollback_changes'):
                    journal['rollback_changes']=prepare_changes(self.manifest['rows'],journal['new_url'],entry['original_url'])
                    journal['status']='rolling_back'; private_json(self.journal_path(entry),journal)
                changes=journal['rollback_changes']
                if not changes: raise Conflict('No migrated references remain')
                self.database.switch(journal['new_url'],entry['original_url'],changes)
                journal['status']='rolled_back'; journal.pop('last_error_type',None); private_json(self.journal_path(entry),journal)
                self.manifest['rows']=rebase(self.manifest['rows'],changes); self.save()
            except Exception as error:
                journal['last_error_type']=type(error).__name__
                private_json(self.journal_path(entry),journal)
        return self.summary()

    def summary(self):
        counts={}; source_bytes=output_bytes=0
        for entry in self.manifest['entries']:
            journal=self.journal(entry)
            status=journal['status'] if journal else entry['status']
            if journal and journal.get('last_error_type'): status+=':attention'
            counts[status]=counts.get(status,0)+1
            if journal:
                source_bytes+=journal.get('original_bytes',0); output_bytes+=journal.get('output_bytes',0)
        return {'unique_referenced_images':len(self.manifest['entries']),'statuses':counts,
                'original_bytes_examined':source_bytes,'normalized_output_bytes':output_bytes,
                'baseline':self.manifest['baseline'],'metadata_scope':self.manifest['metadata_scope'],'disk':self.manifest['disk'],
                'last_audit':self.manifest.get('last_audit')}
