"""Install verified maintenance negotiation with nginx reload only."""
import fcntl,importlib.util,json,os,stat,subprocess,sys,tempfile
from pathlib import Path
from patch import patch_site

RECORD=Path('/var/lib/gingtto-release/operator-config/maintenance-response-20261117')
SITE_FILES=('gingtto-security-phase1-site.conf','gingtto-office-entry-site.conf')

def run(args):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    if p.returncode:raise RuntimeError('Command failed: '+args[0]+' '+p.stderr.decode('utf-8','replace')[-500:])
    return p.stdout

def trusted(path,directory=False):
    info=path.lstat()
    if info.st_uid!=0 or info.st_mode&0o022 or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise RuntimeError('Unexpected owner/type/mode: '+str(path))

def atomic(path,raw,mode=0o644):
    fd,name=tempfile.mkstemp(prefix='.maintenance-response-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

def install(data):
    assert os.geteuid()==0 and data['isolatedPassed'] is True
    spec=importlib.util.spec_from_file_location('installed_release','/usr/local/lib/gingtto-release/release_control.py')
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    cfg=m.Config();files=m.Files(cfg);ops=m.SystemOps(cfg,files)
    def snapshot():
        assert not Path('/etc/gingtto/maintenance').exists(),'Live maintenance is present'
        assert not Path('/etc/gingtto/security-cutover-approved').exists(),'Another release is authorized'
        result={'nginxPid':run(['systemctl','show','nginx','--property=MainPID','--value']).decode().strip()}
        for channel in ('admin','store'):
            a=cfg.app(channel);state=json.loads((cfg.state/(channel+'.json')).read_text())
            assert not state.get('pending') and ops.active(a) and ops.healthy(a)
            result[channel]={'pid':run(['systemctl','show',a['service'],'--property=MainPID','--value']).decode().strip(),'release':state['current']['directory']}
        return result
    with (cfg.state/'controller.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=snapshot();run(['nginx','-t'])
        assert 'include /etc/nginx/conf.d/*.conf;' in Path('/etc/nginx/nginx.conf').read_text()
        desired={}
        for name in SITE_FILES:
            p=Path('/etc/nginx/snippets',name);trusted(p)
            raw=p.read_text();assert raw==data['before'][name],'Site changed after inspection'
            desired[p]=patch_site(raw).encode()
        desired.update({Path('/etc/nginx/conf.d/gingtto-maintenance-response.conf'):data['http'].encode(),
            Path('/etc/nginx/snippets/gingtto-maintenance-response.conf'):data['site'].encode(),
            Path('/var/www/gingtto-admin-maintenance/index.html'):data['admin'].encode(),
            Path('/var/www/gingtto-store-maintenance/index.html'):data['store'].encode()})
        for p in (Path('/etc/nginx/conf.d/gingtto-maintenance-response.conf'),Path('/etc/nginx/snippets/gingtto-maintenance-response.conf'),Path('/var/www/gingtto-store-maintenance/index.html')):
            assert not p.exists() or p.read_bytes()==desired[p],'An existing operator file has different content'
        assert not RECORD.exists(),'Inspect the existing installation record before retrying'
        RECORD.mkdir(mode=0o700)
        original={};created=[]
        for p in desired:
            if p.exists():
                trusted(p);original[str(p)]={'content':p.read_text(),'mode':stat.S_IMODE(p.stat().st_mode)}
            else:original[str(p)]=None
        atomic(RECORD/'before.json',json.dumps({'files':original,'snapshot':before},ensure_ascii=False).encode(),0o600)
        reloaded=False
        try:
            for p,raw in desired.items():
                if not p.parent.exists():p.parent.mkdir(mode=0o755);created.append(p.parent)
                trusted(p.parent,directory=True)
                if not p.exists() or p.read_bytes()!=raw:atomic(p,raw)
            run(['nginx','-t']);reloaded=True;run(['systemctl','reload','nginx'])
            assert snapshot()==before,'A service master or release changed during nginx reload'
            result={'installed':True,'nginxReloadOnly':True,'adminNotRestarted':True,'storeNotRestarted':True,'liveMaintenanceFlagTouched':False,'snapshot':before}
            atomic(RECORD/'installed.json',json.dumps(result,ensure_ascii=False,indent=2).encode(),0o600)
            return result
        except BaseException:
            for p in desired:
                old=original[str(p)]
                if old is None:p.unlink(missing_ok=True)
                else:atomic(p,old['content'].encode(),old['mode'])
            for directory in reversed(created):directory.rmdir()
            run(['nginx','-t'])
            if reloaded:run(['systemctl','reload','nginx'])
            raise

if __name__=='__main__':print(json.dumps(install(json.load(sys.stdin)),ensure_ascii=False))
