"""Offline migration acceptance using transactional fake SQL and fake providers."""
import copy
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from image_library_normalization import (Conflict,FIELDS,LibraryMigration,ReferenceDatabase,
                                         Unsupported,field_images,prepare_changes,private_json,references)
from image_library_storage import LegacyProviders


A='https://res.cloudinary.com/cloud/image/upload/v1/folder/a.png'
B='https://res.cloudinary.com/cloud/image/upload/v1/folder/b.png'
PDF='https://res.cloudinary.com/cloud/image/upload/v1/folder/document.pdf'
STAMP='2026-10-01T00:00:00+00:00'


def rows():
    def row(table,values,**more):
        return {'table':table,'id':1,'values':values,**more}
    return [
        row('products',{'main_image_url':A,'size_chart_image_url':B,'description_image_url':''},updated_at=STAMP),
        row('product_images',{'image_url':A},product_id=1),
        row('banners',{'image_url':A},updated_at=STAMP),
        row('orders',{'label_image_urls':json.dumps([A,B,PDF]),'label_pdf_url':A},updated_at=STAMP),
        row('admin_order_drafts',{'document':{'labelImageUrls':[A,B], 'note':A,
            'items':[{'image':A,'unitPrice':17,'quantity':5}], 'totalAmount':85}},updated_at=STAMP,revision=4),
        row('order_customer_templates',{'customer_info':{'labelImageUrls':[A],'note':A,'phone':'unchanged'}},updated_at=STAMP,revision=2),
        row('purchase_contracts',{'snapshot':{'styleImage':A,'sizeChartImage':B,'attachments':[A,PDF],
            'items':[{'image':A,'sizeChartImage':B,'quantity':5,'unitPrice':17}],
            'totalAmount':85,'status':'pending','note':A,'revision':7}}),
        row('homepage_configs',{'hero_banner_images':json.dumps({'desktop':A,'mobile':B})},updated_at=STAMP),
    ]


class Cursor:
    def __init__(self,items): self.items=items
    def fetchone(self): return self.items[0] if self.items else None
    def __iter__(self): return iter(self.items)


class FakeSQL:
    """Only the adapter's exact SQL subset; connection exit commits or rolls back."""
    def __init__(self):
        self.rows=rows(); self.security_files=0; self.statements=[]; self.fail_update=None

    def connect(self):
        database=self
        class Connection:
            def __enter__(self):
                self.working=copy.deepcopy(database.rows); self.updates=0
                return self
            def __exit__(self,kind,error,traceback):
                if kind is None: database.rows=self.working
            def execute(self,sql,params=()):
                database.statements.append(sql)
                if sql.startswith(('SET ','LOCK ')): return Cursor([])
                if sql=='SELECT current_database() AS name': return Cursor([{'name':'library_test'}])
                if sql=='SELECT count(*) AS n FROM security_files': return Cursor([{'n':database.security_files}])
                if 'information_schema.columns' in sql:
                    result=[]
                    for table,fields in FIELDS.items():
                        sample=next(row for row in self.working if row['table']==table)
                        names={'id',*fields,*[key for key in ('updated_at','revision','product_id') if key in sample]}
                        result.extend({'table_name':table,'column_name':name,'data_type':'jsonb' if fields.get(name)=='json' else 'text'} for name in names)
                    return Cursor(result)
                if sql.startswith('SELECT count(*) AS n FROM '):
                    table=sql.split()[-1]
                    return Cursor([{'n':sum(row['table']==table for row in self.working)}])
                if sql.startswith('SELECT ') and ' ORDER BY id' in sql:
                    columns,tail=sql.removeprefix('SELECT ').split(' FROM ',1)
                    table=tail.split()[0]; result=[]
                    for row in self.working:
                        if row['table']!=table: continue
                        data={}
                        for name in columns.split(','):
                            value=row['values'].get(name,row.get(name))
                            data[name]=datetime.fromisoformat(value) if name=='updated_at' and value else copy.deepcopy(value)
                        result.append(data)
                    return Cursor(result)
                if sql.startswith('UPDATE '):
                    self.updates+=1
                    if database.fail_update==self.updates: raise OSError('injected transaction failure')
                    table=sql.split()[1]
                    assignments=sql.split(' SET ',1)[1].split(' WHERE ',1)[0].split(',')
                    row=next(row for row in self.working if row['table']==table and row['id']==params[-1])
                    for expression,value in zip(assignments,params[:-1]):
                        name=expression.split('=')[0]
                        value=getattr(value,'obj',value)
                        if name in row['values']: row['values'][name]=copy.deepcopy(value)
                        else: row[name]=value
                    return Cursor([{'id':row['id']}])
                raise AssertionError('Unexpected SQL: '+sql)
        return Connection()


