"""Security hardening: Host/Origin checks, token, body limits, SSRF guard, headers.

Most of these talk to a real server over a socket, because what is being tested
is exactly what a browser (or an attacker's page) would send.
"""

from __future__ import annotations

import http.client
import http.server
import json
import os
import socket
import stat
import threading

import pytest

from setm.api.routes import Request, dispatch
from setm.api.security import SECURITY_HEADERS, check_remote_target, host_allowed, origin_allowed
from setm.config import Settings
from setm.errors import ConfigError, StorageError
from setm.kpi.telemetry import Telemetry
from setm.storage import memory
from setm.workspace import Workspace


# --------------------------------------------------------------------------- #
# A live server
# --------------------------------------------------------------------------- #


@pytest.fixture
def live(request):
    from setm.api.server import serve

    name = f"sec-{request.node.name}"
    memory.reset(name)
    settings = Settings(storage=f"memory:{name}", host="127.0.0.1", port=0)
    for key, value in getattr(request, "param", {}).items():
        setattr(settings, key, value)
    workspace = Workspace.open(settings)
    server = serve(workspace, settings, block=False)
    port = server.server_address[1]
    yield {"port": port, "workspace": workspace, "settings": settings}
    server.shutdown()
    server.server_close()
    memory.reset(name)


def send(port, method, path, *, body=None, headers=None, host=None):
    """One request with full control over Host and the other headers."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    connection.putheader("Host", host if host is not None else f"127.0.0.1:{port}")
    data = json.dumps(body).encode() if body is not None else b""
    if body is not None:
        connection.putheader("Content-Type", "application/json")
    connection.putheader("Content-Length", str(len(data)))
    for key, value in (headers or {}).items():
        connection.putheader(key, value)
    connection.endheaders(data)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        payload = raw.decode("utf-8", "replace")
    return response.status, dict(response.getheaders()), payload


def raw_request(port, text: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(text)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


NEW_PERSON = {"type": "Person", "properties": {"name": "Probe"}}


def people(workspace):
    return [n.label for n in workspace.store.nodes_of_type("Person")]


# --------------------------------------------------------------------------- #
# DNS rebinding: the Host header
# --------------------------------------------------------------------------- #


def test_foreign_host_name_is_refused(live):
    status, _, body = send(live["port"], "GET", "/api/health", host="evil.example.com")
    assert status == 421
    assert body["error"]["code"] == "host_not_allowed"


def test_foreign_host_cannot_fetch_the_interface_either(live):
    status, _, _ = send(live["port"], "GET", "/", host="rebound.evil.example:8765")
    assert status == 421


@pytest.mark.parametrize("host", ["127.0.0.1:{port}", "localhost:{port}", "[::1]:{port}", "10.1.2.3"])
def test_loopback_names_and_ip_literals_are_accepted(live, host):
    status, _, _ = send(live["port"], "GET", "/api/health", host=host.format(port=live["port"]))
    assert status == 200


@pytest.mark.parametrize("live", [{"allowed_hosts": ["setm.engineering.internal"]}], indirect=True)
def test_allowed_hosts_setting_admits_a_named_host(live):
    status, _, _ = send(live["port"], "GET", "/api/health", host="setm.engineering.internal:8765")
    assert status == 200


def test_host_rules_unit():
    settings = Settings(host="0.0.0.0")
    assert host_allowed("", settings)  # HTTP/1.0, no Host at all
    assert host_allowed("app.localhost:8765", settings)
    assert not host_allowed("attacker.example", settings)
    assert host_allowed("attacker.example", Settings(allowed_hosts=["*"]))
    assert host_allowed("setm.lab", Settings(host="setm.lab"))


# --------------------------------------------------------------------------- #
# CSRF: the Origin header
# --------------------------------------------------------------------------- #


def test_cross_origin_write_is_refused_and_changes_nothing(live):
    """The exact attack found in the audit: it used to return 201."""
    status, _, body = send(
        live["port"], "POST", "/api/nodes", body=NEW_PERSON, headers={"Origin": "https://evil.example.com"}
    )
    assert status == 403
    assert body["error"]["code"] == "cross_origin_refused"
    assert people(live["workspace"]) == []


@pytest.mark.parametrize("method,path", [("DELETE", "/api/nodes/x"), ("PATCH", "/api/settings"), ("POST", "/api/import")])
def test_every_unsafe_method_is_guarded(live, method, path):
    status, _, _ = send(live["port"], method, path, body={}, headers={"Origin": "https://evil.example.com"})
    assert status == 403


def test_same_origin_write_from_the_interface_works(live):
    port = live["port"]
    status, _, _ = send(port, "POST", "/api/nodes", body=NEW_PERSON, headers={"Origin": f"http://127.0.0.1:{port}"})
    assert status == 201
    assert people(live["workspace"]) == ["Probe"]


def test_non_browser_client_without_origin_still_works(live):
    status, _, _ = send(live["port"], "POST", "/api/nodes", body=NEW_PERSON)
    assert status == 201


def test_cross_site_fetch_metadata_without_origin_is_refused(live):
    status, _, _ = send(live["port"], "POST", "/api/nodes", body=NEW_PERSON, headers={"Sec-Fetch-Site": "cross-site"})
    assert status == 403


def test_null_origin_is_refused(live):
    status, _, _ = send(live["port"], "POST", "/api/nodes", body=NEW_PERSON, headers={"Origin": "null"})
    assert status == 403


def test_reads_are_not_blocked_by_origin(live):
    status, _, _ = send(live["port"], "GET", "/api/health", headers={"Origin": "https://evil.example.com"})
    assert status == 200  # the browser, not the server, withholds the answer (no CORS header)


@pytest.mark.parametrize("live", [{"allowed_origins": ["https://portal.example"]}], indirect=True)
def test_allowed_origins_setting_admits_a_partner_site(live):
    status, _, _ = send(live["port"], "POST", "/api/nodes", body=NEW_PERSON, headers={"Origin": "https://portal.example"})
    assert status == 201


def test_origin_rules_unit():
    settings = Settings()
    assert origin_allowed({"origin": "http://127.0.0.1:8765", "host": "127.0.0.1:8765"}, settings)
    assert not origin_allowed({"origin": "http://127.0.0.1:9999", "host": "127.0.0.1:8765"}, settings)
    assert origin_allowed({"sec-fetch-site": "same-origin"}, settings)
    assert not origin_allowed({"sec-fetch-site": "same-site"}, settings)


# --------------------------------------------------------------------------- #
# Token
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("live", [{"api_token": "s3cret-token"}], indirect=True)
def test_token_is_required_in_the_header_only(live):
    port = live["port"]
    assert send(port, "GET", "/api/health")[0] == 401
    assert send(port, "GET", "/api/health", headers={"X-SETM-Token": "wrong"})[0] == 401
    assert send(port, "GET", "/api/health?token=s3cret-token")[0] == 401  # never in the URL
    assert send(port, "GET", "/api/health", headers={"X-SETM-Token": "s3cret-token"})[0] == 200


@pytest.mark.parametrize("live", [{"api_token": "s3cret-token"}], indirect=True)
def test_metrics_are_behind_the_token(live):
    assert send(live["port"], "GET", "/metrics")[0] == 401


# --------------------------------------------------------------------------- #
# Bodies, errors and headers
# --------------------------------------------------------------------------- #


def test_garbage_content_length_gets_a_clean_400(live):
    port = live["port"]
    reply = raw_request(
        port,
        f"POST /api/nodes HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: abc\r\n\r\n".encode(),
    )
    assert reply.startswith(b"HTTP/1.1 400")
    assert send(port, "GET", "/api/health")[0] == 200  # and the server carries on


def test_oversize_body_is_refused_before_it_is_read(live):
    port = live["port"]
    reply = raw_request(
        port,
        f"POST /api/import HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: {1 << 30}\r\n\r\n".encode(),
    )
    assert reply.startswith(b"HTTP/1.1 413")


@pytest.mark.parametrize("path", ["/", "/app.js", "/api/health", "/api/nope"])
def test_security_headers_on_every_response(live, path):
    _, headers, _ = send(live["port"], "GET", path)
    for name, value in SECURITY_HEADERS.items():
        assert headers.get(name) == value, name


def test_csp_forbids_inline_and_foreign_scripts():
    csp = SECURITY_HEADERS["Content-Security-Policy"]
    assert "script-src 'self';" in csp
    assert "frame-ancestors 'none'" in csp


def test_internal_errors_do_not_leak_details(workspace, monkeypatch):
    import setm.api.routes as routes

    def boom(*_args, **_kwargs):
        raise RuntimeError("/srv/secret/path/config.toml exploded")

    monkeypatch.setattr(routes, "compute_kpis", boom)
    response = dispatch(workspace, Request(method="GET", path="/api/kpi"))
    assert response.status == 500
    assert "secret" not in json.dumps(response.body)


# --------------------------------------------------------------------------- #
# SSRF: where the settings page may point a remote backend
# --------------------------------------------------------------------------- #


@pytest.fixture
def listener():
    """A local HTTP server standing in for an internal service."""
    hits: list[tuple[str, dict[str, str]]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append((self.path, dict(self.headers)))
            if self.path.startswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_address[1]}/landed")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = json.dumps({"nodes": [], "edges": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{server.server_address[1]}", "hits": hits}
    server.shutdown()
    server.server_close()


def call(workspace, method, path, body=None):
    return dispatch(workspace, Request(method=method, path=path, body=body, headers={}))


def test_probe_of_an_internal_address_is_refused(workspace, listener):
    """The audit's SSRF: the server used to fetch the URL and forward an injected header."""
    response = call(
        workspace,
        "POST",
        "/api/settings/test-storage",
        {"storage": f"{listener['url']}/internal/metadata", "storage_options": {"header": "X-Exfil: probe"}},
    )
    assert response.body["ok"] is False
    assert "internal address" in response.body["error"]["message"]
    assert listener["hits"] == []  # nothing left the server


