from pathlib import Path

from dossify import bank_statements as bank


def write_utf16(path: Path, text: str) -> None:
    path.write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))


def test_amounts_are_read_without_knowing_the_locale() -> None:
    cases = {"1,234.56": 1234.56, "1.234,56": 1234.56, "43.700": 43700, "-5": -5, "(12.00)": -12,
             "12,50": 12.5, "1 234,50": 1234.5, "": None, "n/a": None}
    for raw, want in cases.items():
        assert bank.parse_amount(raw) == want, raw


def test_dates_parse_in_the_common_layouts() -> None:
    assert bank.parse_date("2026-03-05 14:30:00") == ("2026-03-05", "14:30")
    assert bank.parse_date("2026.03.05.") == ("2026-03-05", None)
    assert bank.parse_date("05-Mar-2026") == ("2026-03-05", None)
    assert bank.parse_date("05/03/2026") == ("2026-03-05", None)
    assert bank.parse_date("soon") is None


def test_csv_utf16_semicolon_with_signed_amount(tmp_path: Path) -> None:
    write_utf16(tmp_path / "a.csv",
                "Transaction Date Time;Booking Date;Amount;Currency;Partner Name;Transaction Type;Narrative\n"
                "2026.03.05. 14:30;2026.03.06.;-1500;EUR;SHOP ONE;Card purchase;lunch\n"
                "2026.03.07.;2026.03.07.;2000;EUR;A Friend;Transfer;\n")
    rows = bank.collect([tmp_path])
    assert [(r.date, r.time, r.signed, r.card) for r in rows] == [
        ("2026-03-05", "14:30", -1500.0, True), ("2026-03-07", None, 2000.0, False)]
    assert bank.describe(rows[0], lambda s: s.title()) == "Paid 1,500 EUR at Shop One (lunch)"
    assert bank.describe(rows[1], lambda s: s) == "Received 2,000 EUR from A Friend"


def test_csv_with_separate_debit_and_credit_columns(tmp_path: Path) -> None:
    (tmp_path / "b.csv").write_text(
        "Date,Description,Debit,Credit\n2026-04-01,Rent,500.00,\n2026-04-02,Refund,,25.50\n", encoding="utf-8")
    rows = bank.collect([tmp_path])
    assert [r.signed for r in rows] == [-500.0, 25.5]


PDF = """Statement  Currency: BDT
Opening Balance  10,000.00
05-Mar-2026   CARD SHOP ONE      1,000.00    9,000.00
06-Mar-2026   TRANSFER IN        2,500.00   11,500.00
2026.03.07. 2026.03.07. SUBSCRIPTION            43.700      7.800
not a transaction line
"""


def test_pdf_direction_comes_from_the_balance_change() -> None:
    rows = bank.parse_pdf_text(PDF)
    assert [(r.date, r.signed, r.currency) for r in rows] == [
        ("2026-03-05", -1000.0, "BDT"), ("2026-03-06", 2500.0, "BDT"), ("2026-03-07", -43700.0, "BDT")]


def test_pdf_is_read_through_pdftotext_and_missing_tool_is_skipped(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    class Done:
        stdout = PDF

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    (tmp_path / "s.pdf").write_bytes(b"%PDF")
    assert len(bank.collect([tmp_path])) == 3

    def missing(*a, **k):
        raise FileNotFoundError("pdftotext")

    monkeypatch.setattr(subprocess, "run", missing)
    assert bank.collect([tmp_path]) == []


def test_a_transaction_in_both_csv_and_pdf_is_reported_once(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    (tmp_path / "a.csv").write_text("Date,Amount,Currency,Description\n2026-03-05,-1000,BDT,Shop\n")

    class Done:
        stdout = PDF

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    rows = bank.collect([tmp_path])
    assert sum(1 for r in rows if (r.date, r.signed) == ("2026-03-05", -1000.0)) == 1
    assert len(rows) == 3        # csv row, plus the two pdf rows the csv does not cover


def test_unreadable_rows_are_skipped_not_guessed(tmp_path: Path) -> None:
    (tmp_path / "c.csv").write_text("Date,Amount,Description\nyesterday,5,x\n2026-01-01,abc,y\n2026-01-02,7,z\n")
    assert [r.signed for r in bank.collect([tmp_path])] == [7.0]
