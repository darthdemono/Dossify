"""Instagram and Facebook data-download exports.

Options: export, messages ('none' counts only; 'threads' also names who), title_renames, communities, noise_chats."""

import glob, json, os, re
from collections import defaultdict

from dossify import journal as J
from dossify.journal import CACHE_VERSION, Fact, _hm, epoch_local, jload, meta_text, nest, plural
from dossify.people import normalize_identifier

TIER = "core"

_O: dict = {}   # this provider's options, set by the registry before each read


def cached_obj(tag, paths, build):
    """Same memoisation as cached(), for an adapter whose result is a plain
    JSON structure rather than a flat list of facts. The Meta adapters need it
    because they carry group-chat rosters out alongside their facts, and a
    cache hit that dropped the rosters would empty the section at the bottom
    of every month file."""
    paths = sorted(paths)
    if not paths:
        return build(paths)
    try:
        key = json.dumps([CACHE_VERSION, J.CACHE_SALT] +
                         [[p, os.path.getsize(p), int(os.path.getmtime(p))] for p in paths])
    except OSError:
        return build(paths)
    store = os.path.join(J.CACHE, "export-%s.json" % tag)
    try:
        blob = json.load(open(store, encoding="utf-8"))
        if blob.get("key") == key:
            return blob["data"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    data = build(paths)
    try:
        os.makedirs(J.CACHE, exist_ok=True)
        json.dump({"key": key, "data": data}, open(store, "w", encoding="utf-8"))
    except OSError:
        pass
    return data


def meta_root(kind):
    """The extracted Instagram or Facebook export, found by its marker folder.

    Searched across every export root, because the two exports do not have to
    live on the same disk.
    """
    marker = "your_%s_activity" % kind
    for root in J.listify(_O.get("export")):
        if not os.path.isdir(root):
            continue
        cands = [root] + sorted(glob.glob(os.path.join(root, "*")))
        cands += sorted(glob.glob(os.path.join(root, "*", "*")))
        for d in cands:
            if not os.path.isdir(d):
                continue
            if os.path.isdir(os.path.join(d, marker)) or os.path.isdir(
                    os.path.join(d, "personal_information")) and kind in os.path.basename(d).lower():
                return d
    return None


def _meta_posts(path, service, out, verb="Posted on"):
    data = jload(path)
    rows = data if isinstance(data, list) else []
    if isinstance(data, dict):
        for k in ("ig_stories", "ig_reels_media", "ig_archived_post_media",
                  "ig_other_media", "photos", "videos"):
            if isinstance(data.get(k), list):
                rows = data[k]
                break
    for e in rows:
        if not isinstance(e, dict):
            continue
        ts = e.get("creation_timestamp") or e.get("timestamp")
        media = e.get("media") or []
        if not ts and media and isinstance(media[0], dict):
            ts = media[0].get("creation_timestamp")
        if not ts:
            continue
        date, time = epoch_local(ts)
        if not date:
            continue
        cap = meta_text(e.get("title") or "")
        if not cap and media and isinstance(media[0], dict):
            cap = meta_text(media[0].get("title") or "")
        for d in (e.get("data") or []):
            if isinstance(d, dict) and d.get("post"):
                cap = meta_text(d["post"])
        cap = re.sub(r"\s+", " ", cap).strip()
        if len(cap) > 90:
            cap = cap[:87].rstrip() + "..."
        n = len(media) if isinstance(media, list) else 0
        what = "%s %s" % (verb, service)
        if n > 1:
            what += " (%d items)" % n
        out.append(Fact(date, time, "%s%s" % (what, ": " + cap if cap else ""),
                        service.lower()))


def _meta_places(path, service, out):
    """Check-ins, which live inside Facebook posts as an attachment."""
    data = jload(path)
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        date, time = epoch_local(e.get("timestamp"))
        if not date:
            continue
        for att in (e.get("attachments") or []):
            for d in (att.get("data") or []) if isinstance(att, dict) else []:
                place = (d or {}).get("place")
                if isinstance(place, dict) and place.get("name"):
                    out.append(Fact(date, time, "Checked in at %s" % meta_text(place["name"]),
                                    service.lower()))


def meta_handles(root):
    """Display name -> Instagram handle.

    Built from every place the export happens to print the two together: notes
    and reposts, suggested profiles, the advertiser tables. There is no
    name-to-handle file in the download, and the thread folder name is the
    title with its punctuation stripped rather than a username, so this is the
    only route. A name resolving to more than one handle is dropped rather
    than guessed at.
    """
    pairs = defaultdict(set)

    def walk(node, depth=0):
        if depth > 12:
            return
        if isinstance(node, list):
            for x in node:
                walk(x, depth + 1)
            return
        if not isinstance(node, dict):
            return
        lv = node.get("dict")
        if isinstance(lv, list):
            d = {}
            for e in lv:
                if isinstance(e, dict) and "label" in e:
                    d[e["label"]] = e.get("value")
            if d.get("Name") and d.get("Username"):
                pairs[meta_text(d["Name"])].add(d["Username"])
        for v in node.values():
            walk(v, depth + 1)

    paths = [q for q in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True))
             if os.sep + "messages" + os.sep not in q]

    def build(ps):
        for q in ps:
            walk(jload(q))
        return dict((k, sorted(v)[0]) for k, v in pairs.items() if len(v) == 1)

    return cached_obj("ig-handles", paths, build)


