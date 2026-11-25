"""Render an offline parallel edition from validated sentence rows."""

from bisect import bisect_left
from collections import defaultdict
from html import escape
from itertools import groupby
import re
from urllib.parse import quote, urlsplit


# Keep CJK characters individually addressable in text without word separators.
_CJK = r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]"
_LETTER = rf"(?:(?!{_CJK})\w)"
_WORD = rf"{_LETTER}+(?:['’]{_LETTER}+)*"
_TOKEN = re.compile(rf"\[\[[^\[\]\r\n]+\]\]|\s+|{_CJK}|{_WORD}|[^\s]")
_IMAGE = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/]+={0,2}")


def _is_anchor(token):
    return token.startswith("[[") and token.endswith("]]")


def _anchor_html(token, anchors):
    anchor = anchors[token[2:-2]]
    label = escape(anchor["text"])
    kind = anchor["kind"]
    if kind == "link":
        href = anchor["href"]
        parsed = urlsplit(href)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or any(char.isspace() or ord(char) < 32 for char in href)):
            raise ValueError("A link anchor requires an HTTP or HTTPS URL.")
        return f'<a class="locked" href="{escape(href, quote=True)}">{label}</a>'
    tag = {"cite": "sup", "ref": "span", "em": "em", "strong": "strong"}[kind]
    return f'<{tag} class="locked">{label}</{tag}>'


def _lexical_positions(tokens):
    return [i for i, token in enumerate(tokens) if not token.isspace() and not _is_anchor(token)]


def _middle_matches(left, right):
    """Longest common subsequence with the least total token displacement."""
    if not left or not right:
        return []
    if len(left) != len(right):
        # For a pure insertion or deletion every short-side word can match.
        # Earliest ordered long-side matches minimize each displacement.
        reverse = len(left) > len(right)
        short, long = (right, left) if reverse else (left, right)
        pairs = []
        for j, word in enumerate(long):
            i = len(pairs)
            if short[i] == word:
                pairs.append((j, i) if reverse else (i, j))
                if len(pairs) == len(short):
                    return pairs
    # Each prefix score is (matched words, negative total displacement).
    # Keep two score rows and one traceback byte per cell.
    previous = [(0, 0)] * (len(right) + 1)
    traceback = []
    skip_left, skip_right, match = 1, 2, 3
    for i, source_word in enumerate(left, 1):
        current = [(0, 0)]
        steps = bytearray(len(right) + 1)
        for j, revised_word in enumerate(right, 1):
            best, step = previous[j], skip_left
            if current[j - 1] > best:
                best, step = current[j - 1], skip_right
            if source_word == revised_word:
                count, distance = previous[j - 1]
                paired = (count + 1, distance - abs(i - j))
                if paired >= best:
                    best, step = paired, match
            current.append(best)
            steps[j] = step
        previous = current
        traceback.append(steps)

    i, j = len(left), len(right)
    pairs = []
    while i and j:
        step = traceback[i - 1][j]
        if step == match:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif step == skip_left:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _word_matches(left, right):
    # An identical prefix matches at zero cost. So does an identical suffix
    # when both sentences have the same number of tokens.
    start = 0
    left_end, right_end = len(left), len(right)
    while start < min(left_end, right_end) and left[start] == right[start]:
        start += 1
    if left_end == right_end:
        while left_end > start and left[left_end - 1] == right[right_end - 1]:
            left_end -= 1
            right_end -= 1
    pairs = [(i, i) for i in range(start)]
    for i, j in _middle_matches(left[start:left_end], right[start:right_end]):
        pairs.append((start + i, start + j))
    pairs.extend((left_end + i, right_end + i) for i in range(len(left) - left_end))
    return pairs


def _neighbors(positions, rank):
    before = positions[rank - 1] if rank else None
    after = positions[rank] if rank < len(positions) else None
    return before, after


