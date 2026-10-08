"""Tests for Ego Subgraph and Portal v3 UX enhancements."""

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
from core.graphview import GraphService
from core.server import SovereignHTTPHandler, create_app
from tests.graph_fixtures import build_vault, build_wiki


@pytest.fixture(scope="module")
def app_server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ego_test")
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


def http_get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            status, hdrs, body = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as err:
        status, hdrs, body = err.code, err.headers, err.read()
    if hdrs.get("Content-Encoding") == "gzip":
        body = gzip.decompress(body)
    return status, hdrs, (json.loads(body) if body else None)


def test_ego_subgraph_service(tmp_path):
    router, graph = build_vault(tmp_path)
    svc = GraphService(router, graph, wiki_dir=build_wiki(tmp_path))

    # Test wiki note ego subgraph
    res = svc.ego_subgraph("a.md", clearance="restricted", depth=1, limit=30)
    assert res["center"]["id"] == "w:a.md"
    node_ids = {n["id"] for n in res["nodes"]}
    assert "w:a.md" in node_ids
    assert len(res["nodes"]) >= 2
    assert len(res["edges"]) >= 1

    # Test entity ego subgraph
    res_entity = svc.ego_subgraph("ALM-1", clearance="restricted", depth=1)
    e_ids = {n["id"] for n in res_entity["nodes"]}
    assert "e:telecom_alarm:ALM-1" in e_ids


def test_ego_route_http(app_server):
    status, _, data = http_get(f"{app_server}/graph/ego?target=a.md&user_clearance=restricted")
    assert status == 200
    assert data["center"]["id"] == "w:a.md"
    assert len(data["nodes"]) > 0

    # Test missing target returns 400
    status_bad, _, _ = http_get(f"{app_server}/graph/ego")
    assert status_bad == 400


def test_wiki_redirect_handler(app_server):
    # Tests that /docs/wiki/adrs/ADR-1.md redirects to /archive/view?uri=...
    req = urllib.request.Request(f"{app_server}/docs/wiki/adrs/ADR-1.md")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(req)
        code = resp.status
        loc = resp.headers.get("Location")
    except urllib.error.HTTPError as err:
        code = err.code
        loc = err.headers.get("Location")

    assert code == 302
    assert loc and "/archive/view?uri=" in loc