def test_listed_internal_host_may_be_probed(workspace, listener):
    workspace.settings.remote_storage_hosts = ["127.0.0.1"]
    response = call(workspace, "POST", "/api/settings/test-storage", {"storage": f"{listener['url']}/graph"})
    assert response.body["ok"] is True
    assert listener["hits"][0][0] == "/graph"


def test_metadata_endpoint_is_refused(workspace):
    response = call(workspace, "POST", "/api/settings/test-storage", {"storage": "http://169.254.169.254/latest/meta-data/"})
    assert response.body["ok"] is False
    assert "metadata" in response.body["error"]["message"]


def test_patching_storage_to_an_internal_url_is_refused_and_changes_nothing(workspace):
    before = workspace.settings.storage
    response = call(workspace, "PATCH", "/api/settings", {"values": {"storage": "http://localhost:9/graph"}})
    assert response.status == 400
    assert workspace.settings.storage == before


def test_environment_token_is_not_sent_to_a_host_chosen_over_the_api(monkeypatch):
    monkeypatch.setenv("SETM_GITLAB_TOKEN", "glpat-operator")
    monkeypatch.delenv("SETM_GITLAB_HOST", raising=False)
    with pytest.raises(ConfigError, match="SETM_GITLAB_TOKEN"):
        check_remote_target("gitlab:group/project", {"host": "https://collector.invalid"}, Settings())
    # Its own host is fine, and so is a token the caller typed in themselves.
    check_remote_target("gitlab:group/project", {}, Settings())
    check_remote_target("gitlab:group/project", {"host": "https://collector.invalid", "token": "mine"}, Settings())


