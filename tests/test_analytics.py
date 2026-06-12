import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch

from PIL import Image
from PIL import ImageDraw

from potanin_parser.analytics import (
    CHART_SIZE,
    _bounded_categorical_values,
    _fit_text,
    _font,
    _format_rubles,
    _funding_values,
    _limit_individual_values,
    _value_label_layout,
    build_summary,
    generate_charts,
)
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

    def test_font_falls_back_for_pillow_without_sized_default_font(self) -> None:
        fallback_font = object()

        def load_default(*args, **kwargs):
            if kwargs:
                raise TypeError("load_default() got an unexpected keyword argument 'size'")
            return fallback_font

        with (
            patch(
                "potanin_parser.analytics.ImageFont.truetype",
                side_effect=OSError("font unavailable"),
            ) as truetype,
            patch(
                "potanin_parser.analytics.ImageFont.load_default",
                side_effect=load_default,
            ) as default_font,
        ):
            result = _font(24)

        self.assertIs(result, fallback_font)
        self.assertEqual(truetype.call_count, 3)
        self.assertEqual(default_font.call_args_list, [call(size=24), call()])

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

    def test_grant_fund_alone_prevents_high_level_funding_skip(self) -> None:
        summary = build_summary(
            [competition(grant_fund_rub=25_000_000)],
            collected_at="2026-06-12T12:00:00+07:00",
            failed_pages=0,
        )

        self.assertEqual(summary["skipped_charts"], ["status", "deadline"])

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
                [
                    "statuses.png",
                    "deadlines.png",
                    "maximum_support.png",
                    "grant_funds.png",
                ],
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

            self.assertEqual(
                [path.name for path in generated],
                ["maximum_support.png", "grant_funds.png"],
            )
            for funding_path in generated:
                self.assertGreater(funding_path.stat().st_size, 0)
                with Image.open(funding_path) as image:
                    self.assertEqual(image.size, (1600, 900))
                    self.assertEqual(image.format, "PNG")

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

    def test_categorical_values_aggregate_but_funding_values_only_limit(self) -> None:
        values = [(f"Категория {index}", index + 1) for index in range(20)]

        categorical = _bounded_categorical_values(values)
        funding, note = _limit_individual_values(values)

        self.assertEqual(len(categorical), 15)
        self.assertEqual(categorical[-1], ("Остальные (6)", sum(range(15, 21))))
        self.assertEqual(funding, values[:15])
        self.assertEqual(note, "Показано 15 из 20")

    def test_funding_types_keep_both_values_from_same_competition(self) -> None:
        records = [
            competition(
                title="Конкурс с двумя суммами",
                max_support_rub=1_000_000,
                grant_fund_rub=25_000_000,
            )
        ]

        self.assertEqual(
            _funding_values(records, "max_support_rub"),
            [("Конкурс с двумя суммами", 1_000_000)],
        )
        self.assertEqual(
            _funding_values(records, "grant_fund_rub"),
            [("Конкурс с двумя суммами", 25_000_000)],
        )

    def test_text_and_value_layout_use_pixel_bounds(self) -> None:
        image = Image.new("RGB", CHART_SIZE, "white")
        draw = ImageDraw.Draw(image)
        font = _font(24)
        fitted = _fit_text(
            draw,
            "Очень длинное название конкурса, которое не должно заходить на столбцы",
            font,
            max_width=300,
        )
        fitted_box = draw.textbbox((0, 0), fitted, font=font)

        self.assertLessEqual(fitted_box[2] - fitted_box[0], 300)
        self.assertTrue(fitted.endswith("…"))

        inside_position, inside_color = _value_label_layout(
            draw,
            "1 000 000 руб.",
            font,
            bar_left=420,
            bar_right=1400,
            bar_top=200,
            bar_bottom=240,
            chart_right=1510,
        )
        outside_position, outside_color = _value_label_layout(
            draw,
            "1 000 000 руб.",
            font,
            bar_left=420,
            bar_right=440,
            bar_top=200,
            bar_bottom=240,
            chart_right=1510,
        )
        value_width = draw.textbbox((0, 0), "1 000 000 руб.", font=font)[2]

        self.assertEqual(inside_color, "white")
        self.assertLessEqual(90 + fitted_box[2] - fitted_box[0], 390)
        self.assertGreaterEqual(inside_position[0], 420)
        self.assertLessEqual(inside_position[0] + value_width, 1400)
        self.assertEqual(outside_color, "#111827")
        self.assertGreater(outside_position[0], 440)
        self.assertLessEqual(outside_position[0] + value_width, 1510)

    def test_generate_charts_removes_stale_managed_pngs_only(self) -> None:
        records = [
            competition(
                status="Прием заявок",
                application_end_date="2026-11-30",
                max_support_rub=1_000_000,
                grant_fund_rub=25_000_000,
            )
        ]

        with TemporaryDirectory() as directory:
            charts_dir = Path(directory) / "charts"
            generate_charts(records, charts_dir)
            (charts_dir / "funding.png").write_bytes(b"legacy")
            unrelated = charts_dir / "custom.png"
            unrelated.write_bytes(b"custom")

            generated = generate_charts([competition()], charts_dir)

            self.assertEqual(generated, [])
            self.assertEqual(
                sorted(path.name for path in charts_dir.iterdir()),
                ["custom.png"],
            )


if __name__ == "__main__":
    unittest.main()
