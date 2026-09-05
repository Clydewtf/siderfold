from __future__ import annotations

from collections.abc import Iterable
import re
from urllib.parse import urlsplit

from app.domain.models import ProgramAccessMode, ProgramResourceKind


_POTANIN_HOST = "fondpotanin.ru"
_POTANIN_COMPETITION_TITLE = re.compile(
    r"^#\s*фонд\s*потанина\s*(?P<edition>\d{1,4})$",
    re.IGNORECASE,
)
_NON_CONTENT_RESOURCE_SECTIONS = {
    "поделиться",
    "поделиться:",
    "социальные сети",
    "группы фонда в социальных сетях",
    "новости",
    "события",
    "истории",
    "похожие материалы",
    "читайте также",
}
_NON_CONTENT_RESOURCE_TITLES = {
    "назад",
    "вернуться",
    "поделиться",
    "поделиться:",
    "читать далее",
    "подробнее",
}
_NON_CONTENT_RESOURCE_CATEGORIES = {
    "contacts",
    "page",
    "share",
    "social",
}
_PUBLIC_CONTENT_CATEGORIES = frozenset(
    {
        "application",
        "criteria",
        "opportunities",
        "results",
    }
)
_SERVICE_RESOURCE_TITLE = re.compile(
    r"(?:политик\w*\s+(?:конфиденциальности|обработки персональных данных)|"
    r"пользовательск\w*\s+соглашени\w*|настройк\w*\s+cookie)",
    re.IGNORECASE,
)
_RUSSIA_SCOPE_PATTERN = re.compile(
    r"(?:все\s+регионы\s+россии|всех\s+регионах\s+россии|по\s+всей\s+россии|"
    r"на\s+всей\s+территории\s+россии|российск\w*\s+федерац|"
    r"российск\w*\s+(?:организац|нко|некоммерч|юридическ\w*\s+лиц|участник))",
    re.IGNORECASE,
)
_INVITATION_ONLY_PATTERN = re.compile(
    r"(?:по\s+приглашени\w*|приглашени\w*\s+(?:от\s+)?фонд\w*)",
    re.IGNORECASE,
)
_OPEN_APPLICATION_PATTERN = re.compile(
    r"(?:открыт\w*\s+для|все\s+желающ|любой\s+организац)",
    re.IGNORECASE,
)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def public_program_title(title: str, *, source_url: str | None) -> str:
    """Return a reader-friendly title while preserving the source title in provenance."""

    normalized = _clean_text(title) or title
    if source_url is None:
        return normalized
    parsed = urlsplit(source_url)
    if parsed.hostname != _POTANIN_HOST or not parsed.path.startswith("/competitions/"):
        return normalized
    match = _POTANIN_COMPETITION_TITLE.fullmatch(normalized)
    if match is None:
        return normalized
    return f"Фонд Потанина {match.group('edition')}"


def has_russia_scope(texts: Iterable[str | None]) -> bool:
    """Return whether the source explicitly describes a country-wide Russian scope."""

    combined = " ".join(value for text in texts if (value := _clean_text(text)) is not None)
    return bool(_RUSSIA_SCOPE_PATTERN.search(combined))


def infer_access_mode(texts: Iterable[str | None]) -> ProgramAccessMode:
    """Classify an explicitly stated application access condition."""

    combined = " ".join(value for text in texts if (value := _clean_text(text)) is not None)
    if _INVITATION_ONLY_PATTERN.search(combined):
        return ProgramAccessMode.INVITATION_ONLY
    if _OPEN_APPLICATION_PATTERN.search(combined):
        return ProgramAccessMode.OPEN
    return ProgramAccessMode.UNKNOWN


def resolved_access_mode(
    recorded_mode: ProgramAccessMode,
    texts: Iterable[str | None],
) -> ProgramAccessMode:
    """Use stored classification, or recover an explicit condition from public text."""

    if recorded_mode is not ProgramAccessMode.UNKNOWN:
        return recorded_mode
    return infer_access_mode(texts)


def is_public_resource(
    *,
    kind: ProgramResourceKind,
    title: str | None,
    source_section: str | None,
    section_category: str | None = None,
) -> bool:
    """Keep public cards limited to named, competition-specific materials."""

    normalized_title = _clean_text(title)
    if normalized_title is None:
        return False
    if normalized_title.casefold() in _NON_CONTENT_RESOURCE_TITLES:
        return False
    if _SERVICE_RESOURCE_TITLE.search(normalized_title):
        return False
    if kind is ProgramResourceKind.DETAIL:
        return False
    if kind is ProgramResourceKind.APPLICATION:
        return True
    category = _clean_text(section_category)
    if category is not None and category.casefold() in _NON_CONTENT_RESOURCE_CATEGORIES:
        return False
    section = _clean_text(source_section)
    if section is None:
        return False
    if section.casefold() in _NON_CONTENT_RESOURCE_SECTIONS:
        return False
    return True


def is_public_content_section(
    *,
    category: str,
    heading: str,
    content: str,
) -> bool:
    """Avoid repeating structured fields or exposing page chrome as public content."""

    if category not in _PUBLIC_CONTENT_CATEGORIES:
        return False
    normalized_heading = _clean_text(heading)
    normalized_content = _clean_text(content)
    if normalized_heading is None or normalized_content is None:
        return False
    if normalized_heading.casefold().startswith("поделиться"):
        return False
    if ".pdf" in normalized_heading.casefold() or re.search(
        r"\bpdf\b", normalized_content, re.IGNORECASE
    ):
        return False
    return True