def meta_self(root, kind):
    """His own name as this export writes it, so he is never listed among the
    members of his own group chats."""
    if kind == "instagram":
        for q in glob.glob(os.path.join(root, "**", "personal_information.json"),
                           recursive=True):
            for u in ((jload(q) or {}).get("profile_user") or []):
                v = ((u.get("string_map_data") or {}).get("Name") or {}).get("value")
                if v:
                    return meta_text(v)
    for q in glob.glob(os.path.join(root, "**", "profile_information.json"), recursive=True):
        n = ((jload(q) or {}).get("profile_v2") or {}).get("name") or {}
        if n.get("full_name"):
            return meta_text(n["full_name"])
    return ""


def identity():
    """The in-memory projection of the private People.json file."""
    if J._IDENTITY is None:
        raise RuntimeError("journal engine has not been configured")
    return J._IDENTITY


_HANDLE_BY_CARD = None


def handle_by_card():
    """Return only an unambiguous Instagram handle for a card.

    A card can legitimately own several accounts. Choosing the first JSON key
    made an unrelated alias appear in journal rows whose display name supplied
    no handle, so multi-account cards deliberately have no generic fallback.
    """
    global _HANDLE_BY_CARD
    if _HANDLE_BY_CARD is None:
        choices = defaultdict(set)
        for h, card in (identity().get("by_ig_handle") or {}).items():
            choices[card].add(h)
        _HANDLE_BY_CARD = {card: next(iter(handles)) for card, handles in choices.items()
                           if len(handles) == 1}
    return _HANDLE_BY_CARD


def handle_for_display(card, display):
    """Return the explicit account paired with this display name, if any."""
    choices = {
        row.get("handle")
        for person in (identity().get("people") or [])
        if person.get("name") == card
        for row in (person.get("instagram") or [])
        if row.get("display") and normalize_identifier(row["display"]) == normalize_identifier(display)
        and row.get("handle")
    }
    return next(iter(choices)) if len(choices) == 1 else None


def identity_match(key, value):
    """Look up a People.json identity without broadening the spelling match."""
    ident = identity()
    normalized = ident.get(key + "_normalized")
    if normalized is not None:
        return normalized.get(normalize_identifier(value))
    # Compatibility for an in-memory projection created by a pre-1.0.1 engine.
    return (ident.get(key) or {}).get(value)


