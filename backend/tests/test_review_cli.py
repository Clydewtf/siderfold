from __future__ import annotations

import pytest

from app.review.cli import _validated_base_url, render_case, render_queue


def test_review_cli_renders_a_short_queue_without_raw_payload() -> None:
    rendered = render_queue(
        [
            {
                "review_case_id": "case-1",
                "status": "open",
                "title": "Конкурс для региональных инициатив",
                "source_url": "https://source.example.test/competitions/one",
                "reason_codes": ["missing_deadline"],
            }
        ]
    )

    assert "Конкурс для региональных инициатив" in rendered
    assert "missing_deadline" in rendered
    assert "show <review_case_id>" in rendered


def test_review_cli_renders_selected_candidate_fields_only() -> None:
    rendered = render_case(
        {
            "review_case_id": "case-1",
            "staged_record_id": "staged-1",
            "status": "open",
            "opened_at": "2026-09-05T10:00:00+00:00",
            "opened_snapshot": {
                "raw_capture": "s3://private-bucket/raw.html",
                "candidate_payload": {
                    "record": {
                        "title": "Конкурс для региональных инициатив",
                        "record_url": "https://source.example.test/competitions/one",
                        "payload": {
                            "summary": "Поддержка проверенных региональных проектов.",
                            "application": {
                                "start_on": "2026-09-10",
                                "end_on": "2026-10-10",
                            },
                            "funding": {
                                "amounts": [
                                    {
                                        "label": "Фонд конкурса",
                                        "value": {
                                            "value_kind": "exact",
                                            "currency_code": "RUB",
                                            "exact_amount": "5000000",
                                        },
                                    }
                                ]
                            },
                        },
                    }
                },
            },
            "quality_issues": [],
            "actions": [],
        }
    )

    assert "Конкурс для региональных инициатив" in rendered
    assert "Фонд конкурса: 5000000 RUB" in rendered
    assert "s3://private-bucket/raw.html" not in rendered


@pytest.mark.parametrize(
    "url",
    ["https://example.test", "http://api.example.test", "https://127.0.0.1:8000"],
)
def test_review_cli_refuses_to_send_operator_token_to_a_remote_url(url: str) -> None:
    with pytest.raises(ValueError):
        _validated_base_url(url)
