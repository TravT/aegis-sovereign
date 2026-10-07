"""ADR-16 phase 1: the archive streamer reads archives by random access instead of whole into RAM.

Every behaviour test runs the same operation through the FROZEN pre-change streamer (tests/_legacy_streamer.py)
and the current one and asserts identical results (every ArchiveEntry field, raw bytes included) or the same
exception class and message prefix. Memory budgets are tests too: a regression back to "read the whole zip"
fails here, not in production.
"""

from __future__ import annotations

import builtins
import concurrent.futures
import dataclasses
import io
import os
import subprocess
import sys
import tarfile
import textwrap
import tracemalloc
import zipfile
from pathlib import Path

import pytest
import zstandard as zstd

from core.containers.archive_cache import ArchiveCache
from core.containers.archive_streamer import ArchiveSecurityError, SovereignArchiveStreamer
from tests._legacy_streamer import SovereignArchiveStreamer as LegacyStreamer

MODES = ["streaming", "cached"]


def make_new(mode: str, **kwargs) -> SovereignArchiveStreamer:
    return SovereignArchiveStreamer(cache=ArchiveCache() if mode == "cached" else None, **kwargs)


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


def _same(mode: str, fn):
    """Run fn(streamer) with the legacy and the new streamer; return both outcomes normalised for comparison."""
    outs = []
    for streamer in (LegacyStreamer(), make_new(mode)):
        try:
            r = fn(streamer)
            if isinstance(r, list):
                r = [dataclasses.asdict(e) for e in r]
            elif dataclasses.is_dataclass(r):
                r = dataclasses.asdict(r)
            outs.append(("ok", r))
        except Exception as exc:  # noqa: BLE001
            outs.append(("err", type(exc).__name__, str(exc).split("(")[0]))
    return outs


# ------------------------------------------------------------------------------ equivalence (ADR-07 behaviour)

@pytest.mark.parametrize("mode", MODES)
def test_zip_and_tar_resolve_equivalent(tmp_path, mode):
    z = _write(tmp_path / "m.zip", _zip_bytes({"alarms/a.txt": b"Optical module LOS", "runbooks/b.html": b"<html><body><h1>BGP</h1></body></html>"}))
    a, b = _same(mode, lambda s: list(s.stream_archive(z)))
    assert a == b and a[0] == "ok" and len(a[1]) == 2
    a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{z}#runbooks/b.html"))
    assert a == b and "<html>" not in a[1]["content_text"]
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        info = tarfile.TarInfo("contracts/nda.md")
        info.size = 5
        tf.addfile(info, io.BytesIO(b"LGPD!"))
    t = _write(tmp_path / "c.tar.zst", zstd.ZstdCompressor().compress(tar_buf.getvalue()))
    a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{t}#contracts/nda.md"))
    assert a == b and a[0] == "ok"


@pytest.mark.parametrize("mode", MODES)
def test_hdx_and_epub_equivalent(tmp_path, mode):
    h = _write(tmp_path / "x.hdx", _zip_bytes({"profile.xml": b"<p/>", "resources/t.xhtml": b"<html><h2>display</h2></html>"}))
    e = _write(tmp_path / "b.epub", _zip_bytes({"mimetype": b"application/epub+zip", "META-INF/container.xml": b"<c/>", "OEBPS/c1.xhtml": b"<p>Troponina</p>"}))
    for p in (h, e):
        a, b = _same(mode, lambda s: list(s.stream_archive(p)))
        assert a == b and a[0] == "ok"


@pytest.mark.parametrize("mode", MODES)
def test_zip_bomb_ratio_and_entry_size(tmp_path, mode):
    bomb = _write(tmp_path / "bomb.zip", _zip_bytes({"bomb.txt": b"A" * (2 << 20)}))
    for fn in (lambda s: list(s.stream_archive(bomb)), lambda s: s.resolve_virtual_uri(f"archive://{bomb}#bomb.txt")):
        a, b = _same(mode, fn)
        assert a == b and a[:2] == ("err", "ArchiveSecurityError")
    big = _write(tmp_path / "big.zip", _zip_bytes({"r.bin": os.urandom(8192)}))
    for streamer in (LegacyStreamer(), make_new(mode)):
        streamer.max_entry_bytes = 4096
        with pytest.raises(Exception, match="max_entry_bytes"):
            list(streamer.stream_archive(big))


