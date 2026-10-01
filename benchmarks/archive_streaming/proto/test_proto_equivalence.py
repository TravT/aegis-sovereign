"""Behaviour-preservation and security tests for the prototype designs (run OUTSIDE the repo).

Every test runs the SAME operation through D0 (repo code) and a prototype design and asserts identical
results (ArchiveEntry fields incl. raw bytes) or the same exception class + message prefix. The ADR-07
tests from tests/test_containers_and_capsules.py are re-expressed here, parametrised over designs,
plus new cases for nested containers, zip64, encrypted flags, CRC corruption, file replacement under
a cache, zero-disk-write / O_RDONLY enforcement, and a tracemalloc memory budget.

    cd <this dir> && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<appliance>:. <venv>/bin/python -m pytest -q -p no:cacheprovider test_proto_equivalence.py
"""

from __future__ import annotations

import builtins
import dataclasses
import hashlib
import io
import os
import tarfile
import time
import tracemalloc
import zipfile
from pathlib import Path

import pytest
import zstandard as zstd

from core.containers.archive_streamer import ArchiveSecurityError, SovereignArchiveStreamer
from streamers import ArchiveCache, ProtoStreamer, make_streamer

PROTO_DESIGNS = ["D1", "D2", "D2i", "D3"]


def _zip_bytes(files: dict, compression=zipfile.ZIP_DEFLATED, zip64=False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compression) as zf:
        for name, data in files.items():
            if zip64:
                with zf.open(zipfile.ZipInfo(name), "w", force_zip64=True) as w:
                    w.write(data)
            else:
                zf.writestr(name, data)
    return buf.getvalue()


def _write(p: Path, data: bytes) -> Path:
    p.write_bytes(data)
    return p


def _nested(tmp: Path, inner_files: dict, inner_name="pkg.hwics", outer_comp=zipfile.ZIP_DEFLATED,
            inner_comp=zipfile.ZIP_DEFLATED, name="outer.zip", zip64=False) -> Path:
    inner = _zip_bytes(inner_files, inner_comp, zip64=zip64)
    return _write(tmp / name, _zip_bytes({inner_name: inner}, outer_comp, zip64=zip64))


def _same(design: str, fn):
    """Run fn(streamer) with D0 and `design`; return both outcomes normalised for comparison."""
    outs = []
    for d in ("D0", design):
        s = make_streamer(d)
        try:
            r = fn(s)
            if isinstance(r, list):
                r = [dataclasses.asdict(e) for e in r]
            elif dataclasses.is_dataclass(r):
                r = dataclasses.asdict(r)
            outs.append(("ok", r))
        except Exception as exc:  # noqa: BLE001
            outs.append(("err", type(exc).__name__, str(exc).split("(")[0]))
    return outs


@pytest.mark.parametrize("design", PROTO_DESIGNS)
def test_adr07_zip_tar_resolve_equivalent(tmp_path, design):
    z = _write(tmp_path / "m.zip", _zip_bytes({"alarms/a.txt": b"Optical module LOS", "runbooks/b.html": b"<html><body><h1>BGP</h1></body></html>"}))
    a, b = _same(design, lambda s: list(s.stream_archive(z)))
    assert a == b and a[0] == "ok" and len(a[1]) == 2
    a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{z}#runbooks/b.html"))
    assert a == b and "<html>" not in a[1]["content_text"]
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        info = tarfile.TarInfo("contracts/nda.md")
        info.size = 5
        tf.addfile(info, io.BytesIO(b"LGPD!"))
    t = _write(tmp_path / "c.tar.zst", zstd.ZstdCompressor().compress(tar_buf.getvalue()))
    a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{t}#contracts/nda.md"))
    assert a == b and a[0] == "ok"


@pytest.mark.parametrize("design", PROTO_DESIGNS)
def test_adr07_hdx_epub_equivalent(tmp_path, design):
    h = _write(tmp_path / "x.hdx", _zip_bytes({"profile.xml": b"<p/>", "resources/t.xhtml": b"<html><h2>display</h2></html>"}))
    e = _write(tmp_path / "b.epub", _zip_bytes({"mimetype": b"application/epub+zip", "META-INF/container.xml": b"<c/>", "OEBPS/c1.xhtml": b"<p>Troponina</p>"}))
    for p in (h, e):
        a, b = _same(design, lambda s: list(s.stream_archive(p)))
        assert a == b and a[0] == "ok"


@pytest.mark.parametrize("design", PROTO_DESIGNS)
def test_zip_bomb_ratio_and_entry_size(tmp_path, design):
    bomb = _write(tmp_path / "bomb.zip", _zip_bytes({"bomb.txt": b"A" * (2 << 20)}))
    for fn in (lambda s: list(s.stream_archive(bomb)), lambda s: s.resolve_virtual_uri(f"archive://{bomb}#bomb.txt")):
        a, b = _same(design, fn)
        assert a == b and a[:2] == ("err", "ArchiveSecurityError")
    big = _write(tmp_path / "big.zip", _zip_bytes({"r.bin": os.urandom(8192)}))
    outs = []
    for d in ("D0", design):
        s = make_streamer(d) if d == "D0" else make_streamer(d)
        s.max_entry_bytes = 4096
        with pytest.raises(ArchiveSecurityError, match="max_entry_bytes"):
            list(s.stream_archive(big))


