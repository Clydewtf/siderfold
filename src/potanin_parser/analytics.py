import shutil
import stat
from collections import Counter
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from .models import Competition


CHART_SIZE = (1600, 900)
MAX_CHART_BARS = 15
MANAGED_CHART_FILENAMES = {
    "statuses.png",
    "deadlines.png",
    "maximum_support.png",
    "grant_funds.png",
    "funding.png",
}
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


def _funding_values(
    records: Iterable[Competition], field_name: str
) -> list[tuple[str, int]]:
    values = []
    for index, record in enumerate(records, start=1):
        amount = getattr(record, field_name)
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
    if not _funding_values(records, "max_support_rub"):
        skipped_charts.append("maximum_support")
    if not _funding_values(records, "grant_fund_rub"):
        skipped_charts.append("grant_funds")

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


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
) -> str:
    if _text_width(draw, text, font) <= max_width:
        return text

    ellipsis = "…"
    low = 0
    high = len(text)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = f"{text[:middle].rstrip()}{ellipsis}"
        if _text_width(draw, candidate, font) <= max_width:
            low = middle
        else:
            high = middle - 1
    return f"{text[:low].rstrip()}{ellipsis}" if low else ellipsis


def _format_rubles(value: int) -> str:
    return f"{value:,} руб.".replace(",", " ")


def _bounded_categorical_values(
    values: list[tuple[str, int]],
) -> list[tuple[str, int]]:
    if len(values) <= MAX_CHART_BARS:
        return values

    visible = values[: MAX_CHART_BARS - 1]
    remainder = values[MAX_CHART_BARS - 1 :]
    visible.append(
        (f"Остальные ({len(remainder)})", sum(value for _, value in remainder))
    )
    return visible


def _limit_individual_values(
    values: list[tuple[str, int]],
) -> tuple[list[tuple[str, int]], str | None]:
    if len(values) <= MAX_CHART_BARS:
        return values, None
    return values[:MAX_CHART_BARS], f"Показано {MAX_CHART_BARS} из {len(values)}"


def _value_label_layout(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    *,
    bar_left: int,
    bar_right: int,
    bar_top: int,
    bar_bottom: int,
    chart_right: int,
) -> tuple[tuple[int, int], str]:
    text_box = draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    y = bar_top + max(0, (bar_bottom - bar_top - text_height) // 2) - text_box[1]
    if bar_right - bar_left >= text_width + 24:
        return (bar_right - text_width - 12, y), "white"
    return (min(bar_right + 12, chart_right - text_width), y), "#111827"


def _validate_charts_dir(charts_dir: Path) -> int | None:
    try:
        mode = charts_dir.stat(follow_symlinks=False).st_mode
    except (FileNotFoundError, NotADirectoryError):
        mode = None
    if mode is not None:
        if not stat.S_ISDIR(mode):
            raise ValueError("charts_dir must be a real directory")
        return mode

    ancestor = charts_dir.parent
    while True:
        try:
            ancestor_mode = ancestor.stat(follow_symlinks=False).st_mode
        except (FileNotFoundError, NotADirectoryError):
            parent = ancestor.parent
            if parent == ancestor:
                raise ValueError("charts_dir must be below a real directory")
            ancestor = parent
            continue
        if not stat.S_ISDIR(ancestor_mode):
            raise ValueError("charts_dir must be below a real directory")
        return None


def _draw_bar_chart(
    path: Path,
    title: str,
    values: list[tuple[str, int]],
    value_formatter=str,
    aggregate_remainder: bool = True,
) -> None:
    if aggregate_remainder:
        values = _bounded_categorical_values(values)
        note = None
    else:
        values, note = _limit_individual_values(values)
    image = Image.new("RGB", CHART_SIZE, "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(52)
    draw.text((90, 55), title, fill="#1f2937", font=title_font)
    if note:
        draw.text((90, 120), note, fill="#4b5563", font=_font(22))

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
            _fit_text(draw, label, label_font, chart_left - 120),
            fill="#374151",
            font=label_font,
        )
        if width > 0:
            draw.rounded_rectangle(
                (chart_left, top, chart_left + width, bottom),
                radius=min(8, bar_height // 3),
                fill="#2563eb",
            )
        value_text = value_formatter(value)
        value_position, value_color = _value_label_layout(
            draw,
            value_text,
            value_font,
            bar_left=chart_left,
            bar_right=chart_left + width,
            bar_top=top,
            bar_bottom=bottom,
            chart_right=chart_right,
        )
        draw.text(value_position, value_text, fill=value_color, font=value_font)

    image.save(path, format="PNG")


def generate_charts(records: list[Competition], charts_dir: Path) -> list[Path]:
    charts_dir = Path(charts_dir)
    generated = []

    charts_mode = _validate_charts_dir(charts_dir)

    if charts_mode is not None:
        for filename in MANAGED_CHART_FILENAMES:
            path = charts_dir / filename
            try:
                path_mode = path.stat(follow_symlinks=False).st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(path_mode):
                shutil.rmtree(path)
            else:
                path.unlink()

    status_counts = _status_counts(records)
    deadline_counts = _deadline_counts(records)
    maximum_support_values = _funding_values(records, "max_support_rub")
    grant_fund_values = _funding_values(records, "grant_fund_rub")
    if not (
        status_counts
        or deadline_counts
        or maximum_support_values
        or grant_fund_values
    ):
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
    if maximum_support_values:
        path = charts_dir / "maximum_support.png"
        _draw_bar_chart(
            path,
            "Максимальная поддержка конкурса",
            maximum_support_values,
            value_formatter=_format_rubles,
            aggregate_remainder=False,
        )
        generated.append(path)
    if grant_fund_values:
        path = charts_dir / "grant_funds.png"
        _draw_bar_chart(
            path,
            "Общий грантовый фонд конкурса",
            grant_fund_values,
            value_formatter=_format_rubles,
            aggregate_remainder=False,
        )
        generated.append(path)

    return generated
