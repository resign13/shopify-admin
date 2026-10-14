"""High-confidence credential scan; diagnostics never echo matched content."""
from pathlib import Path
import re
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
patterns={
  'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
  'github_token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b'),
  'aws_access_key':re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
}
result=subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=root,capture_output=True,check=True)
findings=[]
for name in set(result.stdout.decode().split('\0')):
    path=root/name
    if not name or not path.is_file() or path.stat().st_size>2*1024*1024:continue
    try:text=path.read_text(encoding='utf-8')
    except UnicodeError:continue
    for kind,expression in patterns.items():
        for match in expression.finditer(text):findings.append((name,text[:match.start()].count('\n')+1,kind))
for name,line,kind in findings:print(f'{name}:{line}: {kind}')
if findings:sys.exit(1)
print('Credential pattern scan passed')
