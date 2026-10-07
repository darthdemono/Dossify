"""Generic bank statement reader for CSV and PDF files.

No bank is named here.  CSV columns are recognised by common header words in any
order, in UTF-8 or UTF-16, with any of comma, semicolon or tab as the delimiter.
PDF statements are read through ``pdftotext -layout`` (poppler) and each
transaction line is recognised as a date, a description and one or two trailing
numbers.  When a line carries an amount and a running balance, direction comes
from the balance change; otherwise from the amount's sign.  A transaction found
in both a CSV and a PDF is reported once.  Rows that cannot be read are skipped,
never guessed.
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

SUMMARY_LINE = re.compile(r"\b(opening|closing|brought forward|carried forward|total|balance)\b", re.I)

DATE_HEADERS = ("transaction date time", "transaction date", "booking date", "posting date",
                "value date", "date", "timestamp")
AMOUNT_HEADERS = ("amount", "transaction amount")
DEBIT_HEADERS = ("debit", "withdrawal", "withdrawals", "paid out", "money out")
CREDIT_HEADERS = ("credit", "deposit", "deposits", "paid in", "money in")
CURRENCY_HEADERS = ("currency", "ccy")
PARTY_HEADERS = ("partner name", "counterparty", "payee", "merchant", "beneficiary", "name",
                 "description", "details", "particulars", "booking info", "transaction details")
NOTE_HEADERS = ("narrative", "memo", "reference", "notes", "remarks")
TYPE_HEADERS = ("transaction type", "type")

DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d.", "%Y.%m.%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y",
                "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y")
DATE_IN_TEXT = re.compile(
    r"(?<![\d./-])(\d{4}[-./]\d{2}[-./]\d{2}\.?|\d{2}[-/.]\d{2}[-/.]\d{4}|\d{2}[- ][A-Za-z]{3,9}[- ]\d{4})(?![\d/])")
NUMBER = r"-?\(?(?:\d[\d.,]*|\.\d+)\)?"
PDF_LINE = re.compile(
    rf"^\s*(?P<d1>\S+)(?:\s+(?P<d2>\d{{4}}[-./]\d{{2}}[-./]\d{{2}}\.?|\d{{2}}[-/.]\d{{2}}[-/.]\d{{4}}))?\s+"
    rf"(?P<desc>.*?\S)\s+(?P<a>{NUMBER})(?:\s+(?P<b>{NUMBER}))?(?:\s*\(.*\))?\s*$")


class Transaction(NamedTuple):
    date: str                # YYYY-MM-DD
    time: str | None         # HH:MM when the source has it
    signed: float            # negative = money out
    currency: str
    party: str
    note: str
    card: bool               # the type says a card was used
    origin: str              # "csv" or "pdf"
    whole: bool = False      # show amounts as whole units, as the source's own option asks


class Source(NamedTuple):
    """A statement file or folder plus the options this source needs."""

    path: Path
    currency: str = ""            # used when the file does not state one
    whole_units: bool = False     # round displayed amounts to whole units
    card_prefixes: tuple[str, ...] = ()   # descriptions starting with these are card purchases


def parse_date(value: str) -> tuple[str, str | None] | None:
    value = (value or "").strip()
    clock = re.search(r"\b([01]\d|2[0-3]):([0-5]\d)", value)
    head = re.sub(r"[T\s]+\d{1,2}:\d{2}(:\d{2})?.*$", "", value).strip()
    for fmt in DATE_FORMATS:
        try:
            day = datetime.strptime(head, fmt)
        except ValueError:
            continue
        return day.strftime("%Y-%m-%d"), (f"{clock.group(1)}:{clock.group(2)}" if clock else None)
    return None


def parse_amount(value: str) -> float | None:
    """Read 1,234.56 / 1.234,56 / 43.700 / (12.00) / -5 without knowing the locale."""
    text = (value or "").strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = text.strip("-()+")
    text = re.sub(r"[^\d.,]", "", text)
    if not text or not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in text or "." in text:
        sep = "," if "," in text else "."
        head, _, tail = text.rpartition(sep)
        if text.count(sep) > 1 or len(tail) == 3 and len(head) >= 1 and tail.isdigit():
            text = text.replace(sep, "")                  # thousands separator
        else:
            text = head + "." + tail
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1")


def _pick(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = row.get(name)
        if value and value.strip():
            return value.strip()
    return ""


def read_csv(path: Path, source: Source | None = None) -> list[Transaction]:
    source = source or Source(path)
    text = _decode(path.read_bytes())
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    out = []
    for raw in reader:
        row = {(k or "").strip().casefold(): v for k, v in raw.items() if k}
        stamp = next((d for d in (parse_date(row.get(h, "")) for h in DATE_HEADERS) if d), None)
        if not stamp:
            continue
        signed = parse_amount(_pick(row, AMOUNT_HEADERS))
        if signed is None:
            credit = parse_amount(_pick(row, CREDIT_HEADERS))
            debit = parse_amount(_pick(row, DEBIT_HEADERS))
            if credit is None and debit is None:
                continue
            signed = (credit or 0.0) - abs(debit or 0.0)
        party = _pick(row, PARTY_HEADERS) or _pick(row, NOTE_HEADERS) or "an unnamed counterparty"
        out.append(Transaction(
            stamp[0], stamp[1], signed, _pick(row, CURRENCY_HEADERS).upper() or source.currency, party,
            _pick(row, NOTE_HEADERS), "card" in _pick(row, TYPE_HEADERS).lower() or _is_card(party, source),
            "csv", source.whole_units))
    return out


def _is_card(party: str, source: Source) -> bool:
    return any(re.match(rf"\s*(?:{re.escape(p)})\b", party, re.I) for p in source.card_prefixes)


def parse_pdf_text(text: str, source: Source | str = "") -> list[Transaction]:
    if isinstance(source, str):
        source = Source(Path("."), currency=source)
    found = re.search(r"\b(?:Currency|Ccy)\b\W{0,3}([A-Z]{3})\b", text)
    currency = found.group(1) if found else source.currency
    out = []
    opening = re.search(r"(?:opening|previous|brought forward)\s+balance\D{0,12}(" + NUMBER + ")", text, re.I)
    previous_balance = parse_amount(opening.group(1)) if opening else None
    for line in text.splitlines():
        m = PDF_LINE.match(line)
        stamp = parse_date(m.group("d1")) if m else None
        if not m or not stamp or SUMMARY_LINE.search(m.group("desc")):
            continue
        amount = parse_amount(m.group("a"))
        balance = parse_amount(m.group("b")) if m.group("b") else None
        if amount is None:
            continue
        if balance is not None:
            if previous_balance is None:
                # No opening balance to compare with: the first line's direction is
                # unknowable from the page, so follow its sign and default to money out.
                signed = amount if amount < 0 else -abs(amount)
            else:
                signed = abs(amount) if balance > previous_balance else -abs(amount)
            previous_balance = balance
        else:
            signed = amount
        party = m.group("desc").strip()
        out.append(Transaction(stamp[0], stamp[1], signed, currency, party, "", _is_card(party, source),
                               "pdf", source.whole_units))
    return out


def read_pdf(path: Path, source: Source | None = None) -> list[Transaction]:
    try:
        text = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True,
                              text=True, timeout=120, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_pdf_text(text, source or Source(path))


def collect(sources: list[Source | Path]) -> list[Transaction]:
    """Every transaction under the given files and folders, CSV first, duplicates removed."""
    files: list[tuple[Path, Source]] = []
    for source in sources:
        source = source if isinstance(source, Source) else Source(source)
        found = source.path.rglob("*") if source.path.is_dir() else [source.path]
        files += [(p, source) for p in sorted(found) if p.is_file() and p.suffix.lower() in (".csv", ".pdf")]
    rows = []
    for f, source in sorted(files, key=lambda item: (item[0].suffix.lower() != ".csv", str(item[0]))):
        try:
            rows += read_csv(f, source) if f.suffix.lower() == ".csv" else read_pdf(f, source)
        except (OSError, UnicodeError, csv.Error):
            continue
    seen_csv = Counter((r.date, round(r.signed, 2), r.currency) for r in rows if r.origin == "csv")
    out = []
    for r in rows:
        key = (r.date, round(r.signed, 2), r.currency)
        if r.origin == "pdf" and seen_csv.get(key, 0) > 0:
            seen_csv[key] -= 1                    # the CSV already reported this one
            continue
        out.append(r)
    return list(dict.fromkeys(out))


def money(n: float, currency: str, whole: bool = False) -> str:
    body = f"{int(round(n)):,}" if (whole and abs(n) >= 1) or abs(n - round(n)) < 0.005 else f"{n:,.2f}"
    return f"{body} {currency}".strip()


def describe(t: Transaction, name) -> str:
    """One journal line.  ``name`` turns a raw counterparty into how a person would say it."""
    who = name(t.party)
    amount = money(abs(t.signed), t.currency, t.whole)
    if t.signed < 0:
        text = f"Paid {amount} {'at' if t.card else 'to'} {who}"
    else:
        text = f"Received {amount} from {who}"
    if t.note and len(t.note) <= 90 and t.note != t.party:
        text += f" ({t.note})"
    return text
