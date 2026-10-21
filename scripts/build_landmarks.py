#!/usr/bin/env python3
"""Build the landmark-navigation data files from the Smyth TEI source.

The owner navigates his physical copy of Smyth by sticky tabs: the major
parts, each particle chapter, and the alphabetized verb list at the back.
This script extracts the digital equivalents of those tabs:

  data/smyth/verbs.json          Appendix: List of Verbs (fully digitized)
  data/smyth/particles.json      particle -> section-range map (from the
                                  book's own Particles chapter headings)

The print indexes are built elsewhere (build_index_english.py; Greek index
pipeline in work/greek-index/) and are never touched by this script.

Source: grammar-smyth/src/smyth_eng_u.xml (Perseus/Alpheios TEI). Read via
an explicit --tei-source path since grammar-smyth/ is a gitignored clone
that does not exist inside a git-worktree checkout. Cross-checks every
section number it emits against data/smyth/sections.jsonl.

Python stdlib only. No network access. Deterministic: two runs over the
same inputs produce byte-identical output (see scripts/verify_landmarks.py).
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEI = ROOT / "grammar-smyth" / "src" / "smyth_eng_u.xml"
DEFAULT_SECTIONS = ROOT / "data" / "smyth" / "sections.jsonl"
OUT_DIR = ROOT / "data" / "smyth"

WS_RE = re.compile(r"\s+")


def norm(text: str | None) -> str:
    return WS_RE.sub(" ", text or "").strip()


def text_of(elem: ET.Element) -> str:
    return norm("".join(elem.itertext()))


def parse_source(path: Path) -> ET.Element:
    # NFC at the door: the source mixes precomposed and decomposed Greek
    # (an accent as one codepoint here, base + combining accent there).
    # Normalizing once up front means every string downstream -- lemmas,
    # slugs, head text -- is comparable and stable.
    #
    # Glyph placeholders ([ιγλιδε] etc.) and the source's stranded breathings
    # are resolved with the same map and repair convert_smyth.py uses, imported
    # rather than copied: a second copy of that table already drifted once and
    # shipped placeholders into verbs.json. The path insert keeps the import
    # working even when the interpreter doesn't prepend the script dir
    # (python3 -P / PYTHONSAFEPATH).
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import convert_smyth

    raw = path.read_text(encoding="utf-8")
    raw = convert_smyth.EUNC_RE.sub("ε", raw)
    for placeholder, glyph in convert_smyth.GLYPH_FIXES.items():
        raw = raw.replace(placeholder, glyph)
    root = ET.fromstring(unicodedata.normalize("NFC", raw))
    parents = {child: parent for parent in root.iter() for child in parent}
    convert_smyth.repair_marks(root, parents)
    convert_smyth.restack_macrons(root)
    return root


def load_valid_sections(path: Path) -> set[int]:
    valid: set[int] = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            valid.add(json.loads(line)["n"])
    return valid


# --------------------------------------------------------------------------
# Minimal TEI -> HTML renderer for appendix verb entries. A smaller sibling
# of convert_smyth.py's Renderer: the appendix only ever uses this subset of
# tags, so it stays self-contained rather than importing that script.
# --------------------------------------------------------------------------

def _escape(text: str | None) -> str:
    return html_lib.escape(WS_RE.sub(" ", text or ""), quote=False)


def render_children(elem: ET.Element) -> str:
    parts = [_escape(elem.text)]
    for child in elem:
        parts.append(render_elem(child))
        parts.append(_escape(child.tail))
    return "".join(parts)


def render_elem(elem: ET.Element) -> str:
    tag = elem.tag
    content = render_children(elem)
    if tag == "foreign":
        lang = (elem.get("lang") or "").lower()
        if lang in {"greek", "grc"}:
            return f'<span lang="grc">{content}</span>'
        lang_attr = f' lang="{html_lib.escape(lang, quote=True)}"' if lang else ""
        return f"<span{lang_attr}>{content}</span>"
    if tag == "gloss":
        return f'<span class="gloss">{content}</span>'
    if tag == "emph":
        wrapper = "strong" if elem.get("rend") == "bold" else "em"
        return f"<{wrapper}>{content}</{wrapper}>"
    if tag == "ref":
        target = elem.get("target") or ""
        match = re.search(r"\d+", target)
        if not match:
            return content
        return f'<a data-ref="smyth:{match.group()}">{content}</a>'
    if tag == "bibl":
        cite = elem.get("n") or text_of(elem)
        return f'<cite data-cite="{html_lib.escape(cite, quote=True)}">{content}</cite>'
    if tag in {"term", "title", "mentioned"}:
        return f'<span class="{tag}">{content}</span>'
    # Unknown wrapper: keep text, drop tag.
    return content


# --------------------------------------------------------------------------
# Appendix: List of Verbs
# --------------------------------------------------------------------------


def find_div1(root: ET.Element, n: str) -> ET.Element | None:
    for div1 in root.iter("div1"):
        if div1.get("n") == n and (div1.get("type") or "").lower() in {"part"}:
            return div1
    return None


def extract_verbs(
    root: ET.Element, valid_sections: set[int]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    appendix = find_div1(root, "5")
    meta: dict[str, object] = {
        "letterGroups": 0,
        "entriesWithoutLemma": [],
        "invalidSectionRefs": [],
    }
    if appendix is None:
        meta["status"] = "appendix div1[@n=5] not found in source"
        return [], meta

    verbs: list[dict[str, object]] = []
    letter_groups = [child for child in appendix if child.tag == "div2"]
    meta["letterGroups"] = len(letter_groups)

    for group in letter_groups:
        group_label = text_of(group.find("head")) or "(no head)"
        for p in group.findall("p"):
            first_foreign = None
            for foreign in p.iter("foreign"):
                if (foreign.get("lang") or "").lower() in {"greek", "grc"}:
                    first_foreign = foreign
                    break
            lemma = text_of(first_foreign) if first_foreign is not None else ""
            if not lemma:
                meta["entriesWithoutLemma"].append(
                    {"group": group_label, "textStart": text_of(p)[:60]}
                )
                continue

            raw_refs = []
            for ref in p.iter("ref"):
                match = re.search(r"\d+", ref.get("target") or "")
                if match:
                    raw_refs.append(int(match.group()))
            sections = sorted(set(raw_refs))
            invalid = [n for n in sections if n not in valid_sections]
            if invalid:
                meta["invalidSectionRefs"].append(
                    {"lemma": lemma, "refs": invalid}
                )
            sections = [n for n in sections if n in valid_sections]

            entry_html = f"<p>{render_children(p)}</p>"
            verbs.append(
                {
                    "lemma": unicodedata.normalize("NFC", lemma),
                    "entryHtml": entry_html,
                    "sections": sections,
                }
            )

    return verbs, meta


# --------------------------------------------------------------------------
# Greek -> Latin slug transliteration (see SPEC-landmarks.md for the table
# and the collision-disambiguation rule).
# --------------------------------------------------------------------------

GREEK_TO_LATIN = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "e",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "u",
    "φ": "ph", "χ": "ch", "ψ": "ps", "ω": "o",
}
ROUGH_BREATHING = "̔"  # combining reversed comma above (dasia)

# Greek alphabetical order, used for both collation and deterministic
# collision tie-breaking. Index 0 = alpha ... 23 = omega.
GREEK_ALPHABET_ORDER = "αβγδεζηθικλμνξοπρστυφχψω"


def base_letters(word: str) -> str:
    """Strip every combining mark, keep the bare base letters, lowercase."""
    nfd = unicodedata.normalize("NFD", word)
    return "".join(ch.lower() for ch in nfd if not unicodedata.combining(ch))


def slugify_particle(word: str) -> str:
    nfd = unicodedata.normalize("NFD", word)
    has_rough = ROUGH_BREATHING in nfd
    out: list[str] = []
    first = True
    for ch in nfd:
        if unicodedata.combining(ch):
            continue
        base = ch.lower()
        latin = GREEK_TO_LATIN.get(base)
        if latin is None:
            continue
        if first and has_rough:
            out.append("rh" if base == "r" else "h" + latin)
        else:
            out.append(latin)
        first = False
    return "".join(out)


def collation_key(word: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Sort key for Greek collation: base letters, in Greek alphabet order,
    accents/breathings ignored.

    Non-Greek characters are ignored, not ranked. The appendix prints stem
    boundaries as hyphens (ἄγ-νῡμι, δί-δωμι) and a few headwords list several
    forms separated by commas; the print list alphabetizes as if those marks
    were not there, so the key drops them. Final sigma folds to medial sigma.

    The NFD codepoint fallback is a *second* tuple element, not a suffix of
    the first: appending it would let a codepoint decide a comparison between
    two different skeletons where one is a prefix of the other (ἀε- vs ἀείρω),
    which would push every bare-stem headword after its longer neighbours."""
    stripped = base_letters(word).replace("ς", "σ")
    primary = tuple(
        GREEK_ALPHABET_ORDER.index(ch)
        for ch in stripped
        if ch in GREEK_ALPHABET_ORDER
    )
    return primary, tuple(ord(c) for c in unicodedata.normalize("NFD", word))


