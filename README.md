# Potanin Competitions Parser

Collects competition cards from the public Potanin Foundation catalog and exports
the normalized dataset, a summary, charts, and a run log.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Usage

```bash
potanin-parser --output output
```

For a reproducible polite network run from the repository root:

```bash
.venv/bin/potanin-parser --output output-smoke --limit 2 --delay 0.5
.venv/bin/potanin-parser --output output --delay 1.0
```

## Collected Dataset

The committed dataset was collected on June 14, 2026 at
`2026-06-14T03:16:18.943017+00:00` from `fondpotanin.ru`.

- 35 competition records were exported to `output/competitions.json` and
  `output/competitions.csv`.
- All catalog pages completed without a fetch failure (`failed_pages: 0`).
- 14 records have a parsed application deadline.
- 10 records have a parsed grant fund or maximum support value.
- Parsed maximum-support values range from 360,000 to 10,000,000 RUB.
- The run produced 53 parse warnings.
- `output/charts/deadlines.png` and `output/charts/funding.png` were generated.
  The status chart was skipped because the source pages expose no dedicated
  status value.

Known missing fields reflect inconsistent source-page content and markup:

- `status` is missing for all 35 records because the collected detail pages do
  not publish a dedicated status label.
- 21 records have no parseable application end date; some historical pages
  describe a program without publishing an application period.
- 25 records have neither a grant fund nor an unambiguous maximum support
  amount in their page content.
- Only 2 records expose a current application action link on the detail page.

The complete machine-readable metrics are in `output/summary.json`. Manual
source-page checks and discrepancies are recorded in `output/run.log`.

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -c "import csv,json,pathlib; p=pathlib.Path('output'); j=json.load(open(p/'competitions.json', encoding='utf-8')); c=list(csv.DictReader(open(p/'competitions.csv', encoding='utf-8-sig'))); s=json.load(open(p/'summary.json', encoding='utf-8')); assert len(j)==len(c)==s['record_count']; assert all(x['source_url'] for x in j); print(s)"
```
