"""Actual installer, SSH/SFTP, sudoers and systemd parser in a disposable Linux.

Run only in an explicit network-none fixture container. No actual systemd
manager exists here; parser/SSH evidence never substitutes for live cutover.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time


def run(argv, *, check=True):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45)
    if check and result.returncode:
        raise AssertionError('Isolated operation failed: ' + Path(argv[0]).name + ': ' + result.stderr[-1200:])
    return result


def main():
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/.dockerenv').is_file() or os.environ.get('SECURITY_INSTALL_FIXTURE') != '1' or {p.name for p in Path('/sys/class/net').iterdir()} != {'lo'}:
        raise RuntimeError('Explicit isolated network-none Linux fixture required')
    import pwd
    source, units = Path('/fixture'), Path('/fixture-units')
    run(['/bin/bash', str(source / 'install_release_controller.sh'), '--install'])
    run(['/bin/bash', str(source / 'install_release_controller.sh'), '--install'])
    run(['/usr/sbin/visudo', '-cf', '/etc/sudoers.d/gingtto-release'])
    deploy = pwd.getpwnam('gingtto-deploy')
    for path in ['/usr/local/sbin/gingtto-release', '/usr/local/lib/gingtto-release/release_control.py', '/etc/gingtto/runtime']:
        run(['/usr/sbin/runuser', '-u', deploy.pw_name, '--', '/bin/sh', '-c', 'test ! -w ' + shlex.quote(path)])

    run(['/usr/bin/ssh-keygen', '-A'])
    Path('/run/sshd').mkdir(exist_ok=True)
    def ssh_policy(user):
        result = run(['/usr/sbin/sshd', '-T', '-C', 'user=' + user + ',host=fixture.local,addr=127.0.0.1'])
        return dict(line.split(' ', 1) for line in result.stdout.splitlines() if ' ' in line)
    root_before = ssh_policy('root')
    destination = Path('/etc/ssh/sshd_config.d/60-gingtto-deploy.conf')
    shutil.copyfile(source / 'gingtto-deploy-sshd.conf.example', destination)
    run(['/usr/sbin/sshd', '-t'])
    assert ssh_policy('root') == root_before, 'Deploy Match changed unrelated/root SSH configuration'
    policy = ssh_policy(deploy.pw_name)
    for key, expected in {'authenticationmethods': 'publickey', 'passwordauthentication': 'no',
            'kbdinteractiveauthentication': 'no', 'allowtcpforwarding': 'no', 'allowagentforwarding': 'no',
            'permittty': 'no', 'permittunnel': 'no', 'x11forwarding': 'no'}.items():
        assert policy[key] == expected, 'Incorrect dedicated SSH policy'
    key = Path('/tmp/fixture-client')
    run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)])
    authorized = Path('/var/lib/gingtto-deploy/.ssh/authorized_keys')
    authorized.write_text('restrict ' + key.with_suffix('.pub').read_text())
    os.chown(authorized, deploy.pw_uid, deploy.pw_gid); authorized.chmod(0o600)
    known = Path('/tmp/fixture-known-hosts')
    known.write_text('[127.0.0.1]:2222 ' + Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text())
    options = ['-i', str(key), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ConnectTimeout=5', '-o', 'UserKnownHostsFile=' + str(known)]
    def ssh(command, check=True):
        return run(['/usr/bin/ssh', *options, '-p', '2222', deploy.pw_name + '@127.0.0.1', command], check=check)
    with subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-p', '2222', '-o', 'ListenAddress=127.0.0.1'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True) as server:
        try:
            for attempt in range(30):
                ready = ssh('true', check=False)
                if ready.returncode == 0: break
                if server.poll() is not None: raise AssertionError('Isolated SSH daemon exited')
                time.sleep(0.1)
            else: raise AssertionError('Dedicated key login failed: ' + ready.stderr[-500:])
            status = json.loads(ssh('sudo -n /usr/local/sbin/gingtto-release status admin').stdout)
            assert status['active'] is False and status['pendingRecovery'] is False
            assert ssh('sudo -n /usr/bin/id -u', check=False).returncode != 0
            bad = 'a' * 64 + ';touch /tmp/forbidden-root-fixture'
            assert ssh(shlex.join(['sudo', '-n', '/usr/local/sbin/gingtto-release', 'voice', 'enable', bad]), check=False).returncode != 0
            assert not Path('/tmp/forbidden-root-fixture').exists()
            ssh('umask 077; mkdir -p /opt/smawell/incoming/admin-123-1')
            upload = Path('/tmp/fixture-upload'); upload.write_bytes(b'synthetic-not-a-release')
            run(['/usr/bin/scp', *options, '-P', '2222', str(upload), deploy.pw_name + '@127.0.0.1:/opt/smawell/incoming/admin-123-1/release.tar.gz'])
            received = Path('/opt/smawell/incoming/admin-123-1/release.tar.gz')
            assert received.read_bytes() == upload.read_bytes() and received.stat().st_uid == deploy.pw_uid
            ssh('chmod 600 /opt/smawell/incoming/admin-123-1/release.tar.gz')
            assert received.stat().st_mode & 0o777 == 0o600
            import sys
            sys.path.insert(0, '/usr/local/lib/gingtto-release')
            from release_control import Config, Files
            sealed = Files(Config()).spool('admin', 'admin-123-1', deploy.pw_uid)
            assert sealed.read_bytes() == upload.read_bytes() and sealed.stat().st_mode & 0o777 == 0o600
        finally:
            server.terminate(); server.wait(timeout=10)

    # Validate the real drop-in syntax/merge with an intentionally old base.
    # Executables below are inert markers, not an application/systemd runtime.
    lint = Path('/tmp/fixture-units'); lint.mkdir()
    for channel, backend in [('admin', 'admin-backend'), ('store', 'storefront-backend')]:
        executable = Path('/opt/smawell/current') / channel / backend / '.venv/bin'
        executable.mkdir(parents=True)
        for name in ['gunicorn', 'python']:
            shutil.copyfile('/bin/true', executable / name); (executable / name).chmod(0o755)
        unit = lint / ('smawell-' + channel + '-api.service')
        unit.write_text('[Unit]\nDescription=Legacy fixture\n[Service]\nUser=root\nEnvironment=PGUSER=obsolete\nEnvironmentFile=-/obsolete/owner.env\nExecStart=/bin/true obsolete\n')
        dropin = unit.with_name(unit.name + '.d'); dropin.mkdir()
        shutil.copyfile(units / ('smawell-' + channel + '-api.security.conf'), dropin / 'security.conf')
    for name in ['gingtto-security-maintenance.service', 'gingtto-security-maintenance.timer',
                 'smawell-order-notification-cleanup.service', 'smawell-order-notification-cleanup.timer']:
        shutil.copyfile(units / name, lint / name)
    paths = [str(p) for p in lint.iterdir() if p.suffix in {'.service', '.timer'}]
    run(['/usr/bin/systemd-analyze', 'verify', '--man=no', *paths])
    print(json.dumps({'installerRepeated': True, 'realSudoersAccepted': True, 'dedicatedKeySsh': True,
        'strictHostFingerprint': True, 'sftpUploadOwnedByDeploy': True, 'arbitraryRootCommandDenied': True,
        'realSftpArchiveIntakePassed': True,
        'boundedArgumentsRejected': True, 'runtimeCodeNotWritable': True, 'rootSshPolicyUnchanged': True,
        'realSystemdParserAcceptedSixUnits': True, 'systemdManager': 'not running; executable markers used only for parser',
        'network': 'none', 'productionModified': False}))


if __name__ == '__main__': main()
