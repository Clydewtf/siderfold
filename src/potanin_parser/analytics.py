from collections import Counter
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from .models import Competition


CHART_SIZE = (1600, 900)
MAX_CHART_BARS = 15
_FONT_PATHS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _status_counts(records: Iterable[Competition]) -> Counter[str]:
    return Counter(record.status for record in records if record.status)


def _deadline_counts(records: Iterable[Competition]) -> Counter[str]:
    return Counter(
        record.application_end_date[:7]
        for record in records
        if record.application_end_date
    )


def _funding_values(records: Iterable[Competition]) -> list[tuple[str, int]]:
    values = []
    for index, record in enumerate(records, start=1):
        amount = (
            record.max_support_rub
            if record.max_support_rub is not None
            else record.grant_fund_rub
        )
        if amount is not None:
            label = record.title.strip() or f"Конкурс {index}"
            values.append((label, amount))
    return values


def build_summary(
    records: list[Competition],
    collected_at: str,
    failed_pages: int,
) -> dict[str, object]:
    status_distribution = Counter(
        record.status or "Не указан" for record in records
    )
    support_values = [
        record.max_support_rub
        for record in records
        if record.max_support_rub is not None
    ]

    skipped_charts = []
    if not _status_counts(records):
        skipped_charts.append("status")
    if not _deadline_counts(records):
        skipped_charts.append("deadline")
    if not _funding_values(records):
        skipped_charts.append("funding")

    return {
        "collection_time": collected_at,
        "source": records[0].source if records else None,
        "record_count": len(records),
        "status_distribution": dict(status_distribution),
        "parsed_deadline_count": sum(
            record.application_end_date is not None for record in records
        ),
        "parsed_funding_count": sum(
            record.grant_fund_rub is not None or record.max_support_rub is not None
            for record in records
        ),
        "minimum_support_rub": min(support_values) if support_values else None,
        "maximum_support_rub": max(support_values) if support_values else None,
        "total_warnings": sum(len(record.parse_warnings) for record in records),
        "failed_pages": failed_pages,
        "skipped_charts": skipped_charts,
    }


def _font(size: int):
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _shorten(label: str, limit: int = 34) -> str:
    return label if len(label) <= limit else f"{label[: limit - 1]}…"


def _format_rubles(value: int) -> str:
    return f"{value:,} руб.".replace(",", " ")


def _bounded_values(values: list[tuple[str, int]]) -> list[tuple[str, int]]:
    if len(values) <= MAX_CHART_BARS:
        return values

    visible = values[: MAX_CHART_BARS - 1]
    remainder = values[MAX_CHART_BARS - 1 :]
    visible.append(
        (f"Остальные ({len(remainder)})", sum(value for _, value in remainder))
    )
    return visible


def _draw_bar_chart(
    path: Path,
    title: str,
    values: list[tuple[str, int]],
    value_formatter=str,
) -> None:
    values = _bounded_values(values)
    image = Image.new("RGB", CHART_SIZE, "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(52)
    draw.text((90, 55), title, fill="#1f2937", font=title_font)

    chart_left = 420
    chart_right = 1510
    chart_top = 160
    chart_bottom = 830
    maximum = max(value for _, value in values)
    bar_gap = max(6, 18 - len(values))
    bar_height = (
        chart_bottom - chart_top - bar_gap * (len(values) - 1)
    ) // len(values)
    font_size = max(16, min(28, bar_height - 8))
    label_font = _font(font_size)
    value_font = _font(max(15, font_size - 2))

    for index, (label, value) in enumerate(values):
        top = chart_top + index * (bar_height + bar_gap)
        bottom = top + bar_height
        width = (
            int((chart_right - chart_left) * value / maximum)
            if maximum > 0
            else 0
        )
        draw.text(
            (90, top + max(0, (bar_height - font_size) // 2)),
            _shorten(label),
            fill="#374151",
            font=label_font,
        )
        if width > 0:
            draw.rounded_rectangle(
                (chart_left, top, chart_left + width, bottom),
                radius=min(8, bar_height // 3),
                fill="#2563eb",
            )
        draw.text(
            (min(chart_left + width + 15, chart_right - 180), top + 3),
            value_formatter(value),
            fill="#111827",
            font=value_font,
        )

    image.save(path, format="PNG")


def generate_charts(records: list[Competition], charts_dir: Path) -> list[Path]:
    charts_dir = Path(charts_dir)
    generated = []

    status_counts = _status_counts(records)
    deadline_counts = _deadline_counts(records)
    funding_values = _funding_values(records)
    if not (status_counts or deadline_counts or funding_values):
        return generated

    charts_dir.mkdir(parents=True, exist_ok=True)
    if status_counts:
        path = charts_dir / "statuses.png"
        _draw_bar_chart(path, "Распределение по статусам", list(status_counts.items()))
        generated.append(path)
    if deadline_counts:
        path = charts_dir / "deadlines.png"
        _draw_bar_chart(
            path,
            "Сроки окончания приема заявок",
            sorted(deadline_counts.items()),
        )
        generated.append(path)
    if funding_values:
        path = charts_dir / "funding.png"
        _draw_bar_chart(
            path,
            "Объем поддержки",
            funding_values,
            value_formatter=_format_rubles,
        )
        generated.append(path)

    return generated
