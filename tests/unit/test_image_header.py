"""Image type and size come from header bytes only (MED-003)."""

from __future__ import annotations

import struct

import pytest

from knowledge_engine.importer.media import image_header

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 7, 9) + b"\x08\x06"
GIF = b"GIF89a" + struct.pack("<HH", 7, 9) + b"\x00" * 8
JPEG = (
    b"\xff\xd8"
    + b"\xff\xe0"  # an APP0 segment before the frame header
    + struct.pack(">H", 16)
    + b"JFIF\x00" * 2
    + b"\x00\x00\x00\x00"
    + b"\xff\xc0"
    + struct.pack(">HBHH", 17, 8, 9, 7)
    + b"\x00" * 12
)
WEBP_VP8X = (
    b"RIFF"
    + b"\x00" * 4
    + b"WEBP"
    + b"VP8X"
    + b"\x0a\x00\x00\x00"
    + b"\x00" * 4
    + (7 - 1).to_bytes(3, "little")
    + (9 - 1).to_bytes(3, "little")
)


@pytest.mark.parametrize(
    ("head", "media_type"),
    [
        (PNG, "image/png"),
        (GIF, "image/gif"),
        (JPEG, "image/jpeg"),
        (WEBP_VP8X, "image/webp"),
    ],
)
def test_reads_type_and_size_from_the_header(head: bytes, media_type: str) -> None:
    assert image_header(head) == (media_type, 7, 9)


def test_truncated_header_gives_type_without_size() -> None:
    assert image_header(PNG[:14]) == ("image/png", None, None)


def test_unknown_bytes_give_nothing() -> None:
    assert image_header(b"not an image at all") == (None, None, None)
