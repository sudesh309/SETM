"""Request-level security, in one place for both servers.

SETM is a local web application: by default it listens on 127.0.0.1 and every
page it serves can change the graph. That makes two browser attacks the ones
that matter, and neither needs the attacker to reach the machine directly:

* **Cross-site request forgery.** Any page the user has open can ``fetch()``
  ``http://127.0.0.1:8765/api/nodes`` with a POST. The browser will not let it
  read the answer, but the write has already happened. :func:`check_origin`
  refuses state-changing requests whose ``Origin`` is not this server.
* **DNS rebinding.** A page on ``evil.example`` re-points its own name at
  127.0.0.1, after which the browser treats the SETM API as same-origin and
  lets it read everything. The one thing the attacker cannot change is the
  ``Host`` header, which still says ``evil.example``: :func:`check_host`
  refuses names it does not recognise.

The rest -- the token check, response headers, body limits and the guard on
where a remote storage backend may point -- lives here too, so the stdlib
server (:mod:`setm.api.server`) and the ASGI adapter (:mod:`setm.api.asgi`)
cannot drift apart.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import socket
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import urlsplit

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Settings
    from .routes import Request, Response

#: Largest request body accepted. A full project export of tens of thousands of
#: elements is a few megabytes; anything near this is a mistake or an attack.
MAX_BODY_BYTES = 16 * 1024 * 1024

#: Methods that change state and so must come from this server's own pages.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Sent with every response. ``style-src 'unsafe-inline'`` is needed because the
#: interface sets element styles from script and single-element reports carry
#: their stylesheet inline; scripts, by contrast, only ever load from this origin.
SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


def _deny(status: int, code: str, message: str) -> "Response":
    from .routes import Response

    return Response(status=status, body={"error": {"code": code, "message": message}})


# --------------------------------------------------------------------------- #
# Host: DNS rebinding
# --------------------------------------------------------------------------- #


def _split_host(value: str) -> str:
    """``Host`` header value -> bare lower-case host name, without the port."""
    value = (value or "").strip().lower()
    if value.startswith("["):  # [::1]:8765
        return value[1 : value.find("]")] if "]" in value else value[1:]
    if value.count(":") == 1:  # name:port or 1.2.3.4:port
        return value.split(":", 1)[0]
    return value  # bare name, or a bare IPv6 literal


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


@lru_cache(maxsize=1)
def _machine_names() -> frozenset[str]:
    names = set()
    try:
        names.add(socket.gethostname().lower())
        names.add(socket.getfqdn().lower())
    except OSError:  # pragma: no cover - no resolver at all
        pass
    return frozenset(n for n in names if n)


def host_allowed(host_header: str, settings: "Settings") -> bool:
    """Is this a name the server legitimately answers to?

    An IP literal is always accepted: rebinding works by pointing a *name* at
    this machine, so a request addressed to a bare address cannot be one.
    """
    host = _split_host(host_header)
    if not host:
        return True  # HTTP/1.0 client with no Host header: not a browser
    if _is_ip_literal(host) or host in _LOOPBACK_NAMES or host.endswith(".localhost"):
        return True
    allowed = {h.strip().lower() for h in settings.allowed_hosts if h.strip()}
    if "*" in allowed:
        return True
    configured = (settings.host or "").strip().lower()
    if configured and configured not in ("0.0.0.0", "::"):
        allowed.add(configured)
    return host in allowed or host in _machine_names()


def check_host(request: "Request", settings: "Settings") -> "Response | None":
    if host_allowed(request.headers.get("host", ""), settings):
        return None
    return _deny(
        421,
        "host_not_allowed",
        "This server does not answer to that host name. If it is legitimately reached "
        "under another name, add it to the 'allowed_hosts' setting.",
    )


# --------------------------------------------------------------------------- #
# Origin: cross-site request forgery
# --------------------------------------------------------------------------- #


def _origin_host(origin: str) -> str:
    split = urlsplit(origin)
    return (split.netloc or "").lower()


def origin_allowed(headers: Mapping[str, str], settings: "Settings") -> bool:
    """Did a state-changing request come from this server's own pages?

    Browsers attach ``Origin`` to every cross-origin POST/PATCH/DELETE, and
    ``Sec-Fetch-Site`` to every request at all, so a request carrying neither
    is from a non-browser client -- curl, a script, the test-suite -- which a
    web page cannot impersonate.
    """
    origin = headers.get("origin", "")
    if origin:
        if origin == "null":  # sandboxed frame, file:// page, opaque redirect
            return False
        allowed = {o.strip().rstrip("/").lower() for o in settings.allowed_origins if o.strip()}
        if origin.rstrip("/").lower() in allowed:
            return True
        return _origin_host(origin) == (headers.get("host", "") or "").lower()
    fetch_site = headers.get("sec-fetch-site", "")
    return fetch_site in ("", "same-origin", "none")


def check_origin(request: "Request", settings: "Settings") -> "Response | None":
    if request.method.upper() not in UNSAFE_METHODS or origin_allowed(request.headers, settings):
        return None
    return _deny(
        403,
        "cross_origin_refused",
        "Changes are only accepted from SETM's own pages. If another site is meant to "
        "call this API, add its origin to the 'allowed_origins' setting.",
    )


# --------------------------------------------------------------------------- #
# Token
# --------------------------------------------------------------------------- #


def require_token(request: "Request", expected: str) -> "Response | None":
    """Enforce the shared API token, when one is configured.

    Only the ``X-SETM-Token`` header is read. A token in the query string ends
    up in server logs, browser history and shell history; the interface sends
    the header on every call, downloads included.
    """
    if not expected:
        return None
    supplied = request.headers.get("x-setm-token", "")
    if not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        return _deny(401, "unauthorised", "Missing or wrong API token")
    return None


def guard(request: "Request", settings: "Settings") -> "Response | None":
    """Every check an API request must pass, cheapest first."""
    return (
        check_host(request, settings)
        or check_origin(request, settings)
        or require_token(request, settings.api_token)
    )


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #


class BodyError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message

    def response(self) -> "Response":
        return _deny(self.status, "bad_request" if self.status == 400 else "payload_too_large", self.message)


def content_length(raw: str | None) -> int:
    """Parse ``Content-Length`` strictly; a malformed one is the client's error."""
    if raw is None or raw.strip() == "":
        return 0
    try:
        length = int(raw.strip())
    except ValueError:
        raise BodyError(400, "Content-Length must be a whole number") from None
    if length < 0:
        raise BodyError(400, "Content-Length cannot be negative")
    if length > MAX_BODY_BYTES:
        raise BodyError(413, f"Request body exceeds {MAX_BODY_BYTES // (1024 * 1024)} MB")
    return length


