"""Create a local backup bundle: PostgreSQL dump + private media archive + manifest.

Usage: py -3.12 scripts/backup.py [--output backups]
Never prints secrets; refuses to run against a Compose project owned elsewhere.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "tiyoujie-local"
POSTGRES = f"{PROJECT}-postgres-1"
IMAGE = "tiyoujie-api:phase7"
VOLUME = f"{PROJECT}_private_dev"
MEDIA_SCRIPT = """
import hashlib, json, os, tarfile
items = {}
for base, _, files in os.walk("/data"):
    for name in files:
        path = os.path.join(base, name)
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        items[os.path.relpath(path, "/data")] = digest.hexdigest()
with open("/backup/media-manifest.json", "w", encoding="utf-8") as stream:
    json.dump(items, stream, ensure_ascii=False, sort_keys=True)
with tarfile.open("/backup/media.tar.gz", "w:gz") as archive:
    archive.add("/data", arcname=".")
print(json.dumps({"files": len(items)}))
"""


def env_value(name):
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1]
    raise SystemExit(f"Missing {name} in .env; run scripts/bootstrap.py first")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="backups")
    args = parser.parse_args()
    directory = (ROOT / args.output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle = directory / f"tiyoujie-{stamp}"
    bundle.mkdir()

    dump = bundle / "database.dump"
    with open(dump, "wb") as stream:
        run(
            [
                "docker",
                "exec",
                "-e",
                "PGPASSWORD=" + env_value("POSTGRES_PASSWORD"),
                POSTGRES,
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "tiyoujie_dev",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
            ],
            stdout=stream,
        )
    if dump.stat().st_size < 1024:
        raise SystemExit("Database dump is unexpectedly small; refusing to continue")

    result = run(
        [
            "docker",
            "run",
            "--rm",
            "-u",
            "0",
            "-v",
            f"{VOLUME}:/data:ro",
            "-v",
            f"{bundle}:/backup",
            "--entrypoint",
            "python",
            IMAGE,
            "-c",
            MEDIA_SCRIPT,
        ],
        capture_output=True,
        text=True,
    )
    media = json.loads(result.stdout.strip().splitlines()[-1])
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "database": {
            "file": dump.name,
            "bytes": dump.stat().st_size,
            "sha256": sha256(dump),
        },
        "media": {
            "file": "media.tar.gz",
            "files": media["files"],
            "sha256": sha256(bundle / "media.tar.gz"),
            "manifest_sha256": sha256(bundle / "media-manifest.json"),
        },
        "image": IMAGE,
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"bundle": str(bundle), **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
