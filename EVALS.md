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
