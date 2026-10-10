import hashlib
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
            path.write_bytes(data)
        return sha

    def load(self, sha: str) -> bytes:
        if not sha.isalnum():
            raise ValueError("Niepoprawny identyfikator pliku.")
        return (self.base / sha).read_bytes()


def get_storage() -> Storage:
    return Storage(current_app.config["STORAGE_DIR"])
