# Potanin Competitions Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать проверяемый Python-парсер публичного каталога конкурсов Фонда Потанина, выгрузить фактические данные в JSON/CSV, построить статистику и подготовить отчёт по практике.

**Architecture:** Консольный конвейер получает ссылки из каталога, последовательно загружает карточки, извлекает семантические разделы и нормализует даты и суммы. Полные записи сохраняются в JSON, плоские — в CSV, а отдельный аналитический модуль формирует сводку и PNG-графики. Сетевой слой отделён от HTML-парсера, поэтому тесты используют локальные фикстуры.

**Tech Stack:** Python 3.11+, `lxml`, `Pillow`, стандартные `urllib`, `csv`, `json`, `logging`, `unittest`; Word-отчёт создаётся через bundled document runtime.

---

## File Structure

- `pyproject.toml` — метаданные проекта, зависимости и CLI-команда.
- `README.md` — установка, запуск и описание результатов.
- `src/potanin_parser/__init__.py` — версия пакета.
- `src/potanin_parser/models.py` — модель записи конкурса.
- `src/potanin_parser/normalization.py` — разбор русских дат и денежных сумм.
- `src/potanin_parser/html_parser.py` — извлечение ссылок каталога и данных карточки.
- `src/potanin_parser/client.py` — последовательная HTTP-загрузка с паузой и повторами.
- `src/potanin_parser/exporters.py` — JSON/CSV экспорт.
- `src/potanin_parser/analytics.py` — сводка и PNG-графики.
- `src/potanin_parser/cli.py` — оркестрация полного запуска.
- `tests/fixtures/catalog.html` — сокращённая копия каталога.
- `tests/fixtures/competition.html` — карточка с датами, несколькими суммами и документами.
- `tests/fixtures/incomplete_competition.html` — карточка с отсутствующими полями.
- `tests/test_normalization.py` — тесты дат и сумм.
- `tests/test_html_parser.py` — тесты каталога и карточек.
- `tests/test_exporters.py` — тесты JSON/CSV.
- `tests/test_analytics.py` — тесты сводки и графиков.
- `output/` — фактическая выгрузка; создаётся программой.
- `report/Отчет по практике 2 Узунов Э. А..docx` — итоговый отчёт.

### Task 1: Project Skeleton and Data Model

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/potanin_parser/__init__.py`
- Create: `src/potanin_parser/models.py`

- [ ] **Step 1: Create package metadata**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "potanin-competitions-parser"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["lxml>=5.0", "Pillow>=10.0"]

[project.scripts]
potanin-parser = "potanin_parser.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Add the typed record model**

```python
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Competition:
    source: str
    source_url: str
    collected_at: str
    title: str
    status: str | None = None
    publication_date: str | None = None
    application_start_date: str | None = None
    application_end_date: str | None = None
    organizer: str = "Фонд Потанина"
    summary: str | None = None
    goals: str | None = None
    tasks: str | None = None
    target_audience: str | None = None
    requirements: str | None = None
    nominations: str | None = None
    project_directions: str | None = None
    procedure: str | None = None
    grant_fund_rub: int | None = None
    max_support_rub: int | None = None
    funding_text: str | None = None
    application_url: str | None = None
    result_urls: list[str] = field(default_factory=list)
    document_urls: list[str] = field(default_factory=list)
    contacts: list[dict[str, str]] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)
    full_text: str = ""
    parse_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 3: Add README commands**

Document installation with `python3 -m venv .venv`, `pip install -e .`, test command `python -m unittest discover -s tests -v`, and run command `potanin-parser --output output`.

- [ ] **Step 4: Verify imports**

Run: `PYTHONPATH=src python3 -c "from potanin_parser.models import Competition; print(Competition.__name__)"`

Expected: `Competition`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md src/potanin_parser
git commit -m "chore: scaffold competitions parser"
```

### Task 2: Date and Money Normalization

**Files:**
- Create: `src/potanin_parser/normalization.py`
- Create: `tests/test_normalization.py`

- [ ] **Step 1: Write failing normalization tests**

```python
import unittest

