from __future__ import annotations

from app.domain.models import ProgramResourceKind
from app.domain.presentation import (
    has_russia_scope,
    is_public_content_section,
    is_public_resource,
    public_program_title,
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


def test_public_resource_policy_keeps_named_competition_materials_only() -> None:
    assert is_public_resource(
        kind=ProgramResourceKind.COMPETITION_DOCUMENT,
        title="Положение о конкурсе",
        source_section="Документы конкурса",
        section_category="documents",
    )
    assert is_public_resource(
        kind=ProgramResourceKind.APPLICATION,
        title="Подать заявку",
        source_section=None,
        section_category="page",
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


def test_country_scope_recognizes_russian_nonprofits_without_guessing_other_text() -> None:
    assert has_russia_scope(("Конкурс открыт для российских некоммерческих организаций.",))
    assert not has_russia_scope(("Фонд поддерживает культурные инициативы.",))
