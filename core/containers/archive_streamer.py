"""ADR-07: Zero-Decompression In-Memory Virtual Container Streaming Engine.

Streams .zip, .tar, .tar.gz, .tar.zst, .epub, and .hdx archives purely in-memory
(io.BytesIO) using read-only kernel flags (O_RDONLY) without writing temporary
files to disk. Enforces strict guardrails against Zip-Bombs and Path Traversal.
"""

from __future__ import annotations

import hashlib
import html
import io
import os
import posixpath
import re
import tarfile
import urllib.parse
import zipfile
import contextlib
import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Set, Tuple, Union

try:
    import zstandard as zstd
except ImportError:
    zstd = None  # type: ignore

from .archive_cache import ArchiveCache, shared_cache
from .archive_io import IndexedInflateFile, InflateIndex, PreadFile, member_data_start

_BINARY_ASSET_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".cfs", ".cfe", ".si", ".ttf", ".woff", ".woff2",
}
_ZIP_FAMILY = (".zip", ".epub", ".hdx", ".hwics", ".xlsx", ".xlsm", ".docx")
_TAR_FAMILY = (".tar.zst", ".tzst", ".tar.gz", ".tgz", ".tar")
_SHARED = object()  # default for the `cache` argument: use the process-wide cache


class ArchiveSecurityError(Exception):
    """Raised when an archive entry violates ADR-07 security guardrails."""


@dataclass(frozen=False)
class ArchiveEntry:
    """Canonical representation of an in-memory streamed archive member."""

    virtual_uri: str
    archive_path: str
    entry_name: str
    compressed_size: int
    uncompressed_size: int
    compression_ratio: float
    content_text: str
    sha256_hash: str
    raw_bytes: bytes = b""


class _ArchiveEntryStream(Sequence[ArchiveEntry], Iterator[ArchiveEntry]):
    """Hybrid sequence and iterator for streamed ArchiveEntry results.

    Supports both generator-style iteration (`next(stream)`, `for e in stream`)
    and sequence operations (`len(stream)`, `stream[0]`, `list(stream)`), while
    ensuring security guardrails are enforced immediately upon invocation.
    """

    def __init__(self, entries: List[ArchiveEntry]) -> None:
        self._entries = entries
        self._index = 0

    def __iter__(self) -> Iterator[ArchiveEntry]:
        return iter(self._entries)

    def __next__(self) -> ArchiveEntry:
        if self._index >= len(self._entries):
            raise StopIteration
        entry = self._entries[self._index]
        self._index += 1
        return entry

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(self, index: int) -> ArchiveEntry:  # type: ignore[override]
        return self._entries[index]


_HTML_TAG_RE = re.compile(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<[^>]+>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"[ \t]+")


def _extract_openxml_bytes_text(content_bytes: bytes, entry_name: str) -> str:
    """Extract readable text and Markdown tables from in-memory .xlsx/.xlsm/.docx bytes."""
    import xml.etree.ElementTree as ET
    lower = entry_name.lower()
    try:
        with zipfile.ZipFile(io.BytesIO(content_bytes), "r") as zf:
            names = set(zf.namelist())
            if lower.endswith((".xlsx", ".xlsm")):
                shared_strings: List[str] = []
                if "xl/sharedStrings.xml" in names:
                    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                    for si in root:
                        texts = [t.text or "" for t in si.iter() if t.tag.endswith("}t") or t.tag == "t"]
                        shared_strings.append("".join(texts))
                out_lines: List[str] = [f"[OpenXML Spreadsheet: {entry_name}]"]
                for name in sorted(names):
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                        sroot = ET.fromstring(zf.read(name))
                        out_lines.append(f"--- Worksheet: {name} ---")
                        row_cnt = 0
                        for row in sroot.iter():
                            if row.tag.endswith("}row") or row.tag == "row":
                                r_vals: List[str] = []
                                for c in row:
                                    t_attr = c.attrib.get("t", "")
                                    val = ""
                                    for child in c:
                                        if child.tag.endswith("}v") or child.tag == "v":
                                            val = child.text or ""
                                        elif child.tag.endswith("}is") or child.tag == "is":
                                            val = "".join(x.text or "" for x in child.iter() if x.tag.endswith("}t") or x.tag == "t")
                                    if t_attr == "s" and val.isdigit():
                                        s_idx = int(val)
                                        if 0 <= s_idx < len(shared_strings):
                                            val = shared_strings[s_idx]
                                    r_vals.append(_WHITESPACE_RE.sub(" ", val).strip())
                                if any(r_vals):
                                    out_lines.append("| " + " | ".join(r_vals[:15]) + " |")
                                    row_cnt += 1
                                    if row_cnt >= 500:
                                        break
                return "\n\n".join(out_lines)
            elif lower.endswith(".docx") and "word/document.xml" in names:
                root = ET.fromstring(zf.read("word/document.xml"))
                paras: List[str] = [f"# {entry_name.split('/')[-1]}"]
                for elem in root.iter():
                    if elem.tag.endswith("}p"):
                        txt = "".join(t.text or "" for t in elem.iter() if t.tag.endswith("}t")).strip()
                        if txt:
                            paras.append(_WHITESPACE_RE.sub(" ", txt))
                return "\n\n".join(paras)
    except Exception:
        pass

    if lower.endswith(".xls"):
        try:
            import xlrd
            wb = xlrd.open_workbook(file_contents=content_bytes)
            xls_lines: List[str] = [f"# {entry_name.split('/')[-1]}"]
            for s_name in wb.sheet_names():
                sheet = wb.sheet_by_name(s_name)
                xls_lines.append(f"## Sheet: {s_name}")
                for r in range(min(sheet.nrows, 300)):
                    row_vals = [str(v).strip() for v in sheet.row_values(r)[:15] if str(v).strip()]
                    if row_vals:
                        xls_lines.append("| " + " | ".join(row_vals) + " |")
            return "\n\n".join(xls_lines)
        except Exception:
            pass

    return content_bytes.decode("utf-8", errors="replace")