class FakeProviders:
    def __init__(self,large,small):
        self.scope={'fake':{'pages':1,'truncated':False}}
        self.originals={A:large,B:small}; self.published={}; self.reads=[]; self.uploads=[]
        self.corrupt_delivery=False
    def metadata(self,urls):
        return {url:{'status':'candidate','bytes':len(self.originals[url]),'provider':'cloudinary'} for url in urls}
    def read_original(self,entry):
        self.reads.append(entry['original_url']); return self.originals[entry['original_url']]
    def publish(self,entry,raw,mime,suffix):
        url='https://res.cloudinary.com/cloud/image/upload/v2/normalized/'+entry['id']+suffix
        self.uploads.append(url)
        if url in self.published and self.published[url]!=(raw,mime): raise Conflict('never overwrite')
        self.published[url]=(raw,mime)
        return url
    def read_published(self,entry,url):
        if self.corrupt_delivery: return b'invalid','image/jpeg'
        return self.published[url]


class LibraryMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def encoded(compress):
            output=io.BytesIO()
            with Image.new('RGB',(800,600),'orange') as image: image.save(output,'PNG',compress_level=compress)
            return output.getvalue()
        cls.large=encoded(0); cls.small=encoded(9)
        assert len(cls.large)>1_000_000

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.sql=FakeSQL()
        self.database=ReferenceDatabase(self.sql.connect,'library_test','legacy',target='fixture/library_test')
        self.provider=FakeProviders(self.large,self.small)
        self.migration=LibraryMigration(self.database,self.provider,self.temp.name)
        self.enterContext(patch('socket.create_connection',side_effect=AssertionError('No network')))

    def stage(self):
        self.migration.audit(); return self.migration.stage()

    def image_entry(self):
        return next(entry for entry in self.migration.manifest['entries'] if entry['original_url']==A)

    def test_audit_is_reference_scoped_and_never_downloads_or_writes_db(self):
        original=copy.deepcopy(self.sql.rows)
        self.migration.audit()
        self.assertEqual(set(entry['original_url'] for entry in self.migration.manifest['entries']),{A,B})
        self.assertEqual(self.provider.reads,[]); self.assertEqual(self.provider.uploads,[])
        self.assertEqual(self.sql.rows,original)
        self.assertFalse(any(sql.startswith('UPDATE ') for sql in self.sql.statements))
        self.assertIn('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY',self.sql.statements)

    def test_dry_run_verifies_backups_and_skips_small_images_without_upload(self):
        original=copy.deepcopy(self.sql.rows)
        report=self.stage()
        self.assertEqual(report['statuses'],{'staged':1,'unchanged':1})
        journal=self.migration.journal(self.image_entry())
        self.assertTrue(journal['backup_verified'])
        self.assertEqual((Path(self.temp.name)/journal['original_file']).read_bytes(),self.large)
        self.assertLessEqual(journal['output_bytes'],1_000_000)
        self.assertEqual(self.provider.uploads,[]); self.assertEqual(self.sql.rows,original)

    def test_trusted_small_original_metadata_skips_download_but_unknown_still_reads(self):
        self.migration.audit()
        entry=next(entry for entry in self.migration.manifest['entries'] if entry['original_url']==B)
        entry['verified_original_image']=True
        self.migration.save(); self.migration.stage()
        self.assertEqual(self.provider.reads,[A])
        self.assertTrue(self.migration.journal(entry)['metadata_only'])
        self.assertEqual(self.migration.journal(entry)['status'],'unchanged')
        # A fresh plan without a format/version-verified metadata match must read B.
        with tempfile.TemporaryDirectory() as directory:
            provider=FakeProviders(self.large,self.small)
            migration=LibraryMigration(self.database,provider,directory)
            migration.audit(); migration.stage()
            self.assertEqual(set(provider.reads),{A,B})

    def test_apply_changes_all_exact_image_fields_and_only_approved_versions(self):
        before=copy.deepcopy(self.sql.rows); self.stage(); report=self.migration.apply()
        self.assertEqual(report['statuses'],{'applied':1,'unchanged':1})
        journal=self.migration.journal(self.image_entry()); new=journal['new_url']
        self.assertNotIn(A,references(self.sql.rows))
        self.assertIn(new,references(self.sql.rows)); self.assertIn(B,references(self.sql.rows))
        self.assertEqual(len(self.provider.uploads),1)
        self.assertEqual(self.provider.originals[A],self.large)
        for old,row in zip(before,self.sql.rows):
            if 'updated_at' in old: self.assertGreater(row['updated_at'],old['updated_at'])
            if 'revision' in old: self.assertEqual(row['revision'],old['revision']+1)
        draft=next(row for row in self.sql.rows if row['table']=='admin_order_drafts')['values']['document']
        self.assertEqual(draft['note'],A); self.assertEqual(draft['totalAmount'],85)
        self.assertEqual(draft['items'][0]['quantity'],5); self.assertEqual(draft['items'][0]['unitPrice'],17)
        contract=next(row for row in self.sql.rows if row['table']=='purchase_contracts')['values']['snapshot']
        self.assertEqual(contract['revision'],8)
        self.assertEqual((contract['totalAmount'],contract['status'],contract['note']),(85,'pending',A))
        self.assertIn(PDF,contract['attachments'])

    def test_readback_mismatch_never_switches_any_reference(self):
        before=copy.deepcopy(self.sql.rows); self.stage(); self.provider.corrupt_delivery=True
        report=self.migration.apply()
        self.assertEqual(self.sql.rows,before)
        self.assertEqual(report['statuses'],{'uploaded:attention':1,'unchanged':1})
        self.assertEqual(len(self.provider.published),1)

    def test_concurrent_json_or_version_edit_conflicts_whole_url(self):
        self.stage()
        row=next(row for row in self.sql.rows if row['table']=='admin_order_drafts')
        row['values']['document']['items'][0]['quantity']=99
        row['revision']+=1
        before=copy.deepcopy(self.sql.rows)
        report=self.migration.apply()
        self.assertEqual(self.sql.rows,before)
        self.assertEqual(report['statuses'],{'switching:attention':1,'unchanged':1})

    def test_concurrently_added_reference_conflicts_instead_of_partial_switch(self):
        self.stage()
        self.sql.rows.append({'table':'banners','id':2,'values':{'image_url':A},'updated_at':STAMP})
        before=copy.deepcopy(self.sql.rows)
        self.migration.apply()
        self.assertEqual(self.sql.rows,before)

    def test_sql_failure_rolls_back_all_prior_updates_for_the_same_url(self):
        self.stage(); before=copy.deepcopy(self.sql.rows); self.sql.fail_update=3
        self.migration.apply()
        self.assertEqual(self.sql.rows,before)
        self.assertTrue(references(self.sql.rows,A))

    def test_resume_after_upload_does_not_publish_again(self):
        self.stage(); self.provider.corrupt_delivery=True; self.migration.apply()
        self.provider.corrupt_delivery=False; report=self.migration.apply()
        self.assertEqual(report['statuses'],{'applied':1,'unchanged':1})
        self.assertEqual(len(self.provider.uploads),1)

    def test_resume_after_commit_before_journal_save_recovers_known_version(self):
        self.stage()
        entry=self.image_entry(); journal=self.migration.journal(entry)
        raw=(Path(self.temp.name)/journal['output_file']).read_bytes()
        journal['new_url']=self.provider.publish(entry,raw,journal['mime'],journal['suffix'])
        journal['changes']=prepare_changes(self.migration.manifest['rows'],A,journal['new_url'])
        journal['status']='switching'
        private_json(self.migration.journal_path(entry),journal)
        self.database.switch(A,journal['new_url'],journal['changes'])
        report=self.migration.apply()
        self.assertEqual(report['statuses'],{'applied':1,'unchanged':1})
        self.assertEqual(len(self.provider.uploads),1)

    def test_rollback_restores_image_references_but_versions_continue_forward(self):
        before=copy.deepcopy(self.sql.rows); self.stage(); self.migration.apply()
        applied=copy.deepcopy(self.sql.rows); report=self.migration.rollback()
        self.assertEqual(report['statuses'],{'rolled_back':1,'unchanged':1})
        self.assertEqual(references(self.sql.rows),references(before))
        for old,current in zip(applied,self.sql.rows):
            if 'updated_at' in old: self.assertGreater(current['updated_at'],old['updated_at'])
            if 'revision' in old: self.assertEqual(current['revision'],old['revision']+1)
        snapshot=next(row for row in self.sql.rows if row['table']=='purchase_contracts')['values']['snapshot']
        self.assertEqual(snapshot['revision'],9)
        self.assertEqual(len(self.provider.published),1)  # Neither new nor original objects are deleted.

    def test_rollback_conflict_preserves_later_business_edit_and_all_references(self):
        self.stage(); self.migration.apply()
        row=next(row for row in self.sql.rows if row['table']=='purchase_contracts')
        row['values']['snapshot']['items'][0]['quantity']=42
        row['values']['snapshot']['revision']+=1
        before=copy.deepcopy(self.sql.rows); report=self.migration.rollback()
        self.assertEqual(self.sql.rows,before)
        self.assertEqual(report['statuses'],{'rolling_back:attention':1,'unchanged':1})

    def test_multiple_images_in_one_document_apply_and_rollback_with_rebased_versions(self):
        self.provider.originals[B]=self.large
        before=copy.deepcopy(self.sql.rows); self.stage(); self.migration.apply()
        self.assertFalse(set(references(self.sql.rows))&{A,B})
        self.migration.rollback()
        self.assertEqual(references(self.sql.rows),references(before))

    def test_existing_private_registry_and_wrong_mode_are_not_applicable(self):
        self.sql.security_files=1
        with self.assertRaises(Unsupported): self.migration.audit()
        self.sql.security_files=0; self.database.mode='private'
        with self.assertRaises(Unsupported): self.migration.audit()
        self.assertEqual(self.provider.uploads,[])

    def test_manifest_cannot_be_reused_against_another_endpoint(self):
        self.migration.audit(); self.database.target='different/library_test'
        with self.assertRaises(Unsupported): self.migration.load()

    def test_new_audit_detects_reintroduced_originals_without_absorbing_edits(self):
        self.stage(); self.migration.apply()
        next(row for row in self.sql.rows if row['table']=='banners')['values']['image_url']=A
        self.migration.audit()
        self.assertEqual(self.migration.summary()['last_audit']['reintroduced_original_urls'],1)

    def test_dry_run_refuses_insufficient_backup_headroom(self):
        self.migration.audit()
        with patch('image_library_normalization.shutil.disk_usage',return_value=Mock(free=1)):
            with self.assertRaises(OSError): self.migration.stage()
        self.assertEqual(self.provider.reads,[])

    def test_apply_requires_completed_dry_run_before_any_upload(self):
        self.migration.audit()
        with self.assertRaises(Unsupported): self.migration.apply()
        self.assertEqual(self.provider.uploads,[])

    def test_reaudit_does_not_reset_staged_or_applied_journals(self):
        self.stage(); entry=self.image_entry()
        staged=self.migration.journal(entry)
        self.migration.audit()
        self.assertEqual(self.migration.journal(entry),staged)
        self.migration.apply(); applied=self.migration.journal(entry)
        self.migration.audit()
        self.assertEqual(self.migration.journal(entry),applied)

    def test_foreign_nonempty_directory_is_rejected_before_permission_changes(self):
        foreign=Path(self.temp.name)/'unrelated'; foreign.mkdir()
        (foreign/'keep.txt').write_text('keep',encoding='utf-8')
        with patch('export_image_cache._private_directory') as permissions:
            with self.assertRaises(Unsupported): LibraryMigration(self.database,self.provider,foreign)
            permissions.assert_not_called()
        self.assertEqual((foreign/'keep.txt').read_text(encoding='utf-8'),'keep')

    def test_standard_library_run_lock_is_exclusive(self):
        with self.migration.run_lock():
            with self.assertRaises(OSError):
                with self.migration.run_lock(): self.fail('Second writer acquired the same journal')

    def test_gallery_only_change_still_advances_parent_product_version(self):
        fixture=rows()
        product=next(row for row in fixture if row['table']=='products')
        product['values']['main_image_url']=B
        for row in fixture:
            if row['table']!='product_images':
                for column in row['values']:
                    value,_=field_images(row['values'][column],FIELDS[row['table']][column],A,B)
                    row['values'][column]=value
        changes=prepare_changes(fixture,A,'https://fixture.invalid/new.jpg')
        parent=next(change for change in changes if change['before']['table']=='products')
        self.assertEqual(parent['before']['values'],parent['after']['values'])
        self.assertGreater(parent['after']['updated_at'],parent['before']['updated_at'])

    def test_exact_matching_never_rewrites_notes_or_substrings(self):
        document={'labelImageUrls':[A,PDF],'note':A,'items':[{'image':A,'description':A+' suffix'}],
                  'attachments':[{'url':A,'note':A}]}
        changed,found=field_images(document,'json',A,'https://fixture.invalid/new.jpg')
        self.assertEqual(found.count(A),3)
        self.assertEqual(changed['note'],A)
        self.assertEqual(changed['attachments'][0]['note'],A)
        self.assertEqual(changed['items'][0]['description'],A+' suffix')
        self.assertEqual(changed['labelImageUrls'][1],PDF)


