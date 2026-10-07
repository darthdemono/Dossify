"""Chat exports from Discord and Snapchat (data-request archives).

Options: export (the extracted archive folder, or several)."""

import glob, os, re
from collections import defaultdict
from datetime import datetime

from dossify import journal as J
from dossify.journal import UTC, cached, jload, local_of, nest

TIER = "core"

_O: dict = {}   # this provider's options, set by the registry before each read


def export_dirs(kind):
    return [path for path in J.listify(_O.get("export")) if os.path.isdir(path)]


def utc_stamp(value, pattern):
    try:
        return local_of(datetime.strptime(str(value), pattern).replace(tzinfo=UTC))
    except (TypeError, ValueError):
        return None, None


def export_label(value, fallback):
    label = re.sub(r"\s+", " ", str(value or "")).strip()[:100] or fallback
    return label.replace("[", r"\[").replace("]", r"\]")


def a_discord():
    """One per channel/day, from the package's own sent-message records only."""
    out = []
    for root in export_dirs("discord"):
        index = jload(os.path.join(root, "Messages", "index.json")) or {}
        paths = sorted(glob.glob(os.path.join(root, "Messages", "c*", "messages.json")))

        def build(_paths, root=root, index=index):
            byday = defaultdict(dict)
            for path in _paths:
                channel_id = os.path.basename(os.path.dirname(path))[1:]
                label = export_label(index.get(channel_id), "channel " + channel_id)
                for row in jload(path) or []:
                    date, time = utc_stamp(row.get("Timestamp"), "%Y-%m-%d %H:%M:%S")
                    if date and (label not in byday[date] or time < byday[date][label]):
                        byday[date][label] = time
            result = []
            for date, channels in byday.items():
                fact = nest(date, "Texted on Discord:",
                            ["%s · %s" % (time, label)
                             for label, time in sorted(channels.items(), key=lambda row: (row[1], row[0]))],
                            "discord")
                if fact:
                    result.append(fact)
            return result

        out += cached("discord-" + re.sub(r"\W+", "_", root), paths, build)
    return out


def a_snapchat():
    """Only outgoing chat rows: a conversation and time, never its contents."""
    out = []
    for root in export_dirs("snapchat"):
        path = os.path.join(root, "json", "chat_history.json")
        if not os.path.isfile(path):
            continue

        def build(_paths, path=path):
            byday = defaultdict(dict)
            for title, rows in (jload(path) or {}).items():
                label = export_label(title, "Snapchat conversation")
                for row in rows or []:
                    if str(row.get("IsSender", "")).lower() not in ("true", "1", "yes"):
                        continue
                    date, time = utc_stamp(row.get("Created"), "%Y-%m-%d %H:%M:%S UTC")
                    if date and (label not in byday[date] or time < byday[date][label]):
                        byday[date][label] = time
            result = []
            for date, chats in byday.items():
                fact = nest(date, "Texted on Snapchat:",
                            ["%s · %s" % (time, label)
                             for label, time in sorted(chats.items(), key=lambda row: (row[1], row[0]))],
                            "snapchat")
                if fact:
                    result.append(fact)
            return result

        out += cached("snapchat-" + re.sub(r"\W+", "_", root), [path], build)
    return out


READERS = {"discord": a_discord, "snapchat": a_snapchat}
LABELS = {'discord': 'Counts of messages read from a Discord data export.', 'snapchat': 'Activity read from a Snapchat data export.'}
