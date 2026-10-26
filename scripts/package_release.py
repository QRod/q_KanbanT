#!/usr/bin/env python3
"""Package exactly tracked distributable files, with deterministic metadata."""
import argparse
import hashlib
import io
from pathlib import Path
import re
import subprocess
import tarfile

parser=argparse.ArgumentParser()
parser.add_argument('version')
parser.add_argument('--output',default='dist')
args=parser.parse_args()
if not re.fullmatch(r'v\d+\.\d+\.\d+',args.version):parser.error('Use vX.Y.Z')
root=Path(__file__).resolve().parents[1]
app='q-inv' if (root/'inventory.py').exists() else 'q-kanbant'
files=[v.decode() for v in subprocess.check_output(['git','ls-files','-z'],cwd=root).split(b'\0') if v]
for name in files:
 if any(p in {'.git','.data','data','secrets','.venv','node_modules','validation','backups','dist','__pycache__'} for p in Path(name).parts):raise SystemExit('Runtime file tracked: '+name)
 if Path(name).suffix in {'.key','.sqlite3','.pem','.xlsx','.log'}:raise SystemExit('Private file tracked: '+name)
if subprocess.check_output(['git','status','--porcelain'],cwd=root).strip():raise SystemExit('Commit or discard source changes before packaging a release')
out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
archive=out/f'{app}-{args.version}.tar.gz'
# gzip headers are normalized to avoid embedding the local filename or timestamp.
import gzip
with archive.open('wb') as stream,gzip.GzipFile(fileobj=stream,mode='wb',mtime=0) as compressed,tarfile.open(fileobj=compressed,mode='w') as tar:
 for name in sorted(files):
  source=root/name
  if not source.is_file() or source.is_symlink():raise SystemExit('Unexpected source: '+name)
  raw=source.read_bytes();info=tarfile.TarInfo(name);info.size=len(raw);info.mode=0o755 if name=='install.sh' else 0o644;info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
  tar.addfile(info,io.BytesIO(raw))
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
(out/'SHA256SUMS').write_text(f'{checksum}  {archive.name}\n')
print(archive);print(checksum)
