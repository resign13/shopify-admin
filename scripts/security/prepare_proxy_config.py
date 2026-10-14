"""Prepare, never install/reload, verified Cloudflare peer includes."""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
from urllib.request import Request, urlopen

SOURCES = {4: 'https://www.cloudflare.com/ips-v4', 6: 'https://www.cloudflare.com/ips-v6'}


def parse_ranges(raw, version):
    if len(raw) > 65536:
        raise ValueError('Unexpected Cloudflare response size')
    values = [ipaddress.ip_network(line.strip(), strict=True) for line in raw.decode('ascii').splitlines() if line.strip()]
    if not (10 if version == 4 else 5) <= len(values) <= 100:
        raise ValueError('Unexpected Cloudflare range count')
    if len(set(values)) != len(values):
        raise ValueError('Duplicate Cloudflare range')
    for value in values:
        if value.version != version or value.prefixlen < (8 if version == 4 else 16) or not value.network_address.is_global or not value.broadcast_address.is_global:
            raise ValueError('Invalid Cloudflare range')
    return values


def prepare(output, ops, downloader=None):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Use a new output directory; existing configuration is preserved')
    admissions = [ipaddress.ip_network(value, strict=True) for value in ops]
    if not admissions or any(n.prefixlen < (24 if n.version == 4 else 64) for n in admissions):
        raise ValueError('Explicit narrow maintenance source networks are required')
    if downloader is None:
        def downloader(url):
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0 GINGTTO-Security-Config/1.0', 'Accept': 'text/plain'})
            with urlopen(request, timeout=20) as response:
                if response.url != url or response.status != 200:
                    raise ValueError('Unexpected Cloudflare redirect or status')
                return response.read(65537)
    networks, manifests = [], []
    for version, url in SOURCES.items():
        raw = downloader(url)
        parsed = parse_ranges(raw, version)
        networks.extend(parsed)
        manifests.append({'source': url, 'sha256': hashlib.sha256(raw).hexdigest(), 'networks': len(parsed)})
    # Do not trust operations clients to supply a client IP. Trust only actual
    # Cloudflare peers; admission-only sources cannot spoof forwarded headers.
    trusted = ''.join(f'set_real_ip_from {n};\n' for n in networks)
    allowed = ''.join(f'{n} 1;\n' for n in dict.fromkeys(networks + admissions))
    output.mkdir(parents=True)
    (output / 'cloudflare-trusted-peers.conf').write_text(trusted, encoding='ascii')
    (output / 'cloudflare-origin-peers.conf').write_text(allowed, encoding='ascii')
    (output / 'manifest.json').write_text(json.dumps({'createdAt': datetime.now(timezone.utc).isoformat(), 'sources': manifests, 'opsNetworks': [str(n) for n in admissions], 'installed': False}, indent=2), encoding='utf-8')
    return len(networks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--ops-network', action='append', required=True)
    args = parser.parse_args()
    count = prepare(args.output, args.ops_network)
    print(f'Prepared {count} verified proxy ranges; no live configuration was modified')
