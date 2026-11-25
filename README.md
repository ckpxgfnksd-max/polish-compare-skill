# Polish Compare

A skill for editing English without losing the author's meaning. It produces a self-contained HTML reading copy. Hover a sentence on the right to see precisely what changed on both sides. If one word changed, just that word lights up in each column. Keyboard focus works too.

The workflow takes a verified source, asks Gemini to polish it paragraph by paragraph, and asks a fresh Gemini session to check each edit. A local Python program matches the results, enforces citation markers and assembles the edition. The writer, reviewer and final editor have distinct jobs.

## Try the offline example

Python 3.10 or newer is required. From the repository root, run:

```sh
python3 examples/demo.py ./work/demo
```

Open `work/demo/comparison.html` in your browser. The invented tram notice includes a one-word edit, untouched sentences, and a rejected edit that turned an observation into a causal claim. The example uses scripted receipts labeled `Fixture`. It runs locally without an account or API key.

## Use the skill

Clone this repository into a skills directory your agent reads. For example:

```sh
git clone https://github.com/ckpxgfnksd-max/polish-compare-skill.git ~/.agents/skills/polish-compare
```

Then invoke `$polish-compare` and supply the private document and the Gemini session or integration authorized to process it. For example:

> 用 Gemini 逐段润色这份英文稿，保留原意和引用。另开会话复核每处改动，最后生成左右对照 HTML，只高亮改过的词。

The helper scripts work offline. The agent runs the two model passes through the authorized client and saves the returned JSON. If a model pass is unavailable, keep its coverage open and report it. For a text-based PDF, the optional importer also requires Poppler's `pdftotext`.

[Skill instructions](SKILL.md) · [PDF intake](references/pdf-intake.md) · [Model prompts, commands and formats](references/workflow.md) · [MIT license](LICENSE)

## Working with an unpublished document

Keep originals, responses, rendered comparisons and review notes in a private directory outside the checkout. A comparison contains both editions, and either edition can identify the document. Public examples should be written from scratch on an unrelated subject.

## Check a checkout

```sh
python3 -m unittest discover -s tests
```
