"""Check every file listed in the private full-workspace snapshot manifest."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root/'WORKSPACE_MANIFEST.json').read_text(encoding='utf-8'))
    failures = []
    for item in manifest['files']:
        path = root/item['path']
        if not path.is_file():
            failures.append(item['path']+': missing')
        elif hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            failures.append(item['path']+': changed')
    print(json.dumps({'checked':len(manifest['files']),'failures':failures},ensure_ascii=True))
    raise SystemExit(bool(failures))


if __name__=='__main__':
    main()
