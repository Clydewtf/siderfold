from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object, *, fallback: str = "Не указано") -> str:
    if not isinstance(value, str):
        return fallback
    normalized = " ".join(value.split())
    return normalized or fallback


def _short(value: object, *, width: int = 120) -> str:
    return textwrap.shorten(_text(value, fallback=""), width=width, placeholder="…") or "Не указано"


def _candidate_record(case: Mapping[str, Any]) -> Mapping[str, Any]:
    snapshot = _mapping(case.get("opened_snapshot"))
    candidate = _mapping(snapshot.get("candidate_payload"))
    record = _mapping(candidate.get("record"))
    return record or candidate


def _funding_label(value: object) -> str:
    funding = _mapping(value)
    kind = funding.get("value_kind")
    currency = _text(funding.get("currency_code"), fallback="")
    amount_keys = {
        "exact": ("", "exact_amount"),
        "minimum": ("от ", "min_amount"),
        "maximum": ("до ", "max_amount"),
    }
    if kind == "range":
        minimum = _text(funding.get("min_amount"), fallback="")
        maximum = _text(funding.get("max_amount"), fallback="")
        return f"{minimum} — {maximum} {currency}".strip() if minimum and maximum else "Сумма неизвестна"
    prefix, key = amount_keys.get(kind, ("", ""))
    amount = _text(funding.get(key), fallback="") if key else ""
    if amount:
        return f"{prefix}{amount} {currency}".strip()
    if kind == "unknown":
        return "Сумма неизвестна"
    if kind == "not_stated":
        return "Сумма не указана"
    return "Сумма не указана"


def _format_queue_item(case: Mapping[str, Any], *, index: int) -> str:
    title = _short(case.get("title"), width=58)
    source_url = _short(case.get("source_url"), width=90)
    reasons = ", ".join(
        value for value in case.get("reason_codes", []) if isinstance(value, str)
    ) or "без специальных причин"
    return (
        f"{index:>2}. {case.get('review_case_id', '—')}\n"
        f"    {case.get('status', '—')} · {title}\n"
        f"    {reasons}\n"
        f"    {source_url}"
    )


def render_queue(cases: Sequence[Mapping[str, Any]]) -> str:
    if not cases:
        return "Открытых кейсов review нет."
    lines = [f"Открытые кейсы review: {len(cases)}", ""]
    lines.extend(_format_queue_item(case, index=index) for index, case in enumerate(cases, 1))
    lines.extend(
        [
            "",
            "Открой конкретный кейс: $PYTHON_BIN -m app.review.cli show <review_case_id>",
        ]
    )
    return "\n".join(lines)


