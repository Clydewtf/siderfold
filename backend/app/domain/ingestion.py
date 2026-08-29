from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection

from app.domain.models import IngestionRun


def build_input_fingerprint(
    *,
    source_url: str,
    content: bytes,
    adapter_name: str,
    adapter_version: str,
) -> str:
    """Return a deterministic SHA-256 key for one normalized ingestion input."""

    digest = sha256()
    for value in (
        source_url.strip().encode("utf-8"),
        adapter_name.encode("utf-8"),
        adapter_version.encode("utf-8"),
        content,
    ):
        digest.update(len(value).to_bytes(8, byteorder="big"))
        digest.update(value)
    return digest.hexdigest()


def get_or_create_ingestion_run(
    connection: Connection,
    *,
    source_id: UUID,
    input_fingerprint: str,
    adapter_name: str,
    adapter_version: str,
    received_at: datetime | None = None,
) -> tuple[UUID, bool]:
    """Reserve one run per source and deterministic input fingerprint.

    Returns the existing run on a repeat delivery instead of creating a second
    ingestion run. The unique database constraint remains the concurrency-safe
    source of truth.
    """

    values: dict[str, object] = {
        "id": uuid4(),
        "source_id": source_id,
        "input_fingerprint": input_fingerprint,
        "adapter_name": adapter_name,
        "adapter_version": adapter_version,
    }
    if received_at is not None:
        values["received_at"] = received_at

    insert_statement = (
        postgresql_insert(IngestionRun)
        .values(**values)
        .on_conflict_do_nothing(index_elements=("source_id", "input_fingerprint"))
        .returning(IngestionRun.id)
    )
    run_id = connection.scalar(insert_statement)
    if run_id is not None:
        return run_id, True

    existing_run_id = connection.scalar(
        select(IngestionRun.id).where(
            IngestionRun.source_id == source_id,
            IngestionRun.input_fingerprint == input_fingerprint,
        )
    )
    if existing_run_id is None:
        raise RuntimeError("ingestion run was not persisted after an idempotency conflict")
    return existing_run_id, False
