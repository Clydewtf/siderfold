from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.sources.cli import main
from app.sources.contract import AdapterReport
from app.sources.fixture_adapter import FixtureCatalogAdapter
from app.sources.registry import DEFAULT_REGISTRY_PATH, SourceLimits, load_registry
from app.sources.runner import execute_adapter


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _fixture_definition():
    return load_registry(DEFAULT_REGISTRY_PATH).get("fixture-catalog")


def test_fixture_adapter_dry_run_is_deterministic_and_builds_import_package() -> None:
    execution = execute_adapter(
        _fixture_definition(),
        FixtureCatalogAdapter(),
        dry_run=True,
        project_root=BACKEND_ROOT,
        started_at=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert execution.package is not None
    assert execution.report.status == "completed"
    assert execution.report.dry_run is True
    assert execution.report.statistics.model_dump(
        exclude={"response_bytes"}
    ) == {
        "discovered": 1,
        "fetched": 1,
        "extracted": 2,
        "valid": 2,
        "warnings": 1,
        "errors": 0,
        "duplicates": 0,
        "requests": 1,
        "artifact_discovered": 0,
        "artifact_fetched": 0,
        "artifact_deferred": 0,
    }
    assert execution.package.metadata.adapter.name == "fixture-catalog"
    assert len(execution.package.rows) == 2


def test_runner_rejects_a_redirect_outside_the_allowlist() -> None:
    class RedirectingAdapter(FixtureCatalogAdapter):
        def fetch(self, resource, context):  # type: ignore[no-untyped-def]
            result = super().fetch(resource, context)
            return replace(result, final_url="https://outside.example.test/catalog/v1.json")

    execution = execute_adapter(
        _fixture_definition(),
        RedirectingAdapter(),
        dry_run=True,
        project_root=BACKEND_ROOT,
    )

    assert execution.package is None
    assert execution.report.status == "failed"
    assert execution.report.statistics.errors == 1
    assert execution.report.issues[0].code == "url_not_allowed"


def test_runner_enforces_response_limits() -> None:
    definition = _fixture_definition().model_copy(
        update={"limits": SourceLimits(max_response_bytes=1, max_total_bytes=1)}
    )

    execution = execute_adapter(
        definition,
        FixtureCatalogAdapter(),
        dry_run=True,
        project_root=BACKEND_ROOT,
    )

    assert execution.package is None
    assert execution.report.status == "failed"
    assert execution.report.issues[0].code == "fetch_error"
    assert execution.report.statistics.requests == 1


def test_dry_run_cli_prints_the_public_report(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = main(
        [
            "--registry",
            str(DEFAULT_REGISTRY_PATH),
            "dry-run",
            "fixture-catalog",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["status"] == "completed"
    assert output["dry_run"] is True
    assert AdapterReport.model_validate(output).statistics.extracted == 2
