"""Guarded business regression plus separate production-quota security tests.

High fixture quotas avoid artificial throttling of dozens of synthetic exports
inside one test. Security tests always run in a separate process with the real
defaults; this never changes an application's runtime quota configuration.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--suite', choices=['all', 'security', 'business'], default='all')
parser.add_argument('--modules', nargs='*')
args = parser.parse_args()
if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
    raise SystemExit('Explicit isolated local *_test database required')
root = Path(__file__).resolve().parents[1]
backend = root / 'admin-backend'
available = {p.stem for p in backend.glob('test_*.py')} - {'test_security', 'test_security_phase1', 'test_cookie_client'}
if args.modules and any(m not in available for m in args.modules):
    raise SystemExit('Unknown business test module')
env = os.environ.copy()
env.update(APP_ENV='test', DB_SCHEMA_AUTO_MIGRATE='1', INTERNAL_COMPAT_ENABLED='0', PRIVATE_STORAGE_BUCKET='')
env.update(SECURITY_ATTACHMENT_MODE='legacy', SECURITY_LOGIN_PROTECTION_ENABLED='0')
env['SECURITY_ADMIN_CAPTCHA_ENABLED'] = '0'  # Dedicated CAPTCHA tests explicitly enable it.
for key in list(env):
    if key.startswith('SECURITY_LIMIT_'): env.pop(key)
if args.suite in {'all', 'security'}:
    result = subprocess.run([sys.executable, '-m', 'unittest', '-v', 'test_security_phase1', 'test_security'], cwd=backend, env=env)
    if result.returncode: raise SystemExit(result.returncode)
if args.suite in {'all', 'business'}:
    for category in ('READ', 'VOICE', 'WRITE', 'UPLOAD', 'EXPORT', 'EXPORT_POLL', 'INVENTORY'):
        env['SECURITY_LIMIT_' + category] = '10000'
    result = subprocess.run([sys.executable, '-m', 'unittest', '-v', *(args.modules or sorted(available))], cwd=backend, env=env)
    raise SystemExit(result.returncode)
