"""HTTP seam of the graph viewer: /graph/v2/meta, /graph/v2/slice, /graph/v2/find.

Runs a real server against the hand-drawn vault of graph_fixtures.py (not the production vault),
so every expected value is known in advance."""

import gzip
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest

from core.graph.store import GraphStore
from core.server import SovereignHTTPHandler, create_app
from tests.graph_fixtures import build_vault, build_wiki


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("graph_routes")
    router, graph = build_vault(tmp)
    previous = getattr(SovereignHTTPHandler, "manager", None)
    create_app(
        searcher=MagicMock(),
        graph_store=GraphStore(db_path=graph),
        router_db_path=router,
        wiki_dir=build_wiki(tmp),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), SovereignHTTPHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    SovereignHTTPHandler.manager = previous


def get(url, headers=None):
    """(status, headers, decoded JSON or None) without following errors as exceptions."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            status, hdrs, body = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as err:
        status, hdrs, body = err.code, err.headers, err.read()
    if hdrs.get("Content-Encoding") == "gzip":
        body = gzip.decompress(body)
    return status, hdrs, (json.loads(body) if body else None)


def test_meta_route_reports_layers_within_the_requested_clearance(base_url):
    status, _, meta = get(f"{base_url}/graph/v2/meta?user_clearance=public")
    assert status == 200
    assert [layer["id"] for layer in meta["layers"]] == ["tree", "entity", "wiki"]
    assert meta["layers"][0]["nodes"] == 7  # hand-counted: what a public caller sees of the tree
    assert meta["reserved_edge_kinds"] == ["CAUSED_BY", "NEXT_STEP"]


def test_slice_route_honours_layer_mode_and_clearance(base_url):
    _, _, public = get(f"{base_url}/graph/v2/slice?layer=tree&mode=all&user_clearance=public")
    _, _, internal = get(f"{base_url}/graph/v2/slice?layer=tree&mode=all&user_clearance=internal")
    assert "t:t5" not in public["nodes"]["id"] and "t:t5" in internal["nodes"]["id"]

    _, _, entities = get(f"{base_url}/graph/v2/slice?layer=entity&user_clearance=public")
    assert len(entities["nodes"]["id"]) == 4

    _, _, clustered = get(f"{base_url}/graph/v2/slice?layer=tree&levels=1&user_clearance=public")
    assert set(clustered["nodes"]["id"]) == {"pkg:P1", "pkg:P2", "t:t1", "t:t7"}
    _, _, focused = get(f"{base_url}/graph/v2/slice?layer=tree&focus=t:t1&levels=1&user_clearance=public")
    assert set(focused["nodes"]["id"]) == {"t:t1", "t:t2"}


def test_clearance_defaults_to_restricted_like_every_other_endpoint(base_url):
    _, _, res = get(f"{base_url}/graph/v2/slice?layer=tree&mode=all")
    assert {"t:t8", "t:t9"} <= set(res["nodes"]["id"])


def test_find_route_returns_matches_with_paths(base_url):
    status, _, hits = get(f"{base_url}/graph/v2/find?q=leaf%20a1a&layer=tree&user_clearance=public")
    assert status == 200
    assert [(h["id"], h["path"]) for h in hits] == [("t:t4", ["pkg:P1", "t:t1", "t:t2", "t:t4"])]
    _, _, wiki = get(f"{base_url}/graph/v2/find?q=alpha&layer=wiki&user_clearance=public")
    assert [h["id"] for h in wiki] == ["w:a.md"]


def test_responses_are_compact_gzipped_on_request_and_cacheable_by_etag(base_url):
    url = f"{base_url}/graph/v2/slice?layer=tree&mode=all&user_clearance=restricted"
    plain_status, plain_headers, plain = get(url)
    assert plain_status == 200 and plain_headers.get("Content-Encoding") is None
    raw = urllib.request.urlopen(url).read()
    assert b"\n  " not in raw  # compact JSON, not indented

    status, headers, zipped = get(url, {"Accept-Encoding": "gzip"})
    assert status == 200 and headers.get("Content-Encoding") == "gzip"
    assert zipped == plain

    etag = headers.get("ETag")
    assert etag
    not_modified, _, body = get(url, {"If-None-Match": etag})
    assert not_modified == 304 and body is None


@pytest.mark.parametrize("query, status", [
    ("layer=bogus", 400),
    ("layer=tree&mode=bogus", 400),
    ("layer=tree&user_clearance=bogus", 400),
    ("layer=tree&levels=abc", 400),
    ("layer=tree&focus=t:nope", 404),
    ("layer=tree&focus=t:t3&user_clearance=public", 404),  # hidden looks exactly like missing
])
def test_slice_route_maps_bad_input_to_client_errors(base_url, query, status):
    got, _, body = get(f"{base_url}/graph/v2/slice?{query}")
    assert got == status and "error" in body


def test_find_route_requires_a_query(base_url):
    status, _, body = get(f"{base_url}/graph/v2/find?layer=tree")
    assert status == 400 and "error" in body
