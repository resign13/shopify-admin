"""Signed, short-lived image challenges with shared PostgreSQL one-use claims."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

ALPHABET = '2346789ABCDEFGHJKMNPQRTUVWXY'
LIFETIME = 300


def random_code():
    return ''.join(secrets.choice(ALPHABET) for _ in range(5))


def digest(key, value):
    return hmac.new(key, value.encode('ascii'), hashlib.sha256).hexdigest()


def issue(key):
    code = random_code()
    nonce = secrets.token_urlsafe(24)
    stamp = int(time.time())
    payload = {'v':1, 'n':nonce, 't':stamp,
               'h':digest(key, 'captcha-answer:' + nonce + ':' + code)}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
    token = encoded + '.' + digest(key, 'captcha-ticket:' + encoded)
    image = Image.new('RGB', (160, 52), '#f4f7fb')
    draw = ImageDraw.Draw(image)
    for _ in range(5):
        draw.line([(secrets.randbelow(160), secrets.randbelow(52)),
                   (secrets.randbelow(160), secrets.randbelow(52))], fill='#bdcbd9', width=1)
    font = ImageFont.load_default(size=29)
    for index, char in enumerate(code):
        glyph = Image.new('RGBA', (32, 48))
        ImageDraw.Draw(glyph).text((4, 5), char, font=font, fill='#19324fff')
        glyph = glyph.rotate(secrets.randbelow(19)-9, resample=Image.Resampling.BICUBIC)
        image.paste(glyph, (10 + index*28, secrets.randbelow(3)), glyph)
    for _ in range(40):
        draw.point((secrets.randbelow(160), secrets.randbelow(52)), fill='#9aafc4')
    output = BytesIO(); image.save(output, format='PNG')
    return {'enabled':True, 'captchaToken':token,
            'image':'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode(),
            'expiresIn':LIFETIME}


def verify(db, key, token, answer):
    if not isinstance(token, str) or not 80 <= len(token) <= 512: return False
    try:
        encoded, signature = token.split('.')
        if not hmac.compare_digest(signature, digest(key, 'captcha-ticket:' + encoded)): return False
        payload = json.loads(base64.b64decode(encoded + '='*((-len(encoded))%4), altchars=b'-_', validate=True))
        if set(payload) != {'v','n','t','h'} or payload['v'] != 1: return False
        if not isinstance(payload['n'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}', payload['n']): return False
        if type(payload['t']) is not int or not 0 <= time.time()-payload['t'] <= LIFETIME: return False
        if not isinstance(payload['h'], str) or not re.fullmatch(r'[a-f0-9]{64}', payload['h']): return False
    except (ValueError, TypeError, UnicodeError):
        return False
    # Consume even a wrong answer. INSERT ... ON CONFLICT is atomic across
    # workers; only the hash of a random nonce is retained, never the answer.
    bucket = digest(key, 'captcha-used:' + payload['n'])
    with db._connect() as conn:
        claimed = conn.execute('INSERT INTO security_rate_buckets(bucket_key) VALUES(%s) ON CONFLICT DO NOTHING RETURNING bucket_key', (bucket,)).fetchone()
    if not claimed or not isinstance(answer, str) or len(answer) > 32: return False
    answer = answer.strip().upper()
    if not re.fullmatch('[' + ALPHABET + ']{5}', answer): return False
    return hmac.compare_digest(payload['h'], digest(key, 'captcha-answer:' + payload['n'] + ':' + answer))
