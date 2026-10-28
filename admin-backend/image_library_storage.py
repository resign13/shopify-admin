"""Bounded provider metadata and immutable destinations for referenced legacy images."""
import base64
import io
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from image_library_normalization import Conflict, IMAGE_EXTENSIONS, Unsupported
from safe_images import MAX_BYTES, check_image, fetch_image


FORMATS={'jpg','jpeg','png','webp','avif','gif','bmp','mpo'}


class LegacyProviders:
    def __init__(self,media,*,max_pages=3):
        if not 1<=max_pages<=3: raise ValueError('Metadata page bound must be 1 to 3')
        self.media,self.max_pages=media,max_pages
        self.scope={}

    def cloud_request(self,path,*,fields=None,raw=None,filename=None,mime=None):
        cloud=os.environ['CLOUDINARY_CLOUD_NAME'].strip()
        auth=base64.b64encode((os.environ['CLOUDINARY_API_KEY'].strip()+':'+os.environ['CLOUDINARY_API_SECRET'].strip()).encode()).decode()
        headers={'Authorization':'Basic '+auth,'Accept':'application/json'}
        body=None
        if fields is not None:
            boundary='----ImageNormalization'+secrets.token_hex(12)
            body=bytearray()
            for key,value in fields.items():
                body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
            body.extend(raw); body.extend(f'\r\n--{boundary}--\r\n'.encode()); body=bytes(body)
            headers['Content-Type']='multipart/form-data; boundary='+boundary
        endpoint='https://api.cloudinary.com/v1_1/'+quote(cloud,safe='')+'/'+path
        with urlopen(Request(endpoint,data=body,headers=headers,method='POST' if fields is not None else 'GET'),timeout=30) as response:
            encoded=response.read(16*1024*1024+1)
        if len(encoded)>16*1024*1024: raise ValueError('Metadata response is too large')
        return json.loads(encoded)

    def classify(self,url):
        p=urlsplit(url)
        if p.query or p.fragment: raise Unsupported('Transformed/query URLs need explicit review')
        cloud=os.environ.get('CLOUDINARY_CLOUD_NAME','').strip()
        if p.scheme=='https' and p.hostname=='res.cloudinary.com' and not p.username and not p.password:
            match=re.fullmatch(r'/'+re.escape(cloud)+r'/image/upload/v([0-9]+)/(.+)\.([A-Za-z0-9]+)',p.path)
            if not match: raise Unsupported('Only versioned original resources in the configured cloud are supported')
            if match[3].lower() not in FORMATS: raise Unsupported('Resource is not a supported image')
            return {'provider':'cloudinary','public_id':unquote(match[2]),'version':int(match[1])}
        source=self.media.legacy_export_source(url)
        if source and source.get('legacy_key') and source.get('legacy_channel')=='admin':
            return {'provider':'r2','key':source['legacy_key']}
        raise Unsupported('Only owned legacy R2 or configured Cloudinary originals are supported')

    def metadata(self,urls):
        result={}; clouds={}; r2={}
        for url in urls:
            try:
                source=self.classify(url)
                result[url]={'status':'candidate','bytes':None,**source}
                if source['provider']=='cloudinary': clouds.setdefault((source['public_id'],source['version']),[]).append(url)
                else: r2.setdefault(source['key'],[]).append(url)
            except Exception as error:
                result[url]={'status':'unsupported','error_type':type(error).__name__,'bytes':None}
        if clouds:
            cursor=None; pages=0
            try:
                for _ in range(self.max_pages):
                    params={'max_results':500}
                    if cursor: params['next_cursor']=cursor
                    data=self.cloud_request('resources/image/upload?'+urlencode(params)); pages+=1
                    for resource in data.get('resources',[]):
                        identity=(resource.get('public_id'),resource.get('version'))
                        aliases=clouds.get(identity,[])
                        if not aliases: continue  # Never stage unreferenced account assets.
                        fmt=str(resource.get('format','')).lower()
                        for url in aliases:
                            requested=Path(urlsplit(url).path).suffix.lower().lstrip('.')
                            same_format=({'jpg':'jpeg'}.get(requested,requested)=={'jpg':'jpeg'}.get(fmt,fmt))
                            result[url].update(bytes=resource.get('bytes'),format=fmt,
                                               verified_original_image=fmt in FORMATS and same_format,
                                               status='candidate' if fmt in FORMATS else 'excluded_non_image')
                    cursor=data.get('next_cursor')
                    if not cursor: break
                self.scope['cloudinary']={'pages':pages,'truncated':bool(cursor),'matched':sum(result[u].get('bytes') is not None for aliases in clouds.values() for u in aliases)}
            except Exception as error:
                self.scope['cloudinary']={'pages':pages,'truncated':True,'error_type':type(error).__name__}
        if r2:
            from image_delivery import r2_client
            cursor=None; pages=0; truncated=False
            try:
                for _ in range(self.max_pages):
                    params={'Bucket':os.environ['R2_BUCKET'],'MaxKeys':1000}
                    if cursor: params['ContinuationToken']=cursor
                    data=r2_client().list_objects_v2(**params); pages+=1
                    for item in data.get('Contents',[]):
                        for url in r2.get(item.get('Key'),[]): result[url]['bytes']=item.get('Size')
                    truncated=bool(data.get('IsTruncated')); cursor=data.get('NextContinuationToken')
                    if not truncated: break
                self.scope['r2']={'pages':pages,'truncated':truncated,'matched':sum(result[u].get('bytes') is not None for us in r2.values() for u in us)}
            except Exception as error:
                self.scope['r2']={'pages':pages,'truncated':True,'error_type':type(error).__name__}
        for entry in result.values():
            if entry['status']=='candidate' and entry['bytes'] is not None and entry['bytes']>MAX_BYTES:
                entry['status']='over_input_limit'
        return result

    def read_original(self,entry):
        actual=self.classify(entry['original_url'])
        if actual['provider']!=entry['provider']: raise Conflict('Source provider changed')
        if actual['provider']=='cloudinary':
            if entry.get('format') and entry['format'] not in FORMATS: raise Unsupported('Cloudinary format is not an image')
            raw=fetch_image(entry['original_url'])
        else:
            source=self.media.legacy_export_source(entry['original_url'])
            raw=self.media.read_legacy_source(source)
        check_image(raw)  # R2 list metadata alone does not establish file type.
        return raw

    def destination(self,entry,suffix):
        if entry['provider']=='cloudinary':
            folder=os.environ.get('CLOUDINARY_UPLOAD_FOLDER','gingtto').strip().strip('/') or 'gingtto'
            return folder+'/normalized/'+entry['id']
        return 'normalized/'+entry['id']+suffix

    def publish(self,entry,raw,mime,suffix):
        key=self.destination(entry,suffix)
        if entry['provider']=='cloudinary':
            fields={'public_id':key,'overwrite':'false','unique_filename':'false','use_filename':'false'}
            try:
                result=self.cloud_request('image/upload',fields=fields,raw=raw,filename=entry['id']+suffix,mime=mime)
            except HTTPError as error:
                if error.code not in {400,409}: raise
                # A process may have stopped after creating this unique object.
                # Read-only lookup and subsequent byte comparison permit resume.
                result=self.cloud_request('resources/image/upload/'+quote(key,safe=''))
            if result.get('public_id')!=key or str(result.get('format','')).lower() not in FORMATS:
                raise Conflict('Unexpected Cloudinary destination')
            url=result.get('secure_url')
            actual=self.classify(url)
            if actual['public_id']!=key: raise Conflict('Unexpected Cloudinary delivery URL')
            return url
        from image_delivery import r2_client
        client=r2_client()
        try:
            client.put_object(Bucket=os.environ['R2_BUCKET'],Key=key,Body=raw,ContentType=mime,IfNoneMatch='*')
        except Exception as error:
            status=getattr(error,'response',{}).get('ResponseMetadata',{}).get('HTTPStatusCode')
            if status!=412: raise
        original=urlsplit(entry['original_url'])
        origin=(original.scheme+'://'+original.netloc) if original.netloc else ''
        return origin+'/uploads/'+quote(key,safe='/')

    def read_published(self,entry,url):
        if entry['provider']=='cloudinary':
            raw=fetch_image(url)
            return raw,check_image(raw)
        from image_delivery import r2_client
        key=self.classify(url)['key']
        response=r2_client().get_object(Bucket=os.environ['R2_BUCKET'],Key=key)
        stream=response['Body']
        try:
            if response.get('ContentLength',0)>MAX_BYTES: raise ValueError('Object exceeds read limit')
            raw=stream.read(MAX_BYTES+1)
        finally: stream.close()
        if len(raw)>MAX_BYTES: raise ValueError('Object exceeds read limit')
        return raw,response.get('ContentType','').split(';',1)[0]
