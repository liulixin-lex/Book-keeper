"""Content-addressed file storage: <root>/<aa>/<bb>/<sha256>."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

CHUNK = 1024 * 1024


class FileTooLarge(Exception):
    pass


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    size_bytes: int
    storage_key: str


class ContentStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def key_for(sha256: str) -> str:
        return f"{sha256[:2]}/{sha256[2:4]}/{sha256}"

    def path_for(self, storage_key: str) -> Path:
        path = (self.root / storage_key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("storage key escapes root")
        return path

    def put(self, stream: BinaryIO, max_bytes: int) -> StoredBlob:
        self.root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        fd, tmp_name = tempfile.mkstemp(dir=self.root, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as tmp:
                while chunk := stream.read(CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLarge(size)
                    digest.update(chunk)
                    tmp.write(chunk)
                tmp.flush()
                os.fsync(tmp.fileno())
            sha = digest.hexdigest()
            key = self.key_for(sha)
            target = self.path_for(key)
            if target.exists():
                os.unlink(tmp_name)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_name, target)
                os.chmod(target, 0o440)
            return StoredBlob(sha, size, key)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    def open(self, storage_key: str) -> BinaryIO:
        return self.path_for(storage_key).open("rb")

    def verify(self, storage_key: str, sha256: str) -> bool:
        digest = hashlib.sha256()
        with self.open(storage_key) as handle:
            while chunk := handle.read(CHUNK):
                digest.update(chunk)
        return digest.hexdigest() == sha256