class ProviderMetadataTest(unittest.TestCase):
    def test_cloudinary_aliases_share_metadata_without_losing_a_url(self):
        alias=A[:-4]+'.jpg'
        with patch.dict('os.environ',{'CLOUDINARY_CLOUD_NAME':'cloud'}):
            provider=LegacyProviders(Mock())
            provider.cloud_request=Mock(return_value={'resources':[
                {'public_id':'folder/a','version':1,'format':'png','bytes':2_000_000}]})
            result=provider.metadata([A,alias])
        self.assertEqual(result[A]['bytes'],2_000_000)
        self.assertEqual(result[alias]['bytes'],2_000_000)
        self.assertTrue(result[A]['verified_original_image'])
        self.assertFalse(result[alias]['verified_original_image'])
        provider.cloud_request.assert_called_once()

    def test_cloudinary_lists_once_and_excludes_pdf_without_processing_unreferenced_assets(self):
        media=Mock()
        with patch.dict('os.environ',{'CLOUDINARY_CLOUD_NAME':'cloud'}):
            provider=LegacyProviders(media)
            provider.cloud_request=Mock(return_value={'resources':[
                {'public_id':'folder/a','version':1,'format':'pdf','bytes':2_000_000},
                {'public_id':'folder/b','version':1,'format':'png','bytes':3_000_000},
                {'public_id':'unreferenced','version':1,'format':'png','bytes':4_000_000}]})
            result=provider.metadata([A,B])
        provider.cloud_request.assert_called_once()
        self.assertEqual(set(result),{A,B})
        self.assertEqual(result[A]['status'],'excluded_non_image')
        self.assertEqual(result[B]['bytes'],3_000_000)

    def test_metadata_truncation_leaves_unmatched_size_unknown(self):
        with patch.dict('os.environ',{'CLOUDINARY_CLOUD_NAME':'cloud'}):
            provider=LegacyProviders(Mock(),max_pages=3)
            provider.cloud_request=Mock(return_value={'resources':[],'next_cursor':'opaque'})
            result=provider.metadata([A])
        self.assertEqual(provider.cloud_request.call_count,3)
        self.assertTrue(provider.scope['cloudinary']['truncated'])
        self.assertIsNone(result[A]['bytes'])

    def test_foreign_cloud_transforms_and_registered_media_are_unsupported(self):
        media=Mock(legacy_export_source=Mock(return_value=None))
        with patch.dict('os.environ',{'CLOUDINARY_CLOUD_NAME':'cloud'}):
            provider=LegacyProviders(media)
            for url in (A.replace('/cloud/','/foreign/'),A.replace('/upload/','/upload/c_limit,w_500/'),
                        '/media/products/00000000-0000-0000-0000-000000000000/file.jpg'):
                with self.subTest(url=url):
                    with self.assertRaises(Unsupported): provider.classify(url)

    def test_r2_single_list_matches_only_referenced_image_keys(self):
        url='https://fixture.invalid/uploads/owned.png'
        media=Mock(legacy_export_source=Mock(return_value={'legacy_channel':'admin','legacy_key':'owned.png'}))
        client=Mock()
        client.list_objects_v2.return_value={'Contents':[{'Key':'owned.png','Size':2_000_000},
                                                        {'Key':'unreferenced.png','Size':9_000_000}], 'IsTruncated':False}
        with patch.dict('os.environ',{'R2_BUCKET':'fixture'}),patch('image_delivery.r2_client',return_value=client):
            provider=LegacyProviders(media); result=provider.metadata([url])
        self.assertEqual(set(result),{url}); self.assertEqual(result[url]['bytes'],2_000_000)
        client.list_objects_v2.assert_called_once_with(Bucket='fixture',MaxKeys=1000)
        client.get_object.assert_not_called()

    def test_r2_named_image_with_pdf_content_is_rejected_by_real_decoder(self):
        url='https://fixture.invalid/uploads/owned.png'
        media=Mock(legacy_export_source=Mock(return_value={'legacy_channel':'admin','legacy_key':'owned.png'}),
                   read_legacy_source=Mock(return_value=b'%PDF-1.7\nnot an image'))
        provider=LegacyProviders(media)
        with self.assertRaises(Exception):
            provider.read_original({'provider':'r2','original_url':url})

    def test_r2_immutable_write_and_readback_use_new_key_and_original_mime(self):
        identifier='00000000-0000-0000-0000-000000000001'
        entry={'provider':'r2','id':identifier,'original_url':'https://fixture.invalid/uploads/old.png'}
        media=Mock(legacy_export_source=Mock(side_effect=lambda url:{'legacy_channel':'admin','legacy_key':url.split('/uploads/',1)[1]}))
        client=Mock(); raw=b'normalized fixture bytes'
        client.get_object.return_value={'Body':io.BytesIO(raw),'ContentLength':len(raw),'ContentType':'image/jpeg'}
        with patch.dict('os.environ',{'R2_BUCKET':'fixture'}),patch('image_delivery.r2_client',return_value=client):
            provider=LegacyProviders(media)
            url=provider.publish(entry,raw,'image/jpeg','.jpg')
            delivered,mime=provider.read_published(entry,url)
        key='normalized/'+identifier+'.jpg'
        client.put_object.assert_called_once_with(Bucket='fixture',Key=key,Body=raw,ContentType='image/jpeg',IfNoneMatch='*')
        self.assertEqual((delivered,mime),(raw,'image/jpeg'))
        client.delete_object.assert_not_called()


if __name__=='__main__': unittest.main()
