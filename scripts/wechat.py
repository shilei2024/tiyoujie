"""Prepare/open this project's local WeChat build. Never uploads or publishes code."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def configuration(appid, api_base, *, ui_only=False):
    if not re.fullmatch(r"wx[a-fA-F0-9]{16}", appid):
        raise ValueError(
            "Provide your actual wx + 16 hexadecimal AppID; touristappid is not valid"
        )
    if ui_only:
        if api_base:
            raise ValueError(
                "UI-only builds must omit API base so no backend requests can be sent"
            )
        return appid, ""
    url = urlsplit(api_base)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError(
            "API base must be a credential-free HTTPS origin with no path/query"
        )
    return appid, api_base.rstrip("/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "open"])
    manifest = json.loads(
        (ROOT / "frontend/src/manifest.json").read_text(encoding="utf-8")
    )
    parser.add_argument(
        "--appid",
        default=os.environ.get("WECHAT_APP_ID") or manifest["mp-weixin"]["appid"],
    )
    parser.add_argument(
        "--ui-only",
        action="store_true",
        help="Compile UI with backend unavailable; keeps HTTPS and domain checks enabled",
    )
    parser.add_argument("--api-base", default=os.environ.get("VITE_API_BASE_URL", ""))
    parser.add_argument(
        "--cli",
        type=Path,
        default=os.environ.get(
            "WECHAT_DEVTOOLS_CLI",
            "C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat",
        ),
    )
    args = parser.parse_args()
    try:
        appid, api_base = configuration(args.appid, args.api_base, ui_only=args.ui_only)
    except ValueError as error:
        parser.error(str(error))
    target = ROOT / "frontend/dist/build/mp-weixin"
    if args.action == "build":
        env = {**os.environ, "VITE_API_BASE_URL": api_base}
        subprocess.run(
            ["npm.cmd" if os.name == "nt" else "npm", "run", "build:mp-weixin"],
            cwd=ROOT / "frontend",
            env=env,
            check=True,
        )
        config_path = target / "project.config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["appid"] = appid
        data["projectname"] = "题有解"
        data.setdefault("setting", {})["urlCheck"] = True
        config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (target / "tiyoujie-build.json").write_text(
            json.dumps({"appid": appid, "api_base": api_base, "url_check": True}),
            encoding="utf-8",
        )
        print(
            json.dumps({"status": "built", "project": str(target)}, ensure_ascii=False)
        )
        return
    stamp_path = target / "tiyoujie-build.json"
    if not stamp_path.is_file():
        parser.error("Run wechat.py build with your AppID/API base first")
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    config = json.loads((target / "project.config.json").read_text(encoding="utf-8"))
    if (
        stamp != {"appid": appid, "api_base": api_base, "url_check": True}
        or config["appid"] != appid
        or not config["setting"].get("urlCheck")
    ):
        parser.error("Build configuration differs; rebuild before opening")
    if os.name != "nt" or not args.cli.is_file():
        parser.error(
            "Provide --cli pointing to the installed Windows WeChat developer CLI"
        )
    result = subprocess.run(
        [str(args.cli.resolve()), "open", "--project", str(target)],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if (
        result.returncode
        or "[error]" in result.stdout + result.stderr
        or "× preparing" in result.stdout + result.stderr
    ):
        print(
            json.dumps(
                {
                    "status": "open_failed",
                    "message": (
                        "Check AppID access and the existing logged-in developer tool; "
                        "no project was uploaded"
                    ),
                }
            )
        )
        sys.exit(1)
    print(json.dumps({"status": "opened", "project": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
