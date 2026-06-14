import unittest
from potanin_parser.normalization import extract_application_dates, parse_money_values


class NormalizationTest(unittest.TestCase):
    def test_extracts_valid_explicit_year_application_period(self):
        text = "Прием заявок осуществляется с 19 декабря 2025 года по 30 ноября 2026 года."
        self.assertEqual(extract_application_dates(text), ("2025-12-19", "2026-11-30"))

    def test_rejects_inverted_explicit_year_application_period(self):
        text = "Прием заявок осуществляется с 19 декабря 2026 года по 30 ноября 2025 года."
        self.assertEqual(extract_application_dates(text), (None, None))

    def test_extracts_application_period_with_shared_year(self):
        text = "Конкурс проводился с 25 марта по 15 декабря 2020 года."
        self.assertEqual(extract_application_dates(text), ("2020-03-25", "2020-12-15"))

    def test_rejects_inverted_application_period_with_shared_year(self):
        text = "Конкурс проводился с 15 декабря по 25 марта 2020 года."
        self.assertEqual(extract_application_dates(text), (None, None))

    def test_parses_money_units(self):
        values = parse_money_values("500 000 рублей, 1 млн рублей и грантовый фонд 25 млн рублей")
        self.assertEqual(values, [500_000, 1_000_000, 25_000_000])

    def test_returns_empty_values_for_missing_data(self):
        self.assertEqual(extract_application_dates("Сроки будут опубликованы позднее"), (None, None))
        self.assertEqual(parse_money_values("Финансирование не указано"), [])

    def test_rejects_malformed_money_numbers(self):
        text = "1,2,3 млн, 12 34 млн и 1 23 456 рублей"
        self.assertEqual(parse_money_values(text), [])

    def test_accepts_only_exact_decimal_ruble_values(self):
        text = "1,5 млн рублей, 12,75 рублей и 0,0015 тыс рублей"
        self.assertEqual(parse_money_values(text), [1_500_000])

    def test_parses_bare_ruble_abbreviations(self):
        self.assertEqual(parse_money_values("500 руб"), [500])
        self.assertEqual(parse_money_values("500 руб."), [500])

    def test_parses_all_russian_genitive_month_names(self):
        months = (
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        )
        for month_number, month_name in enumerate(months, start=1):
            with self.subTest(month=month_name):
                text = f"с 1 {month_name} 2025 года по 2 {month_name} 2025 года"
                expected = (
                    f"2025-{month_number:02d}-01",
                    f"2025-{month_number:02d}-02",
                )
                self.assertEqual(extract_application_dates(text), expected)

    def test_normalizes_whitespace_in_dates_and_money(self):
        dates = "с\u00a01   января\n2025 года\tпо 2 февраля 2025 года"
        money = "1\u00a0500\u00a0рублей"
        self.assertEqual(extract_application_dates(dates), ("2025-01-01", "2025-02-02"))
        self.assertEqual(parse_money_values(money), [1_500])

    def test_invalid_calendar_dates_return_none(self):
        invalid_start = "с 31 февраля 2025 года по 1 марта 2025 года"
        invalid_end = "с 1 марта 2025 года по 31 апреля 2025 года"
        self.assertEqual(extract_application_dates(invalid_start), (None, None))
        self.assertEqual(extract_application_dates(invalid_end), (None, None))

    def test_parses_thousand_and_billion_units(self):
        self.assertEqual(parse_money_values("2 тыс рублей и 3 млрд рублей"), [2_000, 3_000_000_000])

    def test_returns_unique_money_values_in_source_order(self):
        text = "2 млн, 500 000 рублей, 2 млн рублей, 1 тыс и 500 000 рублей"
        self.assertEqual(parse_money_values(text), [2_000_000, 500_000, 1_000])