def render_case(case: Mapping[str, Any]) -> str:
    record = _candidate_record(case)
    payload = _mapping(record.get("payload"))
    application = _mapping(payload.get("application"))
    taxonomy = _mapping(payload.get("taxonomy"))
    eligibility = _mapping(payload.get("eligibility"))
    funding = _mapping(payload.get("funding"))
    summary = _text(payload.get("summary"), fallback="")
    issues = case.get("quality_issues", [])
    actions = case.get("actions", [])
    lines = [
        f"Кейс review: {case.get('review_case_id', '—')}",
        f"Состояние: {case.get('status', '—')}",
        f"Открыт: {case.get('opened_at', '—')}",
        f"Кандидат: {_text(record.get('title'))}",
        f"Страница источника: {_text(record.get('record_url') or record.get('record_key'))}",
        f"Staged record: {case.get('staged_record_id', '—')}",
    ]
    source_title = _text(payload.get("source_title"), fallback="")
    if source_title and source_title != _text(record.get("title")):
        lines.append(f"Название на источнике: {source_title}")

    start_on = _text(application.get("start_on"), fallback="")
    end_on = _text(application.get("end_on"), fallback="")
    if start_on or end_on:
        lines.append(f"Приём заявок: {start_on or '—'} — {end_on or '—'}")
    lines.append(f"Статус на источнике: {_text(payload.get('source_status'))}")
    if summary:
        lines.append(f"Описание: {_short(summary, width=300)}")
    eligibility_summary = _text(eligibility.get("summary"), fallback="")
    if eligibility_summary:
        lines.append(f"Условия участия: {_short(eligibility_summary, width=300)}")

    amounts = funding.get("amounts")
    if isinstance(amounts, list) and amounts:
        lines.append("Финансирование:")
        for amount in amounts:
            item = _mapping(amount)
            lines.append(
                f"  • {_text(item.get('label'))}: {_funding_label(item.get('value'))}"
            )
    else:
        lines.append(f"Финансирование: {_funding_label(record.get('funding'))}")

    for label, values in (("Тематики", taxonomy.get("themes")), ("Регионы", taxonomy.get("geographies"))):
        names = [
            _text(_mapping(value).get("name"), fallback="")
            for value in values
            if isinstance(value, Mapping)
        ] if isinstance(values, list) else []
        if names:
            lines.append(f"{label}: {', '.join(name for name in names if name)}")

    if isinstance(issues, list) and issues:
        lines.append("Проверки качества:")
        for issue in issues:
            item = _mapping(issue)
            lines.append(
                f"  • [{_text(item.get('severity'))}] {_text(item.get('code'))}: {_short(item.get('message'), width=180)}"
            )
    if isinstance(actions, list) and actions:
        lines.append("История решений:")
        for action in actions:
            item = _mapping(action)
            lines.append(
                f"  • {_text(item.get('created_at'))} — {_text(item.get('action'))}: {_short(item.get('reason'), width=180)}"
            )
    return "\n".join(lines)


def _validated_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme != "http" or parsed.hostname not in _LOCAL_HOSTS:
        raise ValueError("review CLI accepts only a local http://127.0.0.1 or http://localhost API URL")
    return normalized


def _request_json(base_url: str, token: str, path: str, query: Mapping[str, object] | None = None) -> object:
    suffix = f"?{urlencode(query)}" if query else ""
    request = Request(
        f"{base_url}{path}{suffix}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - endpoint is local and validated above.
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 401:
            raise RuntimeError("внутренний токен не принят") from error
        if error.code == 404:
            raise RuntimeError("кейс review не найден") from error
        raise RuntimeError(f"внутренний API вернул HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError("не удалось подключиться к локальному backend на 127.0.0.1:8000") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only terminal view for Siderfold review cases.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("INTERNAL_API_BASE_URL", DEFAULT_BASE_URL),
        help="Local backend URL; defaults to http://127.0.0.1:8000.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="Show unresolved review cases.")
    list_parser.add_argument("--limit", type=int, default=50)
    show_parser = subparsers.add_parser("show", help="Show one review case without raw payload noise.")
    show_parser.add_argument("review_case_id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.getenv("INTERNAL_API_TOKEN", "").strip()
    if not token:
        print("Ошибка: задай INTERNAL_API_TOKEN в текущем терминале.", file=sys.stderr)
        return 2
    try:
        base_url = _validated_base_url(args.base_url)
        if args.command == "list":
            if args.limit < 1 or args.limit > 1_000:
                raise ValueError("--limit must be between 1 and 1000")
            payload = _request_json(base_url, token, "/api/internal/v1/review/cases", {"limit": args.limit})
            if not isinstance(payload, list):
                raise RuntimeError("внутренний API вернул некорректную очередь review")
            cases = [item for item in payload if isinstance(item, Mapping)]
            print(render_queue(cases))
            return 0
        payload = _request_json(base_url, token, f"/api/internal/v1/review/cases/{args.review_case_id}")
        if not isinstance(payload, Mapping):
            raise RuntimeError("внутренний API вернул некорректный кейс review")
        print(render_case(payload))
        return 0
    except ValueError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
