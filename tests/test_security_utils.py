import asyncio
import io

import pytest

from backend.security import (
    MAX_UPLOAD_BYTES,
    TooManyRows,
    UnsafePath,
    UploadTooLarge,
    dataset_dir,
    enforce_row_limit,
    new_dataset_id,
    stream_upload_to_file,
    stream_upload_to_file_sync,
    validate_dataset_id,
)


def test_new_dataset_id_is_a_valid_uuid_hex():
    dataset_id = new_dataset_id()
    assert len(dataset_id) == 32
    validate_dataset_id(dataset_id)  # must not raise


def test_validate_dataset_id_rejects_path_traversal_attempts():
    for payload in ["../../etc/passwd", "../secret", "a/b", "..", "demo/../../etc"]:
        with pytest.raises(UnsafePath):
            validate_dataset_id(payload)


def test_validate_dataset_id_accepts_demo_literal():
    assert validate_dataset_id("demo") == "demo"


def test_dataset_dir_resolves_inside_upload_dir():
    dataset_id = new_dataset_id()
    resolved = dataset_dir(dataset_id)
    from backend.security import UPLOAD_DIR

    assert UPLOAD_DIR.resolve() in resolved.parents


class _FakeUploadFile:
    def __init__(self, data: bytes, chunk_size: int = 4096):
        self._stream = io.BytesIO(data)
        self._chunk_size = chunk_size

    async def read(self, size: int) -> bytes:
        return self._stream.read(size)


def test_stream_upload_rejects_oversized_file_without_buffering_it_all(tmp_path):
    oversized = _FakeUploadFile(b"x" * (MAX_UPLOAD_BYTES + 1))
    destination = tmp_path / "out.csv"
    with pytest.raises(UploadTooLarge):
        asyncio.run(stream_upload_to_file(oversized, destination))
    assert not destination.exists()


def test_stream_upload_accepts_a_normal_file(tmp_path):
    data = b"a,b,c\n1,2,3\n"
    upload = _FakeUploadFile(data)
    destination = tmp_path / "out.csv"
    written = asyncio.run(stream_upload_to_file(upload, destination))
    assert written == len(data)
    assert destination.read_bytes() == data


def test_enforce_row_limit_rejects_too_many_rows(tmp_path):
    path = tmp_path / "big.csv"
    path.write_text("\n".join(str(i) for i in range(10)) + "\n")
    with pytest.raises(TooManyRows):
        enforce_row_limit(path, max_rows=5)


def test_enforce_row_limit_accepts_within_bounds(tmp_path):
    path = tmp_path / "small.csv"
    path.write_text("a\nb\nc\n")
    assert enforce_row_limit(path, max_rows=10) == 3


def test_sync_stream_upload_rejects_oversized_file(tmp_path):
    oversized = io.BytesIO(b"x" * (MAX_UPLOAD_BYTES + 1))
    destination = tmp_path / "out.csv"
    with pytest.raises(UploadTooLarge):
        stream_upload_to_file_sync(oversized, destination)
    assert not destination.exists()


def test_sync_stream_upload_accepts_a_normal_file(tmp_path):
    data = b"a,b,c\n1,2,3\n"
    upload = io.BytesIO(data)  # Streamlit's UploadedFile behaves like BytesIO
    destination = tmp_path / "out.csv"
    written = stream_upload_to_file_sync(upload, destination)
    assert written == len(data)
    assert destination.read_bytes() == data
