"""Streaming multipart intake: size cap enforced while bytes arrive, safe names, hash storage."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import Request

MAX_FIELD_BYTES = 4096
MAX_PARTS = 16  # the forms here have at most six fields and one file
ENVELOPE_ALLOWANCE = 1024 * 1024  # multipart framing and text fields on top of the file cap
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadTooLarge(Exception):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"File exceeds the {max_bytes / 2**20:g} MiB limit.")
        self.max_bytes = max_bytes


class BadUpload(Exception):
    pass


@dataclass
class ParsedUpload:
    fields: dict[str, str] = field(default_factory=dict)
    filename: str | None = None
    temp_path: Path | None = None
    sha256: str | None = None
    size: int = 0


def safe_filename(name: str | None) -> str:
    """Basename only, restricted charset, no leading dots; never a path."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    base = _UNSAFE.sub("_", base).lstrip(".")
    if len(base) > 100:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 100 - len(ext) - 1] + dot + ext) if dot else base[:100]
    return base or "upload"


async def read_multipart(request: Request, temp_dir: Path, max_bytes: int) -> ParsedUpload:
    """Parse a multipart body chunk by chunk, writing the first file part to ``temp_dir``.

    Raises UploadTooLarge as soon as the file part passes ``max_bytes``, the whole body passes
    ``max_bytes + ENVELOPE_ALLOWANCE`` (ignored parts count too), or the declared
    Content-Length is clearly over it, and deletes the partial file. A malformed body or more
    than ``MAX_PARTS`` parts is a BadUpload.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes + ENVELOPE_ALLOWANCE:
        raise UploadTooLarge(max_bytes)
    _, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if not boundary:
        raise BadUpload("multipart request without a boundary")

    out = ParsedUpload()
    temp_dir.mkdir(parents=True, exist_ok=True)
    state: dict = {"header": b"", "value": b"", "headers": {}, "sink": None, "name": None}
    digest = hashlib.sha256()

    def on_part_begin() -> None:
        state["parts"] = state.get("parts", 0) + 1
        if state["parts"] > MAX_PARTS:
            raise BadUpload(f"more than {MAX_PARTS} form fields")
        state.update(header=b"", value=b"", headers={}, sink=None, name=None)

    def on_header_field(data: bytes, start: int, end: int) -> None:
        state["header"] += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        state["value"] += data[start:end]

    def on_header_end() -> None:
        state["headers"][state["header"].lower()] = state["value"]
        state["header"] = b""
        state["value"] = b""

    def on_headers_finished() -> None:
        disposition = state["headers"].get(b"content-disposition", b"")
        _, opts = parse_options_header(disposition)
        name = opts.get(b"name", b"").decode("utf-8", "replace")
        filename = opts.get(b"filename")
        state["name"] = name
        if filename is not None and out.temp_path is None:
            out.filename = filename.decode("utf-8", "replace")
            out.temp_path = temp_dir / f".upload-{uuid.uuid4().hex}"
            state["sink"] = out.temp_path.open("wb")
            state["is_file"] = True
        elif filename is not None:
            state["sink"] = None  # a second file part is ignored
            state["is_file"] = False
        else:
            state["sink"] = bytearray()
            state["is_file"] = False

    def on_part_data(data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        sink = state["sink"]
        if sink is None:
            return
        if state.get("is_file"):
            out.size += len(chunk)
            if out.size > max_bytes:
                raise UploadTooLarge(max_bytes)
            digest.update(chunk)
            sink.write(chunk)
        else:
            sink.extend(chunk)
            if len(sink) > MAX_FIELD_BYTES:
                raise BadUpload(f"form field {state['name']!r} is too long")

    def on_part_end() -> None:
        sink = state["sink"]
        if isinstance(sink, bytearray):
            out.fields[state["name"]] = sink.decode("utf-8", "replace")
        elif sink is not None:
            sink.close()
        state["sink"] = None

    parser = MultipartParser(
        boundary,
        callbacks={
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
        },
    )
    received = 0
    try:
        try:
            async for chunk in request.stream():
                received += len(chunk)
                if received > max_bytes + ENVELOPE_ALLOWANCE:
                    raise UploadTooLarge(max_bytes)
                parser.write(chunk)
            parser.finalize()
        except MultipartParseError:
            raise BadUpload("The upload is not a valid multipart/form-data body.") from None
    except BaseException:
        sink = state["sink"]
        if sink is not None and not isinstance(sink, bytearray):
            sink.close()
        discard(out.temp_path)
        raise
    out.sha256 = digest.hexdigest() if out.temp_path is not None else None
    return out


def discard(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def store_upload(temp_path: Path, sha256: str, filename: str | None, uploads_dir: Path) -> Path:
    """Move the streamed file to ``uploads/<sha256>/<safe name>`` (same bytes are stored once)."""
    target_dir = uploads_dir / sha256
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_filename(filename)
    if target.resolve().parent != target_dir.resolve():  # defence in depth; names are sanitized
        discard(temp_path)
        raise BadUpload("unsafe upload name")
    if target.exists():
        discard(temp_path)
    else:
        os.replace(temp_path, target)
    return target
