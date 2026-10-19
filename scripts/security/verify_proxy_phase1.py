"""Exercise actual phase-one nginx in a network-isolated disposable container.

No production requests, configuration installation, database or business writes.
The generated private key is an ephemeral test certificate, not a deployment key.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid

IMAGE = 'nginx:1.30.5-alpine'


def run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, timeout=kwargs.pop('timeout', 60), **kwargs)


def certificate(root):
    openssl = shutil.which('openssl')
    sans = 'DNS:gingtto.store,DNS:*.gingtto.store,DNS:smawell.shop,DNS:*.smawell.shop'
    if openssl:
        r = run([openssl, 'req', '-x509', '-nodes', '-newkey', 'rsa:2048', '-sha256', '-days', '2', '-subj', '/CN=gingtto.store', '-addext', 'subjectAltName=' + sans, '-keyout', str(root / 'tls.key'), '-out', str(root / 'tls.crt')])
        if r.returncode:
            raise RuntimeError('Fixture certificate generation failed')
    else:
        # Local Windows helper only; CI uses its bundled openssl executable.
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'gingtto.store')])
        now = datetime.now(timezone.utc)
        cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=2)).add_extension(x509.SubjectAlternativeName([x509.DNSName(n[4:]) for n in sans.split(',')]), critical=False).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256())
        (root / 'tls.key').write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (root / 'tls.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def prepare(root):
    templates = Path(__file__).parent
    headers = (templates / 'nginx-response-headers.conf').read_text()
    site = (templates / 'nginx-phase1-site.conf').read_text().replace('include /etc/nginx/snippets/gingtto-security-response-headers.conf;', headers)
    http = (templates / 'nginx-phase1-http.conf').read_text()
    http = http.replace('include /etc/nginx/snippets/cloudflare-trusted-peers.conf;', 'set_real_ip_from 127.0.0.2;')
    http = http.replace('include /etc/nginx/snippets/cloudflare-origin-peers.conf;', '127.0.0.1 1; 127.0.0.2 1;')
    routing = (templates / 'nginx-phase1-routing.conf.example').read_text()
    routing = routing.replace('GINGTTO_CERT_PATH', '/fixture/tls.crt').replace('GINGTTO_KEY_PATH', '/fixture/tls.key').replace('SMAWELL_CERT_PATH', '/fixture/tls.crt').replace('SMAWELL_KEY_PATH', '/fixture/tls.key')
    routing = routing.replace('include /etc/nginx/snippets/gingtto-security-phase1-site.conf;', site)
    routing = routing.replace('include /etc/nginx/snippets/gingtto-security-response-headers.conf;', headers)
    routing = routing.replace('include /etc/nginx/snippets/LEGACY_UPLOADS_FOR_THIS_SITE.conf;', 'location /uploads/ { alias /fixture/uploads/; add_header Cache-Control "public, max-age=2592000" always; }')
    routing = routing.replace('/opt/smawell/current/store/frontend/dist', '/fixture/html').replace('/opt/smawell/current/admin/frontend/dist', '/fixture/html')
    routing = routing.replace('/opt/smawell/public-assets/store/', '/fixture/assets/').replace('/opt/smawell/public-assets/admin/', '/fixture/assets/')
    upstream = '''
server { listen PORT; server_name _;
    add_header Cache-Control no-store always;
    location / { default_type application/json;
      return 200 '{"channel":"CHANNEL","client":"$http_x_forwarded_for","proto":"$http_x_forwarded_proto","host":"$host","forwardedHost":"$http_x_forwarded_host"}';
    }
}
'''
    config = 'worker_processes 2; error_log stderr crit; pid /tmp/security-phase1.pid; events {}\nhttp {\n' + http + routing + upstream.replace('PORT', '5301').replace('CHANNEL', 'store') + upstream.replace('PORT', '5302').replace('CHANNEL', 'admin') + '\n}\n'
    (root / 'nginx.conf').write_text(config, encoding='utf-8')
    (root / 'html').mkdir(); (root / 'html/index.html').write_text('<html><title>Isolated phase-one fixture</title></html>')
    (root / 'uploads').mkdir(); (root / 'uploads/legacy.txt').write_text('legacy-access-policy-fixture')
    (root / 'assets').mkdir(); (root / 'assets/old-hash.js').write_text('retained-hashed-asset')
    certificate(root)


def verify(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    prepare(output)
    name = 'gingtto-phase1-qa-' + uuid.uuid4().hex[:10]
    mount = 'type=bind,src=' + str(output).replace('\\', '/') + ',dst=/fixture,readonly'
    check = run(['docker', 'run', '--rm', '--network', 'none', '--mount', mount, IMAGE, 'nginx', '-t', '-c', '/fixture/nginx.conf'])
    (output / 'syntax.log').write_text(check.stdout + check.stderr, encoding='utf-8')
    if check.returncode:
        raise AssertionError('nginx phase-one syntax check failed; see syntax.log')
    started = run(['docker', 'run', '-d', '--rm', '--network', 'none', '--label', 'codex.task=security-phase1', '--name', name, '--mount', mount, IMAGE, 'nginx', '-c', '/fixture/nginx.conf', '-g', 'daemon off;'])
    if started.returncode:
        raise RuntimeError('Isolated nginx startup failed')
    identity = started.stdout.strip()
    evidence = {'syntax': True, 'network': 'none', 'productionModified': False}
    try:
        def request(host, path, *, scheme='https', source='127.0.0.1', headers=()):
            port = 443 if scheme == 'https' else 80
            argv = ['docker', 'exec', identity, 'curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '10', '--cacert', '/fixture/tls.crt', '--resolve', f'{host}:{port}:127.0.0.1', '--interface', source, '-i']
            for key, value in headers:
                argv += ['-H', key + ': ' + value]
            r = run(argv + [f'{scheme}://{host}{path}'])
            if r.returncode:
                return 0, {}, '', r.returncode
            head, _, body = r.stdout.partition('\n\n')
            status = int(head.splitlines()[0].split()[1])
            fields = {}
            for line in head.splitlines()[1:]:
                key, _, value = line.partition(':')
                fields[key.lower()] = value.strip()
            return status, fields, body, 0

        for _ in range(20):
            if request('gingtto.store', '/api/health')[0] == 200:
                break
            live = run(['docker', 'inspect', '--format', '{{.State.Running}}', identity])
            if live.returncode or live.stdout.strip() != 'true':
                raise RuntimeError('Owned fixture container stopped before readiness')
            time.sleep(.2)
        else:
            raise AssertionError('Owned nginx did not become ready')
        aliases = {'gingtto.store': 'store', 'www.gingtto.store': 'store', 'api.gingtto.store': 'store', 'smawell.shop': 'store', 'www.smawell.shop': 'store', 'api.smawell.shop': 'store', 'admin.gingtto.store': 'admin', 'api-admin.gingtto.store': 'admin', 'admin.smawell.shop': 'admin', 'api-admin.smawell.shop': 'admin'}
        for host, channel in aliases.items():
            status, fields, body, _ = request(host, '/api/health')
            assert status == 200 and json.loads(body)['channel'] == channel, 'Alias/upstream mismatch'
            assert fields.get('x-content-type-options') == 'nosniff'
            assert fields.get('strict-transport-security') == 'max-age=300'
        evidence['aliasRoutes'] = len(aliases)
        for path, expected in [('/api/public/products', 410), ('/api/internal/orders', 404)]:
            status, fields, _, _ = request('admin.gingtto.store', path)
            assert status == expected and fields.get('cache-control') == 'no-store'
            assert fields.get('x-frame-options') == 'SAMEORIGIN'
        evidence['retiredAndInternalEndpoints'] = True
        status, fields, _, _ = request('gingtto.store', '/shop', scheme='http')
        assert status == 308 and fields['location'] == 'https://gingtto.store/shop'
        assert request('admin.gingtto.store', '/api/admin/orders', scheme='http')[0] == 426
        evidence['httpPageRedirectApiRejected'] = True
        status, _, body, _ = request('admin.gingtto.store', '/api/health', headers=[('CF-Connecting-IP', '1.2.3.4'), ('X-Forwarded-For', '5.6.7.8'), ('X-Forwarded-Host', 'evil.invalid')])
        assert status == 200 and json.loads(body)['client'] == '127.0.0.1' and json.loads(body)['forwardedHost'] == ''
        status, _, body, _ = request('admin.gingtto.store', '/api/health', source='127.0.0.2', headers=[('CF-Connecting-IP', '1.2.3.4'), ('X-Forwarded-For', '5.6.7.8')])
        assert status == 200 and json.loads(body)['client'] == '1.2.3.4'
        assert request('admin.gingtto.store', '/api/health', source='127.0.0.3', headers=[('CF-Connecting-IP', '127.0.0.1')])[0] == 403
        evidence['trustedProxyAndOriginalPeerAdmission'] = True
        status, fields, _, _ = request('gingtto.store', '/shop')
        assert status == 200 and fields['cache-control'] == 'no-store'
        assert 'unsafe-eval' not in fields['content-security-policy-report-only']
        assert fields.get('strict-transport-security') == 'max-age=300'
        evidence['htmlHeadersAndNoStore'] = True
        status, fields, body, _ = request('gingtto.store', '/uploads/legacy.txt')
        assert status == 200 and '2592000' in fields['cache-control'] and body == 'legacy-access-policy-fixture'
        evidence['legacyUploadPolicyPreserved'] = True
        status, fields, body, _ = request('gingtto.store', '/assets/old-hash.js')
        assert status == 200 and 'immutable' in fields['cache-control'] and body == 'retained-hashed-asset'
        evidence['sharedHashedAssetsRetained'] = True
        maintenance = run(['docker', 'exec', identity, 'sh', '-c', 'mkdir -p /etc/gingtto; touch /etc/gingtto/maintenance'])
        assert maintenance.returncode == 0
        status, fields, _, _ = request('admin.gingtto.store', '/api/admin/orders')
        assert status == 503 and fields.get('retry-after') == '60' and fields.get('cache-control') == 'no-store'
        assert fields.get('x-content-type-options') == 'nosniff'
        run(['docker', 'exec', identity, 'rm', '/etc/gingtto/maintenance'])
        evidence['maintenanceBlocksBusinessRequests'] = True
        # A valid TLS alias but unknown HTTP Host must not reach an upstream.
        assert request('gingtto.store', '/api/health', headers=[('Host', 'unknown.invalid')])[3] != 0
        evidence['unknownHostRejected'] = True
        # Login policy is intentionally not limited in phase one. General query
        # resource limits continue to work, with all headers on the 429 path.
        for _ in range(25):
            assert request('admin.gingtto.store', '/api/auth/admin/login')[0] == 200
        evidence['loginProtectionDeferred'] = True
        command = "seq 1 90 | xargs -P 25 -I '{}' curl -s --noproxy '*' --cacert /fixture/tls.crt --resolve admin.gingtto.store:443:127.0.0.1 -D /tmp/phase1-limit{}.hdr -o /dev/null -w '%{http_code}\\n' https://admin.gingtto.store/api/admin/orders"
        flooded = run(['docker', 'exec', identity, 'sh', '-c', command])
        assert flooded.returncode == 0 and '429' in flooded.stdout.splitlines(), 'General query throttling not exercised'
        # Inspect an actual throttled response from the burst; a later request
        # may already have replenished its quota and correctly return 200.
        limited = run(['docker', 'exec', identity, 'sh', '-c', "for file in /tmp/phase1-limit*.hdr; do if grep -q '^HTTP/1.1 429' \"$file\"; then cat \"$file\"; break; fi; done"])
        fields = {line.partition(':')[0].lower(): line.partition(':')[2].strip() for line in limited.stdout.splitlines()[1:] if ':' in line}
        assert fields.get('retry-after') == '5' and fields.get('cache-control') == 'no-store', '429 response lost retry/cache headers'
        assert fields.get('x-content-type-options') == 'nosniff' and fields.get('strict-transport-security') == 'max-age=300'
        evidence['generalRateLimitAnd429Headers'] = True
        status,fields,body,_ = request('gingtto.store','/api/external/v1/products')
        assert status==200 and fields.get('cache-control')=='no-store' and fields.get('vary')=='Authorization'
        external_command = "seq 1 48 | xargs -P 24 -I '{}' curl -s --noproxy '*' --cacert /fixture/tls.crt --resolve gingtto.store:443:127.0.0.1 -D /tmp/external-limit{}.hdr -o /dev/null -w '%{http_code}\\n' https://gingtto.store/api/external/v1/products"
        external = run(['docker','exec',identity,'sh','-c',external_command])
        assert external.returncode==0 and '429' in external.stdout.splitlines(), 'External API entrance did not reject a burst'
        assert '503' not in external.stdout.splitlines(), 'Entrance overload must return 429, not maintenance'
        evidence['externalApiBurstProtectionAndNoStore']=True
        (output / 'result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        return evidence
    finally:
        # Only stop the exact container returned by this invocation; no project
        # services, other containers, networks, images or volumes are removed.
        run(['docker', 'stop', identity])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.output)))
