#!/usr/bin/env python3
"""Take a Google, Meta, Discord or Snapchat export from a downloaded zip to
the folder you point a provider's `export` option at, and say what is there.

    dossify ingest <config>                        # what is already in place
    dossify ingest <config> add ~/Downloads/*.zip  # dry run, says what it would do
    dossify ingest <config> add ~/Downloads/*.zip --apply
    dossify ingest <config> add *.zip --into ~/Exports --apply
    dossify ingest <config> add ~/Downloads/discord.zip --kind discord --apply
    dossify ingest <config> add ~/Downloads/snapchat.zip --apply

The exports are not copied into the archive. A Takeout runs to tens of
gigabytes and carries a whole mailbox, so it lives on the big disk and only
the derived journal lines come back. Layout, request options and the traps:
Journal/Export Ingest - Google Takeout and Meta.md
"""
import json, os, re, shutil, stat, sys, tempfile, zipfile

HOME = os.path.expanduser("~")
BASE = ""
ROOTS = [os.environ.get("JOURNAL_EXPORTS"), os.path.join(HOME, "Exports")]   # overridden by [ingest] roots
DEFAULT_META_HANDLE = ""


def configure(config) -> None:
    """Read export destinations from ``[ingest]`` in dossify.toml."""
    global BASE, ROOTS, DEFAULT_META_HANDLE
    if not config.output_dir:
        raise ValueError("dossify.toml needs output_dir")
    BASE = str(config.output_dir.resolve())
    roots = [str(root) for root in config.ingest.roots]
    ROOTS = [os.path.expanduser(root) for root in roots if root] or ROOTS
    DEFAULT_META_HANDLE = config.ingest.default_meta_handle

# The files journal_auto.py actually reads, and what each one is for.
WANTED = [
    ("MyActivity.json",             "per-product activity"),
    ("watch-history.json",          "YouTube watch history"),
    ("BrowserHistory.json",         "Chrome history"),
    ("Timeline.json",               "Timeline, phone export"),
    ("location-history.json",       "Timeline, older name"),
    ("Installs.json",               "Play Store installs"),
    ("Purchase History.json",       "Play Store purchases"),
    ("Order History.json",          "Play Store orders"),
    ("Daily activity metrics.csv",  "Fit dailies"),
    ("Saved Places.json",           "Maps saved places"),
    ("Reviews.json",                "Maps reviews"),
    ("posts_1.json",                "Instagram posts"),
    ("stories.json",                "Instagram stories"),
    ("reels.json",                  "Instagram reels"),
    ("liked_posts.json",            "Instagram likes"),
    ("your_posts_1.json",           "Facebook posts"),
    ("comments.json",               "Facebook comments"),
]


def root(create=False):
    for r in ROOTS:
        if r and os.path.isdir(r):
            return r
    if create:
        for r in ROOTS:
            if not r:
                continue
            try:
                os.makedirs(r, exist_ok=True)
                return r
            except OSError:
                continue
    return None


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0


def tree_size(path):
    total, files = 0, 0
    for dirpath, _dirs, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(dirpath, n))
                files += 1
            except OSError:
                pass
    return total, files


class MergeConflict(RuntimeError):
    """Two exports claim one native record ID but disagree about its payload."""


ID_KEYS = ("id", "ID", "message_id", "messageId", "uuid")


