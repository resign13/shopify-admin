"""Standalone nginx on a private loopback port; never touches the live flag."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import json,socket,subprocess,sys,time,urllib.error,urllib.request

def verify(data):
    class Backend(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.server.calls+=1
            self.send_response(self.server.health if self.path=='/api/health' else 401)
            self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"status":"ok"}')
    checks=[]
    def need(value,name):
        if not value:raise AssertionError(name)
        checks.append(name)
    with TemporaryDirectory(prefix='gingtto-maintenance-response-') as dirname,ThreadingHTTPServer(('127.0.0.1',0),Backend) as backend:
        root=Path(dirname);marker=root/'maintenance';permit=root/'permit';backend.calls=0;backend.health=200
        for name in ('admin','store','normal'):(root/name).mkdir()
        (root/'admin/index.html').write_text(data['admin']);(root/'store/index.html').write_text(data['store']);(root/'normal/index.html').write_text('Regular application')
        (root/'headers.conf').write_text(data['headers'])
        http=data['http'].replace('/var/www/gingtto-admin-maintenance',str(root/'admin')).replace('/var/www/gingtto-store-maintenance',str(root/'store')).replace('admin.gingtto.store','admin.fixture')
        site=data['site'].replace('/etc/nginx/snippets/gingtto-security-response-headers.conf',str(root/'headers.conf'))
        health=data['health'].replace('/etc/gingtto/security-cutover-approved',str(permit)).replace('/var/www/gingtto-admin-maintenance/index.html',str(root/'admin/index.html')).replace('/etc/nginx/snippets/gingtto-security-response-headers.conf',str(root/'headers.conf')).replace('127.0.0.1:5302','127.0.0.1:'+str(backend.server_port))
        (root/'http.conf').write_text(http);(root/'site.conf').write_text(site);(root/'health.conf').write_text(health)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        config=f'''pid {root}/nginx.pid;
error_log {root}/error.log;
daemon off;
master_process off;
events {{ worker_connections 32; }}
http {{
  include /etc/nginx/mime.types;
  include {root}/http.conf;
  access_log off;
  client_body_temp_path {root}/body;
  proxy_temp_path {root}/proxy;
  server {{
    listen 127.0.0.1:{port}; server_name admin.fixture; root {root}/normal;
    if (-f {marker}) {{ return 503; }}
    include {root}/site.conf;
    include {root}/health.conf;
    location /api/ {{ proxy_pass http://127.0.0.1:{backend.server_port}; }}
    location / {{ try_files $uri $uri/ /index.html; }}
  }}
  server {{
    listen 127.0.0.1:{port}; server_name store.fixture; root {root}/normal;
    if (-f {marker}) {{ return 503; }}
    include {root}/site.conf;
    location /api/ {{ proxy_pass http://127.0.0.1:{backend.server_port}; }}
    location / {{ try_files $uri $uri/ /index.html; }}
  }}
}}
'''
        (root/'nginx.conf').write_text(config)
        command=['nginx','-p',str(root),'-c',str(root/'nginx.conf')]
        subprocess.run([*command,'-t'],check=True,capture_output=True)
        worker=Thread(target=backend.serve_forever,daemon=True);worker.start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path,host='admin.fixture',accept='text/html',method='GET'):
            req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers={'Host':host,'Accept':accept},method=method,data=b'{}' if method=='POST' else None)
            try:r=opener.open(req,timeout=5)
            except urllib.error.HTTPError as e:r=e
            with r:return r.code,r.headers,r.read()
        try:
            with subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE) as nginx:
                try:
                    for attempt in range(30):
                        try:request('/login');break
                        except urllib.error.URLError:
                            if attempt==29 or nginx.poll() is not None:raise
                            time.sleep(.1)
                    for host in ('admin.fixture','store.fixture'):
                        need(request('/orders',host)[0]==200,'normal document '+host)
                    marker.touch();before=backend.calls
                    for host,page in [('admin.fixture',data['admin']),('store.fixture',data['store'])]:
                        for path in ('/','/login','/orders','/orders?page=2','/index.html'):
                            code,headers,body=request(path,host)
                            need(code==503 and body.decode()==page and headers.get('Content-Type','').startswith('text/html'),'maintenance document '+host+path)
                            need('no-store' in headers.get('Cache-Control','') and headers.get('Retry-After')=='30' and headers.get('X-Gingtto-Maintenance')=='1','document headers '+host+path)
                        code,headers,body=request('/orders',host,method='HEAD')
                        need(code==503 and not body and headers.get('Content-Type','').startswith('text/html'),'HEAD document '+host)
                        for path in ('/api/health','/api/admin/orders','/assets/app.js','/uploads/photo.png','/favicon.svg'):
                            code,headers,body=request(path,host)
                            need(code==503 and headers.get('Content-Type','').startswith('application/json') and json.loads(body)['code']=='maintenance','non-document stays JSON '+host+path)
                        need(request('/api/admin/orders',host,method='POST')[0]==503,'POST not forwarded '+host)
                        need(request('/orders',host,accept='*/*')[1].get('Content-Type','').startswith('application/json'),'non-HTML clients stay JSON '+host)
                    need(backend.calls==before,'maintenance forwarded no business requests')
                    marker.unlink()
                    for host in ('admin.fixture','store.fixture'):need(request('/orders',host)[0]==200,'flag removal restores '+host)
                    permit.touch();backend.health=503
                    code,headers,body=request('/login')
                    need(code==503 and body.decode()==data['admin'],'existing admin health fallback preserved')
                    backend.health=200
                    need(request('/login')[0]==200,'existing admin health recovery preserved')
                    permit.unlink()
                finally:
                    nginx.terminate();nginx.wait(timeout=10)
        finally:
            backend.shutdown();worker.join(timeout=5)
    return {'passed':True,'checks':checks,'liveMaintenanceFlagTouched':False,'serviceRestarted':False}

if __name__=='__main__':print(json.dumps(verify(json.load(sys.stdin))))
