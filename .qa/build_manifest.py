"""Inventory the entire explicitly authorized private workspace snapshot."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = sorted(p for p in root.rglob('*') if '.git' not in p.relative_to(root).parts)
for directory in (p for p in paths if p.is_dir()):
    if not any(directory.iterdir()):
        (directory/'.gitkeep').write_bytes(b'')
paths = sorted(p for p in root.rglob('*') if '.git' not in p.relative_to(root).parts)
files = [{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,
          'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
         for p in paths if p.is_file() and p.name!='WORKSPACE_MANIFEST.json']
manifest = dict(created_at=datetime.now(timezone.utc).isoformat(),
    description='Complete private workspace snapshot; only .git internals and this self-referential manifest are excluded from hashes.',
    directories=[p.relative_to(root).as_posix() for p in paths if p.is_dir()],files=files)
(root/'WORKSPACE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(files),'bytes':sum(f['bytes'] for f in files),'directories':len(manifest['directories'])}))