def meta_person(name, handles, service="Instagram", full=True):
    """One person as a journal line should name them.

    `@handle (Real Name)` where both are known, and whichever one is known
    otherwise. Group-chat inline lists use the same `@handle (Real Name)`
    spelling.
    """
    ident = identity()
    key = "by_ig_display" if service == "Instagram" else "by_fb_name"
    card = identity_match(key, name)
    h = handles.get(name) if handles else None
    if card is None and service == "Instagram":
        # Some threads are titled with the username rather than a display name,
        # so the display lookup misses somebody the map does know by handle.
        probe = h or re.sub(r"^@", "", name.strip())
        card = identity_match("by_ig_handle", probe)
        if card and not h:
            h = probe
    if card and not h and service == "Instagram":
        # Prefer the handle explicitly paired with this display name. A card
        # with several Instagram accounts must not leak an arbitrary alias
        # into another account's thread; only a one-account card can fall back.
        h = handle_for_display(card, name) or handle_by_card().get(card)
    if h and card:
        return "@%s (%s)" % (h, card)
    if h:
        return "@" + h
    return card or name


def meta_title(title, service):
    """The chat as it should read: renamed where he has renamed it, and under
    its community where it belongs to one."""
    t = _O.get("title_renames", {}).get(title, title) if service == "Instagram" else title
    com = _O.get("communities", {}).get(t)
    if not com or t.startswith(com):
        # `Club - Training` already says which community it belongs to, and
        # `Club/Club - Training` says it twice.
        return t
    return "%s/%s" % (com, t)


def meta_noise(title):
    return any(re.search(pat, title or "") for pat in _O.get("noise_chats", []))


def _meta_messages(root, service, out, handles=None, rosters=None, gcdays=None):
    """Counts only. No text ever leaves these files, and the thread name only
    when message_threads is on, because the other half of a chat is not mine."""
    if rosters is None:
        rosters = {}
    if gcdays is None:
        gcdays = defaultdict(set)
    if _O.get("messages", "none") == "none":
        threads = glob.glob(os.path.join(root, "**", "messages", "**", "message_*.json"),
                            recursive=True)
        byday = defaultdict(lambda: [0, set()])
        for p in threads:
            data = jload(p)
            for m in ((data or {}).get("messages") or []):
                date, _ = epoch_local((m.get("timestamp_ms") or 0) / 1000.0)
                if date:
                    byday[date][0] += 1
                    byday[date][1].add(p)
        for date, (n, ps) in byday.items():
            out.append(Fact(date, None, "%s: %s across %s" % (
                service, plural(n, "message"), plural(len(ps), "chat")), service.lower()))
        return
    # Who he texted and when he started, not how many messages went back and
    # forth. "441 messages across 6 chats" is a tally; "texted Hanna at 09:15"
    # is a thing he did. The message count is deliberately not carried.
    where = "Messenger" if service == "Facebook" else service
    me = meta_self(root, "facebook" if service == "Facebook" else "instagram")
    byday = defaultdict(dict)
    calls = defaultdict(list)
    for p in glob.glob(os.path.join(root, "**", "messages", "**", "message_*.json"),
                       recursive=True):
        data = jload(p)
        raw = meta_text((data or {}).get("title") or os.path.basename(os.path.dirname(p)))
        if meta_noise(raw):
            continue
        # Participants are everyone still on the thread minus himself, so a
        # two-name chat is a conversation and anything above that is a group.
        members = [meta_text(x.get("name") or "")
                   for x in ((data or {}).get("participants") or [])]
        members = [x for x in members if x.strip() and x != me]
        group = len(members) > 1
        if not raw.strip():
            # A thread whose title is blank or invisible characters. The person
            # on the other end names it better than an empty bullet does.
            raw = members[0] if len(members) == 1 else os.path.basename(os.path.dirname(p))
        title = meta_title(raw, service)
        key = "%s\t%s" % (service, title)
        if group and len(members) < J.GC_ROSTER_MAX:
            roster = sorted(set(meta_person(x, handles, service) for x in members),
                            key=lambda v: v.lstrip("@").lower())
            # Threads split across message_1.json, message_2.json and so on
            # carry the same roster; a group he left and rejoined does not.
            rosters[key] = sorted(set(rosters.get(key, [])) | set(roster),
                                  key=lambda v: v.lstrip("@").lower())
        for m in ((data or {}).get("messages") or []):
            date, time = epoch_local((m.get("timestamp_ms") or 0) / 1000.0)
            if not date:
                continue
            # A call is a different thing from a chat and carries its own
            # duration: it says who he actually spoke to, and for how long.
            if "call_duration" in m:
                calls[date].append((time, title, m.get("call_duration") or 0))
                continue
            slot = byday[date].get(title)
            if slot is None:
                slot = byday[date][title] = [time, set(), group]
            if time < slot[0]:
                slot[0] = time
            who = meta_text(m.get("sender_name") or "")
            if who and who != me:
                slot[1].add(who)
            if group:
                gcdays[date].add(key)
    for date, chats in byday.items():
        lines = []
        for title, (t, senders, group) in sorted(chats.items(),
                                                 key=lambda kv: (kv[1][0], kv[0])):
            # A one-to-one thread is titled with the other person, so the title
            # itself becomes the handle. A group keeps its name and carries the
            # people who actually said something that day.
            label = title if group else meta_person(title, handles, service)
            if group:
                # Who spoke that day, then how many people were in the room and
                # did not. A group of forty showing one name said nothing about
                # the group; "+39" does.
                said = sorted(set(meta_person(x, handles, service, full=False)
                                  for x in senders),
                              key=lambda v: v.lstrip("@").lower())
                roster = rosters.get("%s\t%s" % (service, title)) or []
                quiet = max(0, len(roster) - len(said))
                if not said:
                    said, quiet = roster, 0
                shown = said[:J.GC_INLINE_MAX]
                rest = (len(said) - len(shown)) + quiet
                if shown:
                    label = "%s {%s%s}" % (label, ", ".join(shown),
                                           " +%d" % rest if rest else "")
            lines.append("%s \u00b7 %s" % (t, label))
        f = nest(date, "Texted on %s:" % where, lines, service.lower())
        if f:
            out.append(f)
    for date, rows in calls.items():
        # A zero duration is left bare rather than called "missed", which is
        # not something the file actually says.
        lines = ["%s \u00b7 %s%s" % (t, name, " (%s)" % _hm(d) if d else "")
                 for t, name, d in sorted(rows)]
        f = nest(date, "Called on %s:" % where, lines, service.lower())
        if f:
            out.append(f)


