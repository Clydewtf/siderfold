import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from potanin_parser.exporters import export_records
from potanin_parser.models import Competition


def sample_records() -> list[Competition]:
    return [
        Competition(
            source="Фонд Потанина",
            source_url="https://example.test/competitions/events",
            collected_at="2026-06-12T12:00:00+07:00",
            title="Конкурс событий",
            status="Прием заявок",
            application_end_date="2026-11-30",
            max_support_rub=1_000_000,
            result_urls=["https://example.test/results/events.pdf"],
            contacts=[{"name": "Анна Иванова", "email": "anna@example.test"}],
            sections={"Цели конкурса": "Развитие сообществ"},
            parse_warnings=["пример предупреждения"],
        ),
        Competition(
            source="Фонд Потанина",
            source_url="https://example.test/competitions/museums",
            collected_at="2026-06-12T12:00:00+07:00",
            title="Музей без границ",
            status="Завершен",
            document_urls=["https://example.test/documents/rules.pdf"],
        ),
    ]


class ExporterTests(unittest.TestCase):
    def test_csv_uses_lf_line_endings(self) -> None:
        with TemporaryDirectory() as directory:
            csv_path = Path(directory) / "competitions.csv"
            export_records(sample_records(), Path(directory))
            csv_bytes = csv_path.read_bytes()

        self.assertNotIn(b"\r\n", csv_bytes)
        self.assertIn(b"\n", csv_bytes)

    def test_exports_json_and_csv_with_nested_values_and_russian_text(self) -> None:
        records = sample_records()

        with TemporaryDirectory() as directory:
            output_dir = Path(directory)
            generated = export_records(records, output_dir)

            with (output_dir / "competitions.json").open(encoding="utf-8") as file:
                json_records = json.load(file)
            with (output_dir / "competitions.csv").open(
                encoding="utf-8", newline=""
            ) as file:
                csv_records = list(csv.DictReader(file))

        self.assertEqual(
            generated,
            [output_dir / "competitions.json", output_dir / "competitions.csv"],
        )
        self.assertEqual(json_records[0]["title"], "Конкурс событий")
        self.assertEqual(json_records[0]["contacts"][0]["name"], "Анна Иванова")
        self.assertEqual(csv_records[0]["title"], "Конкурс событий")
        self.assertEqual(
            json.loads(csv_records[0]["contacts"]),
            [{"name": "Анна Иванова", "email": "anna@example.test"}],
        )
        self.assertEqual(
            json.loads(csv_records[0]["sections"]),
            {"Цели конкурса": "Развитие сообществ"},
        )
        self.assertEqual(
            csv_records[0]["result_urls"],
            "https://example.test/results/events.pdf",
        )
        self.assertEqual(csv_records[0]["parse_warnings"], "пример предупреждения")


if __name__ == "__main__":
    unittest.main()
