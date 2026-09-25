from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from app.analytics.regional import REGIONAL_INDICATORS_VERSION
from app.analytics.snapshots import (
    CALCULATION_VERSION,
    INPUT_MANIFEST_VERSION,
    PROGRAM_SOURCE_KEYS,
    SNAPSHOT_SCOPE,
)


NETWORK_METRICS_VERSION = "catalog-network/v1"
NETWORK_DIMENSIONS = ("program", "theme", "geography")
MIN_SOURCE_NODES_FOR_COMPARISON = 3
MIN_RIGHT_NODES_FOR_CENTRALITY = 5


class NetworkAnalyticsError(ValueError):
    """Raised when a frozen snapshot cannot support a valid network graph."""


def _attr(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _rows(value: object, *, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise NetworkAnalyticsError(f"{field} must be an array of objects")
    return list(value)


def _as_of(snapshot: object) -> datetime:
    value = _attr(snapshot, "as_of")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise NetworkAnalyticsError("snapshot as_of must be an ISO-8601 timestamp") from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise NetworkAnalyticsError("snapshot as_of must include a timezone")
    return value.astimezone(timezone.utc)


def _validate_snapshot(snapshot: object) -> tuple[str, str, str, datetime]:
    snapshot_id = str(_attr(snapshot, "id", ""))
    scope = _attr(snapshot, "scope")
    calculation_version = _attr(snapshot, "calculation_version")
    input_manifest = _attr(snapshot, "input_manifest")
    source_scope = _attr(snapshot, "source_scope")
    metrics = _attr(snapshot, "metrics")
    if not snapshot_id:
        raise NetworkAnalyticsError("snapshot requires an id")
    if scope != SNAPSHOT_SCOPE or calculation_version != CALCULATION_VERSION:
        raise NetworkAnalyticsError("network analytics requires catalog-quality/v3 snapshots")
    if not isinstance(input_manifest, Mapping) or input_manifest.get("version") != INPUT_MANIFEST_VERSION:
        raise NetworkAnalyticsError("network analytics requires catalog-quality-input/v3")
    if not isinstance(source_scope, Mapping) or not isinstance(metrics, Mapping):
        raise NetworkAnalyticsError("snapshot source_scope and metrics must be objects")
    regional = metrics.get("regional_indicators")
    if (
        not isinstance(regional, Mapping)
        or regional.get("version") != REGIONAL_INDICATORS_VERSION
        or regional.get("snapshot_id") != snapshot_id
    ):
        raise NetworkAnalyticsError("snapshot has no matching reproducible E3 indicators")
    data_class = input_manifest.get("data_class")
    if not isinstance(data_class, str) or not data_class:
        raise NetworkAnalyticsError("snapshot data_class must be known")
    as_of = _as_of(snapshot)
    try:
        manifest_as_of = datetime.fromisoformat(str(input_manifest["as_of"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as error:
        raise NetworkAnalyticsError("manifest as_of must be an ISO-8601 timestamp") from error
    if manifest_as_of.tzinfo is None or manifest_as_of.utcoffset() is None:
        raise NetworkAnalyticsError("manifest as_of must include a timezone")
    if manifest_as_of.astimezone(timezone.utc) != as_of:
        raise NetworkAnalyticsError("snapshot as_of conflicts with manifest as_of")
    if input_manifest.get("freshness_window_days") != _attr(snapshot, "freshness_window_days"):
        raise NetworkAnalyticsError("snapshot freshness window conflicts with the frozen manifest")
    return snapshot_id, scope, data_class, as_of


def _metric(
    *,
    value: int | float | None,
    formula: str,
    unit: str,
    sample_size: int,
    snapshot_id: str,
    as_of: datetime,
    filter_description: str,
    limitation: str,
    status: str = "computed",
) -> dict[str, Any]:
    return {
        "value": value,
        "formula": formula,
        "unit": unit,
        "period": {"kind": "point_in_time", "as_of": as_of.isoformat()},
        "filter": filter_description,
        "missing": "A missing explicit source or taxonomy association is not inferred.",
        "sample_size": sample_size,
        "snapshot_id": snapshot_id,
        "limitation": limitation,
        "status": status,
    }


def _connected_components(
    node_ids: Sequence[str],
    adjacency: Mapping[str, set[str]],
) -> tuple[list[list[str]], dict[str, int]]:
    components: list[list[str]] = []
    component_by_node: dict[str, int] = {}
    for start in node_ids:
        if start in component_by_node:
            continue
        component_id = len(components) + 1
        queue = deque([start])
        component_by_node[start] = component_id
        members: list[str] = []
        while queue:
            node_id = queue.popleft()
            members.append(node_id)
            for neighbor in sorted(adjacency.get(node_id, set())):
                if neighbor not in component_by_node:
                    component_by_node[neighbor] = component_id
                    queue.append(neighbor)
        components.append(sorted(members))
    return components, component_by_node


def _build_dimension_graph(
    *,
    dimension: str,
    source_keys: Sequence[str],
    programs: Sequence[Mapping[str, Any]],
    assignments: Mapping[str, Sequence[Mapping[str, str]]],
    snapshot_id: str,
    data_class: str,
    as_of: datetime,
) -> dict[str, Any]:
    source_nodes = [f"source:{key}" for key in source_keys]
    labels: dict[str, dict[str, str]] = {
        f"source:{key}": {"source_key": key, "label": key}
        for key in source_keys
    }
    edge_weights: dict[tuple[str, str], int] = {}
    if dimension == "program":
        for program in programs:
            program_id = str(program["program_id"])
            source_key = str(program["source_key"])
            right_id = f"program:{program_id}"
            labels[right_id] = {"program_id": program_id, "label": program_id}
            edge_weights[(f"source:{source_key}", right_id)] = 1
    else:
        taxonomy_dimension = "themes" if dimension == "theme" else "geographies"
        category_labels: dict[str, dict[str, str]] = {}
        source_programs_by_category: dict[tuple[str, str], set[str]] = defaultdict(set)
        source_by_program = {
            str(program["program_id"]): str(program["source_key"])
            for program in programs
        }
        for program_id, program_assignments in assignments.items():
            source_key = source_by_program[program_id]
            for assignment in program_assignments:
                taxonomy_id = assignment["taxonomy_id"]
                slug = assignment["slug"]
                name = assignment["name"]
                previous_label = category_labels.get(taxonomy_id)
                current_label = {"taxonomy_id": taxonomy_id, "slug": slug, "name": name}
                if previous_label is not None and previous_label != current_label:
                    raise NetworkAnalyticsError(
                        f"conflicting {taxonomy_dimension} labels for taxonomy_id {taxonomy_id}"
                    )
                category_labels[taxonomy_id] = current_label
                source_programs_by_category[(source_key, taxonomy_id)].add(program_id)
        for taxonomy_id, category_label in category_labels.items():
            right_id = f"{dimension}:{taxonomy_id}"
            labels[right_id] = {
                "taxonomy_id": taxonomy_id,
                "slug": category_label["slug"],
                "label": category_label["name"],
            }
        for (source_key, taxonomy_id), program_ids in source_programs_by_category.items():
            edge_weights[(f"source:{source_key}", f"{dimension}:{taxonomy_id}")] = len(program_ids)

    right_nodes = sorted(node_id for node_id in labels if not node_id.startswith("source:"))
    all_nodes = sorted([*source_nodes, *right_nodes])
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in all_nodes}
    strengths: dict[str, int] = {node_id: 0 for node_id in all_nodes}
    edges: list[dict[str, Any]] = []
    for (source_node, right_node), weight in sorted(edge_weights.items()):
        adjacency[source_node].add(right_node)
        adjacency[right_node].add(source_node)
        strengths[source_node] += weight
        strengths[right_node] += weight
        edges.append(
            {
                "source_node": source_node,
                "entity_node": right_node,
                "weight": weight,
                "weight_unit": "programs represented by the association",
            }
        )

    components, component_by_node = _connected_components(all_nodes, adjacency)
    edge_count = len(edges)
    possible_edges = len(source_nodes) * len(right_nodes)
    density = edge_count / possible_edges if possible_edges else None
    small_graph = (
        len(source_nodes) < MIN_SOURCE_NODES_FOR_COMPARISON
        or len(right_nodes) < MIN_RIGHT_NODES_FOR_CENTRALITY
    )
    warnings: list[str] = []
    if small_graph:
        warnings.append("small_graph_no_ranking")
    if not right_nodes:
        warnings.append("empty_entity_partition")

    filter_description = (
        "eligible published programs in a real/test/synthetic class partition; "
        "primary source attribution only; FASIE, Telegram discovery, and fixture sources excluded"
    )
    limitation = (
        "Describes explicit associations in this platform snapshot only; source attribution is not "
        "organizer identity, source-to-taxonomy links are derived through programs, and no edge "
        "implies causality, quality, demand, or whole-market coverage."
    )
    node_metrics: list[dict[str, Any]] = []
    for node_id in all_nodes:
        is_source = node_id.startswith("source:")
        opposite_partition_size = len(right_nodes) if is_source else len(source_nodes)
        degree = len(adjacency[node_id])
        centrality = degree / opposite_partition_size if opposite_partition_size else None
        node_metrics.append(
            {
                "node_id": node_id,
                "partition": "source" if is_source else dimension,
                **labels[node_id],
                "degree": degree,
                "degree_centrality": centrality,
                "degree_centrality_status": (
                    "computed" if centrality is not None else "not_defined_empty_opposite_partition"
                ),
                "strength": strengths[node_id],
                "component_id": component_by_node[node_id],
                "metric_metadata": {
                    "snapshot_id": snapshot_id,
                    "window": {"kind": "point_in_time", "as_of": as_of.isoformat()},
                    "filter": filter_description,
                    "unit": "distinct opposite-partition nodes for degree; programs represented by associations for strength",
                    "degree_formula": "count(distinct adjacent nodes)",
                    "degree_centrality_formula": "degree(node) / size(opposite partition)",
                    "strength_formula": "sum(edge weights incident to node)",
                    "limitation": limitation,
                },
                "warning": "small_graph_no_ranking" if small_graph else None,
            }
        )

    return {
        "dimension": dimension,
        "version": NETWORK_METRICS_VERSION,
        "snapshot_id": snapshot_id,
        "data_class": data_class,
        "window": {"kind": "point_in_time", "as_of": as_of.isoformat()},
        "unit_of_observation": "one unique eligible Program or one explicit taxonomy entity",
        "filter": filter_description,
        "graph_definition": {
            "left_partition": "eligible primary source keys from snapshot.source_scope.program_sources",
            "right_partition": dimension,
            "direction": "undirected association; direction is intentionally not inferred",
            "edge_rule": (
                "one primary-source to program edge per frozen program"
                if dimension == "program"
                else "source-to-taxonomy edge exists when at least one source-attributed program has the explicit frozen taxonomy link"
            ),
            "edge_weight": (
                "1 per source-program pair"
                if dimension == "program"
                else "count(distinct program_id) for the source and taxonomy pair"
            ),
            "node_identity": (
                "program_id"
                if dimension == "program"
                else "taxonomy_id; slug and name are display labels"
            ),
        },
        "metrics": {
            "node_count": _metric(
                value=len(all_nodes), formula="|left nodes| + |right nodes|", unit="nodes",
                sample_size=len(all_nodes), snapshot_id=snapshot_id, as_of=as_of,
                filter_description=filter_description, limitation=limitation,
            ),
            "edge_count": _metric(
                value=edge_count, formula="count(distinct source-entity pairs)", unit="edges",
                sample_size=edge_count, snapshot_id=snapshot_id, as_of=as_of,
                filter_description=filter_description, limitation=limitation,
            ),
            "density": _metric(
                value=density, formula="|E| / (|left| * |right|)", unit="share of possible edges",
                sample_size=edge_count, snapshot_id=snapshot_id, as_of=as_of,
                filter_description=filter_description, limitation=limitation,
                status="computed" if density is not None else "not_defined_empty_partition",
            ),
            "connected_components": _metric(
                value=len(components), formula="number of connected components in the undirected graph",
                unit="components", sample_size=len(all_nodes), snapshot_id=snapshot_id, as_of=as_of,
                filter_description=filter_description, limitation=limitation,
            ),
            "degree_centrality": {
                "formula": "degree(node) / size(opposite partition)",
                "unit": "share of opposite-partition nodes adjacent to node",
                "normalization": "separate per bipartite graph; null when the opposite partition is empty",
                "ranking": "not produced",
                "small_graph_warning": small_graph,
                "period": {"kind": "point_in_time", "as_of": as_of.isoformat()},
                "filter": filter_description,
                "sample_size": len(all_nodes),
                "snapshot_id": snapshot_id,
                "limitation": limitation,
            },
            "strength": {
                "formula": "sum(edge weights incident to node)",
                "unit": "programs represented by incident associations",
                "period": {"kind": "point_in_time", "as_of": as_of.isoformat()},
                "filter": filter_description,
                "sample_size": len(all_nodes),
                "snapshot_id": snapshot_id,
                "limitation": limitation,
            },
        },
        "nodes": node_metrics,
        "edges": edges,
        "components": components,
        "warnings": warnings,
        "limitations": [limitation],
    }


def calculate_network_metrics(snapshot: object) -> dict[str, Any]:
    """Build three source-centered, undirected bipartite graphs from one v3 snapshot."""

    snapshot_id, _scope, data_class, as_of = _validate_snapshot(snapshot)
    source_scope = _attr(snapshot, "source_scope")
    input_manifest = _attr(snapshot, "input_manifest")
    source_entries = _rows(source_scope.get("program_sources"), field="source_scope.program_sources")
    source_keys = sorted(
        {
            str(row["source_key"])
            for row in source_entries
            if isinstance(row.get("source_key"), str)
            and row["source_key"] in PROGRAM_SOURCE_KEYS
        }
    )
    programs = _rows(input_manifest.get("programs"), field="programs")
    program_by_id: dict[str, Mapping[str, Any]] = {}
    for program in programs:
        program_id = program.get("program_id")
        source_key = program.get("source_key")
        if not isinstance(program_id, str) or not program_id:
            raise NetworkAnalyticsError("programs require a non-empty program_id")
        if program_id in program_by_id:
            raise NetworkAnalyticsError(f"duplicate program_id in frozen roster: {program_id}")
        if source_key not in source_keys:
            raise NetworkAnalyticsError("program source is outside the frozen eligible source scope")
        program_by_id[program_id] = program

    taxonomy = input_manifest.get("taxonomy")
    if not isinstance(taxonomy, Mapping):
        raise NetworkAnalyticsError("catalog-quality-input/v3 requires frozen taxonomy links")
    assignments_by_dimension: dict[str, dict[str, list[dict[str, str]]]] = {}
    for dimension, manifest_key in (("theme", "themes"), ("geography", "geographies")):
        by_program: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in _rows(taxonomy.get(manifest_key), field=f"taxonomy.{manifest_key}"):
            program_id = row.get("program_id")
            taxonomy_id = row.get("taxonomy_id")
            slug = row.get("slug")
            name = row.get("name")
            if program_id not in program_by_id:
                raise NetworkAnalyticsError("taxonomy association points outside the frozen program roster")
            if not all(isinstance(value, str) and value for value in (taxonomy_id, slug, name)):
                raise NetworkAnalyticsError("taxonomy links require taxonomy_id, slug, and name")
            association = {
                "taxonomy_id": str(taxonomy_id),
                "slug": str(slug),
                "name": str(name),
            }
            if association not in by_program[str(program_id)]:
                by_program[str(program_id)].append(association)
        assignments_by_dimension[dimension] = by_program

    dimensions = {
        dimension: _build_dimension_graph(
            dimension=dimension,
            source_keys=source_keys,
            programs=programs,
            assignments=assignments_by_dimension.get(dimension, {}),
            snapshot_id=snapshot_id,
            data_class=data_class,
            as_of=as_of,
        )
        for dimension in NETWORK_DIMENSIONS
    }
    return {
        "version": NETWORK_METRICS_VERSION,
        "snapshot_id": snapshot_id,
        "data_class": data_class,
        "as_of": as_of.isoformat(),
        "scope": SNAPSHOT_SCOPE,
        "calculation_version": CALCULATION_VERSION,
        "registry_fingerprint": str(_attr(snapshot, "registry_fingerprint", "")),
        "dimensions": dimensions,
        "limitations": [
            "No dedicated organizer entity or organizer field is present in the current frozen snapshot manifest; source is the only available left partition.",
            "The graph describes connected platform sources and explicit frozen Program-to-taxonomy associations only.",
            "Small graphs are descriptive; centrality rankings are not produced and graph links do not establish causality.",
        ],
    }
