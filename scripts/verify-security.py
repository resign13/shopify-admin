"""Read-only release gate. No login, credential output or business writes."""
import argparse
import os
from pathlib import Path
import sys
parser=argparse.ArgumentParser();parser.add_argument('backend');parser.add_argument('--production-ready',action='store_true');parser.add_argument('--profile', choices=['phase1','private'], default='phase1');args=parser.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/args.backend))
import db
db.load_env_file(Path(__file__).resolve().parents[1]/args.backend/'.env.security')
from security_settings import attachment_mode, login_protection_enabled
if args.profile == 'phase1':
    assert attachment_mode() == 'legacy', 'Private attachments are deferred in this release'
    assert not login_protection_enabled(), 'Login protection section 6.4 is deferred in this release'
with db._connect() as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    for table in ['security_files','security_file_refs','security_rate_buckets','security_audit_events','store_sessions','security_request_metrics']:
        assert conn.execute('SELECT to_regclass(%s) AS value',('public.'+table,)).fetchone()['value'],'Security table missing'
    if args.backend == 'admin-backend': assert not conn.execute('SELECT 1 FROM admin_sessions WHERE token_hash IS NULL OR expires_at IS NULL LIMIT 1').fetchone(),'Legacy live sessions remain'
    if args.production_ready:
        assert os.environ.get('APP_ENV') == 'production', 'Production must retain Secure cookies and HTTPS checks'
        if args.profile == 'private':
            assert attachment_mode() == 'private', 'Private release requires the private attachment profile'
            assert conn.execute("SELECT 1 FROM security_media_migrations WHERE name='legacy-private-v1'").fetchone(),'Legacy media classification incomplete'
            assert os.environ.get('SECURITY_LEGACY_SOURCES_CLOSED')=='1','Legacy object/CDN closure has not been confirmed'
        role=conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert not any(role.values()),'Runtime privileges are excessive'
        assert not conn.execute("SELECT has_schema_privilege(current_user,'public','CREATE') AS value").fetchone()['value'],'Runtime role retains DDL'
print('Read-only security structure checks passed')
