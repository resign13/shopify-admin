"""Explicit release settings; never prints configuration values or credentials."""
import argparse
import os
from pathlib import Path
import secrets
import shutil
import tempfile
from datetime import datetime, timezone


def configure(path, mode):
    path = Path(path)
    if mode not in {'ensure', 'enable', 'disable'} or not path.is_file():
        raise ValueError('Existing backend configuration and a valid mode are required')
    original = path.read_text(encoding='utf-8')
    lines = original.splitlines()
    positions, values = {}, {}
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        key = key.strip()
        if key not in {'ORDER_VOICE_ENABLED', 'ORDER_VOICE_CURSOR_SECRET'}:
            continue
        if key in positions:
            raise ValueError('Duplicate voice configuration keys')
        positions[key], values[key] = i, value.strip().strip('"').strip("'")
    active = values.get('ORDER_VOICE_ENABLED', '').lower() in {'1', 'true', 'on'}
    key = values.get('ORDER_VOICE_CURSOR_SECRET', '')
    if len(key.encode()) < 32:
        if active and mode != 'disable':
            raise ValueError('Active signing configuration requires operator repair')
        key = secrets.token_urlsafe(48)
    enabled = active if mode == 'ensure' else mode == 'enable'
    for name, value in {'ORDER_VOICE_CURSOR_SECRET': key, 'ORDER_VOICE_ENABLED': '1' if enabled else '0'}.items():
        if name in positions:
            lines[positions[name]] = f'{name}={value}'
        else:
            lines.append(f'{name}={value}')
    updated = '\n'.join(lines) + '\n'
    changed = updated != original
    if changed:
        stat = path.stat()
        backup = path.with_name(path.name + '.voice-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
        fd, temporary = tempfile.mkstemp(prefix='.voice-settings-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            if hasattr(os, 'chown'):
                os.chown(temporary, stat.st_uid, stat.st_gid)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {'enabled': enabled, 'changed': changed}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['ensure', 'enable', 'disable'])
    parser.add_argument('--env', type=Path, required=True)
    args = parser.parse_args()
    result = configure(args.env, args.mode)
    print('Voice configuration verified: enabled=%s changed=%s' % (result['enabled'], result['changed']))
