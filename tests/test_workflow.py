"""Offline acceptance tests for the documented edition CLI."""

from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


CLI = Path(__file__).resolve().parents[1] / "scripts" / "edition.py"
SOURCE = "At dusk, the loop tram pauses at Reed Gate[[note]] by [[bay]]."
REVISION = SOURCE.replace("pauses", "stops")
NEIGHBOR = "The conductor may wait for the ferry."
FIXED = 'Pilot timetable, card 8 & insert <green>.'


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def read_packets(directory):
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]


class ReadingView(HTMLParser):
    """Read the visible paragraphs, difference marks and citation superscripts."""

    def __init__(self, markup):
        super().__init__()
        self.paragraphs = []
        self.tags = []
        self.current = None
        self.marks = []
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "p":
            self.current = {"text": "", "del": [], "ins": [], "sup": []}
            self.paragraphs.append(self.current)
        if self.current is not None and tag in ("del", "ins", "sup"):
            self.marks.append(tag)
            self.current[tag].append("")

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data
            for mark in self.marks:
                self.current[mark][-1] += data

    def handle_endtag(self, tag):
        if self.marks and self.marks[-1] == tag:
            self.marks.pop()
        if tag == "p":
            self.current = None


class RendererAlignmentTests(unittest.TestCase):
    def paired_text(self, source, revision):
        script = CLI.with_name("render_html.py")
        spec = importlib.util.spec_from_file_location("fixture_renderer", script)
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        row = {"id": "stop", "paragraph": "route", "locator": "Board",
               "text": source, "final": revision, "anchors": {"n": {"kind": "cite", "text": "4"}}}
        view = ReadingView(renderer.render("Pier display", [row], []))
        return [p for p in view.paragraphs if p["sup"]]

    def test_balanced_phrase_edits_preserve_global_word_and_citation_alignment(self):
        for moving in (False, True):
            with self.subTest(moving=moving):
                start = "We marked yesterday, piers[[n]], gates, and slips." if moving else (
                    "We marked yesterday, piers, gates[[n]], and slips.")
                end = "We marked piers, gates[[n]], and slips in chalk."
                old, new = self.paired_text(start, end)
                self.assertEqual("4" in old["del"], moving)
                self.assertEqual("4" in new["ins"], moving)
                for unchanged in ("piers", "gates", "slips", "and"):
                    self.assertNotIn(unchanged, old["del"])
                    self.assertNotIn(unchanged, new["ins"])

    def test_marker_contact_is_independent_on_each_side(self):
        cases = [
            ("Pier[[n]], after dark.", "Pier [[n]]after dark.", True),
            ("Pier[[n]] after dark.", "Pier, [[n]]after dark.", True),
            ("Pier[[n]] after dark.", "Pier [[n]]soon after dark.", True),
            ("Pier [[n]]after dark.", "Pier immediately [[n]] after dark.", True),
            ("Pier[[n]] after dark.", "Pier[[n]] soon after dark.", False),
        ]
        for source, revision, moved in cases:
            with self.subTest(source=source, revision=revision):
                old, new = self.paired_text(source, revision)
                self.assertEqual("4" in old["del"], moved)
                self.assertEqual("4" in new["ins"], moved)

    def test_whitespace_switches_the_attachment_of_the_superscript(self):
        old, new = self.paired_text("Visit East Pier[[n]] after dark.", "Visit East Pier [[n]]after dark.")
        self.assertEqual(old["del"], ["4"])
        self.assertEqual(new["ins"], ["4"])


class PdfIntakeTests(unittest.TestCase):
    def setUp(self):
        script = CLI.with_name("import_pdf.py")
        spec = importlib.util.spec_from_file_location("fixture_pdf_intake", script)
        self.intake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.intake)

    def test_control_characters_trigger_manual_pdf_recovery(self):
        for bad in (b"\x0b", b"\x1d"):
            with self.subTest(character=bad):
                extracted = b"The pier" + bad + b" carries two tram routes.\n\f"
                response = subprocess.CompletedProcess([], 0, stdout=extracted, stderr=b"")
                with patch.object(self.intake.shutil, "which", return_value="pdftotext"), \
                        patch.object(self.intake.subprocess, "run", return_value=response):
                    with self.assertRaises(ValueError):
                        self.intake.extract(b"fixture")

    def test_roman_folios_do_not_freeze_ordinary_words(self):
        rows = self.intake.make_rows(["Mild\n\nCivil\n\nXIV\n\n23\n"])
        self.assertEqual([(r["text"], r["kind"]) for r in rows],
                         [("Mild", "prose"), ("Civil", "prose"), ("XIV", "fixed"), ("23", "fixed")])
        self.assertTrue(rows[-1]["locator"].endswith("line 7"))


class EditionWorkflowTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.source_file = self.root / "source.json"
        self.drafts = self.root / "drafts"
        self.verdicts = self.root / "verdicts"
        self.drafts.mkdir()
        self.verdicts.mkdir()
        self.output = self.root / "comparison.html"
        self.source = {
            "title": "Transfer notice <proof> & route card",
            "rows": [
                {"id": "tram", "paragraph": "loop", "locator": "Card 8, line 1",
                 "text": SOURCE, "anchors": {
                     "note": {"kind": "cite", "text": "8"},
                     "bay": {"kind": "ref", "text": "bay <R>"},
                 }},
                {"id": "ferry", "paragraph": "loop", "locator": "Card 8, line 2", "text": NEIGHBOR},
                {"id": "credit", "paragraph": "imprint", "locator": "Card 8, imprint",
                 "kind": "fixed", "text": FIXED},
            ],
        }
        write_json(self.source_file, self.source)
        writer_dir = self.root / "writer"
        self.cli("pack", self.source_file, writer_dir, "--batch-size", "1")
        self.writer_packets = read_packets(writer_dir)

    def cli(self, *args, succeeds=True):
        result = subprocess.run(
            [sys.executable, "-B", str(CLI), *map(str, args)],
            cwd=self.root, capture_output=True, text=True, timeout=15,
        )
        if succeeds:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def draft(self, **edits):
        rows = [
            {"id": row["id"], "basis": row["basis"], "text": edits.get(row["id"], row["source"])}
            for packet in self.writer_packets for row in packet["rows"]
        ]
        # An external writer may return a different row order.
        write_json(self.drafts / "response.json", {"rows": rows[::-1]})

    def review(self, name="review"):
        directory = self.root / name
        self.cli("review", self.source_file, self.drafts, directory, "--batch-size", "1")
        return read_packets(directory)

    def pass_rows(self, packets):
        return [{"id": row["id"], "basis": row["basis"], "verdict": "pass"}
                for packet in packets for row in packet["rows"]]

    def record(self, rows):
        write_json(self.verdicts / "response.json", {"rows": rows})

    def build(self, *args, succeeds=True):
        return self.cli("build", self.source_file, self.drafts, self.verdicts, self.output,
                        *args, succeeds=succeeds)

    def test_blind_reader_sees_only_displayed_candidate_paragraphs(self):
        self.draft(tram=REVISION)
        directory = self.root / "blind"
        self.cli("blind", self.source_file, self.drafts, directory)
        packet, = read_packets(directory)
        self.assertEqual(set(packet), {"rows"})
        row, = packet["rows"]
        self.assertEqual(set(row), {"id", "basis", "text"})
        self.assertEqual(row["id"], "p0001")
        visible = REVISION.replace("[[note]]", "[8]").replace("[[bay]]", "bay <R>")
        self.assertEqual(row["text"], visible + " " + NEIGHBOR)
        self.assertEqual(len(row["basis"]), 64)
        self.assertNotIn(self.source["title"], str(packet))

    def test_first_reading_is_frozen_before_fidelity_check(self):
        self.draft(tram=REVISION)
        blind, notes, compare = (self.root / name for name in ("blind", "notes", "compare"))
        self.cli("blind", self.source_file, self.drafts, blind)
        notes.mkdir()
        row = read_packets(blind)[0]["rows"][0]
        flag = {"id": row["id"], "basis": row["basis"], "verdict": "flag",
                "quote": "at Reed Gate", "reason": "Private first-reading observation."}
        for invalid in ([], [dict(flag, quote="not in the passage")], [flag, flag]):
            write_json(notes / "notes.json", {"rows": invalid})
            self.cli("review", self.source_file, self.drafts, compare, "--blind-notes", notes, succeeds=False)
            self.assertFalse(compare.exists())
        write_json(notes / "notes.json", {"rows": [flag]})
        self.cli("review", self.source_file, self.drafts, compare, "--blind-notes", notes)
        packets = read_packets(compare)
        self.assertEqual([r["id"] for r in packets[0]["rows"]], ["tram", "ferry"])
        self.record(self.pass_rows(packets))
        self.build(succeeds=False)
        self.build("--blind-notes", notes)
        self.assertNotIn(flag["reason"], self.output.read_text())
        self.draft(tram=REVISION.replace("stops", "waits"))
        self.cli("review", self.source_file, self.drafts, self.root / "stale", "--blind-notes", notes,
                 succeeds=False)

    def test_review_and_read_a_single_word_edit(self):
        self.assertEqual([[row["id"] for row in packet["rows"]] for packet in self.writer_packets],
                         [["tram", "ferry"]])
        self.draft(tram=REVISION)
        packets = self.review()
        self.assertEqual([[r["id"] for r in p["rows"]] for p in packets], [["tram"]])
        neighbors = packets[0]["context"][0]["rows"]
        self.assertEqual([(r["source"], r["draft"]) for r in neighbors],
                         [(SOURCE, REVISION), (NEIGHBOR, NEIGHBOR)])
        self.record(self.pass_rows(packets))
        self.build()

        view = ReadingView(self.output.read_text(encoding="utf-8"))
        original = SOURCE.replace("[[note]]", "8").replace("[[bay]]", "bay <R>")
        edited = original.replace("pauses", "stops")
        sentences = [p for p in view.paragraphs if p["text"] in (original, edited, NEIGHBOR, FIXED)]
        self.assertEqual([p["text"] for p in sentences],
                         [original, edited, NEIGHBOR, NEIGHBOR, FIXED, FIXED])
        self.assertEqual([(p["del"], p["ins"]) for p in sentences],
                         [(["pauses"], []), ([], ["stops"]), ([], []), ([], []), ([], []), ([], [])])
        self.assertEqual([p["sup"] for p in sentences[:2]], [["8"], ["8"]])
        for literal_tag in ("green", "proof", "r"):
            self.assertNotIn(literal_tag, view.tags)

    def test_pure_word_move_and_shifted_citation_stay_visible(self):
        moved_cite = SOURCE.replace("Gate[[note]] by", "Gate by[[note]]")
        moved_word = NEIGHBOR.replace("may wait", "wait may")
        self.draft(tram=moved_cite, ferry=moved_word)
        self.record(self.pass_rows(self.review()))
        self.build()
        sentences = ReadingView(self.output.read_text(encoding="utf-8")).paragraphs
        source = next(p for p in sentences if "Reed Gate8 by" in p["text"])
        revision = next(p for p in sentences if "Reed Gate by8" in p["text"])
        self.assertEqual(source["del"], ["8"])
        self.assertEqual(revision["ins"], ["8"])
        original = next(p for p in sentences if p["text"] == NEIGHBOR)
        revised = next(p for p in sentences if p["text"] == moved_word)
        self.assertTrue(original["del"] and revised["ins"])
        self.assertLessEqual(set(original["del"] + revised["ins"]), {"may", "wait"})

    def test_exchanged_route_numbers_mark_only_the_two_numbers(self):
        original = "Change from 12 to 65 at the quay."
        edited = "Change from 65 to 12 at the quay."
        self.source["rows"][1]["text"] = original
        write_json(self.source_file, self.source)
        directory = self.root / "routes"
        self.cli("pack", self.source_file, directory)
        self.writer_packets = read_packets(directory)
        self.draft(ferry=edited)
        self.record(self.pass_rows(self.review()))
        self.build()
        sentences = ReadingView(self.output.read_text(encoding="utf-8")).paragraphs
        self.assertEqual(next(p["del"] for p in sentences if p["text"] == original), ["12", "65"])
        self.assertEqual(next(p["ins"] for p in sentences if p["text"] == edited), ["65", "12"])

    def test_fixed_neighbor_is_read_only_context_and_invalidates_drafts(self):
        self.source["rows"][2]["paragraph"] = "loop"
        write_json(self.source_file, self.source)
        packets = self.root / "with-fixed"
        self.cli("pack", self.source_file, packets)
        self.writer_packets = read_packets(packets)
        self.assertEqual([r["id"] for r in self.writer_packets[0]["rows"]], ["tram", "ferry"])
        neighbors = self.writer_packets[0]["context"][0]["rows"]
        self.assertEqual([r["source"] for r in neighbors], [SOURCE, NEIGHBOR, FIXED])
        self.draft(tram=REVISION)
        self.source["rows"][2]["text"] += " Second printing."
        write_json(self.source_file, self.source)
        self.cli("review", self.source_file, self.drafts, self.root / "stale-fixed", succeeds=False)

    def test_unchanged_edition_needs_no_verdicts(self):
        self.draft()
        self.assertEqual(self.review(), [])
        self.build()
        view = ReadingView(self.output.read_text(encoding="utf-8"))
        self.assertNotIn("del", view.tags)
        self.assertNotIn("ins", view.tags)
        self.assertEqual([p["text"] for p in view.paragraphs].count(NEIGHBOR), 2)

    def test_insertion_and_deletion_are_marked_on_the_affected_side(self):
        shortened = SOURCE.replace("loop ", "")
        expanded = NEIGHBOR.replace("ferry", "island ferry")
        self.draft(tram=shortened, ferry=expanded)
        self.record(self.pass_rows(self.review()))
        self.build()
        view = ReadingView(self.output.read_text(encoding="utf-8"))
        original = SOURCE.replace("[[note]]", "8").replace("[[bay]]", "bay <R>")
        wanted = [original, original.replace("loop ", ""), NEIGHBOR, expanded]
        rows = [p for p in view.paragraphs if p["text"] in wanted]
        self.assertEqual([p["text"] for p in rows], wanted)
        self.assertEqual([(p["del"], p["ins"]) for p in rows],
                         [(["loop"], []), ([], []), ([], []), ([], ["island"])])

    def test_missing_review_and_stale_draft_wording(self):
        self.draft(tram=REVISION)
        initial = self.pass_rows(self.review())
        self.build(succeeds=False)
        self.assertFalse(self.output.exists())
        self.record(initial)
        self.draft(tram=REVISION.replace("stops", "waits"))
        self.build(succeeds=False)
        self.assertFalse(self.output.exists())
        self.record(self.pass_rows(self.review("updated")))
        self.build()

    def test_unchanged_edit_requires_a_new_review_when_its_neighbor_changes(self):
        self.draft(tram=REVISION)
        original_review = self.pass_rows(self.review())[0]
        self.draft(tram=REVISION, ferry=NEIGHBOR.replace("may", "might"))
        fresh = self.pass_rows(self.review("changed-context"))
        self.record([original_review if r["id"] == "tram" else r for r in fresh])
        self.build(succeeds=False)
        self.assertFalse(self.output.exists())
        self.record(fresh)
        self.build()

    def test_source_change_invalidates_old_writer_response(self):
        self.draft(tram=REVISION)
        self.source["rows"][0]["anchors"]["note"]["text"] = "10"
        write_json(self.source_file, self.source)
        destination = self.root / "new-review"
        self.cli("review", self.source_file, self.drafts, destination, succeeds=False)
        self.assertFalse(destination.exists())

    def test_draft_cannot_drop_duplicate_or_reorder_anchors(self):
        bad_edits = {
            "missing": REVISION.replace("[[note]]", ""),
            "repeated": REVISION.replace("[[note]]", "[[note]][[note]]"),
            "reordered": "At dusk, the loop tram stops by [[bay]] at Reed Gate[[note]].",
        }
        for name, wording in bad_edits.items():
            with self.subTest(name=name):
                self.draft(tram=wording)
                destination = self.root / name
                self.cli("review", self.source_file, self.drafts, destination, succeeds=False)
                self.assertFalse(destination.exists())

    def test_review_excerpts_preserve_citation_superscripts(self):
        drift = SOURCE.replace("Gate[[note]] by", "Gate, according to the map[[note]], by")
        self.draft(tram=drift)
        flag = self.pass_rows(self.review())[0]
        flag.update(verdict="flag", reason="The marker moved to a different attribution.",
                    source_quote="Gate[[note]]", draft_quote="map[[note]]")
        self.record([flag])
        decisions = self.root / "decisions.json"
        write_json(decisions, {"tram": {"basis": flag["basis"], "action": "source",
                                        "reason": "Keep the original reference scope."}})
        self.build("--decisions", decisions, "--review-notes")
        notes = self.output.read_text(encoding="utf-8").split('<section class="review"', 1)[1]
        self.assertIn('Gate<sup class="locked">8</sup>', notes)
        self.assertIn('map<sup class="locked">8</sup>', notes)

    def test_flag_requires_exact_quotes_and_a_reasoned_decision(self):
        self.draft(ferry=NEIGHBOR.replace("may", "will"))
        flagged = self.pass_rows(self.review())[0]
        flagged.update(verdict="flag", reason="Waiting became certain.",
                       source_quote="may wait", draft_quote="will wait")
        decisions = self.root / "decisions.json"
        restore = {"ferry": {"basis": flagged["basis"], "action": "source", "reason": "The timetable allows a choice."}}
        write_json(decisions, restore)
        self.record([{**flagged, "source_quote": "always waits"}])
        self.build("--decisions", decisions, succeeds=False)
        self.assertFalse(self.output.exists())
        self.record([flagged])
        self.build(succeeds=False)
        self.assertFalse(self.output.exists())
        write_json(decisions, {"ferry": {**restore["ferry"], "basis": "prior-version"}})
        self.build("--decisions", decisions, succeeds=False)
        self.assertFalse(self.output.exists())
        write_json(decisions, {"ferry": {**restore["ferry"], "reason": " "}})
        self.build("--decisions", decisions, succeeds=False)
        self.assertFalse(self.output.exists())
        write_json(decisions, restore)
        self.build("--decisions", decisions)
        html = self.output.read_text(encoding="utf-8")
        self.assertEqual([p["text"] for p in ReadingView(html).paragraphs].count(NEIGHBOR), 2)
        self.assertNotIn(flagged["reason"], html)
        self.assertNotIn(restore["ferry"]["reason"], html)

    def test_receipts_need_only_the_rows(self):
        self.draft(tram=REVISION)
        rows = self.pass_rows(self.review())
        write_json(self.verdicts / "response.json", {"rows": rows})
        self.build()
        self.assertTrue(self.output.is_file())

    def test_pdf_digest_stays_in_the_source_manifest(self):
        digest = "f00d" * 16
        self.source["pdf_sha256"] = digest
        write_json(self.source_file, self.source)
        packets = self.root / "new-writers"
        self.cli("pack", self.source_file, packets)
        self.writer_packets = read_packets(packets)
        self.draft(tram=REVISION)
        reviewing = self.review()
        self.record(self.pass_rows(reviewing))
        self.build()
        for content in (json.dumps(self.writer_packets), json.dumps(reviewing), self.output.read_text()):
            self.assertNotIn(digest, content)
        self.assertEqual(json.loads(self.source_file.read_text())["pdf_sha256"], digest)

    def test_private_evidence_stays_out_of_reading_copy(self):
        self.draft(ferry=NEIGHBOR.replace("may", "will"))
        flag = self.pass_rows(self.review())[0]
        flag.update(verdict="flag", reason="Private reviewer stamp 713.",
                    source_quote="may wait", draft_quote="will wait")
        self.record([flag])
        decisions = self.root / "choices.json"
        write_json(decisions, {"ferry": {"basis": flag["basis"], "action": "source",
                                         "reason": "Private editorial stamp 964."}})
        self.build("--decisions", decisions)
        document = self.output.read_text()
        for private in (flag["reason"], flag["draft_quote"], "Private editorial stamp 964."):
            self.assertNotIn(private, document)
        self.assertEqual([p["text"] for p in ReadingView(document).paragraphs].count(NEIGHBOR), 2)

    def test_legacy_receipt_label_can_still_be_enforced(self):
        self.draft(tram=REVISION)
        receipt = self.drafts / "response.json"
        rows = json.loads(receipt.read_text())["rows"]
        target = self.root / "checked"
        for body in ({"rows": rows}, {"provider": "Other desk", "rows": rows}):
            write_json(receipt, body)
            self.cli("review", self.source_file, self.drafts, target, "--provider", "Route desk",
                     succeeds=False)
        write_json(receipt, {"provider": "Route desk", "rows": rows})
        self.cli("review", self.source_file, self.drafts, target, "--provider", "Route desk")

    def test_legacy_label_is_checked_across_draft_and_review(self):
        self.draft(tram=REVISION)
        draft_file = self.drafts / "response.json"
        draft_rows = json.loads(draft_file.read_text())["rows"]
        write_json(draft_file, {"provider": "Route desk", "rows": draft_rows})
        verdicts = self.pass_rows(self.review())
        file = self.verdicts / "response.json"
        for wrong in ({"rows": verdicts}, {"provider": "Second desk", "rows": verdicts}):
            write_json(file, wrong)
            self.build(succeeds=False)
        write_json(file, {"provider": "ROUTE DESK", "rows": verdicts})
        self.build()
        self.assertNotIn("route desk", self.output.read_text().casefold())

    def test_failed_rebuild_preserves_existing_edition(self):
        self.draft(tram=REVISION)
        verdicts = self.pass_rows(self.review())
        self.record(verdicts)
        self.build()
        first = self.output.read_bytes()
        self.record([])
        self.build(succeeds=False)
        self.assertEqual(self.output.read_bytes(), first)
        self.record(verdicts)
        self.build()
        self.assertEqual(self.output.read_bytes(), first)
        self.draft()
        self.record([])
        self.build(succeeds=False)
        self.assertEqual(self.output.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