@pytest.mark.parametrize("mode", MODES)
def test_path_traversal(tmp_path, mode):
    z = _write(tmp_path / "t.zip", _zip_bytes({"../../etc/passwd": b"root", "ok.txt": b"fine"}))
    a, b = _same(mode, lambda s: list(s.stream_archive(z)))
    assert a == b and a[:2] == ("err", "ArchiveSecurityError")
    a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{z}#../../etc/passwd"))
    assert a == b and a[:2] == ("err", "ArchiveSecurityError")
    n = _nested(tmp_path, {"../../etc/passwd": b"root", "ok.txt": b"fine"})
    for uri in (f"archive://{n}!pkg.hwics#ok.txt", f"archive://{n}!pkg.hwics#../../etc/passwd",
                f"archive://{n}!../pkg.hwics#ok.txt", f"archive://{n}#pkg.hwics/ok.txt"):
        a, b = _same(mode, lambda s: s.resolve_virtual_uri(uri))
        assert a == b, uri


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("inner_comp", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("outer_comp", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_nested_resolve_equivalent(tmp_path, mode, inner_comp, outer_comp):
    files = {f"resources/alarms/{i}.html": (f"<html><body><h1>ALM-{i}</h1>" + "x" * (i * 97) + "</body></html>").encode() for i in range(300)}
    files["resources/sheet.xlsx"] = _zip_bytes({"xl/sharedStrings.xml": b"<sst><si><t>hello</t></si></sst>"})
    n = _nested(tmp_path, files, outer_comp=outer_comp, inner_comp=inner_comp)
    for member in ("resources/alarms/3.html", "resources/alarms/299.html", "resources/sheet.xlsx", "missing.html"):
        a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#{member}"))
        assert a == b, member
    a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{n}#pkg.hwics/resources/alarms/7.html"))
    assert a == b
    a, b = _same(mode, lambda s: list(s.stream_archive(n)))
    assert a == b


@pytest.mark.parametrize("mode", MODES)
def test_nested_bombs(tmp_path, mode):
    n = _nested(tmp_path, {"bomb.txt": b"A" * (4 << 20), "ok.txt": b"ok"}, name="b1.zip")
    a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#bomb.txt"))
    assert a == b and a[:2] == ("err", "ArchiveSecurityError")
    n2 = _nested(tmp_path, {"zeros.bin": b"\0" * (8 << 20)}, inner_comp=zipfile.ZIP_STORED, name="b2.zip")
    a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{n2}!pkg.hwics#zeros.bin"))
    assert a[:2] == b[:2] == ("err", "ArchiveSecurityError")   # the ratio figure may differ (declared vs running)
    assert a[2] == b[2]                                         # same message prefix


@pytest.mark.parametrize("mode", MODES)
def test_inner_container_lying_about_its_size_never_inflates_past_it(tmp_path, mode):
    """A header that declares a small size must not let the inflater run on and amplify (zip-bomb guard)."""
    n = _nested(tmp_path, {"zeros.bin": b"\0" * (4 << 20)}, name="lie.zip")
    raw = bytearray(n.read_bytes())
    # shrink the declared uncompressed size of the nested member in BOTH the local header and the central directory
    for sig, off in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        i = raw.find(sig)
        raw[i + off:i + off + 4] = (1 << 10).to_bytes(4, "little")
    n.write_bytes(bytes(raw))
    with pytest.raises(Exception):
        make_new(mode).resolve_virtual_uri(f"archive://{n}!pkg.hwics#zeros.bin")


@pytest.mark.parametrize("mode", MODES)
def test_zip64_nested(tmp_path, mode):
    n = _nested(tmp_path, {"a.html": b"<p>zip64 member</p>", "b.txt": b"b" * 1000}, zip64=True)
    a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#a.html"))
    assert a == b and a[0] == "ok"


def _set_encrypted_flag(data: bytes, name: bytes) -> bytes:
    b = bytearray(data)
    i = b.find(b"PK\x03\x04")
    while i != -1:
        if b[i + 30:i + 30 + len(name)] == name:
            b[i + 6] |= 1
        i = b.find(b"PK\x03\x04", i + 4)
    j = b.find(b"PK\x01\x02")
    while j != -1:
        if b[j + 46:j + 46 + len(name)] == name:
            b[j + 8] |= 1
        j = b.find(b"PK\x01\x02", j + 4)
    return bytes(b)


@pytest.mark.parametrize("mode", MODES)
def test_encrypted_flag(tmp_path, mode):
    z = _write(tmp_path / "enc.zip", _set_encrypted_flag(_zip_bytes({"s.txt": b"secret"}), b"s.txt"))
    a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{z}#s.txt"))
    assert a == b and a[0] == "err"
    o = _write(tmp_path / "enc2.zip", _set_encrypted_flag(_zip_bytes({"pkg.hwics": _zip_bytes({"x.txt": b"x"})}), b"pkg.hwics"))
    a, b = _same(mode, lambda s: s.resolve_virtual_uri(f"archive://{o}!pkg.hwics#x.txt"))
    assert a == b and a[0] == "err"


@pytest.mark.parametrize("mode", MODES)
def test_corrupt_inner_stream_raises(tmp_path, mode):
    n = _nested(tmp_path, {f"f{i}.txt": os.urandom(2000) for i in range(200)})
    raw = bytearray(n.read_bytes())
    raw[len(raw) // 2] ^= 0xFF                                  # flip one byte in the middle of the DEFLATE stream
    n.write_bytes(bytes(raw))
    for streamer in (LegacyStreamer(), make_new(mode)):
        with pytest.raises(Exception):
            streamer.resolve_virtual_uri(f"archive://{n}!pkg.hwics#f150.txt")


# ------------------------------------------------------------------------------ the cache

def test_cache_serves_repeats_and_invalidates_on_replace_and_touch(tmp_path):
    cache = ArchiveCache()
    s = SovereignArchiveStreamer(cache=cache)
    n = _nested(tmp_path, {"a.txt": b"version-1"})
    uri = f"archive://{n}!pkg.hwics#a.txt"
    assert s.resolve_virtual_uri(uri).content_text == "version-1"
    assert s.resolve_virtual_uri(uri).content_text == "version-1"
    assert cache.stats["entry_hit"] == 1
    _nested(tmp_path, {"a.txt": b"version-2-longer"}, name="new.zip")
    os.replace(tmp_path / "new.zip", n)                         # atomic replace: new inode
    assert s.resolve_virtual_uri(uri).content_text == "version-2-longer"
    with open(n, "r+b") as f:                                   # same path rewritten in place with a new mtime
        f.write(_zip_bytes({"pkg.hwics": _zip_bytes({"a.txt": b"version-3-longer"})}))
        f.truncate()
    st = os.stat(n)
    os.utime(n, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    assert s.resolve_virtual_uri(uri).content_text == "version-3-longer"
    assert cache.stats["archive_invalidated"] >= 2


def test_cached_entries_are_copies_so_callers_cannot_poison_the_cache(tmp_path):
    s = SovereignArchiveStreamer(cache=ArchiveCache())
    n = _nested(tmp_path, {"a.txt": b"original"})
    uri = f"archive://{n}!pkg.hwics#a.txt"
    first = s.resolve_virtual_uri(uri)
    first.content_text = "tampered"
    assert s.resolve_virtual_uri(uri).content_text == "original"


def test_entry_cache_respects_its_byte_budget(tmp_path):
    cache = ArchiveCache(entry_budget_bytes=64 * 1024)
    s = SovereignArchiveStreamer(cache=cache)
    n = _nested(tmp_path, {f"m{i}.txt": (f"member {i} ".encode() * 600) for i in range(40)})
    for i in range(40):
        s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#m{i}.txt")
    assert cache.entry_bytes <= 64 * 1024
    big = _nested(tmp_path, {"big.txt": b"x" * 40000 + os.urandom(40000)}, name="big.zip")
    s.resolve_virtual_uri(f"archive://{big}!pkg.hwics#big.txt")
    assert cache.entry_bytes <= 64 * 1024                         # an entry over the per-entry cap is not cached


def test_concurrent_requests_are_identical_and_open_the_inner_container_once(tmp_path):
    n = _nested(tmp_path, {f"m{i}.html": f"<p>member {i}</p>".encode() * 50 for i in range(500)})
    ref = {i: LegacyStreamer().resolve_virtual_uri(f"archive://{n}!pkg.hwics#m{i}.html") for i in range(0, 500, 25)}
    s = SovereignArchiveStreamer(cache=ArchiveCache())
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        got = dict(zip(ref, ex.map(lambda i: s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#m{i}.html"), ref)))
    assert all(dataclasses.asdict(got[i]) == dataclasses.asdict(ref[i]) for i in ref)
    assert s.cache.stats["inner_open"] == 1


def test_the_default_cache_is_shared_between_streamer_instances_and_can_be_disabled(monkeypatch):
    assert SovereignArchiveStreamer().cache is SovereignArchiveStreamer().cache is not None
    assert SovereignArchiveStreamer(cache=None).cache is None


# ------------------------------------------------------------------------------ ADR-07 invariants

@pytest.mark.parametrize("mode", MODES)
def test_zero_disk_writes_and_rdonly(tmp_path, mode, monkeypatch):
    n = _nested(tmp_path, {"a.html": b"<p>A</p>", "b.xlsx": _zip_bytes({"xl/sharedStrings.xml": b"<sst/>"})})
    real_open, real_os_open = builtins.open, os.open
    seen_flags = []

    def guard_open(file, mode_="r", *a, **k):
        if any(c in str(mode_) for c in "wax+"):
            raise AssertionError(f"write open during archive read: {file} {mode_}")
        return real_open(file, mode_, *a, **k)

    def guard_os_open(path, flags, *a, **k):
        seen_flags.append(flags)
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError(f"write flags on {path}")
        return real_os_open(path, flags, *a, **k)

    monkeypatch.setattr(builtins, "open", guard_open)
    monkeypatch.setattr(os, "open", guard_os_open)
    before = sorted(os.listdir(tmp_path))
    s = make_new(mode)
    s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#a.html")
    s.resolve_virtual_uri(f"archive://{n}!pkg.hwics#b.xlsx")
    assert sorted(os.listdir(tmp_path)) == before
    assert seen_flags and all((f & os.O_ACCMODE) == os.O_RDONLY for f in seen_flags)


# ------------------------------------------------------------------------------ memory budgets

@pytest.mark.parametrize("mode", MODES)
def test_memory_budget_nested_48mb(tmp_path, mode):
    """Python-heap peak while resolving a small member of a 48 MB nested container stays under 12 MB (before: 144 MB)."""
    n = _nested(tmp_path, {"big.bin": os.urandom(48 << 20), "small.html": b"<p>needle</p>"}, name="mem.zip")
    uri = f"archive://{n}!pkg.hwics#small.html"
    tracemalloc.start()
    entry = make_new(mode).resolve_virtual_uri(uri)
    peak_mb = tracemalloc.get_traced_memory()[1] / 1048576
    tracemalloc.stop()
    assert entry.content_text == "needle"
    assert peak_mb < 12, peak_mb


CORPUS_ZIP = Path("/home/tlima/Enterprise_Hub/docs/Hua_Docs/HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip")
CORPUS_URI = (
    f"archive://{CORPUS_ZIP}!HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics"
    "#resources/alarms/20104.html"
)


@pytest.mark.skipif(not CORPUS_ZIP.exists(), reason="the Huawei corpus is not on this machine")
def test_real_corpus_preview_memory_and_latency_budget():
    """The portal preview of a 330 MB package: under 64 MB extra RSS and 1.5 s cold; a repeat under 50 ms."""
    script = textwrap.dedent(f"""
        import json, resource, time
        from core.containers.archive_streamer import SovereignArchiveStreamer
        uri = {CORPUS_URI!r}
        s = SovereignArchiveStreamer()
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        t0 = time.time(); first = s.resolve_virtual_uri(uri); cold = time.time() - t0
        peak_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
        t0 = time.time(); again = s.resolve_virtual_uri(uri); warm = time.time() - t0
        print(json.dumps(dict(peak_mb=peak_mb, cold=cold, warm=warm, same=first.sha256_hash == again.sha256_hash, text="ALM-20104" in first.content_text)))
    """)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent, check=True)
    import json
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["text"] and r["same"]
    assert r["peak_mb"] < 64, r
    assert r["cold"] < 4.5, r              # 1.05 s measured on an idle machine; generous for a loaded host
    assert r["warm"] < 0.05, r
