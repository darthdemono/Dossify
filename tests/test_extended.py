import http.server
import json
import stat
import threading
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pytest

from dossify import checkpoints, conformance, external, formats, identity_claims, oauth, review
from dossify.adapter_api import Fact
from dossify.builtin_adapters import P0_ADAPTERS
from dossify.config import load_config
from dossify.http_adapter import HttpJsonAdapter
from dossify.journal import Fact as LegacyFact
from dossify.legacy_adapters import from_typed, to_typed
from dossify.people import Person
from dossify.pipeline import build_plan, execute_plan

FIXTURES = Path(__file__).parent / "fixtures"


def serve(handler_body, status=200, headers=None):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(status)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(handler_body).encode())

        do_POST = do_GET  # noqa: N815

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---- legacy wrapper round trip --------------------------------------------

def test_legacy_fact_round_trips_exactly_including_midnight_dates() -> None:
    for fact in (LegacyFact("2026-01-01", "23:59", "late", "git"), LegacyFact("2026-07-01", None, "day", "bank_statements"),
                 LegacyFact("2026-01-01", "00:00", "midnight", "claude")):
        assert from_typed(to_typed(fact), LegacyFact) == fact


# ---- identity claims and review tasks -------------------------------------

def test_shared_identifier_is_a_contradiction_only_when_periods_overlap() -> None:
    a = Person(instagram_usernames=["same"])
    b = Person(instagram_usernames=["SAME"])
    found = identity_claims.contradictions(identity_claims.collect({"A": a, "B": b}))
    assert found and "claimed by A, B" in found[0]
    past = Person.model_validate({"identity_claims": [{"provider": "instagram_handle", "identifier": "same",
                                                       "valid_to": "2020-01-01"}]})
    later = Person.model_validate({"identity_claims": [{"provider": "instagram_handle", "identifier": "same",
                                                        "valid_from": "2021-01-01"}]})
    claims = identity_claims.collect({"Old": past, "New": later})
    assert identity_claims.contradictions(claims) == []
    assert identity_claims.resolve_at(claims, "instagram_handle", "same", date(2019, 5, 1)) == "Old"
    assert identity_claims.resolve_at(claims, "instagram_handle", "same", date(2022, 5, 1)) == "New"
    assert identity_claims.resolve_at(claims, "instagram_handle", "nobody", date(2022, 5, 1)) is None


def test_review_tasks_flag_future_records_and_disagreeing_steps() -> None:
    def step(provider, n):
        return Fact(provider_id=provider, adapter_id=provider, source_locator="x",
                    observed_at="2026-10-01T00:00:00+00:00", event_type="health.steps", values={"steps": n})

    found = review.tasks([LegacyFact("2099-01-01", None, "x", "git")], [step("a", 100), step("b", 120)], [],
                         today=date(2026, 10, 7))
    kinds = {t.kind for t in found}
    assert kinds == {"future_dated", "steps_disagree"}
    assert any("never added together" in t.detail for t in found)
    assert review.tasks([], [step("a", 100), step("b", 100)], []) == []


# ---- conformance and external discovery -----------------------------------

class GoodAdapter(P0_ADAPTERS["activitywatch"].__class__):
    pass


def test_builtin_adapters_conform(tmp_path: Path) -> None:
    for name, fixture in (("activitywatch", "activitywatch-export.json"), ("health_archive", "health-steps.csv")):
        adapter = P0_ADAPTERS[name]
        assert conformance.check(adapter, adapter.config_model(source=FIXTURES / fixture), tmp_path) == []


def test_conformance_catches_a_lying_adapter(tmp_path: Path) -> None:
    class Liar(type(P0_ADAPTERS["health_archive"])):
        def execute(self, config, plan, fingerprints):
            result = super().execute(config, plan, fingerprints)
            fact = result.facts[0].model_copy(update={"provider_id": "someone_else"})
            return result.model_copy(update={"facts": (fact, *result.facts[1:])})

    adapter = Liar()
    failures = conformance.check(adapter, adapter.config_model(source=FIXTURES / "health-steps.csv"))
    assert any("different provider" in f for f in failures)