def native_id(row):
    """The provider's own ID for one JSON record, never an inferred key."""
    if not isinstance(row, dict):
        return None
    for key in ID_KEYS:
        value = row.get(key)
        if isinstance(value, (str, int)) and str(value):
            return key, str(value)
    return None


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def merge_json(old, new, where="$"):
    """Return a union of two JSON documents, deduplicated on native IDs.

    Equal metadata is retained once.  A changed scalar or a list without native
    record IDs is not safely mergeable, so it fails before anything is written.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        out = dict(old)
        for key, value in new.items():
            out[key] = value if key not in old else merge_json(old[key], value,
                                                                 "%s.%s" % (where, key))
        return out
    if isinstance(old, list) and isinstance(new, list):
        if not old:
            return new
        if not new:
            return old
        old_ids = [native_id(row) for row in old]
        new_ids = [native_id(row) for row in new]
        if all(old_ids) and all(new_ids):
            out, seen = list(old), {}
            for row, key in zip(old, old_ids):
                if key in seen and compact(seen[key]) != compact(row):
                    raise MergeConflict("%s has conflicting existing ID %s" % (where, key[1]))
                seen[key] = row
            for row, key in zip(new, new_ids):
                prior = seen.get(key)
                if prior is None:
                    out.append(row)
                    seen[key] = row
                elif compact(prior) != compact(row):
                    raise MergeConflict("%s ID %s differs between exports" % (where, key[1]))
            return out
        if compact(old) == compact(new):
            return old
        raise MergeConflict("%s changed but its records have no native IDs" % where)
    if compact(old) == compact(new):
        return old
    raise MergeConflict("%s differs between exports" % where)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise MergeConflict("cannot read JSON %s: %s" % (path, exc))


def safe_extract(zf, dest):
    """Extract without accepting zip-slip paths or symlink entries."""
    root = os.path.realpath(dest)
    for info in zf.infolist():
        if stat.S_ISLNK(info.external_attr >> 16):
            raise MergeConflict("zip contains symlink %s" % info.filename)
        target = os.path.realpath(os.path.join(root, info.filename))
        if os.path.commonpath((root, target)) != root:
            raise MergeConflict("zip contains unsafe path %s" % info.filename)
        if info.is_dir():
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(info) as source, open(target, "wb") as output:
            shutil.copyfileobj(source, output)


def merge_plan(incoming, dest):
    """Validate every collision and return write actions without changing dest."""
    actions = []
    for base, _dirs, names in os.walk(incoming):
        for name in names:
            source = os.path.join(base, name)
            rel = os.path.relpath(source, incoming)
            target = os.path.join(dest, rel)
            if not os.path.exists(target):
                actions.append(("copy", source, target, None))
                continue
            if source.lower().endswith(".json") and target.lower().endswith(".json"):
                merged = merge_json(load_json(target), load_json(source), rel)
                actions.append(("json", source, target, merged))
                continue
            with open(source, "rb") as left, open(target, "rb") as right:
                if left.read() == right.read():
                    continue
            raise MergeConflict("%s differs and is not mergeable JSON" % rel)
    return actions


def apply_merge(actions):
    for kind, source, target, data in actions:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if kind == "copy":
            shutil.copy2(source, target)
            continue
        fd, temporary = tempfile.mkstemp(prefix=".merge-", suffix=".json",
                                         dir=os.path.dirname(target), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def identify(zpath):
    """(kind, handle) from a zip's contents, never from its filename alone."""
    try:
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()[:4000]
    except (OSError, zipfile.BadZipFile):
        return None, None
    blob = "\n".join(names)
    base = os.path.basename(zpath).lower()
    if "your_instagram_activity/" in blob or base.startswith("instagram-"):
        m = re.match(r"instagram-([^-]+)-", base)
        return "instagram", (m.group(1) if m else DEFAULT_META_HANDLE)
    if "your_facebook_activity/" in blob or base.startswith("facebook-"):
        m = re.match(r"facebook-([^-]+)-", base)
        return "facebook", (m.group(1) if m else DEFAULT_META_HANDLE)
    if all(marker in blob for marker in ("Account/user.json", "Messages/index.json",
                                         "Servers/index.json")):
        return "discord", None
    if all(marker in blob for marker in ("json/account.json", "json/chat_history.json",
                                         "json/snap_history.json")):
        return "snapchat", None
    if re.search(r"(^|\n)Takeout/", blob) or base.startswith("takeout-"):
        return "takeout", None
    return None, None


def dest_for(kind, handle, account):
    r = root(create=True)
    if not r:
        return None
    if kind == "takeout":
        if not account:
            return None
        return os.path.join(r, "google-takeout", account)
    if kind == "discord":
        return os.path.join(r, "discord")
    if kind == "snapchat":
        return os.path.join(r, "snapchat")
    return os.path.join(r, "meta", "%s-%s" % (kind, handle))


def cmd_inventory():
    r = root()
    if not r:
        print("No export root. Looked at:")
        for c in ROOTS:
            if c:
                print("  %s" % c)
        print("\nMake one of those and drop the zips through `add`.")
        return
    print("Export root: %s\n" % r)
    found = False
    for group in ("google-takeout", "meta"):
        gdir = os.path.join(r, group)
        if not os.path.isdir(gdir):
            continue
        for d in sorted(os.listdir(gdir)):
            path = os.path.join(gdir, d)
            if not os.path.isdir(path):
                continue
            found = True
            size, nfiles = tree_size(path)
            print("%-40s %10s  %s files" % (d, human(size), "{:,}".format(nfiles)))
            index = {}
            for dirpath, _dirs, names in os.walk(path):
                for n in names:
                    index.setdefault(n, 0)
                    index[n] += 1
            for name, what in WANTED:
                if name in index:
                    print("    %-28s %-24s x%d" % (name, what, index[name]))
            print()
    if not found:
        print("Nothing extracted yet.")


