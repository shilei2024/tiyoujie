import os
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from django.conf import settings

from config.errors import AppError


class StorageProvider(ABC):
    @abstractmethod
    def put(self, key, content): ...

    @abstractmethod
    def read(self, key): ...

    @abstractmethod
    def delete(self, key): ...


def new_key():
    token = uuid.uuid4().hex
    return f"{token[:2]}/{token}.jpg"


class PrivateLocalStorage(StorageProvider):
    def old_keys(self, before):
        root = Path(settings.MEDIA_ROOT).resolve()
        count = 0
        for path in root.glob("[a-f0-9][a-f0-9]/*"):
            if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                continue
            key = path.with_suffix(".jpg").relative_to(root).as_posix()
            if path.suffix not in {".jpg", ".part"} or not re.fullmatch(
                r"[a-f0-9]{2}/[a-f0-9]{32}\.jpg", key
            ):
                continue
            if path.stat().st_mtime < before:
                yield key
                count += 1
                if count >= 100:
                    return

    def path(self, key):
        if not re.fullmatch(r"[a-f0-9]{2}/[a-f0-9]{32}\.jpg", key):
            raise AppError("STORAGE_KEY_INVALID", "文件标识无效。", 400)
        root = Path(settings.MEDIA_ROOT).resolve()
        path = root.joinpath(key)
        if not path.resolve().is_relative_to(root):
            raise AppError("STORAGE_KEY_INVALID", "文件标识无效。", 400)
        return path

    def put(self, key, content):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(".part")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            with os.fdopen(os.open(temporary, flags, 0o600), "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, key):
        path = self.path(key)
        with path.open("rb") as handle:
            content = handle.read(settings.IMAGE_MAX_BYTES + 1)
        if len(content) > settings.IMAGE_MAX_BYTES:
            raise AppError("STORAGE_UNAVAILABLE", "文件暂不可用。", 503)
        return content

    def delete(self, key):
        path = self.path(key)
        path.unlink(missing_ok=True)
        path.with_suffix(".part").unlink(missing_ok=True)


def storage():
    return PrivateLocalStorage()