def test_installed_plugins_load_only_when_a_provider_block_asks_for_them(monkeypatch) -> None:
    class FakeEntry:
        name, value = "extra", "pkg:ADAPTER"

        def load(self):
            return P0_ADAPTERS["health_archive"].__class__

    monkeypatch.setattr(external, "available", lambda: {"extra": FakeEntry()})
    with pytest.raises(ValueError, match="declares provider_id"):
        external.load(["extra"])
    with pytest.raises(ValueError, match="collides"):
        external.load(["git"])
    with pytest.raises(ValueError, match="not installed"):
        external.load(["ghost"])
    assert external.load([]) == {}

    class Config:
        def __init__(self, providers):
            self.providers = providers

    assert external.load_configured(Config({})) == {}            # installed but not switched on
    with pytest.raises(ValueError, match="declares provider_id"):
        external.load_configured(Config({"extra": {}}))             # the block is the opt-in
    assert external.load_configured(Config({"extra": {"enabled": False}})) == {}


# ---- formats and checkpoints ----------------------------------------------

def test_format_detection_names_known_exports_and_rejects_others(tmp_path: Path) -> None:
    assert formats.detect("health_archive", FIXTURES / "health-steps.csv") == "steps-csv"
    junk = tmp_path / "x.csv"
    junk.write_text("nothing,useful\n")
    assert formats.detect("health_archive", junk) is None
    adapter = P0_ADAPTERS["health_archive"]
    result = execute_plan(adapter, adapter.config_model(source=junk), build_plan(adapter, adapter.config_model(source=junk)))
    assert any("unrecognised export format" in w for w in result.warnings)


def test_checkpoint_resume_emits_only_the_overlap_window(tmp_path: Path) -> None:
    adapter = P0_ADAPTERS["health_archive"]
    export = tmp_path / "steps.csv"
    export.write_text("Date,Steps\n2026-01-01,100\n2026-01-02,200\n2026-01-03,300\n")
    config = adapter.config_model(source=export)
    result = execute_plan(adapter, config, build_plan(adapter, config))
    assert checkpoints.state(checkpoints.load(tmp_path, "health_archive"), result) == "first_run"
    checkpoints.save(tmp_path, result)
    previous = checkpoints.load(tmp_path, "health_archive")
    assert checkpoints.state(previous, result) == "unchanged"
    narrowed = checkpoints.since(result, previous, overlap_days=1)
    assert {f.observed_at.date().isoformat() for f in narrowed.facts} == {"2026-01-02", "2026-01-03"}
    previous["inputs"] = {"somewhere": "0" * 64}
    assert checkpoints.state(previous, result) == "changed_input"


# ---- OAuth -----------------------------------------------------------------

def settings(tmp_path: Path, token_url: str, **extra) -> oauth.OAuthSettings:
    return oauth.OAuthSettings(
        authorize_url="http://127.0.0.1:1/authorize", token_url=token_url, client_id="cid",
        scopes=["read"], token_file=tmp_path / "t.json", allow_network=True,
        allowed_hosts=["127.0.0.1"], **extra)


def test_pkce_challenge_is_s256_of_the_verifier() -> None:
    import base64
    import hashlib

    verifier, challenge = oauth.pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected and 43 <= len(verifier) <= 128


def test_oauth_refuses_network_unless_allowed_and_host_listed(tmp_path: Path) -> None:
    s = settings(tmp_path, "http://127.0.0.1:1/token")
    oauth.check_url(s, "http://127.0.0.1:9/x")
    with pytest.raises(PermissionError, match="allowed_hosts"):
        oauth.check_url(s, "http://localhost:9/x")
    with pytest.raises(PermissionError, match="https"):
        oauth.check_url(s.model_copy(update={"allowed_hosts": ["example.com"]}), "http://example.com/x")
    with pytest.raises(PermissionError, match="network access is off"):
        oauth.check_url(s.model_copy(update={"allow_network": False}), "https://127.0.0.1/x")


