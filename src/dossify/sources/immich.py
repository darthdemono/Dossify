"""Photos taken, from an Immich database.

Options: psql (command prefix opening psql), self_names, not_mine_names, cameras (model to label), special_album, derived_name_pattern, camera_name_pattern."""

import re, subprocess
from collections import defaultdict

from dossify.journal import Fact

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_immich():
    """Photos that are actually mine: any picture of me whatever took it, plus
    anything shot on one of my own handsets. A bare per-day count of the whole
    library says nothing about whose photos they are, so it is not used."""
    sql = """
        select to_char(a."fileCreatedAt", 'YYYY-MM-DD'),
               coalesce(e.city, ''),
               coalesce(e.model, ''),
               (select count(*) from album_asset aa
                  join album al on al.id = aa."albumId"
                 where aa."assetId" = a.id and al."albumName" = $ANIK$),
               coalesce(string_agg(distinct p.name, '|')
                        filter (where coalesce(p.name,'') <> ''), '')
        from asset a
             left join asset_exif e on e."assetId" = a.id
             left join asset_face f on f."assetId" = a.id
             -- Immich 2.x associates faces and people through person groups,
             -- rather than the removed asset_face.personId / person.id pair.
             left join person p on p."personGroupId" = f."personGroupId"
        where a."deletedAt" is null
          -- ONLY ORIGINALS. Anything a messenger, a social app or an editor wrote to
          -- disk is either somebody else's picture or a second copy of one I already
          -- have. Two tests: the name must not look derived, and the file must carry
          -- a camera model or be named the way a camera names things, which keeps
          -- video, whose EXIF rarely records the model.
          and a."originalFileName" !~* $DERIVED$
          and (coalesce(e.model, '') <> '' or a."originalFileName" ~* $CAMNAME$)
        group by a.id, 1, 2, 3
    """
    psql = list(_O.get("psql") or [])
    if not psql:
        return []
    for token, value in (("$ANIK$", str(_O.get("special_album") or "")),
                         ("$DERIVED$", str(_O.get("derived_name_pattern") or "$^")),
                         ("$CAMNAME$", str(_O.get("camera_name_pattern") or "$^"))):
        sql = sql.replace(token, "'" + value.replace("'", "''") + "'")
    NOT_MINE = set(_O.get("not_mine_names", []))
    MY_CAMERAS = dict(_O.get("cameras", {}))
    ME_NAMES = set(_O.get("self_names", []))
    try:
        r = subprocess.run(psql + ["-tAF", "\x1f", "-c", sql],
                           capture_output=True, text=True, timeout=300)
    except Exception:
        return []

    groups = defaultdict(int)
    for line in r.stdout.strip().split("\n"):
        parts = line.split("\x1f")
        if len(parts) < 5 or not re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
            continue
        date, city, model, anik, people = parts[0], parts[1].strip(), parts[2].strip(), parts[3], parts[4]
        names = [n for n in people.split("|") if n]
        if names and set(names) <= NOT_MINE:
            continue
        names = [n for n in names if n not in NOT_MINE]
        mine_by_camera = model in MY_CAMERAS
        has_me = bool(ME_NAMES.intersection(names))
        if not mine_by_camera and not has_me:
            continue
        if anik not in ("0", ""):
            # some EXIF model strings list every badge the body ever shipped under
            short = model.split(" / ")[0].strip()
            shot_by = "Anik (%s)" % (short or "camera not recorded")
        elif mine_by_camera:
            shot_by = "my %s" % MY_CAMERAS[model]
        else:
            shot_by = model or ""
        others = tuple(sorted(n for n in names if n not in ME_NAMES))
        groups[(date, others, city, shot_by, has_me)] += 1

    perday = defaultdict(list)
    for (date, others, city, shot_by, has_me), n in groups.items():
        if others and has_me:
            who = "with me and " + _and(others)
        elif others:
            who = "with " + _and(others)
        elif has_me:
            who = "of me"
        else:
            who = ""
        head = ("Picture %s" % who if n == 1 else "%d pictures %s" % (n, who)).strip()
        if city:
            head = ("%s in %s" % (head, city)) if not who else ("%s, in %s" % (head, city))
        perday[date].append("%s, taken by %s" % (head, shot_by) if shot_by else head)

    # A day can hold several distinct groups of photographs and none of them carries
    # a clock, so they would sit in a row looking like separate events. One parent
    # bullet with the groups nested under it reads as what it is: the day's pictures.
    out = []
    for date, lines in perday.items():
        if len(lines) == 1:
            out.append(Fact(date, None, lines[0], "immich"))
        else:
            kids = "\n".join("    - %s" % l for l in sorted(lines))
            out.append(Fact(date, None, "Pictures taken:\n" + kids, "immich"))
    return out


def _and(names):
    names = list(names)
    if len(names) == 1:
        return names[0]
    if len(names) <= 4:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names[:3]) + " and %d others" % (len(names) - 3)


READERS = {"immich_db": a_immich}
LABELS = {'immich': 'Photos read from an Immich library, originals only.'}