def _attachment(tokens, marker, lexical, aligned, rank):
    """Return each aligned neighbor's contact. A new neighbor masks only its own side."""
    before, after = _neighbors(lexical, bisect_left(lexical, marker))
    aligned_before, aligned_after = _neighbors(aligned, rank)
    left = right = None
    if before is not None and before == aligned_before:
        left = not any(t.isspace() for t in tokens[before + 1:marker])
    if after is not None and after == aligned_after:
        right = not any(t.isspace() for t in tokens[marker + 1:after])
    return left, right


def _changed_positions(left, right):
    """Compare words in reading order, then compare marker attachment."""
    positions = [_lexical_positions(tokens) for tokens in (left, right)]
    words = [[tokens[i] for i in indexes] for indexes, tokens in zip(positions, (left, right))]
    unmatched = [set(indexes) for indexes in positions]
    aligned_left, aligned_right = [], []
    matches = _word_matches(*words)
    matches.append((len(words[0]), len(words[1])))
    previous_a = previous_b = -1
    for a, b in matches:
        # A single unmatched word between two matches (or sentence boundaries)
        # on each side is an aligned substitution. Its wording stays marked.
        if a - previous_a == b - previous_b == 2:
            aligned_left.append(positions[0][a - 1])
            aligned_right.append(positions[1][b - 1])
        if a < len(words[0]):
            i, j = positions[0][a], positions[1][b]
            unmatched[0].remove(i)
            unmatched[1].remove(j)
            aligned_left.append(i)
            aligned_right.append(j)
        previous_a, previous_b = a, b

    right_anchors = {token: i for i, token in enumerate(right) if _is_anchor(token)}
    for i, token in enumerate(left):
        if not _is_anchor(token):
            continue
        j = right_anchors[token]
        old_rank = bisect_left(aligned_left, i)
        new_rank = bisect_left(aligned_right, j)
        moved = old_rank != new_rank
        if not moved:
            old = _attachment(left, i, positions[0], aligned_left, old_rank)
            new = _attachment(right, j, positions[1], aligned_right, new_rank)
            moved = any(a != b for a, b in zip(old, new) if a is not None and b is not None)
        if moved:
            unmatched[0].add(i)
            unmatched[1].add(j)
    return unmatched


def _text_html(tokens, anchors, changed, edit_tag):
    parts = []
    for i, token in enumerate(tokens):
        markup = _anchor_html(token, anchors) if _is_anchor(token) else escape(token)
        if i in changed:
            markup = f'<{edit_tag} class="delta">{markup}</{edit_tag}>'
        parts.append(markup)
    return "".join(parts)


def _pair_html(row):
    key = escape(row["id"], quote=True)
    where = escape(row["locator"])
    kind = row.get("kind", "prose")
    if kind not in {"prose", "fixed", "locator"}:
        raise ValueError("Unknown row kind.")
    text = row["text"]
    final = row.get("final", text) if kind == "prose" else text
    left, right = _TOKEN.findall(text), _TOKEN.findall(final)
    changed = _changed_positions(left, right) if text != final else (set(), set())
    anchors = row.get("anchors", {})
    source = _text_html(left, anchors, changed[0], "del")
    revision = _text_html(right, anchors, changed[1], "ins")
    audit = row.get("audit") or {}
    status = {"fixed": "Verbatim", "locator": "Location only"}.get(kind)
    if status is None and audit.get("verdict") == "flag":
        status = f'<a href="#note-{quote(row["id"], safe="")}">Review note</a>'
    status_html = f'<span class="status">{status}</span>' if status else ""
    focus = ' tabindex="0"' if changed[0] or changed[1] else ""
    return (
        f'<div class="pair {kind}" id="pair-{key}" role="group" aria-label="{where}">'
        f'<div class="row-meta"><span>{where}</span>{status_html}</div>'
        f'<div class="source" role="group" aria-label="Original"><p class="sentence" dir="auto">{source}</p></div>'
        f'<div class="revision" role="group" aria-label="Revision"{focus}><p class="sentence" dir="auto">{revision}</p></div>'
        '</div>'
    )


def _figure_html(figure):
    src = figure["src"]
    if not _IMAGE.fullmatch(src):
        raise ValueError("A figure requires an embedded PNG or JPEG.")
    return f'<figure><img src="{src}" alt="{escape(figure["alt"], quote=True)}" loading="lazy"></figure>'