# --------------------------------------------------------------------------
# Particles
# --------------------------------------------------------------------------

PAREN_RE = re.compile(r"\(([^)]*)\)")
ARTIFACT_RE = re.compile(r"<\*>")


def parse_particle_forms(head_text: str) -> tuple[list[str], list[str]]:
    """Split a Particles-chapter heading into individual particle forms.

    Headings name one form ("γάρ") or several closely related forms
    ("δαί, δῆθεν, δήπου, δῆτα", "ἠδέ (AND ἰδε)", "οὐδέ, οὔτε (μηδέ,
    μήτε)"). Parenthesised content is a second list of forms (sometimes
    prefixed with the literal English "AND"), not a gloss, in every
    heading under this chapter -- verified by inspection of all 34 of
    them. A stray "<*>" is a source-encoding artifact (a missing
    ligature/accent glyph in the Perseus digitization) with no semantic
    content; it is stripped and reported.
    """
    notes: list[str] = []
    text = head_text
    if ARTIFACT_RE.search(text):
        notes.append("source contains literal '<*>' artifact (stripped)")
        text = ARTIFACT_RE.sub("", text)

    forms: list[str] = []

    def paren_sub(match: re.Match[str]) -> str:
        inner = re.sub(r"^AND\s+", "", match.group(1).strip())
        forms.extend(part.strip() for part in inner.split(",") if part.strip())
        return ""

    main = PAREN_RE.sub(paren_sub, text)
    forms = [part.strip() for part in main.split(",") if part.strip()] + forms
    return forms, notes


