"""Pure transformation shared by the isolated nginx check and live installer."""
import re

OLD=re.compile(r'error_page 503 = @gingtto_maintenance;\nlocation @gingtto_maintenance \{\n.*?\n\}',re.S)
INCLUDE='include /etc/nginx/snippets/gingtto-maintenance-response.conf;'

def patch_site(raw):
    if raw.count(INCLUDE)==1 and not OLD.search(raw):return raw
    updated,count=OLD.subn(INCLUDE,raw)
    if count!=1:raise ValueError('Expected the single existing JSON maintenance handler')
    return updated
