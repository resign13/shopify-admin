"""Reference-scoped legacy image audit/staging/apply/rollback. Defaults to audit.

Audit lists only DB-referenced candidates, using bounded provider metadata pages.
--dry-run reads/backs up/normalizes referenced originals locally; no provider/DB writes.
--apply or --rollback requires the exact --expected-db and an existing private plan.
No passwords, customer documents, original URLs or provider exception messages print.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',default='admin-backend')
    parser.add_argument('--state-dir',required=True,help='Private non-web-served backup and journal directory')
    parser.add_argument('--expected-db')
    parser.add_argument('--metadata-pages',type=int,default=3)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--audit',action='store_true')
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--apply',action='store_true')
    mode.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    if (args.apply or args.rollback) and not args.expected_db:
        parser.error('Writes require --expected-db')
    backend=Path(__file__).resolve().parents[1]/args.backend
    sys.path.insert(0,str(backend))
    os.environ['DB_SCHEMA_AUTO_MIGRATE']='0'
    os.environ['DB_POOL_ENABLED']='0'
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    import db
    if args.expected_db and db.DB_NAME!=args.expected_db: raise ValueError('Database confirmation does not match')
    if not (args.apply or args.rollback):
        # Explicit libpq options supersede ambient PGOPTIONS in this application.
        original=db.connect
        def readonly(*positional,**keywords):
            keywords['options']=keywords.get('options','')+' -c default_transaction_read_only=on'
            return original(*positional,**keywords)
        db.connect=readonly
    from flask import Flask
    from private_media import Media
    from image_library_normalization import LibraryMigration,ReferenceDatabase
    from image_library_storage import LegacyProviders
    media=Media(Flask('offline-image-library-tool'),db,'admin',backend)
    root=Path(args.state_dir).resolve()
    # Originals and journals may contain sensitive attachment references.
    forbidden=[*media.uploads.values(),*media.roots.values(),backend.parent/'frontend'/'dist']
    if any(root==path.resolve() or path.resolve() in root.parents for path in forbidden):
        raise ValueError('State directory must be outside served/storage directories')
    if (args.apply or args.rollback) and not (root/'manifest.json').is_file():
        raise ValueError('Audit and dry-run must precede writes')
    database=ReferenceDatabase(db._connect,db.DB_NAME,media.mode,target=str(db.DB_HOST)+':'+str(db.DB_PORT)+'/'+db.DB_NAME)
    provider=LegacyProviders(media,max_pages=args.metadata_pages)
    migration=LibraryMigration(database,provider,root)
    with migration.run_lock():
        if args.apply: report=migration.apply()
        elif args.rollback: report=migration.rollback()
        elif args.dry_run:
            migration.audit(); report=migration.stage()
        else:
            migration.audit(); report=migration.summary()
        # The private manifest is the detailed URL/location/size checklist.
        report.update(mode='apply' if args.apply else 'rollback' if args.rollback else 'dry-run' if args.dry_run else 'audit',
                      python=sys.version.split()[0],backend_release=backend.resolve().parent.name)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        failed=any('attention' in status or status=='error' for status in report['statuses'])
        return 1 if failed else 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        record={'error_type':type(error).__name__}
        status=getattr(error,'code',None)
        if isinstance(status,int): record['http_status']=status
        print(json.dumps(record),file=sys.stderr)
        raise SystemExit(1)
