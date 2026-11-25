# Polish Compare

Read an English original beside its edited version. Hover over a revised sentence or focus it with the keyboard. A one-word replacement highlights one word in each column. Unchanged sentences stay plain.

The writer edits each paragraph in context. An independent reader checks every changed sentence against the original, including which claim each reference supports. A local script matches the responses by sentence ID, verifies the citation markers, and builds one offline HTML file.

## Try it

With Python 3.10 or later, run this command from the checkout.

```sh
python3 examples/demo.py ./work/demo
```

Open `work/demo/comparison.html`. The fictional tram notice includes a one-word edit and a rejected rewrite that turned an observation into a causal claim. The example uses scripted responses and runs offline.

## Install

Clone the repository into your skills directory.

```sh
git clone https://github.com/ckpxgfnksd-max/polish-compare-skill.git ~/.agents/skills/polish-compare
```

> 用 $polish-compare 逐段润色这份英文稿，保留原意和引用。逐句复核改动，输出只高亮改动词的左右对照 HTML。

The reading copy contains the original text and accepted edits. Keep unpublished work in a private directory outside the checkout. If another editor needs to inspect rejected wording, build a separate private copy with `--review-notes`. A public demonstration should use a newly written example on an unrelated subject.

[Skill instructions](SKILL.md) · [PDF intake](references/pdf-intake.md) · [Commands and response formats](references/workflow.md) · [Evaluation cases](EVALS.md) · [MIT license](LICENSE)
