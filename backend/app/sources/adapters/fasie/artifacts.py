from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
import logging
from pathlib import PurePosixPath
import re
from stat import S_IFMT, S_IFLNK
from typing import Any
from zipfile import BadZipFile, ZipFile

from lxml import etree
from pypdf import PdfReader

from app.sources.adapters.potanin.normalization import normalize_whitespace, parse_rub_amounts


MAX_EXCERPT_CHARS = 4_000
MAX_PDF_PAGES = 120
MAX_ZIP_ENTRIES = 200
MAX_UNCOMPRESSED_BYTES = 16_000_000
MAX_ENTRY_BYTES = 4_000_000
MAX_XML_BYTES = 2_000_000
MAX_LINKS = 100


@dataclass(frozen=True)
class ArtifactInspectionIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ArtifactInspection:
    payload: dict[str, Any]
    issues: tuple[ArtifactInspectionIssue, ...] = ()


@contextmanager
def _quiet_pypdf_messages():
    logger = logging.getLogger("pypdf._reader")
    previous = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous)


def _excerpt(value: str) -> tuple[str | None, bool]:
    normalized = normalize_whitespace(value)
    if not normalized:
        return None, False
    if len(normalized) <= MAX_EXCERPT_CHARS:
        return normalized, False
    return normalized[:MAX_EXCERPT_CHARS].rstrip(), True


def _result_evidence(value: str) -> list[str]:
    result: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+|\n+", value):
        normalized = normalize_whitespace(part)
        if normalized and re.search(r"победител|итог|результат|лауреат", normalized, re.IGNORECASE):
            result.append(normalized[:500])
        if len(result) >= 20:
            break
    return result


def _funding_observations(value: str) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for part in re.split(r"(?<=[.!?])\s+|\n+", value):
        normalized = normalize_whitespace(part)
        if not normalized or not re.search(r"итого|всего\s+выделено", normalized, re.IGNORECASE):
            continue
        for amount in parse_rub_amounts(normalized):
            observations.append(
                {
                    "scope": "awarded_total",
                    "value": {
                        "value_kind": "exact",
                        "currency_code": "RUB",
                        "exact_amount": str(amount),
                    },
                    "evidence": normalized[:500],
                }
            )
    return observations


def _inspect_pdf(content: bytes) -> ArtifactInspection:
    try:
        with _quiet_pypdf_messages():
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted:
                return ArtifactInspection(
                    {"kind": "pdf", "status": "encrypted"},
                    (ArtifactInspectionIssue("artifact_pdf_encrypted", "The PDF is encrypted."),),
                )
            page_count = len(reader.pages)
            chunks: list[str] = []
            truncated = page_count > MAX_PDF_PAGES
            for page in reader.pages[:MAX_PDF_PAGES]:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if text:
                    chunks.append(text)
                if sum(len(chunk) for chunk in chunks) > MAX_EXCERPT_CHARS:
                    truncated = True
                    break
            text = "\n".join(chunks)
            excerpt, excerpt_truncated = _excerpt(text)
            metadata = reader.metadata
            title = normalize_whitespace(metadata.title) if metadata and metadata.title else None
            return ArtifactInspection(
                {
                    "kind": "pdf",
                    "status": "inspected" if excerpt else "stored_without_text",
                    "page_count": page_count,
                    "title": title,
                    "text_excerpt": excerpt,
                    "text_truncated": truncated or excerpt_truncated,
                    "result_evidence": _result_evidence(text),
                    "funding_observations": _funding_observations(text),
                }
            )
    except Exception as error:
        return ArtifactInspection(
            {"kind": "pdf", "status": "unreadable"},
            (ArtifactInspectionIssue("artifact_pdf_parse_failed", str(error)),),
        )