from potanin_parser.normalization import extract_application_dates, parse_money_values


class NormalizationTest(unittest.TestCase):
    def test_extracts_russian_application_period(self):
        text = "Прием заявок осуществляется с 19 декабря 2025 года по 30 ноября 2026 года."
        self.assertEqual(extract_application_dates(text), ("2025-12-19", "2026-11-30"))

    def test_parses_money_units(self):
        values = parse_money_values("500 000 рублей, 1 млн рублей и грантовый фонд 25 млн рублей")
        self.assertEqual(values, [500_000, 1_000_000, 25_000_000])

    def test_returns_empty_values_for_missing_data(self):
        self.assertEqual(extract_application_dates("Сроки будут опубликованы позднее"), (None, None))
        self.assertEqual(parse_money_values("Финансирование не указано"), [])
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_normalization -v`

Expected: FAIL because `potanin_parser.normalization` does not exist.

- [ ] **Step 3: Implement Russian date parsing**

Define a month-name map for all twelve Russian months, normalize whitespace, match `с <date> по <date>` and return ISO dates. Invalid dates return `None` instead of raising.

- [ ] **Step 4: Implement money parsing**

Match integer/decimal values followed by `тыс`, `млн`, `млрд` or direct ruble wording. Remove non-breaking spaces and multiply by the detected unit. Return unique values in source order.

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_normalization -v`

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/potanin_parser/normalization.py tests/test_normalization.py
git commit -m "feat: normalize competition dates and funding"
```

### Task 3: Catalog and Competition HTML Parsing

**Files:**
- Create: `src/potanin_parser/html_parser.py`
- Create: `tests/fixtures/catalog.html`
- Create: `tests/fixtures/competition.html`
- Create: `tests/fixtures/incomplete_competition.html`
- Create: `tests/test_html_parser.py`

- [ ] **Step 1: Save representative HTML fixtures**

The catalog fixture must contain two `programms__item-link` anchors. The full card fixture must include publication date, semantic `h2` sections, two support limits, application period, application link, result PDF, document list and contact. The incomplete fixture must contain a title and body but no dates or funding.

- [ ] **Step 2: Write failing catalog test**

```python
def test_catalog_returns_absolute_unique_links(self):
    html = fixture("catalog.html")
    links = parse_catalog(html, BASE_URL)
    self.assertEqual(len(links), 2)
    self.assertTrue(all(link.startswith(BASE_URL) for link in links))
```

- [ ] **Step 3: Write failing card tests**

```python
def test_card_extracts_structured_fields(self):
    competition = parse_competition(fixture("competition.html"), CARD_URL, "2026-06-12T12:00:00+07:00")
    self.assertEqual(competition.title, "Конкурс событий для сообщества «#Мынасвязи»")
    self.assertEqual(competition.application_end_date, "2026-11-30")
    self.assertEqual(competition.grant_fund_rub, 25_000_000)
    self.assertEqual(competition.max_support_rub, 1_000_000)
    self.assertTrue(competition.document_urls)

def test_incomplete_card_is_preserved_with_warnings(self):
    competition = parse_competition(fixture("incomplete_competition.html"), CARD_URL, COLLECTED_AT)
    self.assertIsNone(competition.application_end_date)
    self.assertIn("application dates not found", competition.parse_warnings)
```

- [ ] **Step 4: Run tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_html_parser -v`

Expected: FAIL because parser functions do not exist.

- [ ] **Step 5: Implement catalog parsing**

Use `lxml.html.fromstring`, select anchors with class `programms__item-link`, resolve relative URLs through `urllib.parse.urljoin`, remove fragments and preserve first-seen order.

- [ ] **Step 6: Implement semantic section extraction**

Select the principal `.contest__info` block, walk its children, start a new section for each `h2`, and collect normalized text until the next heading. Store every section in `Competition.sections`, then map normalized headings to `goals`, `tasks`, `target_audience`, `nominations`, `project_directions`, `procedure` and `funding_text`.

- [ ] **Step 7: Implement metadata and link extraction**

