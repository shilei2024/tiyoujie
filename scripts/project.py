"""Local-only operations against this project's explicitly named Compose resources."""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "--project-directory",
    str(ROOT),
    "--env-file",
    str(ROOT / ".env"),
    "-f",
    str(ROOT / "compose.yaml"),
    "-p",
    "tiyoujie-local",
]


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def health():
    for path in ("live", "ready"):
        url = f"http://127.0.0.1:18000/api/v1/health/{path}/"
        try:
            with urllib.request.urlopen(url, timeout=8) as response:
                payload = json.load(response)
                print(json.dumps({"check": path, "http": response.status, **payload}))
        except (urllib.error.URLError, TimeoutError):
            raise SystemExit(
                f"Local {path} health check failed; no connection details displayed"
            ) from None


def check_project_ownership():
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "label=com.docker.compose.project=tiyoujie-local",
            "--format",
            '{{.Label "com.docker.compose.project.working_dir"}}',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    for directory in result.stdout.splitlines():
        if not directory.strip() or Path(directory).resolve() != ROOT:
            raise SystemExit(
                "The Compose project name is owned by another directory; refusing"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=[
            "preflight",
            "build",
            "migrate",
            "up",
            "health",
            "down",
            "test",
            "check",
        ],
    )
    parser.add_argument(
        "--dev-login",
        action="store_true",
        help="Explicit local test login, only for up",
    )
    args = parser.parse_args()
    if args.dev_login:
        if args.action != "up":
            raise SystemExit("--dev-login is only supported with up")
        COMPOSE.extend(["-f", str(ROOT / "infra/compose.dev-login.yaml")])
    if not (ROOT / ".env").is_file():
        raise SystemExit(
            "Run scripts/bootstrap.py to create local-only configuration first"
        )
    check_project_ownership()
    run(*COMPOSE, "config", "--quiet")
    match args.action:
        case "preflight":
            run("docker", "version", "--format", "{{.Server.Version}}")
        case "build":
            run(*COMPOSE, "build", "api")
        case "migrate":
            run(*COMPOSE, "up", "-d", "--wait", "postgres", "redis")
            run(
                *COMPOSE,
                "run",
                "--rm",
                "--no-deps",
                "api",
                "python",
                "manage.py",
                "migrate",
                "--noinput",
            )
        case "up":
            run(*COMPOSE, "up", "-d", "--wait", "api", "worker", "beat")
            health()
        case "health":
            health()
        case "down":
            # No -v: preserve all local development volumes and data.
            run(*COMPOSE, "--profile", "test", "down")
        case "check":
            for command in (("check",), ("makemigrations", "--check", "--dry-run")):
                run(
                    *COMPOSE,
                    "run",
                    "--rm",
                    "--no-deps",
                    "api",
                    "python",
                    "manage.py",
                    *command,
                )
        case "test":
            # 测试跑在镜像里，不是源码目录。不先构建就会拿旧镜像验证新代码，
            # 结果是全绿但改的东西根本没被测到。
            run(*COMPOSE, "build", "api")
            try:
                run(
                    *COMPOSE,
                    "--profile",
                    "test",
                    "up",
                    "-d",
                    "--wait",
                    "postgres-test",
                    "redis-test",
                    "worker-test",
                )
                for command in (
                    ("test", "--noinput", "--verbosity=2"),
                    ("queue_probe",),
                    ("queue_ocr_guard_probe",),
                    ("queue_ocr_guard_probe", "--task-type", "analysis"),
                ):
                    run(
                        *COMPOSE,
                        "--profile",
                        "test",
                        "run",
                        "--rm",
                        "tests",
                        "python",
                        "manage.py",
                        *command,
                    )
            finally:
                run(
                    *COMPOSE,
                    "--profile",
                    "test",
                    "stop",
                    "worker-test",
                    "postgres-test",
                    "redis-test",
                )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
