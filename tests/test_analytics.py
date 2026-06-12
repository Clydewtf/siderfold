import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from potanin_parser.analytics import _format_rubles, build_summary, generate_charts
from potanin_parser.models import Competition


def competition(**overrides) -> Competition:
    values = {
        "source": "Фонд Потанина",
        "source_url": "https://example.test/competition",
        "collected_at": "2026-06-12T12:00:00+07:00",
        "title": "Конкурс",
    }
    values.update(overrides)
    return Competition(**values)


class AnalyticsTests(unittest.TestCase):
    @staticmethod
    def _blue_bar_ranges(image: Image.Image) -> list[tuple[int, int]]:
        blue = (37, 99, 235)
        rows = [
            y
            for y in range(image.height)
            if any(image.getpixel((x, y)) == blue for x in range(image.width))
        ]
        ranges = []
        for y in rows:
            if not ranges or y > ranges[-1][1] + 1:
                ranges.append((y, y))
            else:
                ranges[-1] = (ranges[-1][0], y)
        return ranges

    def test_build_summary_reports_collection_and_data_quality_metrics(self) -> None:
        records = [
            competition(
                title="Первый конкурс",
                status="Прием заявок",
                application_end_date="2026-11-30",
                grant_fund_rub=25_000_000,
                max_support_rub=1_000_000,
                parse_warnings=["warning one", "warning two"],
            ),
            competition(
                title="Второй конкурс",
                status="Завершен",
                application_end_date="2025-12-31",
                max_support_rub=500_000,
                parse_warnings=["warning three"],
            ),
            competition(title="Третий конкурс", status=None),
        ]

        summary = build_summary(
            records,
            collected_at="2026-06-12T12:00:00+07:00",
            failed_pages=2,
        )

        self.assertEqual(summary["collection_time"], "2026-06-12T12:00:00+07:00")
        self.assertEqual(summary["source"], "Фонд Потанина")
        self.assertEqual(summary["record_count"], 3)
        self.assertEqual(
            summary["status_distribution"],
            {"Прием заявок": 1, "Завершен": 1, "Не указан": 1},
        )
        self.assertEqual(summary["parsed_deadline_count"], 2)
        self.assertEqual(summary["parsed_funding_count"], 2)
        self.assertEqual(summary["minimum_support_rub"], 500_000)
        self.assertEqual(summary["maximum_support_rub"], 1_000_000)
        self.assertEqual(summary["total_warnings"], 3)
        self.assertEqual(summary["failed_pages"], 2)
        self.assertEqual(summary["skipped_charts"], [])

    def test_formats_funding_values_without_font_specific_symbols(self) -> None:
        self.assertEqual(_format_rubles(0), "0 руб.")
        self.assertEqual(_format_rubles(1_500_000), "1 500 000 руб.")

    def test_build_summary_records_charts_without_corresponding_data(self) -> None:
        summary = build_summary(
            [competition()],
            collected_at="2026-06-12T12:00:00+07:00",
            failed_pages=0,
        )

        self.assertEqual(
            summary["skipped_charts"],
            ["status", "deadline", "funding"],
        )

    def test_generate_charts_creates_readable_non_empty_png_files(self) -> None:
        records = [
            competition(
                status="Прием заявок",
                application_end_date="2026-11-30",
                max_support_rub=1_000_000,
            ),
            competition(
                status="Завершен",
                application_end_date="2025-12-31",
                grant_fund_rub=25_000_000,
            ),
        ]

        with TemporaryDirectory() as directory:
            charts_dir = Path(directory) / "charts"
            generated = generate_charts(records, charts_dir)

            self.assertEqual(
                [path.name for path in generated],
                ["statuses.png", "deadlines.png", "funding.png"],
            )
            for path in generated:
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)
                with Image.open(path) as image:
                    self.assertEqual(image.size, (1600, 900))
                    self.assertEqual(image.format, "PNG")

    def test_generate_funding_chart_for_zero_amount(self) -> None:
        records = [competition(grant_fund_rub=0, max_support_rub=0)]

        with TemporaryDirectory() as directory:
            charts_dir = Path(directory) / "charts"
            generated = generate_charts(records, charts_dir)

            self.assertEqual([path.name for path in generated], ["funding.png"])
            funding_path = generated[0]
            self.assertGreater(funding_path.stat().st_size, 0)
            with Image.open(funding_path) as image:
                self.assertEqual(image.size, (1600, 900))
                value_area = image.crop((420, 160, 520, 220))
                self.assertTrue(
                    any(
                        value_area.getpixel((x, y)) != (255, 255, 255)
                        for y in range(value_area.height)
                        for x in range(value_area.width)
                    )
                )

    def test_many_categories_are_aggregated_inside_chart_bounds(self) -> None:
        records = [
            competition(title=f"Конкурс {index}", status=f"Статус {index:02d}")
            for index in range(20)
        ]

        with TemporaryDirectory() as directory:
            generated = generate_charts(records, Path(directory) / "charts")

            self.assertEqual([path.name for path in generated], ["statuses.png"])
            with Image.open(generated[0]) as image:
                bar_ranges = self._blue_bar_ranges(image)

        self.assertEqual(len(bar_ranges), 15)
        self.assertTrue(
            all(160 <= top <= bottom <= 830 for top, bottom in bar_ranges)
        )


if __name__ == "__main__":
    unittest.main()
