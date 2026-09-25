"""Coverage validation — ensure specification-bearing sections were processed."""

from __future__ import annotations

from core.schemas import CoverageReport, DocumentStructure, Feature
from indexing.structure import specification_sections


def validate_coverage(
    structure: DocumentStructure,
    processed_section_titles: list[str],
    features: list[Feature],
) -> CoverageReport:
    discovered = specification_sections(structure)
    # Prefer leaf sections with blocks
    discovered_titles = []
    for s in discovered:
        if not s.block_ids and s.children:
            continue
        discovered_titles.append(s.title)

    processed_norm = {_norm(t) for t in processed_section_titles}
    feature_names = {_norm(f.feature_name) for f in features}

    missed = []
    for title in discovered_titles:
        nt = _norm(title)
        # Covered if processed OR a feature was named after it
        if nt in processed_norm:
            continue
        if any(nt in fn or fn in nt for fn in feature_names):
            continue
        missed.append(title)

    sections_with_features = 0
    for title in discovered_titles:
        nt = _norm(title)
        if any(nt in fn or fn in nt for fn in feature_names):
            sections_with_features += 1

    processed_count = len({_norm(t) for t in processed_section_titles})
    discovered_count = len(discovered_titles)
    complete = len(missed) == 0 and discovered_count > 0

    if complete:
        status = "COMPLETE"
    elif processed_count == 0:
        status = "INCOMPLETE"
    else:
        status = "PARTIAL"

    return CoverageReport(
        sections_discovered=discovered_count,
        sections_processed=processed_count,
        sections_with_features=sections_with_features,
        coverage_complete=complete,
        missed_sections=missed,
        status=status,  # type: ignore[arg-type]
    )


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())
