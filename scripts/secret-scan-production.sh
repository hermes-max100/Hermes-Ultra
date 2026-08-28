#!/usr/bin/env bash
set -euo pipefail
python3 - "$@" <<'PY'
import collections, math, pathlib, re, subprocess, sys
args=sys.argv[1:]
tracked=[]; explicit=[]; i=0
while i < len(args):
    if args[i] == '--tracked-root':
        if i+1 >= len(args):
            print('missing --tracked-root value', file=sys.stderr); raise SystemExit(2)
        tracked.append(pathlib.Path(args[i+1]).resolve()); i += 2
    elif args[i] in ('-h','--help'):
        print('Usage: secret-scan-production.sh [--tracked-root DIR] [PATH ...]')
        raise SystemExit(0)
    else:
        explicit.append(pathlib.Path(args[i]).resolve()); i += 1
if not tracked and not explicit:
    print('no scan paths supplied', file=sys.stderr); raise SystemExit(2)

files=[]
for root in tracked:
    raw=subprocess.check_output(['git','-C',str(root),'ls-files','-z'])
    for rel in (x.decode() for x in raw.split(b'\0') if x):
        p=(root / rel).resolve()
        if p.is_file(): files.append(p)
for item in explicit:
    if item.is_file(): files.append(item)
    elif item.is_dir():
        for p in item.rglob('*'):
            if p.is_file(): files.append(p.resolve())
    else:
        print(f'scan path not found: {item}', file=sys.stderr); raise SystemExit(2)

blocked_parts={'.git','.terraform','node_modules','venv','.venv','__pycache__'}
seen=set(); ordered=[]
for p in files:
    if any(part in blocked_parts for part in p.parts):
        continue
    key=str(p)
    if key not in seen:
        seen.add(key); ordered.append(p)

patterns=[
 ('BROWSER_SESSION_COOKIE', re.compile(r'(?i)\bCookie\s*:\s*[^\n]*(?:__Secure-(?:1P|3P)?SID|SAPISID|APISID|HSID|SSID|SID)\s*=\s*["\']?([A-Za-z0-9._~+/=-]{16,})')),
 ('BEARER_TOKEN', re.compile(r'(?i)\bAuthorization\s*:\s*Bearer\s+([A-Za-z0-9._~+/=-]{20,})')),
 ('OAUTH_REFRESH_TOKEN', re.compile(r'(?i)\brefresh[_-]?token\b\s*[:=]\s*["\']?([A-Za-z0-9._~+/=-]{20,})')),
 ('API_KEY', re.compile(r'(?i)\b(?:[A-Z0-9_]*API_KEY|api[_-]?key)\b\s*[:=]\s*["\']?((?:sk-|nvapi-|sk-or-v1-)?[A-Za-z0-9._~+/=-]{20,})')),
]
markers=('REDACTED','PLACEHOLDER','CHANGEME','YOUR_','EXAMPLE_','DUMMY_')
def placeholder(value:str)->bool:
    up=value.upper()
    return any(m in up for m in markers) or (value.startswith('<') and value.endswith('>'))

def shannon_entropy(value:str)->float:
    counts=collections.Counter(value)
    n=len(value)
    return -sum((count/n)*math.log2(count/n) for count in counts.values()) if n else 0.0

def suspicious_api_key(value:str)->bool:
    lower=value.lower()
    if lower.startswith(('process.env.','os.environ.','os.getenv','deno.env.','env.')):
        return False
    if lower.startswith(('sk-','nvapi-','sk-or-v1-')):
        return True
    return len(value) >= 24 and shannon_entropy(value) >= 4.0

code_suffixes={'.py','.pyi','.js','.jsx','.ts','.tsx','.mjs','.cjs'}
def code_reference(path:pathlib.Path, line:str, match:re.Match)->bool:
    if path.suffix.lower() not in code_suffixes:
        return False
    value=match.group(1)
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', value):
        return False
    tail=line[match.end(1):]
    if '.' in value:
        return True
    return re.match(r'\s*(?:\(|,|\)|\.|\[|\]|\bor\b|\band\b|\bif\b|\belse\b)', tail) is not None

findings=[]; scanned=0
for p in ordered:
    try:
        with p.open('rb') as fh:
            probe=fh.read(4096)
            if b'\x00' in probe: continue
        with p.open('r', encoding='utf-8', errors='ignore') as fh:
            scanned += 1
            for lineno,line in enumerate(fh,1):
                for name,rx in patterns:
                    m=rx.search(line)
                    if not m:
                        continue
                    value=m.group(1)
                    if placeholder(value):
                        continue
                    if code_reference(p, line, m):
                        continue
                    if name == 'API_KEY' and not suspicious_api_key(value):
                        continue
                    findings.append((str(p),lineno,name))
    except (OSError, UnicodeError):
        continue

if findings:
    print('SECRET_SCAN=FAIL')
    for path,line,name in findings:
        print(f'finding={path}:{line} detector={name}')
    raise SystemExit(1)
print(f'SECRET_SCAN=PASS files={scanned}')
PY
