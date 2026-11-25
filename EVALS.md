# Evaluation

Run `python3 -m unittest discover -s tests -v` from the checkout. The fixtures are invented transit notices. They require Python 3.10 or later and run offline.

## Reading copy and private notes

An author needs an accurate reading copy. An editor investigating a flag also needs the rejected draft and the decision that restored the original. These are distinct outputs.

| Case | Observable result |
| --- | --- |
| Unlabelled editing and review receipts | A complete run builds using only the `rows` envelope. Missing or stale rows still fail validation. |
| Source PDF fingerprint | The manifest retains the digest. A direct search of both packet types and the reading HTML cannot find it. |
| Rejected edit | The two columns show the accepted text. The rejected phrase and two private reasons are absent from the entire HTML file. |
| Private notes requested | The notes edition includes flagged excerpts, with superscript citations preserved. |
| Older labelled run | Matching labels work across both passes. A missing or different label fails when the run expects it. The label stays out of the HTML. |

## Comparison

Three new checks failed on the initial release: unlabelled receipts, omission of the raw PDF digest, and omission of private evidence. The same scenarios pass in the revised release. The full suite also exercises word-level changes, citation placement, fixed text, stale reviews, unresolved flags, and overwrite protection.

These are deterministic acceptance checks. The pass criterion is exact presence or absence in generated files, or acceptance or rejection by the CLI. There is no sampled or held-out estimate of editing quality. A claim about better English would require a separate blind comparison of independently edited texts and checks for meaning drift.

## Blind reading before source comparison

The fictional tram demo records the first wording and the reader’s observations separately. “Carries out a listing” is a fluency flag. A different sentence, “The timetable change caused a shorter wait,” reads smoothly but strengthens the original claim. The final edition resolves each problem against the source.

The CLI tests inspect the blind packet itself: only neutral IDs, fingerprints and candidate paragraph text are present. They check that unchanged neighboring sentences and visible reference labels survive. Missing, duplicate, stale or unsupported first-reading evidence fails validation. A paragraph flagged for readability enters the source comparison even when its wording was unchanged. First-reading reasons stay out of the HTML.

In a separate fictional depot notice, a draft-only reader flagged “make the communication of route changes” and suggested “show route changes.” The sentence about shorter boarding times sounded natural. On seeing the original, the reviewer found that the draft attributed the shorter times to a newly installed reader. The final comparison kept the clearer wording in the first paragraph and restored the cited observation in the second. The source gave no device type or explanation for a closed door, so neither was added.
