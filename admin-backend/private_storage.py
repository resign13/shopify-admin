"""Optional private R2 replication, addressed exclusively by registered storage IDs."""
from functools import lru_cache
import os
import re


def client():
    if os.environ.get('APP_ENV') == 'test':
        raise RuntimeError('External object storage is disabled for isolated fixtures')
    return _client()


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config
    return boto3.client('s3',region_name='auto',
      endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
      aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
      config=Config(connect_timeout=3,read_timeout=10,retries={'total_max_attempts':2},
                    request_checksum_calculation='when_required',response_checksum_validation='when_required'))


client.cache_clear = _client.cache_clear


def key(channel,storage_key):
    if channel not in {'admin','store'} or not re.fullmatch(r'[0-9a-f-]{36}\.[a-z0-9]{1,5}',storage_key):
        raise ValueError('Invalid private storage identifier')
    return 'private/'+channel+'/'+storage_key


def replicate(channel,storage_key,raw,mime):
    bucket=os.environ.get('PRIVATE_STORAGE_BUCKET')
    if not bucket:return
    client().put_object(Bucket=bucket,Key=key(channel,storage_key),Body=raw,ContentType=mime)


def retrieve(channel,storage_key,max_bytes):
    bucket=os.environ.get('PRIVATE_STORAGE_BUCKET')
    if not bucket:raise FileNotFoundError('Private storage is not configured')
    obj=client().get_object(Bucket=bucket,Key=key(channel,storage_key));body=obj['Body']
    try:
        if int(obj.get('ContentLength',0))>max_bytes:raise ValueError('Private object exceeds size limit')
        raw=body.read(max_bytes+1)
        if len(raw)>max_bytes:raise ValueError('Private object exceeds size limit')
        return raw
    finally:body.close()
