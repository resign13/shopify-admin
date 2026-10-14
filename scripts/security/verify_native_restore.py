"""Native pg_dump/pg_restore rehearsal in a newly created disposable container.

Only synthetic *_test databases are used. No existing PostgreSQL endpoint,
container, production configuration or host data volume is accepted.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import uuid

import psycopg
from psycopg import sql


def command(argv, *, env=None, timeout=90):
    result = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Isolated native backup stage failed: ' + Path(argv[0]).name)
    return result.stdout.strip()


def fingerprint(connection):
    connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    tables = [r[0] for r in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
    rows = {name: connection.execute(sql.SQL("SELECT count(*),md5(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text,'[]')) FROM public.{} t").format(sql.Identifier(name))).fetchone() for name in tables}
    sequences = {name: connection.execute(sql.SQL('SELECT last_value,is_called FROM public.{}').format(sql.Identifier(name))).fetchone()
        for name, in connection.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename").fetchall()}
    return rows, sequences


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-fixture', action='store_true', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    report = Path(args.report).resolve()
    if report.exists(): raise ValueError('Existing acceptance report is preserved')
    root = Path(__file__).resolve().parents[2]
    image = 'postgres:16'
    image_digest = command(['docker', 'image', 'inspect', image, '--format', '{{index .RepoDigests 0}}'])
    if not image_digest.startswith('postgres@sha256:'): raise ValueError('Official PostgreSQL image required')
    tag = uuid.uuid4().hex[:12]
    name = 'gingtto-native-restore-' + tag
    source, target = 'gingtto_native_' + tag + '_source_test', 'gingtto_native_' + tag + '_restored_test'
    password = secrets.token_urlsafe(40)
    env = os.environ.copy()
    env.update(POSTGRES_PASSWORD=password, POSTGRES_DB=source)
    container = None
    try:
        container = command(['docker', 'run', '-d', '--name', name, '--label', 'gingtto.security-native-fixture=' + tag,
            '--security-opt', 'no-new-privileges', '--memory', '512m', '--cpus', '1', '--pids-limit', '128',
            '-p', '127.0.0.1::5432', '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB', image_digest], env=env)
        if not re.fullmatch(r'[a-f0-9]{64}', container): raise RuntimeError('Invalid owned fixture container')
        binding = command(['docker', 'port', container, '5432/tcp'])
        if not re.fullmatch(r'127\.0\.0\.1:[0-9]+', binding): raise RuntimeError('Fixture must bind only loopback')
        port = int(binding.rsplit(':', 1)[1])
        base = dict(host='127.0.0.1', port=port, user='postgres', password=password, connect_timeout=2)
        for attempt in range(120):
            try:
                with psycopg.connect(**base, dbname=source) as conn:
                    assert 160000 <= int(conn.execute('SHOW server_version_num').fetchone()[0]) < 170000
                break
            except psycopg.OperationalError: time.sleep(0.5)
        else: raise RuntimeError('Owned isolated PostgreSQL did not become ready')
        child = os.environ.copy()
        child.update(PGHOST='127.0.0.1', PGPORT=str(port), PGDATABASE=source, PGUSER='postgres', PGPASSWORD=password,
            APP_ENV='test', DB_SCHEMA_AUTO_MIGRATE='1', PRIVATE_STORAGE_BUCKET='',
            SECURITY_ATTACHMENT_MODE='legacy', SECURITY_LOGIN_PROTECTION_ENABLED='0')
        command([sys.executable, '-c', 'import sys;sys.path.insert(0,' + repr(str(root / 'admin-backend')) + ');import test_workbench;test_workbench.seed()'], env=child)
        with psycopg.connect(**base, dbname=source) as conn:
            conn.execute('CREATE TABLE public.backup_precision_fixture(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,amount numeric(24,6),payload bytea,metadata jsonb,labels text[],moment timestamptz,missing text)')
            conn.execute("INSERT INTO backup_precision_fixture(amount,payload,metadata,labels,moment) VALUES(123456789012345.123456,%s,%s,%s,'2026-10-13 23:59:59.123456+08')",
                (bytes(range(256)), '{"customer":"中文 Élodie","explicitZero":0}', ['M', 'Tall XL', '含空格']))
            conn.execute("SELECT setval(pg_get_serial_sequence('backup_precision_fixture','id'),1234567,true)")
        with psycopg.connect(**base, dbname=source) as conn: before = fingerprint(conn)
        prefix = ['docker', 'exec', '--user', 'postgres']
        command(prefix + ['-e', 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=120000', container,
            'pg_dump', '-Fc', '--no-password', '--dbname=' + source, '--file=/tmp/security-native.dump'], timeout=180)
        command(prefix + [container, 'pg_restore', '--list', '--file=/dev/null', '/tmp/security-native.dump'])
        command(prefix + [container, 'createdb', '--template=template0', target])
        command(prefix + [container, 'pg_restore', '--exit-on-error', '--no-owner', '--no-acl', '--dbname=' + target,
            '/tmp/security-native.dump'], timeout=180)
        with psycopg.connect(**base, dbname=target) as conn: restored = fingerprint(conn)
        if restored != before: raise AssertionError('Native table/sequence restore differs')
        with psycopg.connect(**base, dbname=source) as conn:
            if fingerprint(conn) != before: raise AssertionError('Read-only backup modified its source')
        business = {table: value for table, value in before[0].items() if table not in {'admin_sessions', 'store_sessions', 'order_notification_starts'}}
        with psycopg.connect(**base, dbname=target) as conn:
            conn.execute('DELETE FROM store_sessions'); conn.execute('DELETE FROM admin_sessions')
            assert conn.execute('SELECT count(*) FROM admin_sessions').fetchone()[0] == 0
            assert conn.execute('SELECT count(*) FROM store_sessions').fetchone()[0] == 0
        with psycopg.connect(**base, dbname=target) as conn:
            after = fingerprint(conn)[0]
            if any(after[table] != value for table, value in business.items()):
                raise AssertionError('Session clearing changed restored business records')
        proof = {'officialImageDigest': image_digest, 'isolatedContainer': True, 'loopbackOnly': True,
            'nativeCustomFormatDump': True, 'nativeCatalogueReadable': True, 'nativeRestoreSucceeded': True,
            'verifiedTables': len(before[0]), 'verifiedSequences': len(before[1]),
            'allTableAndSequenceFingerprintsMatch': True, 'sourceUnchanged': True,
            'clonedSessionsCleared': True, 'existingContainersChanged': False, 'productionModified': False}
    finally:
        if container and re.fullmatch(r'[a-f0-9]{64}', container):
            owner = command(['docker', 'inspect', '--format', '{{index .Config.Labels "gingtto.security-native-fixture"}}', container])
            if owner != tag: raise RuntimeError('Owned fixture label mismatch; no cleanup attempted')
            command(['docker', 'rm', '-f', '-v', container], timeout=45)
    proof['ownedContainerRemoved'] = True
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof))


if __name__ == '__main__': main()