def test_http_environment_token_is_bound_to_its_configured_host(monkeypatch):
    monkeypatch.setenv("SETM_HTTP_TOKEN", "operator-secret")
    monkeypatch.setenv("SETM_STORAGE", "https://plm.invalid/api/graph")
    check_remote_target("https://plm.invalid/api/graph", {}, Settings())
    with pytest.raises(ConfigError, match="SETM_HTTP_TOKEN"):
        check_remote_target("https://collector.invalid/x", {}, Settings())


def test_command_line_storage_is_not_restricted(listener):
    """The guard is for the web API; an operator's own configuration is trusted."""
    from setm.storage.registry import open_storage

    backend = open_storage(f"{listener['url']}/graph")
    assert backend.load().nodes == []


def test_credentialed_backend_refuses_to_follow_redirects(listener):
    from setm.storage.registry import open_storage

    backend = open_storage(f"{listener['url']}/redirect", token="secret")
    with pytest.raises(StorageError, match="302"):
        backend.load()
    assert [path for path, _ in listener["hits"]] == ["/redirect"]  # never reached /landed


# --------------------------------------------------------------------------- #
# Secrets at rest, metrics output
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_settings_file_with_secrets_is_owner_only(tmp_path):
    settings = Settings(api_token="hunter2")
    path = settings.save_file(tmp_path / "setm.toml", include_secrets=True)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "hunter2" in path.read_text()


def test_prometheus_label_values_are_escaped():
    telemetry = Telemetry()
    telemetry.increment("graph.nodes_created", type='Evil"}\nsetm_fake 1')
    text = telemetry.prometheus()
    assert "\nsetm_fake 1" not in text
    assert 'type="Evil\\"}\\nsetm_fake 1"' in text
