#!/usr/bin/env python3
"""One-off: wrap each day's dictated text in #### Manual, add an empty
#### LLM section, and append an empty #### Auto generated block that
journal_auto.py can rewrite in place.

Dry run by default. --apply to write.
"""
import re, os

BASE = ""
DAY = re.compile(r'^## (\d{4}-\d{2}-\d{2})\s*$')
STOP = re.compile(r'^(## |---\s*$)')

PLACEHOLDER = "_Not generated yet._"


def block(date):
    return ["#### Auto generated", "",
            "<!-- auto:begin %s -->" % date, PLACEHOLDER, "<!-- auto:end -->", ""]


def migrate(path, demote_h3):
    src = open(path, encoding="utf-8").read().split("\n")
    out, i, days = [], 0, 0
    while i < len(src):
        m = DAY.match(src[i])
        if not m:
            out.append(src[i]); i += 1; continue
        date = m.group(1)
        out.append(src[i]); i += 1
        # gather this day's body up to the next day / month-level break
        body = []
        while i < len(src) and not (DAY.match(src[i]) or STOP.match(src[i])):
            body.append(src[i]); i += 1
        if any("#### Manual" in l for l in body):
            out.extend(body); continue                      # already migrated
        if demote_h3:
            body = [re.sub(r'^### ', '##### ', l) for l in body]
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        out += ["", "#### Manual", ""] + body + ["", "#### LLM", ""] + block(date)
        days += 1
    return "\n".join(out), days


def run(config, names: list[str], *, apply: bool, demote_h3: bool = False) -> None:
    """Migrate selected month files into Manual/LLM/Auto sections."""
    if not config.output_dir:
        raise ValueError("dossify.toml needs output_dir")
    base = str(config.output_dir.resolve())
    for name in names:
        if not re.fullmatch(r"20\d\d-\d\d\.md", name):
            raise ValueError("month names must look like YYYY-MM.md")
        path = os.path.join(base, name)
        text, count = migrate(path, demote_h3)
        print("%s: %d days wrapped" % (name, count))
        if apply and count:
            open(path, "w", encoding="utf-8").write(text)
            print("   written")
