"""Single-user, read-only OAuth 2.0 for the owner's own accounts.

Authorization code flow with PKCE (RFC 7636) and a loopback redirect (RFC 8252),
standard library only.  Rules this module keeps:

* Nothing touches the network unless ``allow_network = true`` and every host is
  in ``allowed_hosts``.  Token and authorization URLs must be https (loopback
  http is accepted so a local self-hosted service or a test server works).
* Tokens live in a file the owner names, created mode 0600.  A token file that
  group or others can read is refused.  Client secrets are never in TOML: only
  the *name* of an environment variable.
* Scopes are explicit and listed; nothing is requested that the owner did not
  write down.  ``logout`` revokes (when the provider offers a revocation URL)
  and deletes the file.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}


class OAuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorize_url: str
    token_url: str
    client_id: str
    scopes: list[str] = Field(min_length=1)
    token_file: Path
    allow_network: bool = False
    allowed_hosts: list[str] = Field(default_factory=list)
    client_secret_env: str | None = None
    revoke_url: str | None = None
    redirect_port: int = 0


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


def check_url(settings: OAuthSettings, url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if not settings.allow_network:
        raise PermissionError("network access is off; set allow_network = true for this provider")
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOOPBACK):
        raise PermissionError(f"{url} must be https (http only for loopback)")
    if parts.hostname not in settings.allowed_hosts:
        raise PermissionError(f"host {parts.hostname} is not in allowed_hosts")


def pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorization_url(settings: OAuthSettings, redirect_uri: str, state: str, challenge: str) -> str:
    check_url(settings, settings.authorize_url)
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": settings.client_id, "redirect_uri": redirect_uri,
        "scope": " ".join(settings.scopes), "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    return f"{settings.authorize_url}{'&' if '?' in settings.authorize_url else '?'}{query}"


def _post(settings: OAuthSettings, url: str, fields: dict[str, str]) -> dict:
    check_url(settings, url)
    if settings.client_secret_env:
        secret = os.environ.get(settings.client_secret_env)
        if not secret:
            raise PermissionError(f"environment variable {settings.client_secret_env} is not set")
        fields = {**fields, "client_secret": secret}
    request = urllib.request.Request(url, urllib.parse.urlencode(fields).encode(), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read(1_000_000) or b"{}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{_host(url)} answered HTTP {exc.code}") from None


def save_token(path: Path, token: dict) -> None:
    token = {**token, "obtained_at": int(time.time())}
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(token, out)
    os.chmod(path, 0o600)


def load_token(path: Path) -> dict:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise PermissionError(f"{path} is readable by others (mode {mode:o}); run: chmod 600")
    return json.loads(path.read_text(encoding="utf-8"))


def exchange_code(settings: OAuthSettings, code: str, verifier: str, redirect_uri: str) -> dict:
    return _post(settings, settings.token_url, {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": settings.client_id, "code_verifier": verifier})


def access_token(settings: OAuthSettings) -> str:
    """A valid access token, refreshing it when it expires within a minute."""
    token = load_token(settings.token_file)
    expires = token.get("obtained_at", 0) + int(token.get("expires_in", 0) or 0)
    if token.get("expires_in") and time.time() > expires - 60:
        if not token.get("refresh_token"):
            raise PermissionError("token expired and no refresh token; run dossify login again")
        fresh = _post(settings, settings.token_url, {
            "grant_type": "refresh_token", "refresh_token": token["refresh_token"],
            "client_id": settings.client_id})
        fresh.setdefault("refresh_token", token["refresh_token"])
        save_token(settings.token_file, fresh)
        token = fresh
    return token["access_token"]


class _Catcher(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802 (stdlib hook name)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        type(self).result = {k: v[0] for k, v in query.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Dossify received the authorization. You can close this tab.")

    def log_message(self, *args):
        pass


def login(settings: OAuthSettings, announce=print, timeout: int = 300) -> None:
    """Run the loopback flow and store the token.  Prints the URL; the owner opens it."""
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    _Catcher.result = {}
    server = http.server.HTTPServer(("127.0.0.1", settings.redirect_port), _Catcher)
    redirect = f"http://127.0.0.1:{server.server_port}/callback"
    announce("Open this URL in your browser and approve read-only access:\n" +
             authorization_url(settings, redirect, state, challenge))
    server.timeout = timeout
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    thread.join(timeout + 1)
    server.server_close()
    got = _Catcher.result
    if got.get("state") != state:
        raise PermissionError("no valid authorization response (state mismatch or timeout)")
    if "error" in got:
        raise PermissionError(f"provider refused: {got['error']}")
    save_token(settings.token_file, exchange_code(settings, got["code"], verifier, redirect))


def logout(settings: OAuthSettings) -> str:
    """Revoke at the provider when possible, then delete the local token."""
    outcome = "deleted the local token"
    if settings.token_file.exists():
        if settings.revoke_url:
            token = load_token(settings.token_file)
            _post(settings, settings.revoke_url, {"token": token.get("refresh_token") or token["access_token"],
                                                  "client_id": settings.client_id})
            outcome = "revoked at the provider and deleted the local token"
        settings.token_file.unlink()
    else:
        outcome = "no token file to delete"
    return outcome