def find_smythp_range(elem: ET.Element) -> tuple[int, int] | None:
    numbers = []
    for node in elem.iter():
        if node.get("type") == "smythp" and node.get("n", "").isdigit():
            numbers.append(int(node.get("n")))
    if not numbers:
        return None
    return min(numbers), max(numbers)


def find_particles_chapter(root: ET.Element) -> ET.Element | None:
    part4 = find_div1(root, "4")
    if part4 is None:
        return None
    for div2 in part4.iter("div2"):
        head = div2.find("head")
        if head is not None and text_of(head) == "PARTICLES":
            return div2
    return None


def find_an_section(root: ET.Element) -> ET.Element | None:
    """'THE PARTICLE ἄν' lives outside the Particles chapter, under 'THE
    VERB: VOICES' -- ἄν is a modal particle attached to the verb system,
    not one of the connective/asseverative particles in Part IV's own
    Particles chapter. Found by heading text, not position, since div
    depth for this heading is not the same as the Particles subsections."""
    for div in root.iter():
        if div.tag.startswith("div"):
            head = div.find("head")
            if head is not None and text_of(head) == "THE PARTICLE ἄν":
                return div
    return None


def collect_primary_particles(
    root: ET.Element,
) -> tuple[dict[str, list[tuple[int, int]]], list[ET.Element], list[dict[str, object]]]:
    """Return {particle form: [(start, end), ...]}, the list of TEI elements
    claimed as 'primary' (excluded from the mention scan below, including
    their descendants), and a parse-notes log."""
    primary: dict[str, list[tuple[int, int]]] = {}
    excluded_roots: list[ET.Element] = []
    notes: list[dict[str, object]] = []

    chapter = find_particles_chapter(root)
    if chapter is None:
        raise RuntimeError("PARTICLES chapter not found in source")

    for div3 in chapter.findall("div3"):
        head = div3.find("head")
        if head is None:
            continue
        head_text = text_of(head)
        forms, parse_notes = parse_particle_forms(head_text)
        rng = find_smythp_range(div3)
        if rng is None or not forms:
            notes.append({"head": head_text, "issue": "no forms or no section range"})
            continue
        for form in forms:
            primary.setdefault(form, []).append(rng)
        excluded_roots.append(div3)
        if parse_notes:
            notes.append({"head": head_text, "notes": parse_notes, "forms": forms})

    an_section = find_an_section(root)
    if an_section is not None:
        rng = find_smythp_range(an_section)
        if rng is not None:
            primary.setdefault("ἄν", []).append(rng)  # ἄν
            excluded_roots.append(an_section)
    else:
        notes.append({"head": "THE PARTICLE ἄν", "issue": "not found"})

    return primary, excluded_roots, notes


