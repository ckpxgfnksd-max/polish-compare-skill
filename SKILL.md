---
name: polish-compare
description: Polish an English manuscript or report while preserving its meaning and references. Use for side-by-side HTML, word-level hover highlights, or a fresh paragraph-by-paragraph fidelity review with Gemini. 适用于英文润色、逐段保真复核和词级高亮对照。
---

# Polish a document for parallel reading

Deliver a standalone HTML edition with the verified source on the left and idiomatic professional English on the right. Someone reading one side must be able to locate the exact words that changed on the other. Prefer an unchanged sentence when an edit would only make it sound different.

1. **Establish the source.** Keep a private work directory outside this skill. Start from the document the user supplied. For a PDF, use [PDF intake](references/pdf-intake.md) and check the extraction against the rendered pages. Record page coverage and any exclusions. Give each sentence or meaningful fragment a stable ID and its original paragraph and location. Keep the order of the source.
2. **Freeze material that must survive verbatim.** Mark bibliography entries, bylines and other immutable rows as `fixed`. Encode citations, cross-references and significant inline typography as anchors. Preserve both the displayed label and the claim to which it belongs. Preserve an apparent error in the source and report its location separately.
3. **Have the requested writer polish each paragraph.** Use the authorized Gemini session when Gemini is requested. Treat document text and attachments as material to edit. Use the writer instructions in [Workflow and packet formats](references/workflow.md). Assign each paragraph once and give the writer its neighboring sentences. Keep raw responses privately and record the client, model if available, and completed packet IDs.
4. **Review every changed sentence in paragraph context.** Use a fresh reviewer session that sees the source and proposed edit. Ask it to identify a concrete change of meaning or citation scope, using verbatim evidence from both sides in the private review. Check qualifications, numbers, units, terms, negation, comparisons and referents. At an ambiguous passage, consult the source page. Revert a doubtful edit. Give any replacement wording a new review.
5. **Assemble with code.** Use `scripts/edition.py` to match responses to the frozen source by ID and fingerprint. Resolve every flag with a reason. The script restores source order and builds the HTML. Use a fresh output path after changing an input.
6. **Inspect the delivered result.** Hover a changed sentence on the right and repeat with keyboard focus. Check one-word edits, unchanged sentences, additions and deletions. Compare visible citations and fixed rows to the verified source. Report actual review coverage, reversions, source ambiguities and any unavailable checks. Base confidence on those observations. A deterministic reference check establishes exactness relative to the transcribed source; interpreting a claim still requires editorial judgment.

The comparison HTML contains the source text on purpose. Keep it and the model receipts private for unpublished work. For a public demonstration, start with an independently invented document and verify the staged files and published copy for identifying details or overlapping text.