def _review_html(flags):
    if not flags:
        return ""
    notes = []
    for row in flags:
        audit = row["audit"]
        key = escape(row["id"], quote=True)
        decision = {"source": "Original restored", "keep": "Revision retained"}[audit["decision"]]
        fields = []
        for label, field in (("Original excerpt", "source_quote"), ("Draft excerpt", "draft_quote")):
            # Reviewers quote the input packets. Expand their protected markers
            # when a whole marker is present in the quote.
            anchors = row.get("anchors", {})
            excerpt = "".join(
                _anchor_html(token, anchors) if _is_anchor(token) and token[2:-2] in anchors
                else escape(token) for token in _TOKEN.findall(audit[field])
            )
            fields.append(f'<dt>{label}</dt><dd class="excerpt" dir="auto">{excerpt}</dd>')
        notes.append(
            f'<article class="note" id="note-{key}"><h3><a href="#pair-{quote(row["id"], safe="")}">{escape(row["locator"])}</a></h3>'
            f'<dl><dt>Review verdict</dt><dd>Flagged</dd><dt>Reviewer’s reason</dt><dd>{escape(audit["reason"])}</dd>'
            f'{"".join(fields)}<dt>Decision</dt><dd>{decision}</dd>'
            f'<dt>Decision reason</dt><dd>{escape(audit["decision_reason"])}</dd></dl></article>'
        )
    return '<section class="review" id="review-notes"><h2>Review notes</h2>' + "".join(notes) + '</section>'