@pytest.mark.parametrize("design", PROTO_DESIGNS)
def test_path_traversal(tmp_path, design):
    z = _write(tmp_path / "t.zip", _zip_bytes({"../../etc/passwd": b"root", "ok.txt": b"fine"}))
    a, b = _same(design, lambda s: list(s.stream_archive(z)))
    assert a == b and a[:2] == ("err", "ArchiveSecurityError")
    a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{z}#../../etc/passwd"))
    assert a == b and a[:2] == ("err", "ArchiveSecurityError")
    n = _nested(tmp_path, {"../../etc/passwd": b"root", "ok.txt": b"fine"})
    for uri in (f"archive://{n}!pkg.hwics#ok.txt", f"archive://{n}!pkg.hwics#../../etc/passwd",
                f"archive://{n}!../pkg.hwics#ok.txt", f"archive://{n}#pkg.hwics/ok.txt"):
        a, b = _same(design, lambda s: s.resolve_virtual_uri(uri))
        assert a == b, uri


@pytest.mark.parametrize("design", PROTO_DESIGNS)
@pytest.mark.parametrize("inner_comp", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("outer_comp", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_nested_resolve_equivalent(tmp_path, design, inner_comp, outer_comp):
    files = {f"resources/alarms/{i}.html": (f"<html><body><h1>ALM-{i}</h1>" + "x" * (i * 97) + "</body></html>").encode() for i in range(300)}
    files["resources/sheet.xlsx"] = _zip_bytes({"xl/sharedStrings.xml": b"<sst><si><t>hello</t></si></sst>"})
    n = _nested(tmp_path, files, outer_comp=outer_comp, inner_comp=inner_comp)
    for member in ("resources/alarms/3.html", "resources/alarms/299.html", "resources/sheet.xlsx", "missing.html"):
        a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#{member}"))
        assert a == b, member
    # non-compound URI into a nested .hwics (D0 loop path with nested_target) and a full listing
    a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{n}#pkg.hwics/resources/alarms/7.html"))
    assert a == b
    a, b = _same(design, lambda s: list(s.stream_archive(n)))
    assert a == b  # (this synthetic corpus trips the 150:1 guard on the listing path in D0 too)


@pytest.mark.parametrize("design", PROTO_DESIGNS)
def test_nested_bombs(tmp_path, design):
    # (1) bomb member inside the inner container
    n = _nested(tmp_path, {"bomb.txt": b"A" * (4 << 20), "ok.txt": b"ok"}, name="b1.zip")
    a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#bomb.txt"))
    assert a == b and a[:2] == ("err", "ArchiveSecurityError")
    # (2) the inner container itself compresses > 150:1 inside the outer
    n2 = _nested(tmp_path, {"zeros.bin": b"\0" * (8 << 20)}, inner_comp=zipfile.ZIP_STORED, name="b2.zip")
    a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{n2}!pkg.hwics#zeros.bin"))
    assert a[:2] == b[:2] == ("err", "ArchiveSecurityError")  # message ratio figure may differ (declared vs running)
    assert a[2] == b[2]  # same message prefix


@pytest.mark.parametrize("design", PROTO_DESIGNS)
def test_zip64_nested(tmp_path, design):
    n = _nested(tmp_path, {"a.html": b"<p>zip64 member</p>", "b.txt": b"b" * 1000}, zip64=True)
    a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#a.html"))
    assert a == b and a[0] == "ok"


def _set_encrypted_flag(data: bytes, name: bytes) -> bytes:
    b = bytearray(data)
    i = b.find(b"PK\x03\x04" + b"")
    while i != -1:
        if b[i + 30 : i + 30 + len(name)] == name:
            b[i + 6] |= 1
        i = b.find(b"PK\x03\x04", i + 4)
    j = b.find(b"PK\x01\x02")
    while j != -1:
        if b[j + 46 : j + 46 + len(name)] == name:
            b[j + 8] |= 1
        j = b.find(b"PK\x01\x02", j + 4)
    return bytes(b)


@pytest.mark.parametrize("design", PROTO_DESIGNS)
def test_encrypted_flag(tmp_path, design):
    z = _write(tmp_path / "enc.zip", _set_encrypted_flag(_zip_bytes({"s.txt": b"secret"}), b"s.txt"))
    a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{z}#s.txt"))
    assert a == b and a[0] == "err"
    inner = _zip_bytes({"x.txt": b"x"})
    o = _write(tmp_path / "enc2.zip", _set_encrypted_flag(_zip_bytes({"pkg.hwics": inner}), b"pkg.hwics"))
    a, b = _same(design, lambda s: s.resolve_virtual_uri(f"archive://{o}!pkg.hwics#x.txt"))
    assert a == b and a[0] == "err"


@pytest.mark.parametrize("design", ["D2", "D2i", "D3"])
def test_corrupt_inner_stream_raises(tmp_path, design):
    files = {f"f{i}.txt": os.urandom(2000) for i in range(200)}
    n = _nested(tmp_path, files)
    raw = bytearray(n.read_bytes())
    raw[len(raw) // 2] ^= 0xFF  # flip one byte in the middle of the DEFLATE stream
    n.write_bytes(bytes(raw))
    for d in ("D0", design):
        with pytest.raises(Exception):
            make_streamer(d).resolve_virtual_uri(f"archive://{n}!pkg.hwics#f150.txt")


def test_d3_cache_invalidation_on_replace_and_touch(tmp_path):
    cache = ArchiveCache()
    s = make_streamer("D3", cache)
    n = _nested(tmp_path, {"a.txt": b"version-1"})
    uri = f"archive://{n}!pkg.hwics#a.txt"
    assert s.resolve_virtual_uri(uri).content_text == "version-1"
    assert s.resolve_virtual_uri(uri).content_text == "version-1"
    assert cache.stats["entry_hit"] == 1
    tmp = tmp_path / "new.zip"
    _nested(tmp_path, {"a.txt": b"version-2-longer"}, name="new.zip")
    os.replace(tmp, n)  # atomic replace: new inode
    assert s.resolve_virtual_uri(uri).content_text == "version-2-longer"
    data = _zip_bytes({"pkg.hwics": _zip_bytes({"a.txt": b"version-3-longer"})})  # same size, in place
    with open(n, "r+b") as f:
        f.write(data)
        f.truncate()
    st = os.stat(n)
    os.utime(n, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    assert s.resolve_virtual_uri(uri).content_text == "version-3-longer"
    assert cache.stats["archive_invalidated"] >= 2


def test_d3_concurrent_requests_identical(tmp_path):
    import concurrent.futures
    files = {f"m{i}.html": f"<p>member {i}</p>".encode() * 50 for i in range(500)}
    n = _nested(tmp_path, files)
    ref = {i: SovereignArchiveStreamer().resolve_virtual_uri(f"archive://{n}!pkg.hwics#m{i}.html") for i in range(0, 500, 25)}
    s = make_streamer("D3")
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        got = dict(zip(ref, ex.map(lambda i: s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#m{i}.html"), ref)))
    assert all(dataclasses.asdict(got[i]) == dataclasses.asdict(ref[i]) for i in ref)
    assert s.cache.stats["inner_open"] == 1  # single-flight: the inner container was opened once


@pytest.mark.parametrize("design", PROTO_DESIGNS)
def test_zero_disk_writes_and_rdonly(tmp_path, design, monkeypatch):
    n = _nested(tmp_path, {"a.html": b"<p>A</p>", "b.xlsx": _zip_bytes({"xl/sharedStrings.xml": b"<sst/>"})})
    real_open, real_os_open = builtins.open, os.open
    seen_flags = []

    def guard_open(file, mode="r", *a, **k):
        if any(c in mode for c in "wax+"):
            raise AssertionError(f"write open during archive read: {file} {mode}")
        return real_open(file, mode, *a, **k)

    def guard_os_open(path, flags, *a, **k):
        seen_flags.append(flags)
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError(f"write flags on {path}")
        return real_os_open(path, flags, *a, **k)

    monkeypatch.setattr(builtins, "open", guard_open)
    monkeypatch.setattr(os, "open", guard_os_open)
    before = sorted(os.listdir(tmp_path))
    s = make_streamer(design)
    s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#a.html")
    s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#b.xlsx")
    assert sorted(os.listdir(tmp_path)) == before
    assert seen_flags and all((f & os.O_ACCMODE) == os.O_RDONLY for f in seen_flags)


@pytest.mark.parametrize("design,budget_mb", [("D2", 64), ("D2i", 12), ("D3", 12)])
def test_memory_budget_nested_48mb(tmp_path, design, budget_mb):
    """Python-heap peak (tracemalloc) while resolving a small member of a 48 MB nested container.

    D2 (stdlib ZipExtFile) peaks at ~3 x 16 MiB because ZipExtFile.seek() skips forward with read(MAX_SEEK_READ=16 MiB).
    """
    payload = {"big.bin": os.urandom(48 << 20), "small.html": b"<p>needle</p>"}
    n = _nested(tmp_path, payload, name="mem.zip")
    uri = f"archive://{n}!pkg.hwics#small.html"
    peaks = {}
    for d in ("D0", design):
        s = make_streamer(d)
        tracemalloc.start()
        e = s.resolve_virtual_uri(uri)
        peaks[d] = tracemalloc.get_traced_memory()[1] / 1048576
        tracemalloc.stop()
        assert e.content_text == "needle"
    assert peaks["D0"] > 2 * 48  # baseline holds outer + inner (+ join copy)
    assert peaks[design] < budget_mb, peaks
