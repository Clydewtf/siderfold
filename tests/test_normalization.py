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

    def test_rejects_malformed_money_numbers(self):
        text = "1,2,3 млн, 12 34 млн и 1 23 456 рублей"
        self.assertEqual(parse_money_values(text), [])

    def test_accepts_only_exact_decimal_ruble_values(self):
        text = "1,5 млн рублей, 12,75 рублей и 0,0015 тыс рублей"
        self.assertEqual(parse_money_values(text), [1_500_000])

    def test_parses_bare_ruble_abbreviations(self):
        self.assertEqual(parse_money_values("500 руб"), [500])
        self.assertEqual(parse_money_values("500 руб."), [500])
