from __future__ import annotations

from collections.abc import Iterable
import re
from urllib.parse import unquote, urlsplit

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
_WINNER_RESOURCE_PATTERN = re.compile(
    r"(?:победител\w*|лауреат\w*|(?:итог|результат)\w*\s+"
    r"(?:конкурс\w*|отбор\w*|программ\w*))",
    re.IGNORECASE,
)
_WINNER_URL_TERM_PATTERN = re.compile(
    r"(?:победител\w*|лауреат\w*|(?:итог|результат)\w*|"
    r"pobeditel[a-z0-9_-]*|laureat[a-z0-9_-]*|"
    r"(?:itog|rezultat)[a-z0-9_-]*)",
    re.IGNORECASE,
)
_WINNER_URL_DIRECT_TERM_PATTERN = re.compile(
    r"(?:победител\w*|лауреат\w*|pobeditel[a-z0-9_-]*|laureat[a-z0-9_-]*)",
    re.IGNORECASE,
)
_COMPETITION_URL_CONTEXT_PATTERN = re.compile(
    r"(?:конкурс\w*|цикл\w*|konkurs[a-z0-9_-]*|(?:c|ts)ikl[a-z0-9_-]*)",
    re.IGNORECASE,
)
_WINNER_GROUP_LABEL_PATTERN = re.compile(
    r"(?:(?:[ivxlcdm]+|\d+)\s+цикл|20\d{2}\s*[/–-]\s*20\d{2})",
    re.IGNORECASE,
)
_SCHEDULE_MILESTONE_PATTERN = re.compile(
    r"(?:объявлен\w*\s+(?:результат\w*|победител\w*|итог\w*)|"
    r"подведен\w*\s+(?:итог\w*|результат\w*)|"
    r"(?:вводн\w*\s+)?семинар\w*\s+(?:для\s+)?победител\w*|"
    r"заключен\w*\s+договор\w*\s+(?:с\s+)?победител\w*)",
    re.IGNORECASE,
)
_SOCIAL_RESOURCE_HOSTS = frozenset(
    {
        "t.me",
        "telegram.me",
        "vk.com",
        "vkontakte.ru",
    }
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
_OUTER_TITLE_QUOTE_PAIRS = (("«", "»"), ("“", "”"), ('"', '"'))


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _strip_outer_title_quotes(value: str) -> str:
    """Remove one purely decorative pair of quotation marks from a title."""

    for opening, closing in _OUTER_TITLE_QUOTE_PAIRS:
        if value.startswith(opening) and value.endswith(closing) and len(value) > 2:
            stripped = value[len(opening) : len(value) - len(closing)].strip()
            if stripped:
                return stripped
    return value


def public_program_title(title: str, *, source_url: str | None) -> str:
    """Return a reader-friendly title while preserving the source title in provenance."""

    normalized = _strip_outer_title_quotes(_clean_text(title) or title)
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


def is_social_resource_url(url: str | None) -> bool:
    """Return whether a URL points to a social channel rather than source material."""

    if url is None:
        return False
    hostname = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    return hostname in _SOCIAL_RESOURCE_HOSTS or any(
        hostname.endswith(f".{host}") for host in _SOCIAL_RESOURCE_HOSTS
    )


def is_schedule_milestone_title(value: str | None) -> bool:
    """Recognize a dated program milestone rather than a winner-list heading."""

    normalized = _clean_text(value)
    return normalized is not None and _SCHEDULE_MILESTONE_PATTERN.search(normalized) is not None


def is_winner_resource(
    *,
    title: str | None,
    source_section: str | None,
    url: str | None = None,
) -> bool:
    """Recognize a material that directly leads to competition winners or results."""

    url_path = unquote(urlsplit(url).path) if url is not None else None
    if any(
        _WINNER_RESOURCE_PATTERN.search(value) is not None
        for value in (_clean_text(title), _clean_text(source_section))
        if value is not None
    ):
        return True
    normalized_url_path = _clean_text(url_path)
    return (
        normalized_url_path is not None
        and _WINNER_URL_TERM_PATTERN.search(normalized_url_path) is not None
        and (
            _WINNER_URL_DIRECT_TERM_PATTERN.search(normalized_url_path) is not None
            or _COMPETITION_URL_CONTEXT_PATTERN.search(normalized_url_path) is not None
        )
    )


def winner_resource_group_key(title: str | None) -> str | None:
    """Return a stable key for a year or cycle label used to group result files."""

    normalized = _clean_text(title)
    if normalized is None or _WINNER_GROUP_LABEL_PATTERN.fullmatch(normalized) is None:
        return None
    return normalized.casefold()


def is_result_content_heading(heading: str | None) -> bool:
    """Keep result content distinct from timeline milestones mentioning winners."""

    return not is_schedule_milestone_title(heading) and is_winner_resource(
        title=heading,
        source_section=None,
    )


def public_resource_kind(
    kind: ProgramResourceKind,
    *,
    title: str | None,
    source_section: str | None,
    url: str | None = None,
    group_has_winner_evidence: bool = False,
) -> ProgramResourceKind:
    """Expose winner lists consistently even when an older record called them documents."""

    if is_social_resource_url(url):
        return ProgramResourceKind.REFERENCE
    if kind is not ProgramResourceKind.APPLICATION and (
        group_has_winner_evidence
        or is_winner_resource(
            title=title,
            source_section=source_section,
            url=url,
        )
    ):
        return ProgramResourceKind.RESULT
    return kind


def is_public_resource(
    *,
    kind: ProgramResourceKind,
    title: str | None,
    source_section: str | None,
    section_category: str | None = None,
    url: str | None = None,
    group_has_winner_evidence: bool = False,
) -> bool:
    """Keep public cards limited to named, competition-specific materials."""

    normalized_title = _clean_text(title)
    if normalized_title is None:
        return False
    if normalized_title.casefold() in _NON_CONTENT_RESOURCE_TITLES:
        return False
    if _SERVICE_RESOURCE_TITLE.search(normalized_title):
        return False
    category = _clean_text(section_category)
    normalized_category = category.casefold() if category is not None else None
    if is_social_resource_url(url):
        return normalized_category is None or normalized_category in {
            "results",
            "official_channels",
        }
    if kind is ProgramResourceKind.DETAIL:
        return False
    if kind is ProgramResourceKind.APPLICATION:
        # New records render the canonical application URL as a dedicated CTA.
        # The legacy fallback keeps already-published records readable.
        return normalized_category is None
    if kind is ProgramResourceKind.RESULT and not (
        group_has_winner_evidence
        or is_winner_resource(
            title=title,
            source_section=source_section,
            url=url,
        )
    ):
        return False
    if kind is ProgramResourceKind.RESULT:
        return True
    if normalized_category is not None:
        # Parsed inline links retain their provenance, but do not become stand-alone
        # cards. An operator can deliberately place a reviewed reference here.
        return normalized_category == "documents" and kind in {
            ProgramResourceKind.COMPETITION_DOCUMENT,
            ProgramResourceKind.PROGRAM_DOCUMENT,
            ProgramResourceKind.REFERENCE,
        }
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
    if category == "results" and not is_result_content_heading(normalized_heading):
        return False
    if ".pdf" in normalized_heading.casefold() or re.search(
        r"\bpdf\b", normalized_content, re.IGNORECASE
    ):
        return False
    return True
