"""Content-addressed, write-once artifact store under `%AYESHA_HOME%/research/`.

A file's name is the SHA-256 of its (uncompressed) content, so nothing can be silently changed: reading verifies the
hash and a mismatch raises `IntegrityError`. Writes go to a temporary file in the same folder, are flushed and
fsync'd, then atomically renamed, so a crash leaves either the old state or the complete new file, never half a file.
gzip headers carry no time or name, so the same content always gives the same bytes on disk.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import tempfile
from pathlib import Path
from typing import Iterator

from ayesha.research.provenance import sha256_bytes

KINDS = ("raw", "normalized", "quality", "runs", "candidates", "exports")


class IntegrityError(RuntimeError):
    """Stored content does not match its recorded hash (corruption or tampering): never used."""


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    if hasattr(os, "O_DIRECTORY"):  # POSIX: make the rename itself durable
        try:
            dfd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass


def gzip_bytes(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=6) as g:
        g.write(data)
    return buf.getvalue()


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, kind: str, sha: str, ext: str, compressed: bool = True) -> Path:
        if kind not in KINDS:
            raise ValueError(f"unknown artifact kind {kind!r}")
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("artifact id must be a SHA-256 hex digest")
        return self.root / kind / sha[:2] / (sha + ext + (".gz" if compressed else ""))

    def put(self, kind: str, data: bytes, ext: str, compressed: bool = True) -> tuple[str, Path]:
        sha = sha256_bytes(data)
        p = self.path_for(kind, sha, ext, compressed)
        if p.exists():
            self.get(kind, sha, ext, compressed)  # verify the existing copy instead of overwriting it
            return sha, p
        atomic_write(p, gzip_bytes(data) if compressed else data)
        return sha, p

    def get(self, kind: str, sha: str, ext: str, compressed: bool = True) -> bytes:
        p = self.path_for(kind, sha, ext, compressed)
        try:
            raw = p.read_bytes()
            data = gzip.decompress(raw) if compressed else raw
        except FileNotFoundError:
            raise IntegrityError(f"missing artifact {p.name}") from None
        except (OSError, EOFError, gzip.BadGzipFile) as e:
            raise IntegrityError(f"unreadable artifact {p.name}: {type(e).__name__}") from None
        if sha256_bytes(data) != sha:
            raise IntegrityError(f"artifact {p.name} does not match its hash")
        return data

    def writer(self, kind: str, ext: str) -> "StreamWriter":
        """Stream a large artifact (e.g. three years of M5 bars) to disk without holding it in memory."""
        return StreamWriter(self, kind, ext)

    def iter_lines(self, kind: str, sha: str, ext: str) -> Iterator[bytes]:
        """Yield the lines of a compressed artifact; raises IntegrityError at the end if the hash does not match,
        so a caller that collects the lines first never uses corrupted content."""
        p = self.path_for(kind, sha, ext, True)
        h = hashlib.sha256()
        try:
            with gzip.open(p, "rb") as g:
                for line in g:
                    h.update(line)
                    yield line
        except FileNotFoundError:
            raise IntegrityError(f"missing artifact {p.name}") from None
        except (OSError, EOFError, gzip.BadGzipFile) as e:
            raise IntegrityError(f"unreadable artifact {p.name}: {type(e).__name__}") from None
        if h.hexdigest() != sha:
            raise IntegrityError(f"artifact {p.name} does not match its hash")

    def exists(self, kind: str, sha: str, ext: str, compressed: bool = True) -> bool:
        return self.path_for(kind, sha, ext, compressed).exists()

    def files(self, kind: str) -> list[Path]:
        d = self.root / kind
        return sorted(x for x in d.rglob("*") if x.is_file() and not x.name.startswith(".tmp-")) if d.exists() else []

    def size_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file()) if self.root.exists() else 0


class StreamWriter:
    """gzip-compressed artifact written to a temporary file while hashing; `commit` names it by its hash."""

    def __init__(self, store: ArtifactStore, kind: str, ext: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown artifact kind {kind!r}")
        self.store, self.kind, self.ext = store, kind, ext
        d = store.root / kind
        d.mkdir(parents=True, exist_ok=True)
        fd, self.tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=ext + ".gz")
        self.f = os.fdopen(fd, "wb")
        self.gz = gzip.GzipFile(filename="", mode="wb", fileobj=self.f, mtime=0, compresslevel=6)
        self.h = hashlib.sha256()
        self.bytes = 0

    def write(self, data: bytes) -> None:
        self.h.update(data)
        self.gz.write(data)
        self.bytes += len(data)

    def commit(self) -> tuple[str, Path]:
        self.gz.close()
        self.f.flush()
        os.fsync(self.f.fileno())
        self.f.close()
        sha = self.h.hexdigest()
        p = self.store.path_for(self.kind, sha, self.ext, True)
        if p.exists():
            os.unlink(self.tmp)  # same content is already stored
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.tmp, p)
        return sha, p

    def abort(self) -> None:
        try:
            self.gz.close()
            self.f.close()
        finally:
            if os.path.exists(self.tmp):
                os.unlink(self.tmp)
