"""Commits from local git repositories.

Options: roots (folders of repos), repos (single repos), author_terms."""

import glob, os, subprocess

from dossify import journal as J
from dossify.journal import Fact

TIER = "core"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_git():
    roots = []
    for parent in J.listify(_O.get("roots")):          # folders whose children are repositories
        roots += sorted(glob.glob(os.path.join(parent, "*")))
    roots += J.listify(_O.get("repos"))                # repositories named one by one
    out = []
    for d in roots:
        if not os.path.isdir(os.path.join(d, ".git")):
            continue
        name = os.path.basename(d.rstrip("/"))
        try:
            log = subprocess.run(
                ["git", "-C", d, "log", "--no-merges",
                 "--pretty=%h%x1f%aI%x1f%an%x1f%ae%x1f%s"],
                capture_output=True, text=True, timeout=60).stdout
        except Exception:
            continue
        for line in log.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 5:
                continue
            sha, iso, an, ae, subj = parts
            blob = (an + " " + ae).lower()
            author_terms = [str(term).casefold() for term in _O.get("author_terms", [])]
            if author_terms and not any(term in blob for term in author_terms):
                continue
            out.append(Fact(iso[:10], iso[11:16], "%s %s: %s" % (name, sha, subj), "git"))
    return out


READERS = {"git": a_git}
LABELS = {'git': 'Commits read from local git repositories.'}
