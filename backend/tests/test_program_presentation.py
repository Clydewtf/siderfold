from __future__ import annotations

from app.domain.models import ProgramResourceKind
from app.domain.presentation import (
    has_russia_scope,
    is_public_content_section,
    is_public_resource,
    is_social_resource_url,
    is_winner_resource,
    public_resource_kind,
    public_program_title,
    winner_resource_group_key,
)


def test_known_source_label_is_normalized_without_changing_other_titles() -> None:
    assert public_program_title(
        "#фондпотанина25",
        source_url="https://fondpotanin.ru/competitions/fondpotanina25",
    ) == "Фонд Потанина 25"
    assert public_program_title(
        "#фондпотанина25",
        source_url="https://example.test/competitions/fondpotanina25",
    ) == "#фондпотанина25"
    assert public_program_title(
        "Конкурс общественных инициатив",
        source_url="https://fondpotanin.ru/competitions/public-initiatives/",
    ) == "Конкурс общественных инициатив"
    assert public_program_title(
        "«Креативный музей»",
        source_url="https://fondpotanin.ru/competitions/kreativnyy-muzey/",
    ) == "Креативный музей"


def test_public_resource_policy_keeps_named_competition_materials_only() -> None:
    assert is_public_resource(
        kind=ProgramResourceKind.COMPETITION_DOCUMENT,
        title="Положение о конкурсе",
        source_section="Документы конкурса",
        section_category="documents",
    )
    assert not is_public_resource(
        kind=ProgramResourceKind.APPLICATION,
        title="Подать заявку",
        source_section=None,
        section_category="application",
    )
    assert is_public_resource(
        kind=ProgramResourceKind.APPLICATION,
        title="Подать заявку",
        source_section=None,
    )
    assert not is_public_resource(
        kind=ProgramResourceKind.REFERENCE,
        title="Назад",
        source_section="Документы конкурса",
        section_category="documents",
    )
    assert not is_public_resource(
        kind=ProgramResourceKind.REFERENCE,
        title="Новость фонда",
        source_section=None,
        section_category="page",
    )
    assert not is_public_resource(
        kind=ProgramResourceKind.REFERENCE,
        title="Политика обработки персональных данных",
        source_section="Подвал сайта",
        section_category="page",
    )
    assert not is_public_resource(
        kind=ProgramResourceKind.DETAIL,
        title="Подробнее о фонде",
        source_section="О фонде",
        section_category="supplementary",
    )
    assert not is_public_resource(
        kind=ProgramResourceKind.COMPETITION_DOCUMENT,
        title="Термины и определения",
        source_section="Требования к участникам",
        section_category="eligibility",
    )
    assert is_public_resource(
        kind=ProgramResourceKind.REFERENCE,
        title="Официальная ссылка",
        source_section="Документы конкурса",
        section_category="documents",
    )


def test_winner_materials_are_promoted_while_social_channels_remain_references() -> None:
    assert is_winner_resource(
        title="2026 год",
        source_section="Победители разных лет",
    )
    assert public_resource_kind(
        ProgramResourceKind.COMPETITION_DOCUMENT,
        title="Список победителей",
        source_section="Документы конкурса",
    ) is ProgramResourceKind.RESULT
    assert not is_social_resource_url("https://fondpotanin.ru/upload/winners.pdf")
    assert is_social_resource_url("https://t.me/competition")
    assert public_resource_kind(
        ProgramResourceKind.RESULT,
        title="Телеграм-канал конкурса",
        source_section="Победители",
        url="https://t.me/competition",
    ) is ProgramResourceKind.REFERENCE
    assert is_public_resource(
        kind=ProgramResourceKind.REFERENCE,
        title="Телеграм-канал конкурса",
        source_section="Победители",
    )
    assert not is_public_resource(
        kind=ProgramResourceKind.RESULT,
        title="Результаты исследования рынка",
        source_section=None,
    )


def test_winner_file_name_is_kept_when_legacy_context_is_wrong() -> None:
    winner_url = "https://fondpotanin.ru/upload/%D0%BF%D0%BE%D0%B1%D0%B5%D0%B4%D0%B8%D1%82%D0%B5%D0%BB%D0%B8-2026.pdf"

    assert is_winner_resource(
        title="2025/2026",
        source_section="Консультации",
        url=winner_url,
    )
    assert public_resource_kind(
        ProgramResourceKind.COMPETITION_DOCUMENT,
        title="2025/2026",
        source_section="Консультации",
        url=winner_url,
    ) is ProgramResourceKind.RESULT
    assert is_public_resource(
        kind=ProgramResourceKind.RESULT,
        title="2025/2026",
        source_section="Консультации",
        url=winner_url,
    )
    assert is_winner_resource(
        title="IV цикл",
        source_section="Консультации",
        url="https://fondpotanin.ru/press/news/rezultaty-iv-tsikla-konkursa/",
    )
    assert winner_resource_group_key("I цикл") == "i цикл"
    assert public_resource_kind(
        ProgramResourceKind.COMPETITION_DOCUMENT,
        title="I цикл",
        source_section="Консультации",
        group_has_winner_evidence=True,
    ) is ProgramResourceKind.RESULT
    assert is_public_resource(
        kind=ProgramResourceKind.RESULT,
        title="I цикл",
        source_section="Консультации",
        group_has_winner_evidence=True,
    )


def test_public_content_policy_excludes_page_chrome_and_structured_duplicates() -> None:
    assert is_public_content_section(
        category="criteria",
        heading="Критерии оценки",
        content="Заявки оцениваются экспертами по опубликованным критериям.",
    )
    assert not is_public_content_section(
        category="goals",
        heading="Цели",
        content="Поддержка проектов.",
    )
    assert not is_public_content_section(
        category="unclassified",
        heading="Поделиться:",
        content="Ссылка на социальные сети.",
    )
    assert not is_public_content_section(
        category="application",
        heading="Документы конкурса.pdf",
        content="Скачать PDF.",
    )
    assert not is_public_content_section(
        category="results",
        heading="Объявление результатов конкурса",
        content="Не позднее 27 февраля 2026 года.",
    )
    assert not is_public_content_section(
        category="results",
        heading="Вводный семинар для победителей",
        content="Не позднее 6 марта 2026 года.",
    )


def test_country_scope_recognizes_russian_nonprofits_without_guessing_other_text() -> None:
    assert has_russia_scope(("Конкурс открыт для российских некоммерческих организаций.",))
    assert not has_russia_scope(("Фонд поддерживает культурные инициативы.",))
