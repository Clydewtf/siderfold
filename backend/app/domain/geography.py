"""Canonical labels and filter expansion for the geography taxonomy.

The stored taxonomy remains intentionally flat: a program is linked to the
exact geography supplied by the source (a subject, city, country, or federal
district).  The public catalog can nevertheless offer a useful hierarchy by
expanding a selected federal district to its subjects at query time.  Keeping
that expansion here avoids a schema migration while making the filter
semantics explicit and deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final
from unicodedata import normalize as unicode_normalize


FederalDistrict = tuple[str, str]


FEDERAL_DISTRICTS: Final[tuple[FederalDistrict, ...]] = (
    ("central", "Центральный"),
    ("northwestern", "Северо-Западный"),
    ("volga", "Приволжский"),
    ("southern", "Южный"),
    ("north-caucasian", "Северо-Кавказский"),
    ("ural", "Уральский"),
    ("siberian", "Сибирский"),
    ("far-eastern", "Дальневосточный"),
)


# Names are compared case-insensitively by the API.  The list intentionally
# includes the spellings used by source adapters (``Республика Татарстан``,
# ``Удмуртская республика`` and so on) rather than trying to infer a subject
# from its suffix.  A subject can therefore be selected exactly as it appears
# on a source and still be covered by its federal-district filter.
FEDERAL_DISTRICT_SUBJECT_NAMES: Final[dict[str, tuple[str, ...]]] = {
    "central": (
        "Белгородская область", "Брянская область", "Владимирская область",
        "Воронежская область", "Ивановская область", "Калужская область",
        "Костромская область", "Курская область", "Липецкая область",
        "Московская область", "Москва", "Орловская область", "Рязанская область",
        "Смоленская область", "Тамбовская область", "Тверская область",
        "Тульская область", "Ярославская область",
    ),
    "northwestern": (
        "Архангельская область", "Вологодская область", "Калининградская область",
        "Ленинградская область", "Мурманская область", "Ненецкий автономный округ",
        "Новгородская область", "Псковская область", "Республика Карелия",
        "Республика Коми", "Санкт-Петербург",
    ),
    "southern": (
        "Адыгея", "Республика Адыгея", "Астраханская область", "Волгоградская область",
        "Калмыкия", "Республика Калмыкия", "Краснодарский край", "Республика Крым", "Ростовская область",
        "Севастополь",
    ),
    "north-caucasian": (
        "Дагестан", "Республика Дагестан", "Ингушетия", "Республика Ингушетия", "Кабардино-Балкарская Республика",
        "Карачаево-Черкесская Республика", "Северная Осетия — Алания",
        "Республика Северная Осетия — Алания", "Чеченская Республика", "Ставропольский край",
    ),
    "volga": (
        "Башкортостан", "Республика Башкортостан", "Кировская область", "Марий Эл", "Республика Марий Эл", "Мордовия", "Республика Мордовия",
        "Нижегородская область", "Оренбургская область", "Пензенская область",
        "Пермский край", "Самарская область", "Саратовская область",
        "Республика Татарстан", "Удмуртская республика", "Удмуртская Республика", "Республика Удмуртия", "Ульяновская область",
        "Чувашская Республика", "Республика Чувашия",
    ),
    "ural": (
        "Курганская область", "Свердловская область", "Тюменская область",
        "Ханты-Мансийский автономный округ — Югра", "Челябинская область",
        "Ямало-Ненецкий автономный округ",
    ),
    "siberian": (
        "Алтай", "Республика Алтай", "Алтайский край", "Иркутская область", "Кемеровская область", "Кемеровская область — Кузбасс",
        "Красноярский край", "Новосибирская область", "Омская область",
        "Республика Тыва", "Республика Хакасия", "Томская область",
    ),
    "far-eastern": (
        "Амурская область", "Еврейская автономная область", "Забайкальский край",
        "Камчатский край", "Магаданская область", "Приморский край",
        "Республика Саха (Якутия)", "Сахалинская область", "Хабаровский край",
        "Чукотский автономный округ",
    ),
}


def _name_key(value: str) -> str:
    normalized = unicode_normalize("NFKC", value).replace("ё", "е").casefold()
    return re.sub(r"[\s_\-–—]+", " ", normalized).strip()


_FEDERAL_DISTRICT_BY_NAME: Final[dict[str, FederalDistrict]] = {
    **{
        _name_key(name): (slug, name)
        for slug, name in FEDERAL_DISTRICTS
    },
    **{
        _name_key(f"{name} федеральный округ"): (slug, name)
        for slug, name in FEDERAL_DISTRICTS
    },
    "цфо": ("central", "Центральный"),
    "сзфо": ("northwestern", "Северо-Западный"),
    "пфо": ("volga", "Приволжский"),
    "юфо": ("southern", "Южный"),
    "скфо": ("north-caucasian", "Северо-Кавказский"),
    "уфо": ("ural", "Уральский"),
    "сфо": ("siberian", "Сибирский"),
    "дфо": ("far-eastern", "Дальневосточный"),
}


_FEDERAL_DISTRICT_BY_SLUG: Final[dict[str, FederalDistrict]] = {
    "central": ("central", "Центральный"),
    "centralny": ("central", "Центральный"),
    "centralnyi": ("central", "Центральный"),
    "centralnyy": ("central", "Центральный"),
    "northwestern": ("northwestern", "Северо-Западный"),
    "north-western": ("northwestern", "Северо-Западный"),
    "severo-zapadny": ("northwestern", "Северо-Западный"),
    "severo-zapadnyi": ("northwestern", "Северо-Западный"),
    "severo-zapadnyy": ("northwestern", "Северо-Западный"),
    "volga": ("volga", "Приволжский"),
    "privolzhsky": ("volga", "Приволжский"),
    "privolzhskiy": ("volga", "Приволжский"),
    "southern": ("southern", "Южный"),
    "south": ("southern", "Южный"),
    "yuzhny": ("southern", "Южный"),
    "yuzhnyi": ("southern", "Южный"),
    "north-caucasian": ("north-caucasian", "Северо-Кавказский"),
    "north-caucasus": ("north-caucasian", "Северо-Кавказский"),
    "severo-kavkazsky": ("north-caucasian", "Северо-Кавказский"),
    "severo-kavkazskiy": ("north-caucasian", "Северо-Кавказский"),
    "ural": ("ural", "Уральский"),
    "urals": ("ural", "Уральский"),
    "uralsky": ("ural", "Уральский"),
    "uralskiy": ("ural", "Уральский"),
    "siberian": ("siberian", "Сибирский"),
    "siberia": ("siberian", "Сибирский"),
    "sibirsky": ("siberian", "Сибирский"),
    "sibirskiy": ("siberian", "Сибирский"),
    "far-eastern": ("far-eastern", "Дальневосточный"),
    "far-east": ("far-eastern", "Дальневосточный"),
    "dalnevostochny": ("far-eastern", "Дальневосточный"),
    "dalnevostochnyi": ("far-eastern", "Дальневосточный"),
    "dalnevostochnyy": ("far-eastern", "Дальневосточный"),
}

_FEDERAL_DISTRICT_SLUG_SUFFIXES: Final[tuple[str, ...]] = (
    "-federal-district",
    "-federalny-okrug",
    "-federalnyi-okrug",
    "-federalnyy-okrug",
)


def _federal_district_from_slug(value: str) -> FederalDistrict | None:
    normalized = value.strip().casefold()
    canonical = _FEDERAL_DISTRICT_BY_SLUG.get(normalized)
    if canonical is not None:
        return canonical
    for suffix in _FEDERAL_DISTRICT_SLUG_SUFFIXES:
        if normalized.endswith(suffix):
            return _FEDERAL_DISTRICT_BY_SLUG.get(normalized[: -len(suffix)])
    return None


def normalize_geography_entry(*, slug: str, name: str) -> tuple[str, str]:
    """Return the canonical federal-district entry, if the input is an alias.

    Labels outside this closed alias set are returned as-is.  In particular,
    this intentionally preserves cities, oblasts, krais, republics and country
    labels for the caller to model at their actual level of specificity.
    """

    canonical = _FEDERAL_DISTRICT_BY_NAME.get(_name_key(name))
    if canonical is None:
        canonical = _federal_district_from_slug(slug)
    return canonical if canonical is not None else (slug, name)


def canonical_federal_district(slug: str) -> FederalDistrict | None:
    """Resolve a filter slug/name alias to the canonical district, if any."""

    return _federal_district_from_slug(slug) or _FEDERAL_DISTRICT_BY_NAME.get(_name_key(slug))


def federal_district_filter_names(slugs: Sequence[str] | None) -> tuple[str, ...]:
    """Return names that should match a selected federal-district slug.

    The result contains the canonical district label, its historical full
    label, and all known subjects.  SQL callers should compare these names
    case-insensitively and combine them with an exact slug match for ordinary
    geography filters.
    """

    if not slugs:
        return ()
    names: set[str] = set()
    for slug in slugs:
        canonical = canonical_federal_district(slug)
        if canonical is None:
            continue
        canonical_slug, canonical_name = canonical
        names.add(canonical_name)
        names.add(f"{canonical_name} федеральный округ")
        names.update(FEDERAL_DISTRICT_SUBJECT_NAMES.get(canonical_slug, ()))
    return tuple(sorted(names, key=_name_key))