_STYLE = """
:root {
  color-scheme: light dark;
  --paper: #f8f7f3; --sheet: #fffefa; --ink: #242623; --muted: #555e57;
  --rule: #d3d6cc; --heavy: #838c81; --link: #245f52;
  --old-bg: #ffe2d9; --old-ink: #6c221b; --new-bg: #d6efdf; --new-ink: #124331;
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  --sans: "Avenir Next", Avenir, system-ui, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; color: var(--ink); background: var(--paper); font: 1rem/1.55 var(--sans); }
main { max-width: 82rem; margin: 0 auto; padding: clamp(1rem, 4vw, 4rem); }
header { padding-block: 1rem 1.7rem; border-bottom: 2px solid var(--ink); }
h1, h2, h3, p, figure, dl, dd { margin: 0; }
h1 { max-width: 34ch; font: 500 clamp(2rem, 4vw, 3.6rem)/1.08 var(--serif); text-wrap: balance; }
h1, h2, h3, p, dt, dd, .row-meta, img { overflow-wrap: anywhere; }
.guide { color: var(--muted); margin-top: 1rem; max-width: 68ch; }
.note-jump { display: inline-block; margin-top: .6rem; }
a { color: var(--link); text-underline-offset: .15em; }
:focus-visible { outline: 2px solid var(--link); outline-offset: 3px; }
.headings, .pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: clamp(1.5rem, 5vw, 5rem); }
.headings { padding: 1.1rem 0 .8rem; border-bottom: 1px solid var(--heavy); font-weight: 650; }
.paragraph { padding-block: .65rem 1rem; border-bottom: 1px solid var(--rule); }
.pair { padding-block: .4rem; scroll-margin-block: 1.5rem; }
.row-meta { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: .25rem 1rem; align-items: baseline;
  margin-bottom: .18rem; font: 500 .76rem/1.4 var(--sans); color: var(--muted); }
.status { font-weight: 650; }
.sentence { white-space: pre-wrap; font: 400 clamp(1.04rem, 1.45vw, 1.23rem)/1.55 var(--serif); }
.source, .revision { min-width: 0; }
.locked:is(sup) { font: 600 .68em/0 var(--sans); vertical-align: super; }
.fixed .sentence, .locator .sentence { font-size: 1rem; }
.locator .sentence { font-style: italic; }
:where(del, ins).delta { text-decoration: none; color: inherit; background: transparent; }
.pair:has(.revision:hover, .revision:focus-within, .revision:active) del.delta {
  color: var(--old-ink); background: var(--old-bg); text-decoration: line-through; }
.pair:has(.revision:hover, .revision:focus-within, .revision:active) ins.delta {
  color: var(--new-ink); background: var(--new-bg); text-decoration: underline; text-underline-offset: .15em; }
.pair:has(.revision:hover, .revision:focus-within, .revision:active) .delta > .locked {
  color: inherit; background-color: inherit; text-decoration: inherit; }
figure { padding-block: 1rem; }
figure img { display: block; max-width: 100%; max-height: 60rem; width: auto; height: auto; margin: auto; }
.review { padding-block: 2.5rem 1rem; }
.review h2 { font: 500 2rem/1.15 var(--serif); }
.note { margin-top: 1rem; padding: 1.2rem; border: 1px solid var(--rule); background: var(--sheet); }
.note h3 { font: 650 .95rem/1.4 var(--sans); margin-bottom: .8rem; }
.note dl { display: grid; grid-template-columns: minmax(7rem, 10rem) minmax(0, 1fr); gap: .4rem 1.5rem; }
.note dt { color: var(--muted); font-size: .87rem; }
.note .excerpt { white-space: pre-wrap; font: 1.05rem/1.45 var(--serif); }
@media (prefers-color-scheme: dark) {
  :root { --paper: #1d211e; --sheet: #242925; --ink: #eeeae3; --muted: #b4bdb4;
    --rule: #455047; --heavy: #7e8d7f; --link: #a9d9c8;
    --old-bg: #603831; --old-ink: #ffded4; --new-bg: #224e3d; --new-ink: #d4f3e2; }
}
@media screen and (max-width: 42rem) {
  main { padding: 1rem; }
  .headings { display: none; }
  .pair { grid-template-columns: minmax(0, 1fr); gap: .55rem; padding-block: .85rem; }
  .paragraph { padding-block: .25rem; }
  .row-meta { margin: 0; }
  .source::before, .revision::before { display: block; font: 600 .75rem/1.4 var(--sans); color: var(--muted); }
  .source::before { content: 'Original'; } .revision::before { content: 'Revision'; }
  .note dl { display: block; } .note dt:not(:first-child) { margin-top: .55rem; }
}
@media print {
  :root { color-scheme: light; --paper: white; --sheet: white; --ink: black; --link: black;
    --muted: #333; --rule: #aaa; --heavy: #555; }
  main { max-width: none; padding: 0; }
  h1 { font-size: 24pt; }
  .guide, .note-jump { display: none; }
  .pair, .headings { column-gap: 1.5rem; }
  .pair, figure, .note { break-inside: avoid; }
  .sentence, .fixed .sentence, .locator .sentence { font-size: 10pt; }
  .row-meta { font-size: 8pt; }
  del.delta { text-decoration: line-through; } ins.delta { text-decoration: underline; }
  .review { padding-top: 1.5rem; }
  figure img { max-height: 80vh; }
}
"""


def render(title, rows, figures):
    """Return one self-contained comparison document in canonical row order."""
    rows = list(rows)
    flags = [row for row in rows if (row.get("audit") or {}).get("verdict") == "flag"]
    after = defaultdict(list)
    for figure in figures:
        after[figure["after"]].append(_figure_html(figure))
    paragraphs = []
    for _, group in groupby(rows, key=lambda row: row["paragraph"]):
        content = []
        for row in group:
            content.append(_pair_html(row))
            content.extend(after.get(row["id"], ()))
        paragraphs.append('<div class="paragraph">' + "".join(content) + '</div>')
    title = escape(title)
    jump = ""
    if flags:
        label = "review note" if len(flags) == 1 else "review notes"
        jump = f'<a class="note-jump" href="#review-notes">{len(flags)} {label}</a>'
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title}</title><style>{_STYLE}</style></head><body><main>'
        f'<header><h1 dir="auto">{title}</h1><p class="guide">Hover over a revision, tap it, '
        'or reach it with the Tab key to see edits and moved references in both columns.</p>'
        f'{jump}</header><div class="headings" aria-hidden="true"><span>Original</span><span>Revision</span></div>'
        f'{"".join(paragraphs)}{_review_html(flags)}</main></body></html>\n'
    )