# --------------------------------------------------------------------------- #
# Remote storage targets: server-side request forgery
# --------------------------------------------------------------------------- #

#: Addresses no storage backend has a reason to reach from a browser-issued
#: request, whatever the allow-list says: cloud instance-metadata services.
_METADATA_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fd00:ec2::/32"),
)


def remote_host_of(uri: str, options: Mapping[str, Any]) -> str:
    """The host a storage target would make the server connect to, if any."""
    from ..errors import ConfigError
    from ..storage.registry import parse_uri

    try:
        scheme, target, uri_options = parse_uri(uri)
    except ConfigError:
        return ""  # not a remote target; opening it will report the real problem
    merged = {**uri_options, **{k: v for k, v in options.items() if v not in (None, "")}}
    if scheme in ("http", "https"):
        return (urlsplit(target).hostname or "").lower()
    if scheme == "gitlab":
        host = str(merged.get("host") or os.environ.get("SETM_GITLAB_HOST") or "https://gitlab.com")
        return (urlsplit(host if "://" in host else f"https://{host}").hostname or "").lower()
    return ""


def _resolved_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    if _is_ip_literal(host):
        return [ipaddress.ip_address(host)]
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []  # unresolvable: the backend will fail on its own, with a clearer message
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0].split("%", 1)[0]))
        except ValueError:  # pragma: no cover
            continue
    return out


def check_remote_target(uri: str, options: Mapping[str, Any], settings: "Settings") -> None:
    """Refuse a storage target, chosen over the API, that points somewhere internal.

    Storage chosen on the command line, in the environment or in ``setm.toml`` is
    the operator's own decision and is never checked. Storage chosen through the
    settings page arrives as an HTTP request, so it could have been forged, and
    the backend would then make SETM itself connect to a place of the caller's
    choosing -- an internal service, or a cloud metadata endpoint -- with SETM's
    credentials attached. Public hosts are allowed; anything on a private,
    loopback or link-local address must be named in ``remote_storage_hosts``.
    """
    from ..errors import ConfigError

    host = remote_host_of(uri, options)
    if not host:
        return
    listed = {h.strip().lower() for h in settings.remote_storage_hosts if h.strip()}
    addresses = _resolved_addresses(host)
    if any(any(a in net for net in _METADATA_NETWORKS) for a in addresses):
        if host not in listed:
            raise ConfigError(f"Refusing to use '{host}' as storage: it is a link-local / metadata address.")
    if host in listed or "*" in listed:
        return
    internal = host in _LOOPBACK_NAMES or any(
        a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_unspecified
        for a in addresses
    )
    if internal:
        raise ConfigError(
            f"Refusing to point storage at '{host}' from the web interface: it is an internal "
            "address. Add it to the 'remote_storage_hosts' setting (or configure the storage on "
            "the command line or in setm.toml) if this is intended."
        )
    leaked = _environment_credential_for(uri, options, host)
    if leaked:
        raise ConfigError(
            f"Refusing to send the {leaked} credential from this server's environment to "
            f"'{host}', which it was not configured for. Enter a token for that host "
            "explicitly, or add the host to 'remote_storage_hosts'."
        )


def _environment_credential_for(uri: str, options: Mapping[str, Any], host: str) -> str:
    """Name of an environment credential the backend would send to ``host`` unasked.

    The backends fall back to ``SETM_GITLAB_TOKEN`` / ``SETM_HTTP_TOKEN`` when no
    token is given. That is right for the host the operator set them up for,
    and a leak for any other: a changed target would carry the operator's token
    to a server of the caller's choosing.
    """
    from ..errors import ConfigError
    from ..storage.registry import parse_uri

    try:
        scheme, _, uri_options = parse_uri(uri)
    except ConfigError:
        return ""
    if options.get("token") or uri_options.get("token"):
        return ""  # an explicit token is the caller's own
    if scheme == "gitlab":
        name = next((v for v in ("SETM_GITLAB_TOKEN", "GITLAB_TOKEN") if os.environ.get(v)), "")
        home = os.environ.get("SETM_GITLAB_HOST") or "https://gitlab.com"
        home_host = (urlsplit(home if "://" in home else f"https://{home}").hostname or "").lower()
        return name if name and host != home_host else ""
    if scheme in ("http", "https") and os.environ.get("SETM_HTTP_TOKEN"):
        configured = os.environ.get("SETM_STORAGE", "")
        home_host = (urlsplit(configured).hostname or "").lower() if "://" in configured else ""
        return "SETM_HTTP_TOKEN" if host != home_host else ""
    return ""


__all__ = [
    "MAX_BODY_BYTES",
    "SECURITY_HEADERS",
    "BodyError",
    "check_host",
    "check_origin",
    "check_remote_target",
    "content_length",
    "guard",
    "host_allowed",
    "origin_allowed",
    "require_token",
]