def _clean_markup_text(raw_text: str, entry_name: str) -> str:
    """Strip HTML/XHTML/XML markup tags when processing structured documents."""
    lower_name = entry_name.lower()
    if lower_name.endswith((".html", ".xhtml", ".htm", ".opf")):
        stripped = _HTML_TAG_RE.sub(" ", raw_text)
        unescaped = html.unescape(stripped)
        lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in unescaped.splitlines()]
        return "\n".join(line for line in lines if line)
    return raw_text


class SovereignArchiveStreamer:
    """In-memory virtual container streamer enforcing ADR-07 security invariants."""

    SUPPORTED_EXTENSIONS: Tuple[str, ...] = (
        ".zip",
        ".tar",
        ".tar.gz",
        ".tgz",
        ".tar.zst",
        ".tzst",
        ".epub",
        ".hdx",
        ".hwics",
        ".xlsx",
        ".xlsm",
        ".docx",
    )

    DEFAULT_MAX_COMPRESSION_RATIO: float = 150.0
    DEFAULT_MAX_ENTRY_BYTES: int = 50 * 1024 * 1024  # 50 MB per leaf entry
    DEFAULT_MAX_TOTAL_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB for enterprise .hwics packages

    def __init__(
        self,
        max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
        max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        allowed_extensions: Optional[Set[str]] = None,
        cache: Optional[ArchiveCache] = _SHARED,  # type: ignore[assignment]
        checkpoint_spacing: int = 4 << 20,
    ) -> None:
        # ADR-16: `cache` is the process-wide cache by default, so streamers built per call share it; None disables it.
        self.cache: Optional[ArchiveCache] = shared_cache() if cache is _SHARED else cache
        self.checkpoint_spacing = checkpoint_spacing
        self.max_compression_ratio = float(max_compression_ratio)
        self.max_entry_bytes = int(max_entry_bytes)
        self.max_total_bytes = int(max_total_bytes)
        self.allowed_extensions = (
            {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in allowed_extensions}
            if allowed_extensions is not None
            else None
        )

    @staticmethod
    def build_virtual_uri(archive_path: Union[str, Path], entry_name: str) -> str:
        """Construct canonical ADR-07 virtual URI: archive://<archive_path>#<internal_entry_path>."""
        clean_entry = entry_name.lstrip("/")
        return f"archive://{archive_path}#{clean_entry}"

    @staticmethod
    def parse_compound_archive_path(archive_path: Union[str, Path]) -> Tuple[str, Optional[str]]:
        """Split a compound archive path `<outer.zip>!<inner.hwics>` into (outer_path, inner_entry)."""
        path_str = str(archive_path)
        while "%" in path_str:
            unquoted = urllib.parse.unquote(path_str)
            if unquoted == path_str:
                break
            path_str = unquoted
        if "!" in path_str and not Path(path_str).exists():
            outer, inner = path_str.split("!", 1)
            return outer, inner.lstrip("/")
        return path_str, None

    @staticmethod
    def parse_virtual_uri(virtual_uri: str) -> Tuple[str, str]:
        """Parse canonical virtual URI into (archive_path, internal_entry_path)."""
        if not isinstance(virtual_uri, str) or "#" not in virtual_uri:
            raise ValueError(f"Invalid virtual URI (missing '#'): {virtual_uri!r}")

        if virtual_uri.startswith("archive://"):
            body = virtual_uri[len("archive://") :]
        elif virtual_uri.startswith("virtual://"):
            body = virtual_uri[len("virtual://") :]
        else:
            raise ValueError(
                f"Invalid virtual URI scheme (expected 'archive://'): {virtual_uri!r}"
            )

        archive_path, internal_entry_path = body.split("#", 1)
        while "%" in archive_path:
            unquoted = urllib.parse.unquote(archive_path)
            if unquoted == archive_path:
                break
            archive_path = unquoted
        while "%" in internal_entry_path:
            unquoted_internal = urllib.parse.unquote(internal_entry_path)
            if unquoted_internal == internal_entry_path:
                break
            internal_entry_path = unquoted_internal
        if not archive_path or not internal_entry_path:
            raise ValueError(f"Incomplete virtual URI: {virtual_uri!r}")
        return archive_path, internal_entry_path

    @staticmethod
    def _validate_entry_path(entry_name: str) -> None:
        """Reject path traversal ('..', leading '/', backslash traversal, drive prefixes)."""
        if not entry_name:
            raise ArchiveSecurityError("Path traversal detected in archive entry")

        normalized_slashes = entry_name.replace("\\", "/")
        if normalized_slashes.startswith("/") or normalized_slashes.startswith("\\"):
            raise ArchiveSecurityError("Path traversal detected in archive entry")

        if re.match(r"^[A-Za-z]:", normalized_slashes):
            raise ArchiveSecurityError("Path traversal detected in archive entry")

        parts = normalized_slashes.split("/")
        if ".." in parts or ".." in entry_name:
            raise ArchiveSecurityError("Path traversal detected in archive entry")

        norm = posixpath.normpath(normalized_slashes)
        if norm.startswith("..") or norm.startswith("/"):
            raise ArchiveSecurityError("Path traversal detected in archive entry")

    def _validate_sizes_and_ratio(
        self,
        compressed_size: int,
        uncompressed_size: int,
        cumulative_uncompressed: int,
    ) -> float:
        """Validate entry sizes and compression ratio against ADR-07 thresholds."""
        ratio = float(uncompressed_size) / float(max(1, compressed_size))
        if ratio > self.max_compression_ratio:
            raise ArchiveSecurityError(
                f"Zip-bomb compression ratio exceeded ({ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
            )

        if uncompressed_size > self.max_entry_bytes:
            raise ArchiveSecurityError(
                f"Archive entry exceeds max_entry_bytes ({uncompressed_size} > {self.max_entry_bytes})"
            )

        if cumulative_uncompressed + uncompressed_size > self.max_total_bytes:
            raise ArchiveSecurityError(
                f"Cumulative archive size exceeds max_total_bytes "
                f"({cumulative_uncompressed + uncompressed_size} > {self.max_total_bytes})"
            )

        return ratio

    @staticmethod
    def _read_file_readonly_bytes(archive_path: Path) -> bytes:
        """Read archive bytes into memory using OS O_RDONLY descriptor without disk temp files."""
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        fd = os.open(str(archive_path), flags)
        try:
            with os.fdopen(fd, "rb") as f:
                return f.read()
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

    def _should_include_entry(self, entry_name: str, is_epub: bool = False) -> bool:
        """Check whether entry should be indexed based on extension filters."""
        if is_epub:
            lower = entry_name.lower()
            if lower == "mimetype" or lower.endswith("container.xml"):
                return False
        if self.allowed_extensions is not None:
            _, ext = os.path.splitext(entry_name.lower())
            return ext in self.allowed_extensions
        return True

    def _read_member_bytes_bounded(
        self,
        zf: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        max_bytes: int,
        cumulative_bytes: int = 0,
    ) -> bytes:
        """Read a ZIP member stream in 64KB chunks with strict ratio and size bounds (one growing buffer)."""
        buf = io.BytesIO()
        with zf.open(info, mode="r") as member_fp:
            actual_read = 0
            while True:
                chunk = member_fp.read(65536)
                if not chunk:
                    break
                actual_read += len(chunk)
                actual_ratio = float(actual_read) / float(max(1, info.compress_size))
                if actual_ratio > self.max_compression_ratio:
                    raise ArchiveSecurityError(
                        f"Zip-bomb compression ratio exceeded ({actual_ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
                    )
                if actual_read > max_bytes:
                    raise ArchiveSecurityError(
                        f"Archive entry exceeds max_entry_bytes ({actual_read} > {max_bytes})"
                    )
                if cumulative_bytes + actual_read > self.max_total_bytes:
                    raise ArchiveSecurityError(
                        "Cumulative archive size exceeds max_total_bytes"
                    )
                buf.write(chunk)
        return buf.getvalue()

    @staticmethod
    def _text_for(filename: str, content_bytes: bytes, sha256_hex: str) -> str:
        """Per-member text extraction (the same for the fast path and the listing path)."""
        _, ext = os.path.splitext(filename.lower())
        if ext in _BINARY_ASSET_EXTS:
            return f"[Binary Asset: {filename} ({len(content_bytes)} bytes, sha256={sha256_hex[:16]})]"
        if ext in (".xlsx", ".xlsm", ".docx"):
            return _extract_openxml_bytes_text(content_bytes, filename)
        return _clean_markup_text(content_bytes.decode("utf-8", errors="replace"), filename)

    def _check_nested_declared(self, info: zipfile.ZipInfo, cumulative: int) -> None:
        """Refuse a nested package whose declared size or ratio is beyond the ADR-07 limits, before reading it."""
        ratio = float(info.file_size) / float(max(1, info.compress_size))
        if ratio > self.max_compression_ratio:
            raise ArchiveSecurityError(
                f"Zip-bomb compression ratio exceeded ({ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
            )
        if cumulative + info.file_size > self.max_total_bytes:
            raise ArchiveSecurityError(
                f"Cumulative archive size exceeds max_total_bytes ({cumulative + info.file_size} > {self.max_total_bytes})"
            )

    def _open_nested(
        self,
        zf: zipfile.ZipFile,
        base: Optional[PreadFile],
        info: zipfile.ZipInfo,
        cumulative: int,
        index_key: Optional[tuple] = None,
    ) -> zipfile.ZipFile:
        """Open a zip member that is itself a zip without materialising it and without touching the disk.

        STORED: a zero-copy window over the outer descriptor. DEFLATED: an indexed inflate adapter (one pass,
        then checkpoints). Encrypted or without a random-access outer: the stdlib stream, as before.
        """
        if info.flag_bits & 0x1:
            inner = self._read_member_bytes_bounded(zf=zf, info=info, max_bytes=self.max_total_bytes, cumulative_bytes=cumulative)
            return zipfile.ZipFile(io.BytesIO(inner), mode="r")
        self._check_nested_declared(info, cumulative)
        if isinstance(base, PreadFile):
            start = member_data_start(base, info)
            if info.compress_type == zipfile.ZIP_STORED:
                return zipfile.ZipFile(PreadFile(base.fd, base.start + start, info.compress_size), mode="r")
            if info.compress_type == zipfile.ZIP_DEFLATED:
                if self.cache is not None and index_key is not None:
                    index = self.cache.inflate_index(index_key, self.checkpoint_spacing)
                else:
                    index = InflateIndex(self.checkpoint_spacing)
                return zipfile.ZipFile(IndexedInflateFile(base, start, info.compress_size, info.file_size, info.CRC, index), mode="r")
        return zipfile.ZipFile(zf.open(info), mode="r")

    def _entry_from_member(
        self,
        info: zipfile.ZipInfo,
        content_bytes: bytes,
        archive_path_str: str,
        fallback_ratio: float,
    ) -> ArchiveEntry:
        final_ratio = float(len(content_bytes)) / float(max(1, info.compress_size))
        if final_ratio > self.max_compression_ratio:
            raise ArchiveSecurityError(
                f"Zip-bomb compression ratio exceeded ({final_ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
            )
        sha256_hex = hashlib.sha256(content_bytes).hexdigest()
        return ArchiveEntry(
            virtual_uri=self.build_virtual_uri(archive_path_str, info.filename),
            archive_path=archive_path_str,
            entry_name=info.filename,
            compressed_size=info.compress_size,
            uncompressed_size=len(content_bytes),
            compression_ratio=final_ratio if len(content_bytes) > 0 else fallback_ratio,
            content_text=self._text_for(info.filename, content_bytes, sha256_hex),
            sha256_hash=sha256_hex,
            raw_bytes=content_bytes,
        )

    def _stream_zipfile(
        self,
        zf: zipfile.ZipFile,
        base: Optional[PreadFile],
        archive_path_str: str,
        is_epub: bool = False,
        target_entry: Optional[str] = None,
        index_key: Optional[tuple] = None,
    ) -> List[ArchiveEntry]:
        """Stream entries from an open ZIP/EPUB/HDX/HWICS purely in memory."""
        entries: List[ArchiveEntry] = []
        cumulative_bytes = 0

        # v2 Fast-Path: O(1) dictionary lookup or case-insensitive fallback when resolving a specific virtual_uri target_entry
        if target_entry is not None:
            actual_entry = target_entry if target_entry in zf.NameToInfo else None
            if actual_entry is None:
                target_lower = posixpath.normpath(target_entry).lstrip("/").lower()
                for name in zf.NameToInfo:
                    if name.lower() == target_lower or name.lower().endswith("/" + target_lower):
                        actual_entry = name
                        break
            if actual_entry is not None and actual_entry in zf.NameToInfo:
                self._validate_entry_path(actual_entry)
                info = zf.NameToInfo[actual_entry]
                if not info.is_dir() and not info.filename.endswith("/"):
                    ratio = self._validate_sizes_and_ratio(
                        compressed_size=info.compress_size,
                        uncompressed_size=info.file_size,
                        cumulative_uncompressed=0,
                    )
                    content_bytes = self._read_member_bytes_bounded(
                        zf=zf, info=info, max_bytes=self.max_entry_bytes, cumulative_bytes=0
                    )
                    return [self._entry_from_member(info, content_bytes, archive_path_str, ratio)]

        for info in zf.infolist():
            # Validate path traversal on EVERY member (including directories)
            self._validate_entry_path(info.filename)

            if info.is_dir() or info.filename.endswith("/"):
                continue

            lower_member = info.filename.lower()

            # Transparent nested ZIP-in-ZIP (.zip -> .hwics / .hdx), streamed without materialising the inner package
            if lower_member.endswith((".hwics", ".hdx")) and target_entry != info.filename:
                self._check_nested_declared(info, cumulative_bytes)
                nested_target = target_entry
                if nested_target and nested_target.startswith(f"{info.filename}/"):
                    nested_target = nested_target[len(info.filename) + 1 :]
                key = (index_key, info.filename) if index_key is not None else None
                with self._open_nested(zf, base, info, cumulative_bytes, index_key=key) as inner_zf:
                    nested_entries = self._stream_zipfile(
                        inner_zf, None, f"{archive_path_str}!{info.filename}", is_epub=False, target_entry=nested_target
                    )
                for ne in nested_entries:
                    cumulative_bytes += ne.uncompressed_size
                    if cumulative_bytes > self.max_total_bytes:
                        raise ArchiveSecurityError("Cumulative archive size exceeds max_total_bytes")
                entries.extend(nested_entries)
                continue

            # Always enforce zip-bomb guardrails across leaf archive members
            ratio = self._validate_sizes_and_ratio(
                compressed_size=info.compress_size,
                uncompressed_size=info.file_size,
                cumulative_uncompressed=cumulative_bytes,
            )

            if target_entry is not None and info.filename != target_entry:
                continue

            if target_entry is None and not self._should_include_entry(info.filename, is_epub=is_epub):
                continue

            content_bytes = self._read_member_bytes_bounded(
                zf=zf, info=info, max_bytes=self.max_entry_bytes, cumulative_bytes=cumulative_bytes
            )
            cumulative_bytes += len(content_bytes)
            entries.append(self._entry_from_member(info, content_bytes, archive_path_str, ratio))

        return entries

    def _stream_zip_buffer(
        self,
        raw_bytes: bytes,
        archive_path_str: str,
        is_epub: bool = False,
        target_entry: Optional[str] = None,
    ) -> List[ArchiveEntry]:
        """Stream entries from a ZIP/EPUB/HDX/HWICS byte buffer (callers that already hold the bytes)."""
        with zipfile.ZipFile(io.BytesIO(raw_bytes), mode="r") as zf:
            return self._stream_zipfile(zf, None, archive_path_str, is_epub=is_epub, target_entry=target_entry)

    def _decompress_zstd_bounded(self, raw_bytes: bytes) -> bytes:
        """Decompress a .zst stream purely in-memory while enforcing Zip-Bomb guardrails."""
        compressed_len = max(1, len(raw_bytes))
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(io.BytesIO(raw_bytes)) as reader:
            chunks: List[bytes] = []
            total_decompressed = 0
            while True:
                chunk = reader.read(65536)
                if not chunk:
                    break
                total_decompressed += len(chunk)
                # Note: A tar container adds header overhead (minimum 1024-10240 bytes)
                # so we check entry-level ratios inside _stream_tar_buffer, and bound
                # raw stream allocation to max_total_bytes to prevent RAM exhaustion.
                if total_decompressed > self.max_total_bytes:
                    ratio = float(total_decompressed) / float(compressed_len)
                    if ratio > self.max_compression_ratio:
                        raise ArchiveSecurityError(
                            f"Zip-bomb compression ratio exceeded ({ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
                        )
                    raise ArchiveSecurityError(
                        f"Decompressed stream exceeds max_total_bytes ({total_decompressed} > {self.max_total_bytes})"
                    )
                chunks.append(chunk)
            return b"".join(chunks)

    def _stream_tar_buffer(
        self,
        raw_bytes: bytes,
        archive_path_str: str,
        compression_mode: str = "",
        target_entry: Optional[str] = None,
    ) -> List[ArchiveEntry]:
        """Stream entries from .tar, .tar.gz, or .tar.zst purely in memory."""
        archive_compressed_size = max(1, len(raw_bytes))

        if compression_mode == "zst":
            tar_bytes = self._decompress_zstd_bounded(raw_bytes)
            tar_stream = io.BytesIO(tar_bytes)
            tar_open_mode = "r:"
        elif compression_mode == "gz":
            tar_stream = io.BytesIO(raw_bytes)
            tar_open_mode = "r:gz"
        else:
            tar_stream = io.BytesIO(raw_bytes)
            tar_open_mode = "r:*"

        entries: List[ArchiveEntry] = []
        cumulative_bytes = 0

        with tarfile.open(fileobj=tar_stream, mode=tar_open_mode) as tf:
            members = tf.getmembers()
            total_uncompressed_all = sum(max(0, m.size) for m in members if m.isfile())

            for member in members:
                self._validate_entry_path(member.name)

                if not member.isfile():
                    continue

                if compression_mode in ("zst", "gz") and total_uncompressed_all > 0:
                    estimated_compressed = max(
                        1,
                        int(round(archive_compressed_size * (member.size / total_uncompressed_all))),
                    )
                else:
                    estimated_compressed = max(1, member.size)

                ratio = self._validate_sizes_and_ratio(
                    compressed_size=estimated_compressed,
                    uncompressed_size=member.size,
                    cumulative_uncompressed=cumulative_bytes,
                )

                if target_entry is not None and member.name != target_entry:
                    continue

                if target_entry is None and not self._should_include_entry(member.name):
                    continue

                extracted_fp = tf.extractfile(member)
                if extracted_fp is None:
                    continue

                with extracted_fp:
                    content_bytes = extracted_fp.read(self.max_entry_bytes + 1)
                    if len(content_bytes) > self.max_entry_bytes:
                        raise ArchiveSecurityError(
                            f"Archive entry exceeds max_entry_bytes ({len(content_bytes)} > {self.max_entry_bytes})"
                        )

                cumulative_bytes += len(content_bytes)
                if cumulative_bytes > self.max_total_bytes:
                    raise ArchiveSecurityError("Cumulative archive size exceeds max_total_bytes")

                sha256_hex = hashlib.sha256(content_bytes).hexdigest()
                decoded_text = content_bytes.decode("utf-8", errors="replace")
                clean_text = _clean_markup_text(decoded_text, member.name)

                entries.append(
                    ArchiveEntry(
                        virtual_uri=self.build_virtual_uri(archive_path_str, member.name),
                        archive_path=archive_path_str,
                        entry_name=member.name,
                        compressed_size=estimated_compressed,
                        uncompressed_size=len(content_bytes),
                        compression_ratio=ratio,
                        content_text=clean_text,
                        sha256_hash=sha256_hex,
                        raw_bytes=content_bytes,
                    )
                )

        return entries

    def _limits_key(self) -> tuple:
        """Settings that change what a read returns or refuses: part of every cached entry's key."""
        return (self.max_compression_ratio, self.max_entry_bytes, self.max_total_bytes)

    @contextlib.contextmanager
    def _open_archive(self, path_obj: Path):
        """The outer zip as (base, zf, cache_entry): shared and kept by the cache, or opened and closed for this call."""
        if self.cache is not None:
            with self.cache.archive(path_obj) as arc:
                yield arc.base, arc.zf, arc
        else:
            with PreadFile.open(path_obj) as base, zipfile.ZipFile(base, mode="r") as zf:
                yield base, zf, None

    def _dispatch_archive(
        self,
        archive_path: Union[str, Path],
        target_entry: Optional[str] = None,
    ) -> List[ArchiveEntry]:
        """Identify the container format and stream its entries: zips by random access, tars in memory."""
        outer_path_str, inner_container_entry = self.parse_compound_archive_path(archive_path)
        path_obj = Path(outer_path_str)
        archive_path_str = str(archive_path)
        lower_name = path_obj.name.lower()

        if inner_container_entry is not None:
            self._validate_entry_path(inner_container_entry)
        is_zip = inner_container_entry is not None or lower_name.endswith(_ZIP_FAMILY)
        if not is_zip and not lower_name.endswith(_TAR_FAMILY):
            with PreadFile.open(path_obj) as probe:  # unknown extension: look at the magic bytes
                is_zip = probe.pread(4, 0) == b"PK\x03\x04"
        if not is_zip:
            return self._dispatch_buffered(path_obj, archive_path_str, lower_name, target_entry)

        with self._open_archive(path_obj) as (base, zf, arc):
            cache = self.cache
            entry_key = None
            if cache is not None and target_entry is not None and arc is not None:
                entry_key = (arc.key, inner_container_entry, target_entry, archive_path_str, self._limits_key())
                cached = cache.get_entry(entry_key)
                if cached is not None:
                    return [cached]

            if inner_container_entry is None:
                res = self._stream_zipfile(
                    zf, base, archive_path_str, is_epub=lower_name.endswith(".epub"),
                    target_entry=target_entry, index_key=arc.key if arc is not None else None,
                )
            else:
                res = self._stream_inner_container(zf, base, arc, outer_path_str, inner_container_entry, archive_path_str, target_entry)

            if entry_key is not None and len(res) == 1:
                cache.put_entry(entry_key, res[0])
            return res

    def _stream_inner_container(self, zf, base, arc, outer_path_str, inner_name, archive_path_str, target_entry):
        """Compound path `<outer.zip>!<inner.hwics>`: the inner package is opened once and reused when cached."""
        def open_inner() -> zipfile.ZipFile:
            try:
                inner_info = zf.getinfo(inner_name)
            except KeyError as exc:
                raise KeyError(f"Nested container {inner_name!r} not found in {outer_path_str!r}") from exc
            return self._open_nested(zf, base, inner_info, 0, index_key=(arc.key, inner_name) if arc is not None else None)

        is_epub = inner_name.lower().endswith(".epub")
        if arc is None:
            with open_inner() as inner_zf:
                return self._stream_zipfile(inner_zf, None, archive_path_str, is_epub=is_epub, target_entry=target_entry)
        with arc.lock:  # one opener, and one reader at a time on the shared inner zip
            inner_zf = arc.inner.get(inner_name)
            if inner_zf is None:
                inner_zf = arc.inner[inner_name] = open_inner()
                self.cache.stats["inner_open"] += 1
            return self._stream_zipfile(inner_zf, None, archive_path_str, is_epub=is_epub, target_entry=target_entry)

    def _dispatch_buffered(self, path_obj: Path, archive_path_str: str, lower_name: str, target_entry: Optional[str]) -> List[ArchiveEntry]:
        """Tar family and magic-byte detection: these formats are not random access, so they are read whole."""
        raw_bytes = self._read_file_readonly_bytes(path_obj)

        if lower_name.endswith((".tar.zst", ".tzst")):
            return self._stream_tar_buffer(
                raw_bytes=raw_bytes, archive_path_str=archive_path_str, compression_mode="zst", target_entry=target_entry,
            )
        if lower_name.endswith((".tar.gz", ".tgz")):
            return self._stream_tar_buffer(
                raw_bytes=raw_bytes, archive_path_str=archive_path_str, compression_mode="gz", target_entry=target_entry,
            )
        if lower_name.endswith(".tar"):
            return self._stream_tar_buffer(
                raw_bytes=raw_bytes, archive_path_str=archive_path_str, compression_mode="", target_entry=target_entry,
            )
        if raw_bytes.startswith(b"\x28\xb5\x2f\xfd"):
            return self._stream_tar_buffer(
                raw_bytes=raw_bytes, archive_path_str=archive_path_str, compression_mode="zst", target_entry=target_entry,
            )

        raise ValueError(f"Unsupported archive container format: {archive_path_str}")

    def stream_archive(self, archive_path: Union[str, Path]) -> _ArchiveEntryStream:
        """Stream all entries from an archive container purely in memory (io.BytesIO)."""
        entries = self._dispatch_archive(archive_path=archive_path, target_entry=None)
        return _ArchiveEntryStream(entries)

    def resolve_virtual_uri(self, virtual_uri: str) -> ArchiveEntry:
        """Resolve an `archive://<archive_path>#<internal_entry_path>` URI purely in memory."""
        archive_path_str, raw_internal_entry = self.parse_virtual_uri(virtual_uri)

        # 1. Strip chunking, sheet, and anchor fragments (e.g. ::part::0001, ::sheet::SheetName, #sec:...)
        sub_target = ""
        clean_internal = raw_internal_entry
        if "::" in clean_internal:
            parts = clean_internal.split("::", 1)
            clean_internal = parts[0]
            sub_target = parts[1]
        elif "#" in clean_internal:
            parts = clean_internal.split("#", 1)
            clean_internal = parts[0]
            sub_target = parts[1]

        # 2. Check for nested container paths (e.g. `path/to/inner.zip!subfolder/file.wsdl`)
        if "!" in clean_internal:
            outer_entry, inner_entry = clean_internal.split("!", 1)
            self._validate_entry_path(outer_entry)
            self._validate_entry_path(inner_entry)
            outer_matches = self._dispatch_archive(
                archive_path=archive_path_str,
                target_entry=outer_entry,
            )
            if not outer_matches:
                raise KeyError(
                    f"Outer entry {outer_entry!r} not found in archive {archive_path_str!r}"
                )
            outer_bytes = outer_matches[0].raw_bytes
            with zipfile.ZipFile(io.BytesIO(outer_bytes), mode="r") as inner_zf:
                try:
                    inner_info = inner_zf.getinfo(inner_entry)
                    inner_bytes = inner_zf.read(inner_info)
                except KeyError:
                    target_lower = inner_entry.lower()
                    matching_names = [
                        n for n in inner_zf.namelist()
                        if n == inner_entry or n.endswith("/" + inner_entry)
                        or n.lower() == target_lower or n.lower().endswith("/" + target_lower)
                    ]
                    if not matching_names:
                        raise KeyError(
                            f"Inner entry {inner_entry!r} not found in nested container {outer_entry!r}"
                        )
                    inner_info = inner_zf.getinfo(matching_names[0])
                    inner_bytes = inner_zf.read(inner_info)

                sha256_hex = hashlib.sha256(inner_bytes).hexdigest()
                entry = ArchiveEntry(
                    virtual_uri=virtual_uri,
                    archive_path=archive_path_str,
                    entry_name=inner_info.filename,
                    compressed_size=inner_info.compress_size,
                    uncompressed_size=len(inner_bytes),
                    compression_ratio=float(len(inner_bytes)) / float(max(1, inner_info.compress_size)),
                    content_text=self._text_for(inner_info.filename, inner_bytes, sha256_hex),
                    sha256_hash=sha256_hex,
                    raw_bytes=inner_bytes,
                )
                if sub_target:
                    setattr(entry, "sub_target", sub_target)
                return entry

        self._validate_entry_path(clean_internal)

        matches = self._dispatch_archive(
            archive_path=archive_path_str,
            target_entry=clean_internal,
        )
        if not matches:
            norm_target = posixpath.normpath(clean_internal).lstrip("/")
            matches = self._dispatch_archive(
                archive_path=archive_path_str,
                target_entry=norm_target,
            )
            if not matches:
                target_lower = norm_target.lower()
                all_entries = self._dispatch_archive(archive_path=archive_path_str, target_entry=None)
                matches = [
                    e for e in all_entries
                    if e.entry_name.lower() == target_lower or e.entry_name.lower().endswith("/" + target_lower)
                ]
                if not matches:
                    raise KeyError(
                        f"Entry {clean_internal!r} not found in archive {archive_path_str!r}"
                    )
        entry = matches[0]
        if sub_target:
            setattr(entry, "sub_target", sub_target)
        return entry