def collect_mentions(
    root: ET.Element,
    particle_forms: list[str],
    excluded_roots: list[ET.Element],
    valid_sections: set[int],
) -> dict[str, set[int]]:
    """Scan every <head> in the document for occurrences of a particle's
    unaccented skeleton, outside the particle's own primary section(s).
    A hit's whole smythp range counts as a "mention" for every section it
    covers -- this is the "section heads mentioning a particle" source
    named in the brief, since no Greek back-of-book index survives in the
    digitization to draw mentions from instead."""
    excluded_ids = {id(e) for root_elem in excluded_roots for e in root_elem.iter()}
    skeleton_to_form: dict[str, list[str]] = {}
    for form in particle_forms:
        skeleton_to_form.setdefault(base_letters(form), []).append(form)

    mentions: dict[str, set[int]] = {form: set() for form in particle_forms}

    for div in root.iter():
        if not div.tag.startswith("div"):
            continue
        if id(div) in excluded_ids:
            continue
        head = div.find("head")
        if head is None:
            continue
        head_text = text_of(head)
        if not head_text:
            continue
        tokens = re.findall(r"[Ͱ-Ͽἀ-῿]+", head_text)
        token_skeletons = {base_letters(tok) for tok in tokens}
        hit_forms: set[str] = set()
        for skeleton in token_skeletons:
            hit_forms.update(skeleton_to_form.get(skeleton, []))
        if not hit_forms:
            continue
        rng = find_smythp_range(div)
        if rng is None:
            continue
        start, end = rng
        for form in hit_forms:
            for n in range(start, end + 1):
                if n in valid_sections:
                    mentions[form].add(n)

    return mentions


