import json
from pathlib import Path

import pytest

from dossify import ledger, privacy, profiles
from dossify.claims import Claim, load_user_claims
from dossify.dossier import build
from dossify.journal import Fact


def facts():
    return [
        Fact("2026-01-01", "09:00", "Messaged someone", "instagram"),
        Fact("2026-01-01", "10:00", "Messaged again", "instagram"),
        Fact("2026-01-01", "11:00", "Paid 500 HUF at a shop", "bank_statements"),
        Fact("2026-03-05", "12:00", "Committed a change", "git"),
    ]


def test_privacy_none_is_unrestricted_and_presets_resolve() -> None:
    assert privacy.resolve(None, {}) == {}
    kept, excluded = privacy.apply(facts(), {})
    assert len(kept) == 4 and excluded == {}
    with pytest.raises(ValueError):
        privacy.resolve("nope", {})
    with pytest.raises(ValueError):
        privacy.resolve("balanced", {"mood": "raw"})
    with pytest.raises(ValueError):
        privacy.resolve("balanced", {"health": "sometimes"})


def test_count_collapses_a_day_and_hidden_drops_it() -> None:
    kept, excluded = privacy.apply(facts(), privacy.resolve("balanced", {}))
    texts = [f.text for f in kept if f.src == "instagram"]
    assert texts == ["2 instagram records (details withheld by privacy policy)"]
    assert excluded == {"instagram": "count"}
    kept, excluded = privacy.apply(facts(), privacy.resolve(None, {"message_content": "hidden"}))
    assert not [f for f in kept if f.src == "instagram"]
    assert excluded["instagram"] == "hidden"


def test_digest_caps_lines_and_chronicle_adds_coverage() -> None:
    lines = [f"- line {i}" for i in range(20)]
    digest = profiles.shape_day(lines, facts(), "digest")
    assert len(digest) == profiles.DIGEST_LINES + 1 and "8 more lines" in digest[-1]
    assert profiles.shape_day(lines, facts(), "journal") == lines
    chronicle = profiles.shape_day(lines, facts(), "chronicle")
    assert chronicle[:20] == lines and "4 records from 3 sources" in chronicle[-1]


def test_profile_kinds_are_enforced() -> None:
    assert profiles.get("dossier", "document").kind == "document"
    with pytest.raises(ValueError):
        profiles.get("digest", "document")
    with pytest.raises(ValueError):
        profiles.get("novel")


def test_silent_gaps_report_only_long_silences() -> None:
    assert ledger.silent_gaps(["2026-01-01", "2026-01-05"]) == []
    gaps = ledger.silent_gaps(["2026-01-01", "2026-02-01"])
    assert gaps == [["2026-01-02", "2026-01-31", 30]]
    assert ledger.summarise("x", []).status == "no_events"
    assert ledger.summarise("x", facts()).active_days == 2


def test_forbidden_predicates_and_claims_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Claim(predicate="emotional_state", value="sad", claim_type="inferred")
    good = tmp_path / "claims.json"
    good.write_text(json.dumps([{"predicate": "lives_in", "value": "Budapest",
                                 "claim_type": "user_asserted"}]))
    assert load_user_claims(good)[0].value == "Budapest"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"predicate": "x", "value": "y", "claim_type": "inferred"}]))
    with pytest.raises(ValueError):
        load_user_claims(bad)
    assert load_user_claims(None) == []


@pytest.mark.parametrize("profile", ["dossier", "casefile", "monograph"])
def test_document_profiles_state_counts_and_gaps(profile: str) -> None:
    outcomes = [ledger.summarise("instagram", facts()[:2]), ledger.Outcome("mail", "failed", error="boom"),
                ledger.summarise("git", facts()[3:])]
    text = build(facts(), outcomes, profile=profile, period="all", claims=[], policy={},
                 sources={"git": "Git commits"}, digest="a" * 64, run_id="r1", timezone="UTC")
    assert "records.total" in text and "| 4 |" in text
    assert "`mail`: failed" in text or "Source `mail`: failed" in text
    assert "No records in 2026-02" in text
    if profile == "casefile":
        assert "## Day index" in text and "## Gap register" in text
    if profile == "monograph":
        assert "## Abstract" in text and "]: git: Git commits" in text


def test_document_period_filters_records() -> None:
    text = build(facts(), [], profile="dossier", period="2026-03", claims=[], policy={},
                 sources={}, digest="b" * 64, run_id=None, timezone="UTC")
    assert "Records: 1 from 1 sources" in text
