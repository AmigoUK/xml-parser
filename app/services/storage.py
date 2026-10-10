import hashlib
import os
import tempfile
from pathlib import Path

from flask import current_app


class Storage:
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir) / "raw"
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self.base / sha
        if not path.exists():
            fd, tmp = tempfile.mkstemp(dir=self.base, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, path)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        return sha

    def load(self, sha: str) -> bytes:
        if not sha.isalnum():
            raise ValueError("Niepoprawny identyfikator pliku.")
        return (self.base / sha).read_bytes()


def get_storage() -> Storage:
    return Storage(current_app.config["STORAGE_DIR"])