def _meta_adapter(kind, service):
    root = meta_root(kind)
    if not root:
        return []
    handles = meta_handles(root) if kind == "instagram" else {}

    def build(_paths):
        out, skip = [], set()
        rosters, gcdays = {}, defaultdict(set)
        for pat, verb in (("posts_*.json", "Posted on"),
                          ("your_posts*.json", "Posted on"),
                          ("stories.json", "Story on"),
                          ("reels.json", "Reel on"),
                          ("archived_posts.json", "Archived post on"),
                          ("profile_photos.json", "New profile photo on"),
                          ("other_content.json", "Posted on"),
                          ("your_uncategorized_photos.json", "Photo on")):
            for p in glob.glob(os.path.join(root, "**", pat), recursive=True):
                skip.add(p)
                _meta_posts(p, service, out, verb)
                if service == "Facebook":
                    _meta_places(p, service, out)
        _meta_messages(root, service, out, handles, rosters, gcdays)
        # _meta_counts is every tally Meta keeps: likes, searches, profile
        # visits, notifications. Dropped from the journal 09-09-2026 for the
        # same reason as the Google ones. The function stays because the
        # export inventory still uses its labels to say what a file is.
        return {"facts": [list(f) for f in out],
                "rosters": rosters,
                "gcdays": dict((d, sorted(v)) for d, v in gcdays.items())}
    paths = sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True))
    blob = cached_obj("meta-" + kind, paths, build)
    J.GC_ROSTERS.update(blob.get("rosters") or {})
    for date, keys in (blob.get("gcdays") or {}).items():
        J.GC_DAYS[date].update(keys)
    return [Fact(*row) for row in blob.get("facts") or []]


def a_instagram():
    return _meta_adapter("instagram", "Instagram")


def a_facebook():
    return _meta_adapter("facebook", "Facebook")


READERS = {"instagram": a_instagram, "facebook": a_facebook}
LABELS = {'instagram': 'Activity read from an Instagram data export.', 'facebook': 'Activity read from a Facebook data export.'}
