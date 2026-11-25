# Prepare a PDF manuscript

From the skill directory, run the importer with a local PDF and a new output filename. It requires Python 3.10+ and Poppler's `pdftotext` on `PATH`. Run `pdftotext -v` to check the installation. The output directory must already exist.

```sh
python3 scripts/import_pdf.py transit-draft.pdf source.json --title "Transit draft"
```

The importer hashes the exact PDF bytes it reads. It groups lines separated by blank space into candidate paragraphs, then splits prose at likely sentence endings. It uses physical PDF page numbers starting at 1. “Extracted line” counts LF-delimited lines in Poppler's layout text, including blank lines. To reproduce those coordinates locally, run `pdftotext -layout -enc UTF-8 -eol unix transit-draft.pdf -`. The editor's printed line numbers and page labels may differ.

## Verify the source before packing

Open the rendered PDF alongside the preliminary manifest. Work page by page. Read rows in order and check that every in-scope sentence, caption and footnote appears once. Check names, units, dates, decimals, symbols and superscripts against the page. A searchable header can sit above a scanned body. Even a successful extraction needs this comparison.

- **Reading order and margins.** Trace each column from top to bottom. Reorder interleaved text, remove layout-only running headers and folios after checking them, and move printed line numbers into `locator`. A standalone “I” can be either prose or a front-matter page number. Check its placement on the page. If an exact printed line or column is unclear, use the physical page and an identifiable paragraph or caption. Give a range only when both ends can be checked.
- **Sentence and paragraph boundaries.** Repair splits around abbreviations and initial letters, and separate merged sentences or paragraphs. The importer starts a new paragraph on each page. Rejoin continuations and record both page locations when a sentence crosses a page. Inspect every hyphen at a line ending. Restore the full word for a discretionary break or keep the lexical hyphen for a term such as “off-peak.” Use the same paragraph ID on consecutive sentences that belong together. Assign final row IDs before generating packets.
- **Verbatim and omitted material.** Mark bylines, reference entries, headings or other material that must remain verbatim as `fixed`. A recognized standalone English bibliography heading sets that heading and all following rows to `fixed`, including subsequent pages. Check where the bibliography actually starts and ends. Reclassify any appendix prose after it and mark references under unrecognized headings manually. For a deliberately omitted passage, set `kind` to `locator` and supply the precise location in `locator`. Include this passage when checking coverage.
- **Citations and formatting.** Compare each inline citation, figure/table reference, emphasis span and link with the PDF. Replace its text with a unique token such as `[[r1]]` in that row and record its original display value in `anchors`. For example, `{"r1":{"kind":"cite","text":"1,2"}}` preserves the citation as a superscript. Keep the token at its original position relative to punctuation. A plain figure label can use `{"f1":{"kind":"ref","text":"Figure 2"}}`. Restore formatting lost by text extraction before giving the prose to an editor.
- **Captions and images.** Keep each caption in its printed order and independently verify the labels, panel letters and units. Add a local PNG or JPEG for each in-scope illustration. A `figures` entry such as `{"after":"s014","file":"assets/route-map.png","alt":"Map of the three proposed bus stops"}` places the image after that row. Resolve filenames relative to the manifest directory. Open the image to check the crop and legibility, then check its placement in the comparison.

## Recover missing text

The importer stops and lists affected pages when a page has empty, numeric-only, or visibly corrupt extracted text. It reports sparse pages for inspection. Render each affected page to distinguish an intentional blank or diagram from missing text. For a scan, OCR a working copy with a local tool or transcribe the relevant content manually. Compare the transcription with the rendered original, including tables, captions and footnotes. If a page contains only an in-scope diagram, account for it with a location and the image.

Importing an OCR copy records the copy's hash. After reconciling every page against the original, set `pdf_sha256` in the final source manifest to the original file's SHA-256. The following prints that digest locally.

```sh
python3 -c "import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())" transit-draft.pdf
```

For a blank page or a layout that cannot be extracted reliably, assemble the manifest manually using the same fields. Explicitly identify any unresolved or unavailable passage by location in the working record and settle its inclusion before generating polish packets.
