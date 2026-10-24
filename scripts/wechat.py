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
    if not appid:
        raise ValueError(
            "No AppID: pass --appid wx... or export WECHAT_APP_ID. "
            "manifest.json keeps it empty on purpose so a build can never "
            "silently target the previous mini program account"
        )
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
    parser.add_argument("action", choices=["build", "open", "upload"])
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
        "--version",
        default="0.1.0",
        help="Version shown in the WeChat console; required for upload",
    )
    parser.add_argument(
        "--desc",
        default="题有解 体验版",
        help="Upload remark shown in the WeChat console",
    )
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
    if args.action == "upload":
        upload(parser, args, target)
        return
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


def upload(parser, args, target):
    """上传开发版本（不发布、不提交审核，正式发布仍需人工在后台点）。

    开发者工具必须先登录，否则 CLI 只会返回一句难以理解的错误，所以先问登录态。
    """
    login = subprocess.run(
        [str(args.cli.resolve()), "islogin"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if '"login":true' not in (login.stdout + login.stderr).replace(" ", ""):
        parser.error(
            "WeChat devtools is not logged in; open the IDE and scan the QR code first"
        )
    result = subprocess.run(
        [
            str(args.cli.resolve()),
            "upload",
            "--project",
            str(target),
            "-v",
            args.version,
            "-d",
            args.desc,
        ],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout + result.stderr
    if result.returncode or "[error]" in output:
        print(
            json.dumps(
                {"status": "upload_failed", "message": output.strip()[-600:]},
                ensure_ascii=False,
            )
        )
        sys.exit(1)
    print(
        json.dumps(
            {
                "status": "uploaded",
                "version": args.version,
                "desc": args.desc,
                "note": "Set it as the trial build in the WeChat console; nothing was released",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
