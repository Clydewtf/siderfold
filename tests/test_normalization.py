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
