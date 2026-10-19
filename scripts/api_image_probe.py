"""Operator-run public-image acceptance client, not an application fetch proxy.

Exact HTTPS origins, certificate validation, bounded redirects/bytes/time and
GET-only transient retries. Never forwards API credentials/cookies. Production
safe_images SSRF/DNS pinning is deliberately not modified by this local tool.
"""
import ipaddress
import socket
import time
from urllib.parse import urlsplit, urljoin

import requests
from urllib3.util import Timeout


class ImageProbe:
    def __init__(self, origins, *, proxy_url=None, connect_seconds=15, read_seconds=20,
                 budget_seconds=60, max_bytes=10*1024*1024, max_attempts=2):
        self.origins=set(origins)
        for origin in self.origins:
            p=urlsplit(origin)
            if p.scheme!='https' or not p.hostname or p.username or p.password or p.path or p.query or p.fragment or p.port not in {None,443}:
                raise ValueError('Invalid trusted HTTPS image origin')
        if proxy_url:
            p=urlsplit(proxy_url)
            if p.scheme not in {'http','https'} or not p.hostname or p.path not in {'','/'} or p.query or p.fragment:
                raise ValueError('Invalid explicitly configured image proxy')
        if not (1<=connect_seconds<=30 and 1<=read_seconds<=30 and 1<=budget_seconds<=90 and 1<=max_attempts<=2 and 1<=max_bytes<=32*1024*1024):
            raise ValueError('Invalid bounded image sample settings')
        self.proxy=proxy_url
        self.connect_seconds,self.read_seconds,self.budget_seconds=connect_seconds,read_seconds,budget_seconds
        self.max_bytes,self.max_attempts=max_bytes,max_attempts
        self.sessions={}

    def close(self):
        for session in self.sessions.values(): session.close()
        self.sessions.clear()

    def _validate(self,url):
        p=urlsplit(url)
        if (p.scheme!='https' or not p.hostname or p.username or p.password or p.fragment or p.port not in {None,443}
            or 'https://'+p.netloc not in self.origins or len(url)>2048 or any(ord(c)<=32 or c=='\\' for c in url)):
            raise ValueError('untrusted_image_url')
        if not self.proxy:
            rows=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
            if not rows or any('%' in row[4][0] or not ipaddress.ip_address(row[4][0]).is_global or ipaddress.ip_address(row[4][0]).is_multicast for row in rows):
                raise ValueError('nonpublic_direct_destination')
        # With an explicit operator proxy, CONNECT uses the exact trusted host;
        # its DNS is remote, rather than the computer's local fake-IP resolver.
        return 'https://'+p.netloc

    def _session(self,origin):
        if origin not in self.sessions:
            s=requests.Session();s.trust_env=False
            s.headers.update({'Accept':'image/*','Accept-Encoding':'identity','User-Agent':'GINGTTO-Local-Image-Acceptance/1.0'})
            if self.proxy: s.proxies={'https':self.proxy}
            self.sessions[origin]=s
        self.sessions[origin].cookies.clear()
        return self.sessions[origin]

    def sample(self,url,kind='image'):
        started=time.perf_counter();deadline=time.monotonic()+self.budget_seconds
        result={'kind':kind,'certificateVerification':True,'credentialsForwarded':False,
            'transport':'explicit_operator_proxy' if self.proxy else 'validated_direct',
            'connectTimeoutSeconds':self.connect_seconds,'readTimeoutSeconds':self.read_seconds,
            'budgetSeconds':self.budget_seconds,'limitBytes':self.max_bytes,'attempts':[]}
        original=url
        for attempt in range(1,self.max_attempts+1):
            attempt_started=time.perf_counter();response=None;origin=None;size=0;retry=False
            entry={'number':attempt}
            try:
                url=original
                for hop in range(4):
                    origin=self._validate(url)
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('image_sample_budget_exhausted')
                    session=self._session(origin)
                    response=session.get(url,stream=True,allow_redirects=False,verify=True,
                        timeout=Timeout(total=remaining,connect=min(self.connect_seconds,remaining),read=min(self.read_seconds,remaining)))
                    entry['status']=response.status_code
                    if response.status_code in {301,302,303,307,308}:
                        if hop==3:raise ValueError('image_redirect_limit')
                        url=urljoin(url,response.headers.get('Location',''));response.close();response=None
                        continue
                    break
                result.update(status=response.status_code,ttfbMs=round((time.perf_counter()-started)*1000,2),
                    contentType=response.headers.get('Content-Type',''),cdnCache=response.headers.get('CF-Cache-Status','unknown'))
                if response.status_code!=200:
                    # A 429 is reported, not retried before its Retry-After.
                    retry=response.status_code in {502,503,504}
                    raise ValueError('upstream_http_'+str(response.status_code))
                if not result['contentType'].lower().startswith('image/'):
                    raise ValueError('unexpected_image_content_type')
                if response.headers.get('Content-Encoding','identity')!='identity':
                    raise ValueError('unexpected_image_encoding')
                if int(response.headers.get('Content-Length','0'))>self.max_bytes:
                    raise ValueError('image_byte_limit')
                chunks=[]
                for chunk in response.iter_content(65536):
                    if time.monotonic()>deadline:raise TimeoutError('image_sample_budget_exhausted')
                    size+=len(chunk)
                    if size>self.max_bytes:raise ValueError('image_byte_limit')
                    chunks.append(chunk)
                # Reuse the unchanged production image-content validation.
                from safe_images import check_image
                check_image(b''.join(chunks))
                elapsed=time.perf_counter()-started
                entry['success']=True
                result.update(bytes=size,totalMs=round(elapsed*1000,2),MiBPerSecond=round(size/1024/1024/elapsed,6),KiBPerSecond=round(size/1024/elapsed,2))
                result.pop('error',None)
            except requests.exceptions.SSLError as error:
                reason=str(error).upper()
                if 'CERTIFICATE_VERIFY_FAILED' in reason or 'SSLCERTVERIFICATIONERROR' in reason:
                    entry['error']='tls_certificate_validation_failed'
                elif any(v in reason for v in ('EOF','CONNECTION_RESET','ECONNRESET','TLSV1_ALERT_INTERNAL_ERROR')):
                    entry['error']='transient_tls_connection_error';retry=True
                else:entry['error']='tls_protocol_error'
            except (requests.exceptions.Timeout,requests.exceptions.ConnectionError) as error:
                entry['error']='network_timeout' if isinstance(error,requests.exceptions.Timeout) else 'connection_error'
                retry=True
            except (ValueError,TimeoutError,OSError) as error:
                entry['error']=str(error) if isinstance(error,(ValueError,TimeoutError)) and str(error).startswith(('upstream_http_','image_','untrusted_','nonpublic_','unexpected_')) else type(error).__name__
            finally:
                if response is not None:response.close()
                entry.update(durationMs=round((time.perf_counter()-attempt_started)*1000,2),bytesRead=size)
                result['attempts'].append(entry)
            if entry.get('success'):break
            result['error']=entry['error']
            if not retry or attempt>=self.max_attempts or time.monotonic()+.25>=deadline:break
            # Only a failed origin's connection pool is discarded. No weak TLS,
            # HTTP downgrade, browser credentials or hidden extra attempts.
            if origin and origin in self.sessions:self.sessions.pop(origin).close()
            time.sleep(.25)
        result.setdefault('totalMs',round((time.perf_counter()-started)*1000,2))
        return result
