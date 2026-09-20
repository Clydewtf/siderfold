from pathlib import Path

import pytest
from pydantic import ValidationError

from app.sources.registry import (
    DEFAULT_REGISTRY_PATH,
    SourceAccessMethod,
    SourceDefinition,
    SourceLimits,
    SourceRegistryStatus,
    is_url_allowed,
    load_registry,
    require_allowed_url,
)
from app.sources.runner import list_registered_sources


def _definition(**overrides: object) -> SourceDefinition:
    values: dict[str, object] = {
        "source_key": "example-source",
        "name": "Example source",
        "canonical_url": "https://example.test/catalog",
        "allowed_url_prefixes": ("https://example.test/catalog",),
        "access_method": SourceAccessMethod.HTTP,
        "schedule": "manual",
        "status": SourceRegistryStatus.ACTIVE,
        "responsible": "data-team",
        "adapter_name": "fixture-catalog",
        "adapter_version": "1.0.0",
    }
    values.update(overrides)
    return SourceDefinition.model_validate(values)


def test_default_registry_contains_a_non_secret_fixture_source() -> None:
    registry = load_registry(DEFAULT_REGISTRY_PATH)

    definition = registry.get("fixture-catalog")
    assert definition.access_method is SourceAccessMethod.FIXTURE
    assert definition.status is SourceRegistryStatus.ACTIVE
    assert definition.secret_env_vars == ()
    assert definition.fixture_path == "tests/fixtures/adapters/catalog_v1.json"


def test_potanin_registry_entry_bounds_discovery_and_card_requests() -> None:
    definition = load_registry(DEFAULT_REGISTRY_PATH).get("potanin-competitions")

    assert definition.access_method is SourceAccessMethod.HTTP
    assert definition.limits.timeout_seconds == 45
    assert definition.limits.max_run_seconds == 1800
    assert definition.secret_env_vars == ()
    assert definition.allowed_exact_urls == (
        "https://fondpotanin.ru/sitemap-iblock-competitions.xml",
    )
    assert is_url_allowed(
        "https://fondpotanin.ru/sitemap-iblock-competitions.xml",
        definition,
    )
    assert is_url_allowed(
        "https://fondpotanin.ru/competitions/example-card/",
        definition,
    )
    assert not is_url_allowed("https://zayavka.fondpotanin.ru/ru/", definition)
    assert not is_url_allowed("https://fondpotanin.ru/activity/programms/", definition)


def test_fasie_registry_requires_http_and_allowlisted_home_and_feed_urls() -> None:
    definition = load_registry(DEFAULT_REGISTRY_PATH).get("fasie-competitions")
    values = definition.model_dump(mode="python")

    with pytest.raises(ValidationError, match="requires http access"):
        SourceDefinition.model_validate(
            {
                **values,
                "access_method": SourceAccessMethod.FIXTURE,
                "fixture_path": "tests/fixtures/adapters/catalog_v1.json",
            }
        )

    with pytest.raises(ValidationError, match="home_url must be covered"):
        SourceDefinition.model_validate(
            {
                **values,
                "allowed_url_prefixes": ("https://fasie.ru/upload",),
            }
        )

    listed = {
        item["source_key"]: item
        for item in list_registered_sources(load_registry(DEFAULT_REGISTRY_PATH))
    }
    assert listed["fasie-competitions"]["fasie"] == {
        "home_url": "https://fasie.ru/",
        "press_feed_url": "https://fasie.ru/press/fund/",
        "lookback_days": 365,
        "max_feed_pages": 90,
    }
    assert all(
        listed[key]["schedule"] == "manual"
        for key in ("potanin-competitions", "timchenko-competitions", "fasie-competitions")
    )


def test_allowlist_matches_an_explicit_path_prefix_only() -> None:
    definition = _definition()

    assert is_url_allowed("https://example.test/catalog/alpha?view=full#top", definition)
    assert not is_url_allowed("https://example.test/catalogue/alpha", definition)
    assert not is_url_allowed("https://other.example.test/catalog/alpha", definition)
    assert not is_url_allowed("http://example.test/catalog/alpha", definition)
    assert (
        require_allowed_url("https://EXAMPLE.TEST/catalog/alpha#top", definition)
        == "https://example.test/catalog/alpha"
    )


def test_registry_rejects_invalid_limits_schedule_and_fixture_configuration() -> None:
    with pytest.raises(ValidationError):
        SourceLimits(max_requests=0)

    with pytest.raises(ValidationError):
        SourceLimits(max_run_seconds=0)

    with pytest.raises(ValidationError):
        _definition(schedule="every day")

    with pytest.raises(ValidationError):
        _definition(
            access_method=SourceAccessMethod.FIXTURE,
            fixture_path=None,
        )

    with pytest.raises(ValidationError):
        _definition(secret_env_vars=("not-a-valid-name",))


def test_fixture_path_is_resolved_relative_to_the_backend_root() -> None:
    definition = load_registry(DEFAULT_REGISTRY_PATH).get("fixture-catalog")

    fixture_path = definition.resolve_fixture_path(Path(__file__).resolve().parents[1])

    assert fixture_path.is_absolute()
    assert fixture_path.name == "catalog_v1.json"
    assert fixture_path.is_file()