Extract title from `h1`, status from page status elements, publication date from `.aside__period`, application link from the orange action button, result links containing `побед` or `итог`, document links under `.documents`, and contact cards under `.contacts`.

- [ ] **Step 8: Connect normalization and warnings**

Derive application dates from the procedure/full text. Derive `grant_fund_rub` from the grant-fund section and `max_support_rub` from support wording. Add warnings for missing title, dates, funding and content block; do not reject the record.

- [ ] **Step 9: Run parser tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_html_parser -v`

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add src/potanin_parser/html_parser.py tests
git commit -m "feat: parse catalog and competition cards"
```

### Task 4: HTTP Client and Pipeline

**Files:**
- Create: `src/potanin_parser/client.py`
- Create: `src/potanin_parser/cli.py`
- Create: `tests/test_client.py`

- [ ] **Step 1: Write failing retry test with a fake opener**

```python
def test_client_retries_then_returns_html(self):
    opener = FakeOpener([TimeoutError(), FakeResponse(b"<html>ok</html>")])
    client = HttpClient(opener=opener, retries=2, delay_seconds=0)
    self.assertEqual(client.get("https://example.test"), "<html>ok</html>")
    self.assertEqual(opener.calls, 2)
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_client -v`

Expected: FAIL because `HttpClient` does not exist.

- [ ] **Step 3: Implement polite HTTP client**

Use `urllib.request.Request` with a descriptive `User-Agent`, `Accept-Language: ru`, a 30-second timeout, two retries and configurable pause. Decode from the response charset with UTF-8 fallback. Raise a final `FetchError` containing the URL and original error.

- [ ] **Step 4: Implement CLI orchestration**

Support `--catalog-url`, `--output`, `--delay`, and `--limit`. Configure file and console logging, fetch `?SHOWALL_1=1`, parse links, process each card independently, append a warning record to the log on failure, and call export/analytics functions.

- [ ] **Step 5: Run client tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_client -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/potanin_parser/client.py src/potanin_parser/cli.py tests/test_client.py
git commit -m "feat: add resilient collection pipeline"
```

### Task 5: JSON/CSV Export and Analytics

**Files:**
- Create: `src/potanin_parser/exporters.py`
- Create: `src/potanin_parser/analytics.py`
- Create: `tests/test_exporters.py`
- Create: `tests/test_analytics.py`

- [ ] **Step 1: Write failing export tests**

Create two `Competition` objects, export them to a temporary directory, reload JSON with `json.load`, read CSV with `csv.DictReader`, and assert that nested contacts are valid JSON strings and Russian text is preserved.

- [x] **Step 2: Write failing analytics tests**

Assert that `build_summary` returns total records, status counts, records with deadlines/funding, min/max support and warning count. Assert that chart generation creates non-empty PNG files in `charts/`.

- [ ] **Step 3: Run tests to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_exporters tests.test_analytics -v`

Expected: FAIL because exporter and analytics modules do not exist.

- [x] **Step 4: Implement JSON and CSV export**

Write UTF-8 JSON with `ensure_ascii=False` and indentation. Build CSV columns from the model fields; join URL/warning lists with ` | ` and serialize `contacts`/`sections` with `json.dumps(..., ensure_ascii=False)`.

- [x] **Step 5: Implement summary generation**

Return a dictionary containing collection time, source, record count, status distribution, count of parsed deadlines, count of parsed funding fields, minimum/maximum support, total warnings and failed-page count supplied by the pipeline.

- [x] **Step 6: Implement PNG charts with Pillow**

Create readable 1600x900 white-background bar charts using bundled fonts or Pillow's default font. Generate status, deadline and funding charts only when corresponding data exists. Return a list of generated files and record skipped charts in the summary.