def assign_slugs(forms: list[str]) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Collision-free slug assignment. Forms sharing a bare transliteration
    (accent/breathing differences the slug can't carry, e.g. ἄρα vs ἆρα)
    are sorted by NFD codepoint order for determinism; the first keeps the
    bare slug, the rest get -2, -3, ..."""
    groups: dict[str, list[str]] = {}
    for form in forms:
        groups.setdefault(slugify_particle(form), []).append(form)

    slugs: dict[str, str] = {}
    collisions: list[dict[str, object]] = []
    for base_slug, members in groups.items():
        ordered = sorted(set(members), key=lambda w: unicodedata.normalize("NFD", w))
        if len(ordered) > 1:
            collisions.append({"slug": base_slug, "particles": ordered})
        for index, form in enumerate(ordered):
            slugs[form] = base_slug if index == 0 else f"{base_slug}-{index + 1}"

    return slugs, collisions


def build_particles(
    root: ET.Element, valid_sections: set[int]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    primary, excluded_roots, parse_notes = collect_primary_particles(root)
    forms = sorted(primary.keys(), key=collation_key)

    mentions = collect_mentions(root, forms, excluded_roots, valid_sections)
    slugs, collisions = assign_slugs(forms)

    particles: list[dict[str, object]] = []
    for form in forms:
        primary_sections: set[int] = set()
        for start, end in primary[form]:
            for n in range(start, end + 1):
                if n in valid_sections:
                    primary_sections.add(n)
                else:
                    parse_notes.append(
                        {"particle": form, "issue": f"primary range references missing section {n}"}
                    )
        mention_sections = mentions.get(form, set()) - primary_sections
        entries = [{"n": n, "role": "primary"} for n in sorted(primary_sections)]
        entries += [{"n": n, "role": "mention"} for n in sorted(mention_sections)]
        particles.append(
            {
                "particle": unicodedata.normalize("NFC", form),
                "slug": slugs[form],
                "sections": entries,
            }
        )

    meta = {
        "primarySource": (
            "TOC subsection headings under Part IV > PARTICLES (SS2769-3003), "
            "plus the standalone 'THE PARTICLE ἄν' heading under "
            "Part IV > THE VERB: VOICES (SS1761-1768)."
        ),
        "mentionSource": (
            "Every other <head> in the source whose text contains the "
            "particle's unaccented letter-skeleton; its whole printed "
            "section range is recorded as 'mention'. There is no digitized "
            "Greek back-of-book index to draw mentions from instead (see "
            "SPEC-landmarks.md)."
        ),
        "particleCount": len(particles),
        "slugCollisions": collisions,
        "parseNotes": parse_notes,
    }
    return particles, meta


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tei-source", type=Path, default=DEFAULT_TEI)
    parser.add_argument("--sections", type=Path, default=DEFAULT_SECTIONS)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not args.tei_source.exists():
        print(f"error: TEI source not found: {args.tei_source}", file=sys.stderr)
        return 1
    if not args.sections.exists():
        print(f"error: sections.jsonl not found: {args.sections}", file=sys.stderr)
        return 1

    root = parse_source(args.tei_source)
    valid_sections = load_valid_sections(args.sections)

    verbs, verbs_meta = extract_verbs(root, valid_sections)
    verbs.sort(key=lambda v: collation_key(v["lemma"]))
    verbs_meta["count"] = len(verbs)
    write_json(
        args.out_dir / "verbs.json",
        {
            "work": "smyth",
            "source": "Appendix: List of Verbs (TEI div1[@type='part'][@n='5'])",
            "collation": "greek-alphabet-order (see SPEC-landmarks.md)",
            "verbs": verbs,
            "_meta": verbs_meta,
        },
    )

    particles, particles_meta = build_particles(root, valid_sections)
    write_json(
        args.out_dir / "particles.json",
        {
            "work": "smyth",
            "particles": particles,
            "_meta": particles_meta,
        },
    )

    # index-english.json / index-greek.json are NOT written here.  They were
    # stubs when the print indexes were undigitized; index-english.json is now
    # built for real by build_index_english.py (index-greek to follow), and an
    # unconditional stub write here would clobber it.

    print(f"verbs: {len(verbs)} entries, {verbs_meta['letterGroups']} letter groups")
    print(f"particles: {len(particles)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
