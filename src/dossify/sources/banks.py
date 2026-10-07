"""Bank statements (CSV and PDF): the counterparty cleaner and the reader.

Options: sources, names, strip_prefixes, strip_suffixes, accent_digraphs, contacts_csv."""

import csv, glob, os, re
from pathlib import Path

from dossify import journal as J
from dossify.journal import Fact

TIER = "core"

_O: dict = {}   # this provider's options, set by the registry before each read


_CONTACTS = None


def contact_name(raw):
    """A counterparty that is a person, under the name his address book uses.

    Statements print people surname-first and inconsistently: `Smith John` one
    month, `john smith` the next. Matching on the export means a new friend
    needs no code change, and nobody gets renamed on a guess: every
    token has to line up, so a single shared first name never matches.
    """
    global _CONTACTS
    if _CONTACTS is None:
        _CONTACTS = []
        wanted = os.path.expanduser(str(_O.get("contacts_csv") or ""))
        pattern = wanted if os.path.isabs(wanted) else os.path.join(J.ARCHIVE, wanted)
        for f in (sorted(glob.glob(pattern))[-1:] if wanted else []):
            try:
                for row in csv.DictReader(open(f, encoding="utf-8")):
                    name = (row.get("File As") or row.get("Name") or row.get("Display Name") or "").strip()
                    if name:
                        _CONTACTS.append((name, {t for t in re.findall(r"[a-z]+", name.lower())
                                                 if len(t) > 2}))
            except (OSError, ValueError):
                pass
    want = {t for t in re.findall(r"[a-z]+", (raw or "").lower()) if len(t) > 2}
    if len(want) < 2:
        return None
    for name, toks in _CONTACTS:
        if len(toks) < 2:
            continue
        if all(any(t.startswith(w) or w.startswith(t) for t in toks) for w in want):
            return name
    # Transliterated names differ by a letter between the bank and the book:
    # one letter between the bank and the book. Compare the whole sorted
    # name and demand a very close match, so only a spelling gap is bridged.
    import difflib
    mine = " ".join(sorted(want))
    best, score = None, 0.0
    for name, toks in _CONTACTS:
        if len(toks) < 2 or len(toks) != len(want):
            continue
        r = difflib.SequenceMatcher(None, mine, " ".join(sorted(toks))).ratio()
        if r > score:
            best, score = name, r
    return best if score >= 0.88 else None


def _source(item):
    """A `sources` entry is a path string or {path, currency, whole_units, card_prefixes}."""
    from dossify.bank_statements import Source

    if isinstance(item, str):
        return Source(Path(item))
    return Source(Path(os.path.expanduser(item["path"])), str(item.get("currency") or ""),
                  bool(item.get("whole_units")), tuple(item.get("card_prefixes") or ()))


def bank_name(raw):
    """A counterparty as a person would say it, not as the terminal wrote it."""
    t = re.sub(r"\s+", " ", raw or "").strip(" ./")
    for prefix in _O.get("strip_prefixes", []):
        t = re.sub(r"^(?:%s)[/ ]+" % prefix, "", t, flags=re.I)
    for suffix in _O.get("strip_suffixes", []):
        t = re.sub(r"\s*/\s*(?:%s)\s*[\d.]*$" % suffix, "", t, flags=re.I).strip(" /")
    # an account number is not a counterparty and does not belong in a diary
    t = re.sub(r"\b\d{9,}\b", "", t).strip(" :/-")
    for a, b in _O.get("accent_digraphs", {}).items():
        t = t.replace(a, b)
    up = t.upper()
    for pat, name in _O.get("names", {}).items():
        if re.search(pat, up):
            return name
    # Banks can write a transfer as `SENDER/RECIPIENT`. Try the whole string,
    # then each half, so a configured contact still resolves when order varies.
    person = contact_name(t)
    if not person:
        for part in re.split(r"\s*/\s*", t):
            person = contact_name(part)
            if person:
                break
    if person:
        return person
    t = re.sub(r"\s*\b\d{3,6}\b\s*", " ", t).strip()          # store numbers
    t = re.sub(r"\s+(KFT|ZRT|BT|LTD|LIMITED)\.?$", "", t, flags=re.I).strip()
    if t and t == t.upper() and len(t) > 3:
        t = t.title()
    return t or "an unnamed counterparty"


def a_bank_statements():
    """Every CSV or PDF bank statement under the configured `sources`."""
    global _CONTACTS
    from dossify import bank_statements

    _CONTACTS = None
    sources = [_source(item) for item in J.listify(_O.get("sources"))]
    return [Fact(r.date, r.time, bank_statements.describe(r, bank_name), "bank_statements")
            for r in bank_statements.collect(sources)]


READERS = {"bank_statements": a_bank_statements}
LABELS = {'bank_statements': 'Bank statements read from CSV and PDF files.'}
