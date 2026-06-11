from pathlib import Path
import unittest

from potanin_parser.html_parser import parse_catalog, parse_competition


BASE_URL = "https://fondpotanin.ru"
CARD_URL = f"{BASE_URL}/competitions/events"
COLLECTED_AT = "2026-06-12T12:00:00+07:00"
FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class CatalogParserTests(unittest.TestCase):
    def test_returns_absolute_unique_competition_links(self) -> None:
        links = parse_catalog(fixture("catalog.html"), BASE_URL)

        self.assertEqual(
            links,
            [
                f"{BASE_URL}/competitions/events",
                f"{BASE_URL}/competitions/museums",
            ],
        )
        self.assertEqual(len(links), 2)
        self.assertTrue(all(link.startswith(BASE_URL) for link in links))

    def test_removes_fragments_and_deduplicates_in_source_order(self) -> None:
        html = """
        <a class="programms__item-link" href="/competitions/events#details">First</a>
        <a class="programms__item-link" href="/competitions/events#results">Duplicate</a>
        <a class="programms__item-link" href="/competitions/museums">Second</a>
        """

        self.assertEqual(
            parse_catalog(html, BASE_URL),
            [
                f"{BASE_URL}/competitions/events",
                f"{BASE_URL}/competitions/museums",
            ],
        )


class CompetitionParserTests(unittest.TestCase):
    def test_uses_grant_fund_heading_as_amount_context(self) -> None:
        competition = parse_competition(
            fixture("heading_fund_competition.html"), CARD_URL, COLLECTED_AT
        )

        self.assertEqual(competition.grant_fund_rub, 25_000_000)
        self.assertEqual(competition.max_support_rub, 1_000_000)

    def test_extracts_grant_fund_when_support_limits_appear_first(self) -> None:
        competition = parse_competition(
            fixture("competition.html"), CARD_URL, COLLECTED_AT
        )

        self.assertEqual(competition.grant_fund_rub, 25_000_000)

    def test_extracts_maximum_support_when_minimum_appears_first(self) -> None:
        competition = parse_competition(
            fixture("competition.html"), CARD_URL, COLLECTED_AT
        )

        self.assertEqual(competition.max_support_rub, 1_000_000)

    def test_parses_complete_competition_card(self) -> None:
        competition = parse_competition(
            fixture("competition.html"), CARD_URL, COLLECTED_AT
        )

        self.assertEqual(competition.title, "Конкурс событий для сообщества «#Мынасвязи»")
        self.assertEqual(competition.status, "Прием заявок")
        self.assertEqual(competition.publication_date, "2026-06-12")
        self.assertEqual(competition.application_end_date, "2026-11-30")
        self.assertEqual(competition.grant_fund_rub, 25_000_000)
        self.assertEqual(competition.max_support_rub, 1_000_000)
        self.assertEqual(competition.application_url, f"{BASE_URL}/apply/events")
        self.assertTrue(competition.result_urls)
        self.assertTrue(competition.document_urls)
        self.assertTrue(competition.contacts)
        self.assertIn("Цели конкурса", competition.sections)
        self.assertEqual(competition.goals, "Развитие горизонтальных связей.")
        self.assertIn("Заявки принимаются", competition.procedure)
        self.assertEqual(competition.parse_warnings, [])

    def test_keeps_incomplete_card_and_records_warnings(self) -> None:
        competition = parse_competition(
            fixture("incomplete_competition.html"), CARD_URL, COLLECTED_AT
        )

        self.assertEqual(competition.title, "Конкурс без опубликованных сроков")
        self.assertIn("Описание конкурса сохранено", competition.full_text)
        self.assertIsNone(competition.application_end_date)
        self.assertIsNone(competition.grant_fund_rub)
        self.assertIn("application dates not found", competition.parse_warnings)
        self.assertIn("funding not found", competition.parse_warnings)


if __name__ == "__main__":
    unittest.main()
