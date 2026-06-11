from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Competition:
    source: str
    source_url: str
    collected_at: str
    title: str
    status: str | None = None
    publication_date: str | None = None
    application_start_date: str | None = None
    application_end_date: str | None = None
    organizer: str = "Фонд Потанина"
    summary: str | None = None
    goals: str | None = None
    tasks: str | None = None
    target_audience: str | None = None
    requirements: str | None = None
    nominations: str | None = None
    project_directions: str | None = None
    procedure: str | None = None
    grant_fund_rub: int | None = None
    max_support_rub: int | None = None
    funding_text: str | None = None
    application_url: str | None = None
    result_urls: list[str] = field(default_factory=list)
    document_urls: list[str] = field(default_factory=list)
    contacts: list[dict[str, str]] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)
    full_text: str = ""
    parse_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
