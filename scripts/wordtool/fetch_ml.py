#!/usr/bin/env python3
"""Fetch the Middle Liddell TEI for the grc-ml pack (stdlib only).

Downloads one file from PerseusDL/canonical-pdlrefwk at the commit pinned
in build_wordtool.py into scripts/wordtool/sources/ (gitignored) and
verifies its sha256. The file is CC BY-SA 4.0; the repo README asks that
Perseus be credited and offered any modifications.

Run: python3 scripts/wordtool/fetch_ml.py
then: python3 scripts/wordtool/build_wordtool.py --ml-only
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request

from build_wordtool import ML_SHA256, ML_SOURCE, ML_URL


def main() -> int:
    if ML_SOURCE.exists() and hashlib.sha256(ML_SOURCE.read_bytes()).hexdigest() == ML_SHA256:
        print(f"already fetched: {ML_SOURCE}")
        return 0
    print(f"fetching {ML_URL}", flush=True)
    req = urllib.request.Request(ML_URL, headers={"User-Agent": "grammars-wordtool"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()
    sha = hashlib.sha256(data).hexdigest()
    if sha != ML_SHA256:
        print(f"sha256 mismatch: got {sha}, pinned {ML_SHA256}", file=sys.stderr)
        return 1
    ML_SOURCE.parent.mkdir(parents=True, exist_ok=True)
    ML_SOURCE.write_bytes(data)
    print(f"wrote {ML_SOURCE} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
