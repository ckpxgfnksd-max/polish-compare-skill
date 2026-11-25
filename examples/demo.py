"""Build an offline example using explicitly scripted writer and reviewer responses."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).with_name("source.json")
REVISIONS = {
    "s001": "The northbound tram leaves daily.",
    "s003": "The timetable change caused a shorter wait[[note]].",
    "s004": "Riders can use the kiosk to print a pass.",
    "s005": "This ticket lists stop names in alphabetical order.",
}


def receipt(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def edition(*args):
    subprocess.run([sys.executable, str(ROOT / "scripts" / "edition.py"), *map(str, args)], check=True)


def scripted_rows(packets):
    for packet in sorted(packets.glob("*.json")):
        yield from json.loads(packet.read_text(encoding="utf-8"))["rows"]


def read_without_source(target, drafts, prefix):
    packets = target / (prefix + "-blind-packets")
    notes = target / (prefix + "-blind-notes")
    notes.mkdir()
    edition("blind", SOURCE, drafts, packets)
    results = []
    for row in scripted_rows(packets):
        item = {"id": row["id"], "basis": row["basis"], "verdict": "pass"}
        if "carries out a listing" in row["text"]:
            item.update(verdict="flag", quote="carries out a listing",
                        reason="Use a direct verb for the action printed on the ticket.")
        results.append(item)
    receipt(notes / "fixture.json", {"rows": results})
    return notes


def main(target):
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise SystemExit("Choose a new or empty example directory.")
    drafts, verdicts = target / "drafts", target / "verdicts"
    drafts.mkdir()
    verdicts.mkdir()
    writers, reviewers = target / "writer-packets", target / "reviewer-packets"
    edition("pack", SOURCE, writers, "--batch-size", "1")
    writer_rows = [
        {"id": row["id"], "basis": row["basis"], "text": REVISIONS.get(row["id"], row["source"])}
        for row in scripted_rows(writers)
    ]
    first_drafts = target / "first-drafts"
    first_drafts.mkdir()
    first = [dict(row) for row in writer_rows]
    ticket = next(row for row in first if row["id"] == "s005")
    ticket["text"] = "This ticket carries out a listing of stop names in alphabetical order."
    receipt(first_drafts / "fixture.json", {"rows": first})
    read_without_source(target, first_drafts, "first")

    # The editor checks the flagged phrase against the source and chooses "lists".
    receipt(drafts / "fixture.json", {"rows": writer_rows})
    notes = read_without_source(target, drafts, "final")
    edition("review", SOURCE, drafts, reviewers, "--blind-notes", notes, "--batch-size", "1")
    reviewer_rows = []
    for row in scripted_rows(reviewers):
        entry = {"id": row["id"], "basis": row["basis"], "verdict": "pass"}
        if row["id"] == "s003":
            entry.update(verdict="flag", source_quote="was associated with", draft_quote="caused",
                         reason="The proposed verb asserts causation.")
        reviewer_rows.append(entry)
    receipt(verdicts / "fixture.json", {"rows": reviewer_rows})
    decisions = target / "decisions.json"
    flag = next(row for row in reviewer_rows if row["verdict"] == "flag")
    receipt(decisions, {flag["id"]: {"basis": flag["basis"], "action": "source",
                                      "reason": "The recorded observation supports association alone."}})
    output = target / "comparison.html"
    edition("build", SOURCE, drafts, verdicts, output, "--decisions", decisions, "--blind-notes", notes)
    print(output.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path)
    main(parser.parse_args().output_directory)