- [x] **Step 7: Run tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_exporters tests.test_analytics -v`

Expected: all tests pass.

- [x] **Step 8: Commit**

```bash
git add src/potanin_parser/exporters.py src/potanin_parser/analytics.py tests
git commit -m "feat: export and analyze competition data"
```

### Task 6: Full Verification and Real Data Collection

**Files:**
- Modify: `README.md`
- Create: `output/competitions.json`
- Create: `output/competitions.csv`
- Create: `output/summary.json`
- Create: `output/charts/*.png`
- Create: `output/run.log`

- [ ] **Step 1: Install the local project**

Run: `python3 -m venv .venv && .venv/bin/pip install -e .`

Expected: editable package and dependencies install successfully.

- [ ] **Step 2: Run the complete test suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests pass with no errors.

- [ ] **Step 3: Run a two-card network smoke test**

Run: `.venv/bin/potanin-parser --output output-smoke --limit 2 --delay 0.5`

Expected: two records in JSON/CSV and no pipeline crash.

- [ ] **Step 4: Run the full collection**

Run: `.venv/bin/potanin-parser --output output --delay 1.0`

Expected: all catalog links attempted, successful records exported, individual failures logged.

- [ ] **Step 5: Validate artifacts programmatically**

Run: `.venv/bin/python -c "import csv,json,pathlib; p=pathlib.Path('output'); j=json.load(open(p/'competitions.json', encoding='utf-8')); c=list(csv.DictReader(open(p/'competitions.csv', encoding='utf-8-sig'))); s=json.load(open(p/'summary.json', encoding='utf-8')); assert len(j)==len(c)==s['record_count']; assert all(x['source_url'] for x in j); print(s)"`

Expected: assertions pass and the real summary is printed.

- [ ] **Step 6: Manually compare three records to their source pages**

Check one open competition, one completed competition and one competition with multiple support amounts. Record any discrepancy in `run.log` and fix parser logic if it is systematic.

- [ ] **Step 7: Update README with actual output description**

Document the collection date, actual record count, known missing fields and commands needed to repeat the run.

- [ ] **Step 8: Commit source and reproducible outputs**

```bash
git add README.md output
git commit -m "data: collect Potanin competition dataset"
```

### Task 7: Practice Report

**Files:**
- Create: `report/Отчет по практике 2 Узунов Э. А..docx`
- Create: `report/Отчет по практике 2 Узунов Э. А..pdf`

- [ ] **Step 1: Read the Documents skill and use its required artifact workflow**

Use the bundled document runtime, generate the DOCX programmatically, render every page to PNG, inspect the rendering, and iterate on layout defects before delivery.

- [ ] **Step 2: Draft report content from verified artifacts**

Use the structure from the design: introduction, source analysis, task statement, architecture, implementation, experiment, results, limitations, future work and conclusion. Reuse the institutional title-page data from the previous report, but give the new work an implementation-focused title.

- [ ] **Step 3: Insert evidence**

Include the actual collection date, record count, field completeness table, example record, architecture diagram, relevant code excerpts, status/funding/deadline charts and source URLs. Do not state metrics that are absent from `summary.json`.

- [ ] **Step 4: Render and inspect**

Render the DOCX to page PNGs and PDF. Check title page, contents, headings, table overflow, image resolution, page breaks, captions and bibliography.

- [ ] **Step 5: Correct layout and rerender**

Resolve widows/orphans, clipped tables, low-resolution charts and inconsistent styles. Repeat rendering until pages are readable and stable.

- [ ] **Step 6: Verify final files**

Confirm the DOCX opens, the PDF page count matches, every chart is visible and all reported numbers match `output/summary.json`.

- [ ] **Step 7: Commit report**

```bash
git add report
git commit -m "docs: add parser practice report"
```

### Task 8: Final Audit

**Files:**
- Review all tracked project files and generated artifacts.

- [ ] **Step 1: Run tests from a clean command**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 2: Re-run artifact validation**

Run the validation command from Task 6 and compare the summary values with the report.

- [ ] **Step 3: Inspect Git scope**

Run: `git status --short` and `git diff --check`.

Expected: only intentional untracked user files remain; no whitespace errors.

- [ ] **Step 4: Record final limitations**

Ensure README and report explicitly state that the dataset covers the public Fund catalog at collection time, PDF bodies are not parsed, and site layout changes may require selector updates.
