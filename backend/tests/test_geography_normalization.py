from __future__ import annotations

import pytest

from app.domain.geography import federal_district_filter_names, normalize_geography_entry
from app.review.service import _taxonomy_entries


@pytest.mark.parametrize(
    ("slug", "name", "expected"),
    [
        (
            "far-eastern-federal-district",
            "Дальневосточный федеральный округ",
            ("far-eastern", "Дальневосточный"),
        ),
        (
            "volga-federalny-okrug",
            "Приволжский федеральный округ",
            ("volga", "Приволжский"),
        ),
        ("sfo", "СФО", ("siberian", "Сибирский")),
        ("northwestern", "Северо-Западный", ("northwestern", "Северо-Западный")),
    ],
)
def test_federal_district_aliases_use_one_public_label(
    slug: str,
    name: str,
    expected: tuple[str, str],
) -> None:
    assert normalize_geography_entry(slug=slug, name=name) == expected


def test_concrete_subject_of_russia_is_not_replaced_with_its_federal_district() -> None:
    assert normalize_geography_entry(
        slug="nizhny-novgorod-oblast",
        name="Нижегородская область",
    ) == ("nizhny-novgorod-oblast", "Нижегородская область")


def test_review_taxonomy_collapses_federal_district_aliases_before_publication() -> None:
    entries = _taxonomy_entries(
        {
            "taxonomy": {
                "geographies": [
                    {
                        "slug": "far-eastern-federal-district",
                        "name": "Дальневосточный федеральный округ",
                    },
                    {"slug": "far-eastern", "name": "Дальневосточный"},
                    {"slug": "moscow", "name": "Москва"},
                ]
            }
        },
        "geographies",
    )

    assert entries == [
        ("far-eastern", "Дальневосточный"),
        ("moscow", "Москва"),
    ]


def test_federal_district_filter_expands_to_subject_names() -> None:
    names = federal_district_filter_names(["far-eastern"])

    assert "Дальневосточный" in names
    assert "Дальневосточный федеральный округ" in names
    assert "Приморский край" in names
