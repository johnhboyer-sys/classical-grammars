#!/usr/bin/env python3
"""Fetch the pinned GitHub source files the converters read but git ignores.

The source clones (grammar-ag-tei/, grammar-agdt/, grammar-smyth/ and
grammar-bennett/) are gitignored and live only on the owner's machine, so CI
has nothing for the converters and verifiers to read.  This script downloads
just the files they need, from raw.githubusercontent.com at a pinned commit:

  * Allen & Greenough TEI, PerseusDL/canonical-pdlrefwk at the sourceCommit in
    data/ag/meta.json, to the path convert_ag.py and verify_ag.py expect.
  * AGDT 2.5 guidelines, PerseusDL/treebank_data at the commit pinned in
    SPEC-constructions.md, to the path build_constructions.py expects.
  * Smyth's TEI, the Perseus Tufts TEI P4 digitization as carried in
    alpheios-project/grammar-smyth (src/smyth_eng_u.xml, about 11 MB), which
    convert_smyth.py, verify_smyth.py and verify_landmarks.py read.  The commit
    is the master head at the time of pinning; convert_smyth.py reproduces
    data/smyth/sections.jsonl and meta.json byte for byte from it.
  * Bennett's HTML, the Alpheios XHTML edition in alpheios-project/grammar-bennett
    (CC BY-NC-SA 3.0 US): only the eleven files convert_bennett.py opens, not
    index.htm or the images.  Same test: the master head reproduces
    data/bennett/sections.jsonl and meta.json byte for byte.

The Smyth and Bennett pins are recorded here only; data/smyth/meta.json and
data/bennett/meta.json name a path, not a commit.  A file already on disk is
left alone and reported "present".  A fetched file is checked against the
sha256 recorded below; a mismatch is a failure and nothing is written.  Exit
status is non-zero only on a download or checksum failure.  Stdlib only;
urllib honours the usual proxy environment variables on its own.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = "https://raw.githubusercontent.com"

AG_COMMIT = "02768b0c37d6102be4899fc0eb57f9d348195243"
AGDT_COMMIT = "bf4334f0af5e13d16b04c1cccd6237e683ac6f5f"
SMYTH_COMMIT = "d7796df9b3cbccd0a04cdc2b7aebe7d7869e1d28"
BENNETT_COMMIT = "3f9a9f54d5673d54bd516d33d86cc528d72232e9"

# (repository, commit, path inside the repository, destination under ROOT, sha256)
SOURCES = [
    (
        "PerseusDL/canonical-pdlrefwk",
        AG_COMMIT,
        "data/viaf39744457/001/viaf39744457.001.perseus-eng1.xml",
        "grammar-ag-tei/data/viaf39744457/001/viaf39744457.001.perseus-eng1.xml",
        "ba21262eeca68ab53a77c5907c0c021a2c9ba9f8fe18ea623363813433304020",
    ),
    (
        "PerseusDL/treebank_data",
        AGDT_COMMIT,
        "AGDT2/guidelines/Greek_guidelines_2.5.md",
        "grammar-agdt/AGDT2/guidelines/Greek_guidelines_2.5.md",
        "20dcb7ab27a7c6cea7d68c607f70261338a3c0f770d18539612afc506e98829d",
    ),
    (
        "alpheios-project/grammar-smyth",
        SMYTH_COMMIT,
        "src/smyth_eng_u.xml",
        "grammar-smyth/src/smyth_eng_u.xml",
        "3d5ba15fe7d3449def129f5f83c92f96718177f7aba2bdeffa8bb64bf1a39d8e",
    ),
]

# convert_bennett.py: SECTION_FILES, FRONT_MATTER_FILES, footnotes.htm, toc.htm.
BENNETT_FILES = {
    "part1.htm": "a1c8635176a1a8f197c61746c61f1a6533cbb29a76db641076679371b7723619",
    "part2.htm": "c7cc263e21678c31cffb24dcc16d6209cad4e5487a8deb6a436dc6d6fac89a9e",
    "part3.htm": "320b85bc63d01021142d548b961c9a45fd47a361d1a5b157755bcdd5437d215f",
    "part4.htm": "7804109823a2cf9578e3dc26fd0e9fff3857e08679a7e14e6ff7cfc7b7860280",
    "part5.htm": "09798313fa067191c36bf2b7030a01960141de54af6e79394c297f553eb6fea0",
    "part6.htm": "a1b83d0e4d26ac2c576ecfd393dbf3da8ca934081089444ed177303774d29e5b",
    "supplement.htm": "d77ee600abb6c5052112bbb30d8c4981fa75a9b3c5f6c675cd4549d56b0fd3d9",
    "preface.htm": "0c7ed2275697a112ffc87fa776eada89551d6675dd9c9a49e2f6d8233c244229",
    "intro.htm": "bc106f0c45296f963eb9757f08b67a4e198ce07ae678854cac78b3607c33f27f",
    "footnotes.htm": "93b69b6915e926923959e3eea71950894ad6d2de56ab5bb17e9a5e83e15c9d17",
    "toc.htm": "a4c5f2dbecf0a5fd1f5710f23a02fc31897d660815ffcd4de6695353050911c2",
}
SOURCES += [
    ("alpheios-project/grammar-bennett", BENNETT_COMMIT, name, f"grammar-bennett/{name}", sha256)
    for name, sha256 in BENNETT_FILES.items()
]


def fetch(repo: str, commit: str, path: str, dest: Path, sha256: str) -> bool:
    label = dest.relative_to(ROOT).as_posix()
    if dest.exists():
        print(f"present  {label}")
        return True
    url = f"{RAW}/{repo}/{commit}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=300) as response:
            data = response.read()
    except (urllib.error.URLError, OSError) as exc:
        print(f"failed   {label}: {exc}")
        return False
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        print(f"failed   {label}: sha256 {digest} does not match recorded {sha256}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"fetched  {label} ({len(data)} bytes, {repo}@{commit[:12]})")
    return True


def main() -> int:
    ok = True
    for repo, commit, path, dest, sha256 in SOURCES:
        ok = fetch(repo, commit, path, ROOT / dest, sha256) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
