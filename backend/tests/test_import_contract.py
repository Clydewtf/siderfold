from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.import_bridge.cli import main
from app.import_bridge.contract import PackageValidationError, load_contract, load_json_contract
from app.import_bridge.potanin import load_potanin_output


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "imports"


def test_json_v1_contract_parses_anonymized_fixture() -> None:
    package = load_contract(FIXTURES_ROOT / "potanin_import_v1.json", input_format="json")

    assert package.metadata.contract_version == "siderfold.import/v1"
    assert package.metadata.source.canonical_url == "https://foundation.example.test"
    assert len(package.rows) == 2
    assert package.rows[0].record is not None
    assert package.rows[0].record.record_key == "foundation-a:competition:alpha"
    assert package.rows[0].record.funding is not None
    assert package.rows[0].record.funding.value_kind.value == "maximum"
    assert not package.rows[0].issues


def test_csv_v1_contract_parses_the_same_shape() -> None:
    package = load_contract(FIXTURES_ROOT / "potanin_import_v1.csv", input_format="csv")

    assert package.metadata.capture.content_format == "text/csv"
    assert len(package.rows) == 2
    assert package.rows[1].record is not None
    assert package.rows[1].record.record_key == "foundation-a:competition:beta"
    assert not package.rows[1].issues


def test_invalid_row_is_retained_as_a_row_level_validation_error(tmp_path: Path) -> None:
    payload = json.loads((FIXTURES_ROOT / "potanin_import_v1.json").read_text())
    payload["records"].append(
        {
            "record_key": "",
            "title": "",
            "record_url": "not-a-url",
            "funding": {
                "value_kind": "exact",
                "currency_code": "RUB",
                "min_amount": "10"
            }
        }
    )
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(payload))

    package = load_json_contract(invalid_path)

    invalid_row = package.rows[-1]
    assert invalid_row.record is None
    assert {issue.field for issue in invalid_row.issues} >= {
        "record_key",
        "title",
        "record_url",
        "funding",
    }


def test_empty_json_package_is_rejected_before_database_writes(tmp_path: Path) -> None:
    payload = json.loads((FIXTURES_ROOT / "potanin_import_v1.json").read_text())
    payload["records"] = []
    empty_path = tmp_path / "empty.json"
    empty_path.write_text(json.dumps(payload))

    with pytest.raises(PackageValidationError) as error:
        load_json_contract(empty_path)

    assert error.value.issues[0].field == "records"


def test_potanin_adapter_uses_selected_fields_and_excludes_contacts() -> None:
    package = load_potanin_output(FIXTURES_ROOT / "potanin_output_sample.json")

    assert package.metadata.adapter.name == "potanin-local-output"
    assert package.rows[0].record is not None
    record = package.rows[0].record
    assert "contacts" not in record.payload
    assert "full_text" not in record.payload
    assert record.funding is not None
    assert any("total fund" in warning for warning in record.warnings)


def test_potanin_cli_requires_a_dry_run() -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                str(FIXTURES_ROOT / "potanin_output_sample.json"),
                "--format",
                "potanin-json",
            ]
        )

    assert error.value.code == 2
