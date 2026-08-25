"""Upload-path and resource-limit safety, per SECURITY.md's threat table.

T3 path traversal: never trust a client-supplied filename or dataset_id for
building a filesystem path. Every path is either a UUID this server
generated, or is validated to resolve inside UPLOAD_DIR before use.

T4 resource exhaustion: enforce a byte-size ceiling while streaming an
upload to disk (not after buffering the whole thing in memory), and a row
count ceiling on the written file.
"""

from __future__ import annotations

import uuid
from pathlib import Path

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ROWS = 100_000
CHUNK_SIZE = 1024 * 1024  # 1 MB

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = ROOT / "uploads"


class UploadTooLarge(ValueError):
    pass


class TooManyRows(ValueError):
    pass


class UnsafePath(ValueError):
    pass


def new_dataset_id() -> str:
    return uuid.uuid4().hex


def dataset_dir(dataset_id: str) -> Path:
    """Resolve dataset_id to a directory inside UPLOAD_DIR, asserting the
    resolved path is actually inside it. dataset_id must already be a
    server-generated UUID hex string (see new_dataset_id) -- this is a
    defense-in-depth assertion, not the only check: callers must not accept
    an arbitrary client-supplied dataset_id here without validating its
    shape first (see validate_dataset_id).
    """
    candidate = (UPLOAD_DIR / dataset_id).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if upload_root != candidate and upload_root not in candidate.parents:
        raise UnsafePath(f"resolved path {candidate} escapes {upload_root}")
    return candidate


def validate_dataset_id(dataset_id: str) -> str:
    """Only a 32-char lowercase hex UUID (uuid4().hex) or the literal 'demo'
    is accepted -- rejects anything that looks like a path component."""
    if dataset_id == "demo":
        return dataset_id
    try:
        uuid.UUID(hex=dataset_id)
    except ValueError as exc:
        raise UnsafePath(f"invalid dataset_id: {dataset_id!r}") from exc
    return dataset_id


async def stream_upload_to_file(upload_file, destination: Path) -> int:
    """Write an UploadFile to destination in chunks, aborting as soon as
    MAX_UPLOAD_BYTES is exceeded rather than buffering the whole file
    first. Returns the byte count written."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload_file.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                handle.close()
                destination.unlink(missing_ok=True)
                raise UploadTooLarge(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")
            handle.write(chunk)
    return total


def enforce_row_limit(path: Path, max_rows: int = MAX_ROWS) -> int:
    """Counts rows by streaming lines rather than loading the file into
    memory. Raises TooManyRows without deleting the file -- callers decide
    whether to clean up."""
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for count, _ in enumerate(handle, start=1):
            if count > max_rows:
                raise TooManyRows(f"exceeds {max_rows} rows")
    return count
