"""Read-only origin inspection; emit booleans/metadata, never raw configuration."""
import json
import os
from pathlib import Path
import re
import subprocess


def run(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return -1, ''


def server_blocks(text):
    text = re.sub(r'(?m)^\s*#.*$', '', text)
    for start in re.finditer(r'\bserver\s*\{', text):
        depth, end = 1, start.end()
        while end < len(text) and depth:
            depth += (text[end] == '{') - (text[end] == '}')
            end += 1
        yield text[start.end():end-1]


code, nginx = run(['nginx', '-T'])
sites = []
for block in server_blocks(nginx):
    names = re.findall(r'\bserver_name\s+([^;]+);', block)
    domains = [n for line in names for n in line.split() if n.endswith(('gingtto.store', 'smawell.shop'))]
    if not domains:
        continue
    sites.append({
        'domains': domains,
        'tlsListener': bool(re.search(r'listen\s+[^;]*\b443\b', block)),
        'certificateConfigured': 'ssl_certificate ' in block,
        'httpRedirectConfigured': bool(re.search(r'return\s+30[18]\s+https', block)),
        'privateUploadStaticAlias': bool(re.search(r'location\s+[^\{]*/uploads[^\{]*\{[^}]*\b(alias|root)\s', block)),
        'legacyPublicIngressClosed': bool(re.search(r'location[^\{]*/api/public[^\{]*\{[^}]*return\s+410', block)),
        'legacyInternalIngressClosed': bool(re.search(r'location[^\{]*/api/internal[^\{]*\{[^}]*return\s+(403|404|410)', block)),
        'forwardedForRebuilt': bool(re.search(r'proxy_set_header\s+X-Forwarded-For\s+\$remote_addr\s*;', block)),
        'acceptsIncomingForwardedChain': '$proxy_add_x_forwarded_for' in block,
        'hstsConfigured': 'Strict-Transport-Security' in block,
        'noStoreConfigured': 'no-store' in block,
    })

_, listeners = run(['ss', '-lntH'])
bindings = []
for line in listeners.splitlines():
    fields = line.split()
    if len(fields) < 4:
        continue
    address, _, port = fields[3].rpartition(':')
    if port not in {'5432', '5301', '5302', '5000', '5001', '8000', '8001'}:
        continue
    bindings.append({'port': int(port), 'loopbackOnly': address.strip('[]') in {'127.0.0.1', '::1'}})

services = []
_, listing = run(['systemctl', 'list-units', '--type=service', '--all', '--no-legend', '--plain'])
for line in listing.splitlines():
    name = line.split()[0] if line.split() else ''
    if not re.search(r'(gingtto|smawell).+\.service$', name):
        continue
    _, info = run(['systemctl', 'show', name, '-p', 'User', '-p', 'ActiveState', '-p', 'NoNewPrivileges', '-p', 'ProtectSystem', '-p', 'ExecStart'])
    values = dict(line.split('=', 1) for line in info.splitlines() if '=' in line)
    services.append({'service': name, 'active': values.get('ActiveState'),
                     'runsAsRoot': values.get('User') in {'', 'root', None},
                     'gunicorn': 'gunicorn' in values.get('ExecStart', ''),
                     'noNewPrivileges': values.get('NoNewPrivileges') == 'yes',
                     'protectSystem': values.get('ProtectSystem')})

environments = []
database_roles = []
for base in (Path('/opt/smawell/shopify-admin/admin-backend'), Path('/opt/smawell/shopify/storefront-backend')):
    for filename in ('.env', '.env.security'):
        path = base / filename
        if not path.is_file():
            continue
        values = {}
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip().strip('\"\'')
        environments.append({'application': 'admin' if 'admin-backend' in str(base) else 'store',
                             'securityEnvironment': filename == '.env.security',
                             'runtimeUsesPostgresRole': values.get('PGUSER', 'postgres') == 'postgres',
                             'privateBucketConfigured': bool(values.get('PRIVATE_STORAGE_BUCKET')),
                             'publicBucketConfigured': bool(values.get('R2_BUCKET')),
                             'privateAndPublicBucketSame': bool(values.get('PRIVATE_STORAGE_BUCKET')) and values.get('PRIVATE_STORAGE_BUCKET') == values.get('R2_BUCKET'),
                             'environmentWorldReadable': bool(path.stat().st_mode & 0o004)})
        name = values.get('PGDATABASE', 'lumiere_admin')
        role = values.get('PGUSER', 'postgres').replace("'", "''")
        if filename == '.env' and re.fullmatch(r'[A-Za-z0-9_]+', name):
            query = ("BEGIN READ ONLY; SELECT json_build_object('superuser',rolsuper,'createDb',rolcreatedb,"
                     "'createRole',rolcreaterole,'bypassRls',rolbypassrls,'schemaCreate',has_schema_privilege(rolname,'public','CREATE')) "
                     "FROM pg_roles WHERE rolname='" + role + "'; COMMIT;")
            status, result = run(['runuser', '-u', 'postgres', '--', 'psql', '-XAt', '-d', name, '-c', query])
            rows = [line for line in result.splitlines() if line.startswith('{')]
            database_roles.append({'application': 'admin' if 'admin-backend' in str(base) else 'store',
                                   'verified': status == 0 and bool(rows),
                                   'capabilities': json.loads(rows[0]) if status == 0 and rows else None})

_, sshd = run(['sshd', '-T'])
_, firewall = run(['ufw', 'status'])
backup = Path('/opt/smawell/backups')
print(json.dumps({'nginxConfigValid': code == 0, 'sites': sites, 'applicationAndDatabaseBindings': bindings,
                  'services': services, 'environmentMetadata': environments,
                  'runtimeDatabaseRoles': database_roles,
                  'cloudflareClientIpHeader': bool(re.search(r'real_ip_header\s+CF-Connecting-IP\s*;', nginx)),
                  'trustedProxyRangeCount': len(re.findall(r'set_real_ip_from\s', nginx)),
                  'sshPasswordAuthentication': 'passwordauthentication yes' in sshd,
                  'sshRootPasswordLogin': bool(re.search(r'(?m)^permitrootlogin yes$', sshd)),
                  'ufwActive': 'Status: active' in firewall,
                  'backupDirectoryWorldAccessible': backup.exists() and bool(backup.stat().st_mode & 0o007)}))