def _safe_zip(content: bytes) -> tuple[ZipFile | None, tuple[ArtifactInspectionIssue, ...]]:
    try:
        archive = ZipFile(BytesIO(content))
        infos = archive.infolist()
    except (BadZipFile, OSError, ValueError) as error:
        return None, (ArtifactInspectionIssue("artifact_zip_invalid", str(error)),)
    if len(infos) > MAX_ZIP_ENTRIES:
        archive.close()
        return None, (ArtifactInspectionIssue("artifact_zip_entry_limit", "Archive contains too many entries."),)
    total_size = 0
    for info in infos:
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if (
            path.is_absolute()
            or ".." in path.parts
            or re.match(r"^[A-Za-z]:/", info.filename.replace("\\", "/"))
            or S_IFMT(info.external_attr >> 16) == S_IFLNK
        ):
            archive.close()
            return None, (ArtifactInspectionIssue("artifact_zip_unsafe_path", f"Unsafe archive member: {info.filename}"),)
        if info.file_size > MAX_ENTRY_BYTES:
            archive.close()
            return None, (ArtifactInspectionIssue("artifact_zip_entry_limit", f"Archive member is too large: {info.filename}"),)
        total_size += info.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            archive.close()
            return None, (ArtifactInspectionIssue("artifact_zip_uncompressed_limit", "Archive expands beyond the safety limit."),)
        if info.compress_size and info.file_size / info.compress_size > 1_000:
            archive.close()
            return None, (ArtifactInspectionIssue("artifact_zip_compression_ratio", f"Suspicious compression ratio: {info.filename}"),)
    return archive, ()


def _xml_text(raw: bytes) -> tuple[str | None, ArtifactInspectionIssue | None]:
    if len(raw) > MAX_XML_BYTES:
        return None, ArtifactInspectionIssue("artifact_xml_size_limit", "XML member exceeds the inspection limit.")
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        return None, ArtifactInspectionIssue("artifact_xml_doctype", "XML with DOCTYPE or ENTITY is rejected.")
    try:
        root = etree.fromstring(raw)
    except (etree.XMLSyntaxError, ValueError) as error:
        return None, ArtifactInspectionIssue("artifact_xml_parse_failed", str(error))
    return normalize_whitespace(" ".join(root.itertext())), None


def _inspect_office_zip(content: bytes, *, kind: str) -> ArtifactInspection:
    archive, issues = _safe_zip(content)
    if archive is None:
        return ArtifactInspection({"kind": kind, "status": "rejected"}, issues)
    try:
        names = {info.filename for info in archive.infolist()}
        if any(name.casefold().endswith("vbaproject.bin") for name in names):
            return ArtifactInspection(
                {"kind": kind, "status": "rejected", "reason": "macro_project_present"},
                (ArtifactInspectionIssue("artifact_macro_project", "Office macro projects are not inspected."),),
            )
        wanted = (
            [name for name in names if name.startswith("word/") and name.endswith(".xml")]
            if kind == "docx"
            else [name for name in names if name.startswith("xl/") and name.endswith(".xml")]
        )
        chunks: list[str] = []
        local_issues: list[ArtifactInspectionIssue] = []
        for name in sorted(wanted)[:30]:
            raw = archive.read(name)
            text, issue = _xml_text(raw)
            if issue is not None:
                local_issues.append(issue)
                continue
            if text:
                chunks.append(text)
            if sum(len(chunk) for chunk in chunks) > MAX_EXCERPT_CHARS:
                break
        full_text = "\n".join(chunks)
        excerpt, truncated = _excerpt(full_text)
        payload = {
            "kind": kind,
            "status": "inspected" if excerpt else "stored_without_text",
            "text_excerpt": excerpt,
            "text_truncated": truncated,
            "result_evidence": _result_evidence(full_text),
            "funding_observations": _funding_observations(full_text),
            "xml_members_inspected": min(len(wanted), 30),
        }
        return ArtifactInspection(payload, tuple(local_issues))
    except Exception as error:
        return ArtifactInspection(
            {"kind": kind, "status": "unreadable"},
            (ArtifactInspectionIssue("artifact_zip_read_failed", str(error)),),
        )
    finally:
        archive.close()


def inspect_fasie_artifact(content: bytes, *, content_format: str, source_url: str) -> ArtifactInspection:
    """Inspect one FASIE attachment without executing office content or macros."""

    normalized = content_format.casefold()
    if "pdf" in normalized or content.startswith(b"%PDF"):
        return _inspect_pdf(content)
    if "wordprocessingml" in normalized or source_url.casefold().endswith(".docx"):
        return _inspect_office_zip(content, kind="docx")
    if "spreadsheetml" in normalized or source_url.casefold().endswith(".xlsx"):
        return _inspect_office_zip(content, kind="xlsx")
    return ArtifactInspection(
        {"kind": "binary", "status": "rejected", "content_format": content_format},
        (ArtifactInspectionIssue("artifact_format_unknown", "The attachment format has no safe inspector."),),
    )
