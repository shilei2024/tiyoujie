"""Check tracked and unignored source without loading real secrets or generated files."""

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements-dir", type=Path)
    args = parser.parse_args()
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    names = sorted(set(result.stdout.decode().split("\0")) - {""})
    errors = []
    checked = 0
    links = 0

    def normalize(value):
        return re.sub(r"\s+", "", value)

    source_fragments = set()
    if args.requirements_dir:
        for path in args.requirements_dir.glob("*.md"):
            source = normalize(path.read_text(encoding="utf-8-sig"))
            source_fragments.update(
                source[i : i + 100] for i in range(max(0, len(source) - 99))
            )
    patterns = (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\bAKIA[A-Z0-9]{16}\b",
        r"\bsk-[A-Za-z0-9_-]{24,}\b",
    )
    for name in names:
        path = ROOT / name
        if name == ".env" or (
            path.name.startswith(".env.") and path.name != ".env.example"
        ):
            errors.append(f"Secret configuration must not be tracked: {name}")
            continue
        if path.suffix not in {
            ".py",
            ".ts",
            ".vue",
            ".md",
            ".json",
            ".yaml",
            ".yml",
            ".html",
        }:
            continue
        if path.name in {"package-lock.json"}:
            continue
        text = path.read_text(encoding="utf-8")
        checked += 1
        if "\ufffd" in text:
            errors.append(f"Invalid text encoding: {name}")
        if any(re.search(pattern, text) for pattern in patterns):
            errors.append(f"Possible secret in {name}; contents suppressed")
        if source_fragments:
            content = normalize(text)
            if any(
                content[i : i + 100] in source_fragments
                for i in range(max(0, len(content) - 99))
            ):
                errors.append(
                    f"Long requirements fragment in {name}; contents suppressed"
                )
        if path.suffix == ".md":
            if len(re.findall(r"^\s*```", text, re.MULTILINE)) % 2:
                errors.append(f"Unbalanced Markdown fence: {name}")
            for target in re.findall(r"\]\(([^\n)]+)\)", text):
                if target.startswith(("https://", "http://", "#", "mailto:")):
                    continue
                links += 1
                if not (path.parent / target.split("#")[0]).exists():
                    errors.append(f"Broken local link in {name}")
    print(
        f"Source files checked: {checked}; local links: {links}; issues: {len(errors)}"
    )
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
