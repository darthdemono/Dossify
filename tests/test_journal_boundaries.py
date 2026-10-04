from dossify.journal import Fact, rebuild_day


def test_rebuild_day_preserves_manual_and_llm_sections_verbatim() -> None:
    manual = "Woke up late, ate dinner, then moved house."
    llm = "A private reflection stays here too."
    existing = [
        "## 2026-01-01",
        "",
        "#### Manual",
        "",
        manual,
        "",
        "",
        "",
        "",
        "",
        "#### LLM",
        "",
        llm,
        "",
        "#### Auto generated",
        "",
        "<!-- auto:begin 2026-01-01 -->",
        "- old generated line",
        "<!-- auto:end -->",
    ]

    rebuilt = rebuild_day("2026-01-01", existing, [Fact("2026-01-01", "12:00", "New event", "test")], {"test": 1})
    text = "\n".join(rebuilt)

    assert f"{manual}\n\n\n\n\n" in text
    assert llm in text
    assert "- old generated line" not in text
    assert "- 12:00 · New event[^a1]" in text