def test_token_file_is_private_and_a_leaky_one_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    oauth.save_token(path, {"access_token": "a"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.chmod(0o644)
    with pytest.raises(PermissionError, match="readable by others"):
        oauth.load_token(path)


def test_full_loopback_login_refresh_and_logout(tmp_path: Path) -> None:
    server = serve({"access_token": "A1", "refresh_token": "R1", "expires_in": 3600})
    s = settings(tmp_path, f"http://127.0.0.1:{server.server_port}/token",
                 revoke_url=f"http://127.0.0.1:{server.server_port}/revoke")
    seen = {}

    def browser(message: str) -> None:
        url = message.split("\n", 1)[1]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        assert query["code_challenge_method"] == ["S256"] and query["scope"] == ["read"]
        seen["redirect"] = query["redirect_uri"][0]

        def approve():
            urllib.request.urlopen(f"{seen['redirect']}?code=abc&state={query['state'][0]}", timeout=10).read()

        threading.Timer(0.3, approve).start()

    oauth.login(s, announce=browser, timeout=10)
    assert oauth.access_token(s) == "A1"
    stale = json.loads(s.token_file.read_text())
    stale["obtained_at"] -= 7200
    s.token_file.write_text(json.dumps(stale))
    refreshed = serve({"access_token": "A2", "expires_in": 3600})
    s2 = s.model_copy(update={"token_url": f"http://127.0.0.1:{refreshed.server_port}/token"})
    assert oauth.access_token(s2) == "A2"
    assert json.loads(s.token_file.read_text())["refresh_token"] == "R1"
    assert "deleted the local token" in oauth.logout(s2.model_copy(update={"revoke_url": None}))
    assert not s.token_file.exists()


def test_login_rejects_a_mismatched_state(tmp_path: Path) -> None:
    s = settings(tmp_path, "http://127.0.0.1:1/token")

    def browser(message: str) -> None:
        url = message.split("\n", 1)[1]
        redirect = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["redirect_uri"][0]
        threading.Timer(0.3, lambda: urllib.request.urlopen(f"{redirect}?code=abc&state=forged", timeout=10).read()).start()

    with pytest.raises(PermissionError, match="state mismatch"):
        oauth.login(s, announce=browser, timeout=10)
    assert not s.token_file.exists()


# ---- read-only self-hosted JSON adapter ------------------------------------

def test_http_json_reads_one_page_and_declares_its_host(tmp_path: Path, monkeypatch) -> None:
    server = serve({"data": {"items": [{"id": 7, "when": "2026-10-01T10:00:00Z", "name": "Scanned a thing"},
                                       {"id": 8, "when": "bad"}]}})
    url = f"http://127.0.0.1:{server.server_port}/api"
    adapter = HttpJsonAdapter()
    base = {"url": url, "items_path": "data.items", "time_field": "when", "title_field": "name", "id_field": "id"}
    with pytest.raises(PermissionError, match="allow_network"):
        build_plan(adapter, adapter.config_model(**base))
    config = adapter.config_model(**base, allow_network=True)
    plan = build_plan(adapter, config)
    assert plan.permissions.network_hosts == ("127.0.0.1",) and plan.permissions.read_paths == ()
    result = execute_plan(adapter, config, plan)
    assert [f.display for f in result.facts] == ["Scanned a thing"] and result.facts[0].source_record_id == "7"
    assert conformance.check(adapter, config) == []
    monkeypatch.delenv("NOPE", raising=False)
    with pytest.raises(PermissionError, match="NOPE"):
        execute_plan(adapter, adapter.config_model(**base, allow_network=True, token_env="NOPE"),
                     build_plan(adapter, adapter.config_model(**base, allow_network=True, token_env="NOPE")))


def test_http_json_refuses_a_redirect_to_another_host(tmp_path: Path) -> None:
    server = serve({}, status=302, headers={"Location": "http://localhost:1/elsewhere"})
    adapter = HttpJsonAdapter()
    config = adapter.config_model(url=f"http://127.0.0.1:{server.server_port}/", allow_network=True)
    with pytest.raises(Exception, match="redirect to another host refused"):
        execute_plan(adapter, config, build_plan(adapter, config))


def test_config_accepts_adapters_and_oauth_blocks(tmp_path: Path) -> None:
    (tmp_path / "dossify.toml").write_text(
        '[oauth.svc]\nauthorize_url = "https://a/x"\ntoken_url = "https://a/t"\n'
        'client_id = "c"\nscopes = ["read"]\ntoken_file = "tok.json"\nallowed_hosts = ["a"]\n')
    config = load_config(tmp_path / "dossify.toml")
    assert config.oauth["svc"].token_file == tmp_path / "tok.json"
    assert config.oauth["svc"].allow_network is False
