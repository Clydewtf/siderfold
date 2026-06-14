import csv
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from .models import Competition


JSON_FILENAME = "competitions.json"
CSV_FILENAME = "competitions.csv"
_JSON_COLUMNS = {"contacts", "sections"}
_JOINED_COLUMNS = {"result_urls", "document_urls", "parse_warnings"}


def _csv_value(name: str, value: Any) -> Any:
    if name in _JSON_COLUMNS:
        return json.dumps(value, ensure_ascii=False)
    if name in _JOINED_COLUMNS:
        return " | ".join(value)
    if value is None:
        return ""
    return value


def export_records(records: list[Competition], output_dir: Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_FILENAME
    csv_path = output_dir / CSV_FILENAME

    json_path.write_text(
        json.dumps(
            [record.to_dict() for record in records],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    fieldnames = [field.name for field in fields(Competition)]
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for record in records:
            values = record.to_dict()
            writer.writerow(
                {name: _csv_value(name, values[name]) for name in fieldnames}
            )

    return [json_path, csv_path]
