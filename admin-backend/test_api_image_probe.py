"""No external traffic: validate the local download client's security/retries."""
import os
if os.environ.get('PGHOST')!='127.0.0.1' or not os.environ.get('PGDATABASE','').endswith('_test'):
    raise RuntimeError('Explicit local *_test configuration required')
import io
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PIL import Image
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from api_image_probe import ImageProbe


class Response:
    def __init__(self,body,status=200,**headers):
        self.status_code=status;self.body=body;self.headers={'Content-Type':'image/jpeg',**headers};self.closed=False
    def iter_content(self,size):yield self.body
    def close(self):self.closed=True


class ApiImageProbeTest(unittest.TestCase):
    def setUp(self):
        buf=io.BytesIO();Image.new('RGB',(2,2),'white').save(buf,format='JPEG');self.jpeg=buf.getvalue()
        self.steps=[];self.calls=[];self.sessions=[]
        owner=self
        class Session:
            def __init__(self):
                self.headers={};self.proxies={};self.trust_env=True;self.closed=False;self.cleared=0
                self.cookies=SimpleNamespace(clear=self.clear);owner.sessions.append(self)
            def clear(self):self.cleared+=1
            def get(self,url,**kwargs):
                owner.calls.append((self,url,kwargs))
                item=owner.steps.pop(0)
                if isinstance(item,BaseException):raise item
                return item
            def close(self):self.closed=True
        self.mock=patch('api_image_probe.requests.Session',Session);self.mock.start()
        self.dns=patch('api_image_probe.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]);self.dns.start()
        self.sleep=patch('api_image_probe.time.sleep');self.sleep.start()
        self.probe=ImageProbe({'https://images.example.test'})
    def tearDown(self):self.probe.close();self.sleep.stop();self.dns.stop();self.mock.stop()
    def test_success_reuses_session_never_sends_api_headers_or_cookies(self):
        self.steps=[Response(self.jpeg),Response(self.jpeg)]
        for index in (1,2):
            result=self.probe.sample('https://images.example.test/'+str(index)+'.jpg?signature=opaque')
            self.assertEqual(result['bytes'],len(self.jpeg));self.assertNotIn('error',result)
            self.assertTrue(result['certificateVerification']);self.assertFalse(result['credentialsForwarded'])
        self.assertEqual(len(self.sessions),1);self.assertEqual(self.sessions[0].cleared,2)
        self.assertFalse(self.sessions[0].trust_env)
        for _,_,kwargs in self.calls:
            self.assertIs(kwargs['verify'],True);self.assertNotIn('headers',kwargs);self.assertFalse(kwargs['allow_redirects'])
    def test_local_copy_publishes_only_valid_complete_images(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'nested'/'photo.jpg'
            self.steps=[Response(self.jpeg)]
            result=self.probe.sample('https://images.example.test/photo.jpg',destination=path)
            self.assertNotIn('error',result);self.assertEqual(path.read_bytes(),self.jpeg)
            self.steps=[Response(b'not an image')]
            result=self.probe.sample('https://images.example.test/photo.jpg',destination=path)
            self.assertIn('error',result);self.assertEqual(path.read_bytes(),self.jpeg)
            self.assertEqual(list(path.parent.glob('*.tmp')),[])
    def test_transient_tls_eof_get_retries_once_on_fresh_connection_pool(self):
        self.steps=[requests.exceptions.SSLError('UNEXPECTED_EOF_WHILE_READING'),Response(self.jpeg)]
        result=self.probe.sample('https://images.example.test/image.jpg')
        self.assertNotIn('error',result);self.assertEqual(len(result['attempts']),2)
        self.assertEqual(len(self.sessions),2);self.assertTrue(self.sessions[0].closed)
    def test_certificate_errors_never_retry_or_disable_verification(self):
        self.steps=[requests.exceptions.SSLError('CERTIFICATE_VERIFY_FAILED')]
        result=self.probe.sample('https://images.example.test/image.jpg')
        self.assertEqual(result['error'],'tls_certificate_validation_failed');self.assertEqual(len(self.calls),1)
    def test_read_timeout_retry_is_bounded_and_diagnostics_omit_urls(self):
        self.steps=[requests.exceptions.ReadTimeout('https://secret@host/file?TOKEN=secret')]*2
        result=self.probe.sample('https://images.example.test/image.jpg')
        self.assertEqual(result['error'],'network_timeout');self.assertEqual(len(self.calls),2)
        self.assertNotIn('secret',str(result));self.assertNotIn('TOKEN',str(result))
    def test_bad_origin_http_credentials_and_fragment_rejected(self):
        for url in ['http://images.example.test/x','https://bad.example.test/x','https://user@images.example.test/x','https://images.example.test/x#fragment','https://images.example.test/x\ny']:
            self.assertEqual(self.probe.sample(url)['error'],'untrusted_image_url')
        self.assertEqual(self.calls,[])
    def test_nonpublic_dns_and_multicast_are_rejected(self):
        for address in ('127.0.0.1','10.0.0.1','169.254.169.254','224.0.0.1','198.18.0.1','::ffff:127.0.0.1'):
            with patch('api_image_probe.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))]):
                self.assertEqual(self.probe.sample('https://images.example.test/x')['error'],'nonpublic_direct_destination')
        self.assertEqual(self.calls,[])
    def test_explicit_proxy_handles_fake_ip_without_weakening_target_host_or_tls(self):
        self.probe.close();self.probe=ImageProbe({'https://images.example.test'},proxy_url='http://operator:secret@127.0.0.1:7897')
        self.steps=[Response(self.jpeg)]
        with patch('api_image_probe.socket.getaddrinfo',side_effect=AssertionError('Proxy resolves its target')):
            result=self.probe.sample('https://images.example.test/x')
        self.assertNotIn('error',result);self.assertNotIn('secret',str(result))
        self.assertTrue(self.calls[0][2]['verify'])
    def test_redirect_revalidated_and_no_http_downgrade(self):
        for target in ('http://images.example.test/x','https://evil.example.test/x'):
            self.steps=[Response(b'',302,Location=target)]
            self.assertEqual(self.probe.sample('https://images.example.test/x')['error'],'untrusted_image_url')
        self.assertEqual(len(self.calls),2)
    def test_redirect_loop_http_errors_and_retry_after_not_ignored(self):
        self.steps=[Response(b'',302,Location='/loop') for _ in range(4)]
        self.assertEqual(self.probe.sample('https://images.example.test/x')['error'],'image_redirect_limit')
        for code in (403,404,429):
            self.steps=[Response(b'',code,**{'Retry-After':'120'})]
            result=self.probe.sample('https://images.example.test/x');self.assertEqual(len(result['attempts']),1)
    def test_body_limit_content_type_and_real_image_validation(self):
        for response in (Response(self.jpeg,**{'Content-Length':str(11*1024*1024)}),Response(b'not an image'),Response(self.jpeg,**{'Content-Type':'text/html'})):
            self.steps=[response];self.assertIn('error',self.probe.sample('https://images.example.test/x'))
            self.assertTrue(response.closed)
    def test_deadline_before_request_and_configuration_bounds(self):
        self.probe.budget_seconds=1
        with patch('api_image_probe.time.monotonic',side_effect=[0,2]):
            result=self.probe.sample('https://images.example.test/x')
        self.assertEqual(result['error'],'image_sample_budget_exhausted');self.assertEqual(self.calls,[])
        for kwargs in ({'connect_seconds':0},{'max_attempts':3},{'budget_seconds':999},{'max_bytes':999999999}):
            with self.assertRaises(ValueError):ImageProbe({'https://images.example.test'},**kwargs)

if __name__=='__main__':unittest.main()
