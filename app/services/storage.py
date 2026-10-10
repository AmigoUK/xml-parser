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
        return self.store(data)[0]

    def store(self, data: bytes) -> tuple[str, bool]:
        """Zapis atomowy (plik tymczasowy + fsync + os.replace + fsync katalogu). Zwraca (sha256, czy_utworzono)."""
        sha = hashlib.sha256(data).hexdigest()
        path = self.base / sha
        if path.exists():
            return sha, False
        fd, tmp = tempfile.mkstemp(dir=self.base, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())  # po awarii nie zostanie plik o dobrej nazwie z obciętą treścią (BE-9)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._fsync_dir()
        return sha, True

    def _fsync_dir(self) -> None:
        try:
            dfd = os.open(self.base, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dfd)
        except OSError:
            pass
        finally:
            os.close(dfd)

    def _path(self, sha: str) -> Path:
        if not sha or not sha.isalnum():
            raise ValueError("Niepoprawny identyfikator pliku.")
        return self.base / sha

    def load(self, sha: str) -> bytes:
        return self._path(sha).read_bytes()

    def delete(self, sha: str) -> None:
        self._path(sha).unlink(missing_ok=True)


def check_storage_dir(base_dir: str | Path) -> None:
    """Fail-fast przy starcie: STORAGE_DIR musi istnieć (albo dać się utworzyć) i być zapisywalny (BE-9)."""
    try:
        raw = Path(base_dir) / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=raw, prefix=".probe-"):
            pass
    except OSError as exc:
        raise RuntimeError(f"STORAGE_DIR „{base_dir}” nie jest zapisywalnym katalogiem ({exc.strerror or exc}). "
                           "Ustaw STORAGE_DIR na katalog wolumenu z prawem zapisu.") from None


def get_storage() -> Storage:
    return Storage(current_app.config["STORAGE_DIR"])
