"""ADR-08: 60-Second Auto-Discovery Radar.

Performs read-only filesystem traversal (`os.scandir`) within a strict time budget
to identify, classify, and rank high-value enterprise document directories while
filtering out developer/system noise directories.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union


class ExtensionBreakdown(dict):
    """Dictionary of `{extension: count}` that also supports index access and set/list comparison."""

    def __getitem__(self, key: Union[str, int]):  # type: ignore[override]
        if isinstance(key, int):
            keys = list(self.keys())
            return keys[key]
        return super().__getitem__(key)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, set, tuple)):
            return set(self.keys()) == set(other)
        return super().__eq__(other)


VALID_DOMAIN_CATEGORIES: Tuple[str, ...] = (
    "fiscal_nfe",
    "medical_clinical",
    "legal_contracts",
    "engineering_manuals",
    "general_knowledge",
)


@dataclass
class DirectoryCandidate:
    """Ranked directory candidate discovered by the OnboardingRadar."""

    path: str
    file_count: int
    total_bytes: int
    supported_extensions: Dict[str, int] = field(default_factory=ExtensionBreakdown)
    domain_category: str = "general_knowledge"
    priority_score: float = 0.0


class OnboardingRadar:
    """Read-only workspace scanner and vertical domain classifier (ADR-08)."""

    SUPPORTED_EXTENSIONS: Set[str] = {
        ".pdf",
        ".md",
        ".docx",
        ".doc",
        ".eml",
        ".msg",
        ".xml",
        ".txt",
        ".html",
        ".xhtml",
        ".epub",
        ".hdx",
        ".csv",
        ".json",
    }

    SKIP_EXTENSIONS: Set[str] = {
        ".db",
        ".db-wal",
        ".db-shm",
        ".sqlite",
        ".sqlite3",
        ".zdict",
        ".aegis-no-index",
    }

    NOISY_DIRECTORIES: Set[str] = {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "appdata",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".idea",
        ".vscode",
        "site-packages",
        "$recycle.bin",
        "system volume information",
        ".aegis_vault",
        "aegis_index",
        "extracted_diagrams",
        "qdrant",
        "Hua_Docs",
        "hua_docs",
    }

    SKIP_DIRS: Set[str] = NOISY_DIRECTORIES

    DOMAIN_KEYWORDS: Dict[str, Tuple[str, ...]] = {
        "fiscal_nfe": (
            "nfe",
            "danfe",
            "fiscal",
            "sped",
            "cfop",
            "icms",
            "cnpj",
            "nota_fiscal",
            "notas_fiscais",
            "fatura",
            "invoice",
            "tribut",
            "sefaz",
            "xml_nfe",
        ),
        "medical_clinical": (
            "medical",
            "clinical",
            "clinic",
            "clinica",
            "patient",
            "paciente",
            "prontuario",
            "laudo",
            "exame",
            "anvisa",
            "sngpc",
            "dicom",
            "hl7",
            "fhir",
            "longevity",
            "hospital",
            "prescricao",
        ),
        "legal_contracts": (
            "legal",
            "contract",
            "contrato",
            "nda",
            "msa",
            "sla",
            "clausula",
            "procuracao",
            "aditivo",
            "juridico",
            "litigation",
            "peticao",
            "processo",
            "compliance",
            "lgpd",
            "gdpr",
            "acordo",
        ),
        "engineering_manuals": (
            "engineering",
            "manual",
            "manuais",
            "hdx",
            "hedex",
            "datasheet",
            "schematic",
            "runbook",
            "telecom",
            "firmware",
            "hardware",
            "switch",
            "router",
            "architecture",
            "specification",
            "rfc",
            "sop",
        ),
    }

    def __init__(
        self,
        supported_extensions: Optional[Set[str]] = None,
        noisy_directories: Optional[Set[str]] = None,
    ) -> None:
        raw_exts = (
            {e.lower() if e.startswith(".") else f".{e.lower()}" for e in supported_extensions}
            if supported_extensions is not None
            else set(self.SUPPORTED_EXTENSIONS)
        )
        self.skip_extensions = {e.lower() for e in self.SKIP_EXTENSIONS}
        self.supported_extensions = raw_exts - self.skip_extensions
        self.noisy_directories = (
            {d.lower() for d in noisy_directories} | {d.lower() for d in self.SKIP_DIRS}
            if noisy_directories is not None
            else {d.lower() for d in self.NOISY_DIRECTORIES}
        )
        self.skip_dirs = self.noisy_directories

    def _is_noisy_dir(self, dir_name: str) -> bool:
        if dir_name in self.SKIP_DIRS:
            return True
        lower = dir_name.lower()
        if lower in self.noisy_directories:
            return True
        if lower.startswith(".") and lower not in (".", ".."):
            return True
        return False

    def _classify_directory(
        self,
        dir_path: str,
        filenames: List[str],
        ext_counts: Dict[str, int],
    ) -> str:
        """Classify a directory into one of the 5 canonical ADR-08 domain categories."""
        scores: Dict[str, float] = {
            "fiscal_nfe": 0.0,
            "medical_clinical": 0.0,
            "legal_contracts": 0.0,
            "engineering_manuals": 0.0,
        }

        path_lower = dir_path.lower()
        joined_files_lower = " ".join(filenames).lower()

        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in path_lower:
                    scores[domain] += 6.0
                if kw in joined_files_lower:
                    scores[domain] += 3.5 * joined_files_lower.count(kw)

        # Extension affinity heuristics
        xml_count = ext_counts.get(".xml", 0)
        total_files = max(1, sum(ext_counts.values()))
        if xml_count > 0:
            scores["fiscal_nfe"] += 4.0 * (xml_count / total_files) + min(5.0, xml_count * 1.5)

        if ext_counts.get(".hdx", 0) > 0:
            scores["engineering_manuals"] += 10.0

        if ext_counts.get(".docx", 0) > 0 or ext_counts.get(".pdf", 0) > 0:
            if any(k in path_lower or k in joined_files_lower for k in ("contrat", "contract", "nda", "legal", "jurid")):
                scores["legal_contracts"] += 5.0

        best_domain, best_score = max(scores.items(), key=lambda kv: kv[1])
        if best_score >= 2.5:
            return best_domain
        return "general_knowledge"

    @staticmethod
    def _compute_priority_score(
        file_count: int,
        total_bytes: int,
        ext_counts: Dict[str, int],
        domain_category: str,
    ) -> float:
        """Compute deterministic priority score in [0.0, 100.0]."""
        if file_count <= 0:
            return 0.0

        # Base density score from file count (up to 45 pts)
        count_score = min(45.0, 15.0 * math.log10(file_count + 1) + min(20.0, file_count * 2.5))

        # Volume score from total bytes (up to 20 pts)
        volume_score = min(20.0, 3.0 * math.log10(max(10, total_bytes)))

        # Format richness & high-value document formats (up to 15 pts)
        high_value_exts = {".pdf", ".docx", ".xml", ".hdx", ".epub", ".eml", ".md"}
        high_value_hits = sum(1 for ext in ext_counts if ext in high_value_exts)
        diversity_score = min(15.0, high_value_hits * 4.0)

        # Domain specificity bonus (up to 20 pts)
        domain_bonus_map = {
            "fiscal_nfe": 20.0,
            "medical_clinical": 20.0,
            "legal_contracts": 19.0,
            "engineering_manuals": 18.0,
            "general_knowledge": 8.0,
        }
        domain_bonus = domain_bonus_map.get(domain_category, 8.0)

        raw_score = count_score + volume_score + diversity_score + domain_bonus
        return round(max(0.0, min(100.0, raw_score)), 2)

    def scan_workspace(
        self,
        root_paths: Union[str, Path, Iterable[Union[str, Path]]],
        max_scan_seconds: float = 60.0,
    ) -> List[DirectoryCandidate]:
        """Scan root paths strictly read-only (`os.scandir`) within `max_scan_seconds`."""
        deadline = time.monotonic() + max(0.01, float(max_scan_seconds))

        if isinstance(root_paths, (str, Path)):
            roots = [Path(root_paths)]
        else:
            roots = [Path(p) for p in root_paths]

        candidates: List[DirectoryCandidate] = []
        visited_realpaths: Set[str] = set()

        for root in roots:
            if time.monotonic() >= deadline:
                break
            if not root.exists() or not root.is_dir():
                continue

            stack: List[str] = [str(root.resolve())]
            while stack:
                if time.monotonic() >= deadline:
                    break

                current_dir = stack.pop()
                if current_dir in visited_realpaths:
                    continue
                visited_realpaths.add(current_dir)

                current_path_obj = Path(current_dir)
                if self._is_noisy_dir(current_path_obj.name) or (current_path_obj / ".aegis-no-index").exists():
                    continue

                ext_counts: Dict[str, int] = ExtensionBreakdown()
                filenames: List[str] = []
                total_bytes = 0
                file_count = 0
                subdirs: List[str] = []
                has_no_index_sentinel = False

                try:
                    with os.scandir(current_dir) as it:
                        for entry in it:
                            if time.monotonic() >= deadline:
                                break
                            if entry.name == ".aegis-no-index":
                                has_no_index_sentinel = True
                                break
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    if not self._is_noisy_dir(entry.name) and not (Path(entry.path) / ".aegis-no-index").exists():
                                        subdirs.append(entry.path)
                                elif entry.is_file(follow_symlinks=False):
                                    lower_name = entry.name.lower()
                                    if any(lower_name.endswith(se) for se in self.skip_extensions):
                                        continue
                                    _, ext = os.path.splitext(lower_name)
                                    if ext in self.supported_extensions and ext not in self.skip_extensions:
                                        stat_res = entry.stat(follow_symlinks=False)
                                        file_count += 1
                                        total_bytes += stat_res.st_size
                                        ext_counts[ext] = ext_counts.get(ext, 0) + 1
                                        filenames.append(entry.name)
                            except OSError:
                                continue
                except OSError:
                    continue

                if has_no_index_sentinel:
                    continue

                for sd in sorted(subdirs, reverse=True):
                    stack.append(sd)

                if file_count > 0:
                    domain = self._classify_directory(
                        dir_path=current_dir,
                        filenames=filenames,
                        ext_counts=ext_counts,
                    )
                    score = self._compute_priority_score(
                        file_count=file_count,
                        total_bytes=total_bytes,
                        ext_counts=ext_counts,
                        domain_category=domain,
                    )
                    candidates.append(
                        DirectoryCandidate(
                            path=current_dir,
                            file_count=file_count,
                            total_bytes=total_bytes,
                            supported_extensions=ext_counts,
                            domain_category=domain,
                            priority_score=score,
                        )
                    )

        candidates.sort(key=lambda c: (c.priority_score, c.file_count, c.total_bytes), reverse=True)
        return candidates
