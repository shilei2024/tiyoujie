"""Create local-only random secrets without displaying them or overwriting existing files."""

import argparse
import base64
import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--with-credential-key", action="store_true")
args = parser.parse_args()
target = ROOT / ".env"
if target.exists():
    print("Existing .env preserved; no values displayed.")
else:
    with target.open("x", encoding="utf-8", newline="\n") as file:
        for name in (
            "DJANGO_SECRET_KEY",
            "POSTGRES_PASSWORD",
            "TEST_POSTGRES_PASSWORD",
        ):
            file.write(f"{name}={secrets.token_urlsafe(64)}\n")
    target.chmod(0o600)
    print(
        "Created ignored .env with random local-only values. Do not use it for deployment."
    )

if args.with_credential_key:
    content = target.read_text(encoding="utf-8")
    names = {line.split("=", 1)[0] for line in content.splitlines() if "=" in line}
    if (
        "CREDENTIAL_KEYS_JSON" not in names
        and "CREDENTIAL_ACTIVE_KEY_VERSION" not in names
    ):
        keys = json.dumps(
            {"v1": base64.b64encode(secrets.token_bytes(32)).decode()},
            separators=(",", ":"),
        )
        with target.open("a", encoding="utf-8", newline="\n") as file:
            file.write(
                f"\nCREDENTIAL_KEYS_JSON={keys}\nCREDENTIAL_ACTIVE_KEY_VERSION=v1\n"
            )
        print("Added local-only credential encryption key; value suppressed.")
    else:
        print(
            "Credential key entries already exist; preserved without inspection or overwrite."
        )