def cmd_add(args):
    apply = "--apply" in args
    replace = "--replace" in args
    if "--into" in args:
        i = args.index("--into")
        if i + 1 < len(args):
            # An explicit root beats the search order. The 12 TB disk is first
            # in ROOTS and is not always the right answer - on 11-09-2026 it was
            # resetting its SATA link mid-extraction, so Instagram went local.
            ROOTS.insert(0, os.path.expanduser(args[i + 1]))
    account = None
    if "--account" in args:
        i = args.index("--account")
        if i + 1 < len(args):
            account = args[i + 1]
    forced_kind = None
    if "--kind" in args:
        i = args.index("--kind")
        if i + 1 < len(args):
            forced_kind = args[i + 1].lower()
            if forced_kind not in ("discord", "facebook", "instagram", "snapchat", "takeout"):
                print("Unknown --kind %s" % forced_kind)
                return 2
    zips = [a for a in args if a.endswith(".zip") and os.path.isfile(a)]
    if not zips:
        print("No zip files given.")
        return 2
    plan = []
    for z in sorted(zips):
        kind, handle = identify(z)
        if forced_kind:
            kind, handle = forced_kind, (DEFAULT_META_HANDLE if forced_kind in ("facebook", "instagram") else None)
        if not kind:
            print("SKIP  %s  (not a recognised export; use --kind after inspection)" % os.path.basename(z))
            continue
        if kind == "takeout" and not account:
            print("SKIP  %s  (a Takeout zip does not name its account; pass --account)"
                  % os.path.basename(z))
            continue
        dest = dest_for(kind, handle, account)
        if not dest:
            print("SKIP  %s  (no writable export root)" % os.path.basename(z))
            continue
        plan.append((z, kind, dest))
    if not plan:
        return 1
    grouped = {}
    for row in plan:
        grouped.setdefault(row[2], []).append(row)
    for dest, rows in grouped.items():
        raw = 0
        for z, kind, _ in rows:
            with zipfile.ZipFile(z) as zf:
                raw += sum(i.file_size for i in zf.infolist())
        parent = os.path.dirname(dest)
        while not os.path.isdir(parent):
            parent = os.path.dirname(parent)
        free = shutil.disk_usage(parent).free
        exists = os.path.isdir(dest) and os.listdir(dest)
        note = ""
        if exists and not replace:
            note = "  [merging by native JSON record ID; conflicts stop]"
        if exists and replace:
            note = "  [REPLACING what is there]"
        for z, kind, _ in rows:
            print("%-9s %-46s -> %s" % (kind, os.path.basename(z), dest))
        print("          %s total uncompressed, %s free%s" % (human(raw), human(free), note))
        if raw > free:
            print("          NOT ENOUGH SPACE. Nothing extracted.")
            return 1
        if not apply:
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix=".ingest-", dir=os.path.dirname(dest)) as work:
                incoming = os.path.join(work, "incoming")
                for number, (z, _kind, _dest) in enumerate(rows):
                    part = os.path.join(work, "part-%d" % number)
                    with zipfile.ZipFile(z) as zf:
                        safe_extract(zf, part)
                    if number == 0:
                        shutil.move(part, incoming)
                    else:
                        apply_merge(merge_plan(part, incoming))
                if exists and not replace:
                    actions = merge_plan(incoming, dest)
                    apply_merge(actions)
                    copied = sum(kind == "copy" for kind, *_ in actions)
                    merged = sum(kind == "json" for kind, *_ in actions)
                    print("          merged: %d new files, %d JSON files" % (copied, merged))
                else:
                    if exists:
                        shutil.rmtree(dest)
                    shutil.move(incoming, dest)
                    print("          extracted")
        except MergeConflict as exc:
            print("          REFUSED: %s" % exc)
            return 1
    if not apply:
        print("\nDry run. Add --apply to extract.")
    else:
        print("\nDone. Now run journal_auto.py to see what it picks up:")
        print("  dossify journal <private-dossify.toml> --apply")
    return 0


def self_test():
    old = {"messages": [{"ID": "15", "body": "same"}]}
    new = {"messages": [{"ID": "15", "body": "same"},
                        {"ID": "16", "body": "new"}]}
    merged = merge_json(old, new)
    assert [row["ID"] for row in merged["messages"]] == ["15", "16"]
    with tempfile.TemporaryDirectory() as work:
        dest, incoming = os.path.join(work, "old"), os.path.join(work, "new")
        os.makedirs(dest); os.makedirs(incoming)
        with open(os.path.join(dest, "messages.json"), "w", encoding="utf-8") as fh:
            json.dump(old, fh)
        with open(os.path.join(incoming, "messages.json"), "w", encoding="utf-8") as fh:
            json.dump(new, fh)
        apply_merge(merge_plan(incoming, dest))
        assert [row["ID"] for row in load_json(os.path.join(dest, "messages.json"))["messages"]] == ["15", "16"]
    try:
        merge_json(old, {"messages": [{"ID": "15", "body": "changed"}]})
    except MergeConflict:
        return
    raise AssertionError("changed native ID was not rejected")


def run(config, args: list[str]) -> int | None:
    configure(config)
    if args == ["--self-test"]:
        self_test()
        print("merge self-test passed")
        return
    if args and args[0] == "add":
        sys.exit(cmd_add(args[1:]))
    cmd_inventory()
