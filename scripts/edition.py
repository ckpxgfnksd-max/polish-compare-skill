#!/usr/bin/env python3
"""Prepare editing packets and assemble verified responses into a parallel edition."""

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys
import tempfile
from urllib.parse import urlsplit


class Invalid(ValueError):
    """An input or an existing destination does not meet the edition contract."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid(f"Duplicate JSON key {key!r}")
        result[key] = value
    return result


def read_json(path):
    if not path.is_file():
        raise Invalid(f"Expected a JSON file at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (UnicodeError, ValueError) as error:
        raise Invalid(f"{path}: {error}") from error


def fields(value, required, optional, where):
    if not isinstance(value, dict):
        raise Invalid(f"{where}: expected a JSON object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        raise Invalid(f"{where}: missing fields {sorted(missing)}, unexpected fields {sorted(extra)}")
    return value


def array(value, where):
    if not isinstance(value, list):
        raise Invalid(f"{where}: expected an array")
    return value


def nonempty(value, where):
    if not isinstance(value, str) or not value.strip():
        raise Invalid(f"{where}: expected nonempty text")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", value):
        raise Invalid(f"{where}: invalid control character or Unicode surrogate")
    return value


def fingerprint(*values):
    serialized = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


KEY = r"[A-Za-z_][A-Za-z0-9_.-]*"
TOKEN = re.compile(r"\[\[(" + KEY + r")\]\]")


def anchor_order(text, where):
    residue = TOKEN.sub("", text)
    if "[[" in residue or "]]" in residue:
        raise Invalid(f"{where}: malformed anchor token")
    return TOKEN.findall(text)


def check_link(href, where):
    href = nonempty(href, where)
    if "\\" in href or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in href):
        raise Invalid(f"{where}: expected an HTTP or HTTPS URL")
    try:
        parts = urlsplit(href)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            raise Invalid(f"{where}: expected an absolute HTTP or HTTPS URL")
        _ = parts.port  # Access also validates an optional port.
    except ValueError as error:
        raise Invalid(f"{where}: invalid HTTP or HTTPS URL") from error


def validate_anchors(anchors, text, where):
    if not isinstance(anchors, dict):
        raise Invalid(f"{where}: anchors must be an object")
    order = anchor_order(text, where)
    if len(order) != len(anchors) or set(order) != anchors.keys():
        raise Invalid(f"{where}: every defined anchor must appear exactly once")
    for key, anchor in anchors.items():
        label = f"{where} anchor {key!r}"
        fields(anchor, ("kind", "text"), ("href",), label)
        kind = anchor["kind"]
        if kind not in ("cite", "ref", "em", "strong", "link"):
            raise Invalid(f"{label}: unsupported kind")
        nonempty(anchor["text"], label)
        if kind == "link":
            check_link(anchor.get("href"), label)
        elif "href" in anchor:
            raise Invalid(f"{label}: only links accept href")


def source_rows(raw):
    rows = []
    seen_rows = set()
    seen_paragraphs = set()
    for index, item in enumerate(array(raw, "rows"), 1):
        where = f"source row {index}"
        fields(item, ("id", "paragraph", "locator", "text"), ("kind", "anchors"), where)
        row = {"kind": "prose", "anchors": {}, **item}
        for key in ("id", "paragraph", "locator", "text"):
            nonempty(row[key], f"{where} {key}")
        row_id, paragraph = row["id"], row["paragraph"]
        if not re.fullmatch(KEY, row_id):
            raise Invalid(f"{where}: invalid row ID {row_id!r}")
        if row_id in seen_rows:
            raise Invalid(f"Duplicate source row ID {row_id!r}")
        if paragraph in seen_paragraphs and rows[-1]["paragraph"] != paragraph:
            raise Invalid(f"Paragraph {paragraph!r} is not contiguous")
        if row["kind"] not in ("prose", "fixed", "locator"):
            raise Invalid(f"{where}: unsupported row kind")
        validate_anchors(row["anchors"], row["text"], where)
        rows.append(row)
        seen_rows.add(row_id)
        seen_paragraphs.add(paragraph)
    if not rows:
        raise Invalid("Source rows must contain at least one row")
    return rows


def read_figure(root, name):
    path = Path(name)
    if (path.is_absolute() or PureWindowsPath(name).drive or "\\" in name
            or ".." in path.parts or ":" in name):
        raise Invalid(f"Expected a local relative figure path, got {name!r}")
    actual = (root / path).resolve()
    if not actual.is_relative_to(root) or not actual.is_file():
        raise Invalid(f"Missing figure or figure outside the source directory: {name!r}")
    suffix = path.suffix.lower()
    data = actual.read_bytes()
    if suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", data
    if suffix in (".jpg", ".jpeg") and data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", data
    raise Invalid(f"Figure must have a matching PNG or JPEG signature and extension: {name!r}")


def load_source(path, embed=False):
    source = fields(read_json(path), ("title", "rows"), ("figures", "pdf_sha256"), "source")
    nonempty(source["title"], "title")
    source["rows"] = source_rows(source["rows"])
    if "pdf_sha256" in source:
        digest = nonempty(source["pdf_sha256"], "pdf_sha256")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise Invalid("pdf_sha256 must contain 64 hexadecimal digits")
        source["pdf_sha256"] = digest.lower()
    ids = {row["id"] for row in source["rows"]}
    figures = []
    root = path.parent.resolve()
    for index, figure in enumerate(array(source.get("figures", []), "figures"), 1):
        where = f"figure {index}"
        fields(figure, ("after", "alt", "file"), (), where)
        for key in ("after", "alt", "file"):
            nonempty(figure[key], f"{where} {key}")
        if figure["after"] not in ids:
            raise Invalid(f"{where}: unknown insertion row {figure['after']!r}")
        mime, data = read_figure(root, figure["file"])
        if embed:
            encoded = base64.b64encode(data).decode("ascii")
            figures.append({"after": figure["after"], "alt": figure["alt"],
                            "src": f"data:{mime};base64,{encoded}"})
    return source, figures


def paragraph_context(source, drafts=None):
    contexts = {}
    for row in source["rows"]:
        if row["kind"] == "locator":
            continue
        entry = {"id": row["id"], "kind": row["kind"], "locator": row["locator"],
                 "source": row["text"], "anchors": row["anchors"]}
        if drafts is not None:
            entry["draft"] = drafts.get(row["id"], row["text"])
        contexts.setdefault(row["paragraph"], []).append(entry)
    return contexts


def editing_rows(source, contexts):
    rows = {}
    for paragraph_id, paragraph in contexts.items():
        basis = fingerprint("polish-v2", source["title"], source.get("pdf_sha256"),
                            paragraph_id, paragraph)
        for row in paragraph:
            if row["kind"] != "prose":
                continue
            rows[row["id"]] = {
                "id": row["id"], "paragraph": paragraph_id, "locator": row["locator"],
                "source": row["source"], "anchors": row["anchors"],
                "basis": fingerprint(basis, row["id"]),
            }
    return rows


def load_responses(directory, expected, provider, phase):
    if not directory.is_dir():
        raise Invalid(f"Expected a {phase} response directory at {directory}")
    records = {}
    for path in sorted(directory.glob("*.json")):
        response = fields(read_json(path), ("provider", "rows"), (), str(path))
        declared = nonempty(response["provider"], f"{path} provider")
        if declared.casefold() != provider.casefold():
            raise Invalid(f"{path}: expected provider {provider!r}, got {declared!r}")
        for record in array(response["rows"], f"{path} rows"):
            required = ("id", "basis", "text") if phase == "draft" else ("id", "basis", "verdict")
            optional = () if phase == "draft" else ("reason", "source_quote", "draft_quote")
            fields(record, required, optional, str(path))
            row_id = nonempty(record["id"], f"{path} id")
            if row_id not in expected:
                raise Invalid(f"{path}: unexpected {phase} row {row_id!r}")
            if row_id in records:
                raise Invalid(f"{path}: duplicate {phase} for {row_id!r}")
            if record["basis"] != expected[row_id]["basis"]:
                raise Invalid(f"{path}: stale {phase} basis for {row_id!r}")
            records[row_id] = record
    missing = expected.keys() - records.keys()
    if missing:
        raise Invalid(f"Missing {phase} responses for {sorted(missing)}")
    return records


def read_drafts(directory, editable, provider):
    records = load_responses(directory, editable, provider, "draft")
    drafts = {}
    for row_id, record in records.items():
        text = nonempty(record["text"], f"{row_id} draft")
        if anchor_order(text, row_id) != anchor_order(editable[row_id]["source"], row_id):
            raise Invalid(f"{row_id}: the draft must preserve each anchor once, in source order")
        drafts[row_id] = text
    return drafts


def review_rows(source, editable, drafts):
    contexts = paragraph_context(source, drafts)
    context_bases = {key: fingerprint(context) for key, context in contexts.items()}
    changed = {}
    for row_id, row in editable.items():
        draft = drafts[row_id]
        if draft != row["source"]:
            changed[row_id] = {**row, "draft": draft,
                               "basis": fingerprint("review-v1", row["basis"], draft,
                                                    context_bases[row["paragraph"]])}
    return changed, contexts


def packets(source, assigned, phase, size, contexts):
    groups = {}
    for row in assigned.values():
        groups.setdefault(row["paragraph"], []).append(row)
    batch = []
    for group in groups.values():
        if batch and len(batch) + len(group) > size:
            yield packet(source, phase, batch, contexts)
            batch = []
        batch.extend(group)
    if batch:
        yield packet(source, phase, batch, contexts)


def packet(source, phase, batch, contexts):
    result = {"phase": phase, "title": source["title"], "rows": batch}
    if "pdf_sha256" in source:
        result["pdf_sha256"] = source["pdf_sha256"]
    paragraphs = dict.fromkeys(row["paragraph"] for row in batch)
    result["context"] = [{"paragraph": p, "rows": contexts[p]} for p in paragraphs]
    return result


def matching_directory(destination, contents):
    if destination.is_symlink() or not destination.is_dir():
        return False
    paths = list(destination.iterdir())
    if {p.name for p in paths} != contents.keys():
        return False
    return all(not p.is_symlink() and p.is_file() and p.read_bytes() == contents[p.name]
               for p in paths)


def write_packets(destination, generated):
    contents = {}
    for number, item in enumerate(generated, 1):
        data = json.dumps(item, ensure_ascii=False, indent=2) + "\n"
        contents[f"{number:03d}.json"] = data.encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if matching_directory(destination, contents):
        return
    if destination.is_symlink() or (destination.exists() and
            (not destination.is_dir() or any(destination.iterdir()))):
        raise Invalid(f"Packet destination contains other work: {destination}")
    with tempfile.TemporaryDirectory(dir=destination.parent) as workspace:
        stage = Path(workspace) / "packets"
        stage.mkdir()
        for name, data in contents.items():
            (stage / name).write_bytes(data)
        try:
            stage.rename(destination)
        except OSError:
            if not matching_directory(destination, contents):
                raise


def verify_verdicts(records, changed):
    for row_id, record in records.items():
        verdict = record["verdict"]
        if verdict not in ("pass", "flag"):
            raise Invalid(f"{row_id}: verdict must be pass or flag")
        if verdict == "flag":
            nonempty(record.get("reason"), f"{row_id} flag reason")
        for side in ("source", "draft"):
            key = side + "_quote"
            if verdict == "flag" or key in record:
                quote = nonempty(record.get(key), f"{row_id} {key}")
                if quote not in changed[row_id][side]:
                    raise Invalid(f"{row_id}: {key} is absent from the {side} text")
        if "reason" in record:
            nonempty(record["reason"], f"{row_id} reason")


def read_decisions(path, verdicts):
    decisions = {} if path is None else read_json(path)
    if not isinstance(decisions, dict):
        raise Invalid("Decisions must be an object keyed by flagged row ID")
    flags = {key for key, value in verdicts.items() if value["verdict"] == "flag"}
    if flags != decisions.keys():
        raise Invalid(f"Decisions must cover every flag exactly: missing {sorted(flags - decisions.keys())}, "
                      f"unexpected {sorted(decisions.keys() - flags)}")
    for row_id, decision in decisions.items():
        fields(decision, ("basis", "action", "reason"), (), f"{row_id} decision")
        if decision["basis"] != verdicts[row_id]["basis"]:
            raise Invalid(f"{row_id}: stale decision basis for flagged passage")
        if decision["action"] not in ("source", "keep"):
            raise Invalid(f"{row_id}: action must be source or keep")
        nonempty(decision["reason"], f"{row_id} decision reason")
    return decisions


def final_rows(source, drafts, verdicts, decisions):
    rows = []
    for row in source["rows"]:
        row_id = row["id"]
        final = drafts.get(row_id, row["text"])
        audit = None
        if row_id in verdicts:
            record = verdicts[row_id]
            audit = {key: record[key] for key in ("verdict", "reason", "source_quote", "draft_quote")
                     if key in record}
        if row_id in decisions:
            decision = decisions[row_id]
            audit.update(decision=decision["action"], decision_reason=decision["reason"])
            if decision["action"] == "source":
                final = row["text"]
        rows.append({**row, "final": final, "audit": audit})
    return rows


def publish_html(path, document):
    if path.suffix.lower() not in (".html", ".htm"):
        raise Invalid("The output filename must end in .html or .htm")
    data = document.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as workspace:
        stage = Path(workspace) / "edition"
        stage.write_bytes(data)
        try:
            os.link(stage, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise Invalid(f"Output already exists with other content: {path}") from None


def positive_size(value):
    size = int(value)
    if size < 1:
        raise argparse.ArgumentTypeError("batch size must be positive")
    return size


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("pack", "review", "build"):
        command = commands.add_parser(name)
        command.add_argument("source", type=Path)
        if name != "pack":
            command.add_argument("drafts", type=Path)
            command.add_argument("--provider", default="Gemini",
                                 help="Expected provider label on responses (default: Gemini)")
        if name == "build":
            command.add_argument("verdicts", type=Path)
            command.add_argument("output", type=Path)
            command.add_argument("--decisions", type=Path)
        else:
            command.add_argument("packets_dir", type=Path)
            command.add_argument("--batch-size", type=positive_size, default=24)
    return parser.parse_args()


def load_renderer():
    path = Path(__file__).resolve().with_name("render_html.py")
    spec = importlib.util.spec_from_file_location("render_html", path)
    if spec is None or spec.loader is None:
        raise Invalid(f"Cannot load the edition renderer at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render


def run(args):
    source, figures = load_source(args.source, embed=args.command == "build")
    context = paragraph_context(source)
    editable = editing_rows(source, context)
    if args.command == "pack":
        write_packets(args.packets_dir, packets(source, editable, "polish", args.batch_size, context))
        return
    provider = nonempty(args.provider, "--provider")
    drafts = read_drafts(args.drafts, editable, provider)
    changed, contexts = review_rows(source, editable, drafts)
    if args.command == "review":
        write_packets(args.packets_dir, packets(source, changed, "review", args.batch_size, contexts))
        return
    verdicts = load_responses(args.verdicts, changed, provider, "verdict")
    verify_verdicts(verdicts, changed)
    decisions = read_decisions(args.decisions, verdicts)
    render = load_renderer()
    document = render(source["title"], final_rows(source, drafts, verdicts, decisions), figures)
    if "pdf_sha256" in source:
        # The digest is validated hexadecimal and never carries a local filename.
        marker = '<meta name="source-pdf-sha256" content="' + source["pdf_sha256"] + '">'
        document = document.replace("</head>", marker + "\n</head>", 1)
    publish_html(args.output, document)


if __name__ == "__main__":
    try:
        run(arguments())
    except (Invalid, OSError, RuntimeError) as error:
        sys.exit(f"edition: {error}")
