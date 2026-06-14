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

    def test_ignores_unsafe_and_fragment_only_links(self) -> None:
        html = """
        <a class="programms__item-link" href="#catalog">Fragment</a>
        <a class="programms__item-link" href="javascript:alert(1)">Script</a>
        <a class="programms__item-link" href="data:text/plain,unsafe">Data</a>
        <a class="programms__item-link" href="/competitions/safe">Safe</a>
        """

        self.assertEqual(
            parse_catalog(html, BASE_URL),
            [f"{BASE_URL}/competitions/safe"],
        )


class CompetitionParserTests(unittest.TestCase):
    def test_extracts_application_link_from_current_orange_button_class(self) -> None:
        competition = parse_competition(
            """
            <html><body>
              <h1>Открытый конкурс</h1>
              <div class="contest__info">
                <h2>Когда и как проводится</h2>
                <p>Прием заявок осуществляется с 1 июня 2026 года по 30 июня 2026 года.</p>
              </div>
              <a class="aside__link button button--orange" href="https://apply.example/">
                Отправить заявку на участие
              </a>
            </body></html>
            """,
            CARD_URL,
            COLLECTED_AT,
        )

        self.assertEqual(competition.application_url, "https://apply.example/")

    def test_extracts_application_end_date_from_current_schedule_markup(self) -> None:
        competition = parse_competition(
            """
            <html><body>
              <h1>Конкурс с графиком</h1>
              <div class="contest__info"><p>Описание конкурса.</p></div>
              <li class="schedule__item schedule__item--blue">
                <h3 class="schedule__item-caption">Прием заявок на участие</h3>
                <p>До 16 декабря 2025 года</p>
              </li>
            </body></html>
            """,
            CARD_URL,
            COLLECTED_AT,
        )

        self.assertIsNone(competition.application_start_date)
        self.assertEqual(competition.application_end_date, "2025-12-16")

    def test_handles_comments_and_nested_section_wrappers(self) -> None:
        competition = parse_competition(
            fixture("nested_competition.html"), CARD_URL, COLLECTED_AT
        )

        self.assertEqual(competition.goals, "Развить партнерства.")
        self.assertEqual(competition.application_start_date, "2026-07-01")
        self.assertEqual(competition.application_end_date, "2026-08-31")
        self.assertEqual(competition.grant_fund_rub, 30_000_000)
        self.assertEqual(competition.max_support_rub, 2_000_000)
        self.assertEqual(competition.full_text.count("Развить партнерства."), 1)

    def test_keeps_empty_html_as_warned_record(self) -> None:
        competition = parse_competition("", CARD_URL, COLLECTED_AT)

        self.assertEqual(competition.title, "")
        self.assertEqual(competition.full_text, "")
        self.assertIn("title not found", competition.parse_warnings)
        self.assertIn("content block not found", competition.parse_warnings)

    def test_uses_page_text_when_content_block_is_missing(self) -> None:
        competition = parse_competition(
            "<html><body><h1>Карточка</h1><p>Полезное описание страницы.</p></body></html>",
            CARD_URL,
            COLLECTED_AT,
        )

        self.assertEqual(competition.full_text, "Карточка Полезное описание страницы.")
        self.assertIn("content block not found", competition.parse_warnings)

    def test_falls_back_to_full_text_for_each_funding_value(self) -> None:
        competition = parse_competition(
            fixture("funding_fallback_competition.html"), CARD_URL, COLLECTED_AT
        )

        self.assertEqual(competition.grant_fund_rub, 40_000_000)
        self.assertEqual(competition.max_support_rub, 3_000_000)

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
        self.assertEqual(
            competition.result_urls,
            [f"{BASE_URL}/results/events.pdf"],
        )
        self.assertEqual(
            competition.document_urls,
            [
                f"{BASE_URL}/documents/regulations.pdf",
                f"{BASE_URL}/documents/budget.xlsx",
            ],
        )
        self.assertEqual(
            competition.contacts,
            [
                {
                    "text": "Анна Иванова events@example.org +7 495 123-45-67",
                    "name": "Анна Иванова",
                    "email": "events@example.org",
                    "phone": "+74951234567",
                }
            ],
        )
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
