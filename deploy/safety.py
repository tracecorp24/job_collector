"""Dağıtım öncesi doğrulanmış SQLite kopyası ve durdurulmuş servise geri yükleme."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile


def integrity(database):
    path = Path(database).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
        checks = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    if checks != ["ok"]:
        raise ValueError("SQLite bütünlük kontrolü başarısız.")
    return path


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def snapshot(database, destination, sha):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Tam sürüm SHA'sı gerekli.")
    source = Path(database).resolve(strict=True)
    target = Path(destination).resolve()
    if source == target or target.exists():
        raise ValueError("Yedek yeni ve ayrı bir dosya olmalı.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
        connection.execute("VACUUM INTO ?", (str(target),))
    integrity(target)
    result = {"sha": sha, "database": target.name, "sha256": digest(target),
              "created_at": datetime.now(timezone.utc).isoformat()}
    manifest = target.with_suffix(target.suffix + ".json")
    with manifest.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    return result


def restore(backup, database):
    source = Path(backup).resolve(strict=True)
    target = Path(database).resolve()
    if source == target:
        raise ValueError("Kaynak ve hedef aynı olamaz.")
    manifest = json.loads(source.with_suffix(source.suffix + ".json").read_text(encoding="utf-8"))
    if manifest.get("database") != source.name or digest(source) != manifest.get("sha256"):
        raise ValueError("Yedek parmak izi doğrulanamadı.")
    integrity(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".linko-restore-", suffix=".db", dir=target.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original, \
                closing(sqlite3.connect(temporary)) as replacement:
            original.backup(replacement)
        integrity(temporary)
        with temporary.open("r+b") as output:
            os.fsync(output.fileno())
        # Çağıran önce servisi durdurur. Eski yan dosyalar yeni DB'ye uygulanmaz.
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(target) + suffix)
            if sidecar.exists():
                sidecar.rename(Path(str(temporary) + ".previous" + suffix))
        os.replace(temporary, target)
        return manifest
    finally:
        if temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    copy = sub.add_parser("snapshot")
    copy.add_argument("--database", required=True)
    copy.add_argument("--destination", required=True)
    copy.add_argument("--sha", required=True)
    rollback = sub.add_parser("restore")
    rollback.add_argument("--backup", required=True)
    rollback.add_argument("--database", required=True)
    check = sub.add_parser("check")
    check.add_argument("--database", required=True)
    args = parser.parse_args()
    if args.action == "snapshot":
        result = snapshot(args.database, args.destination, args.sha)
    elif args.action == "restore":
        result = restore(args.backup, args.database)
    else:
        result = {"integrity": "ok", "database": str(integrity(args.database))}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
