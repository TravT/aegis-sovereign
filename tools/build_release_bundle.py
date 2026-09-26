#!/usr/bin/env python3
"""
Aegis Sovereign Knowledge Appliance v2.1.0 — Turnkey Release Bundle Builder.

Assembles a portable, self-contained release bundle and/or `.tar.gz` archive containing:
  - core/ (Router, Chunker, Searcher, GraphStore, MCP Server, Archive Streamer, HDX/OpenXML parsers, Server)
  - desktop/ (NanoRunner local LLM bridge + HUD specs)
  - web/portal/ (Two-Pronged Web Search Portal UI)
  - scripts/sovereign_mcp.py (Stdio MCP v2 entrypoint)
  - mcp/sovereign-vault/ (All 7 tool JSON schemas + instructions.md)
  - skills/manage-sovereign-vault/SKILL.md
  - docs/manuals/ (All 14 Operator Manuals 01–14)
  - install.sh + MANIFEST.json (with SHA-256 checksums of all packaged components)
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


APPLIANCE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APPLIANCE_ROOT.parent.parent
RELEASE_VERSION = "2.1.0"

REQUIRED_MCP_SCHEMAS = [
    "sovereign_optimize_context.json",
    "sovereign_search_vault.json",
    "sovereign_get_entity_dossier.json",
    "sovereign_node_status.json",
    "sovereign_route_and_analyze.json",
    "sovereign_inspect_archive.json",
    "sovereign_scan_onboarding_radar.json",
    "instructions.md",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def collect_bundle_entries() -> List[Tuple[Path, str]]:
    """
    Returns a list of (source_absolute_path, archive_relative_path) tuples
    representing all files to be included in the release bundle.
    """
    entries: List[Tuple[Path, str]] = []

    def add_tree(src_dir: Path, rel_prefix: str) -> None:
        if not src_dir.exists():
            return
        for p in sorted(src_dir.rglob("*")):
            if not p.is_file():
                continue
            if any(part in ("__pycache__", ".pytest_cache", "node_modules", ".next", ".git") for part in p.parts):
                continue
            if p.suffix in (".pyc", ".pyo", ".db", ".db-wal", ".db-shm"):
                continue
            rel = f"{rel_prefix}/{p.relative_to(src_dir).as_posix()}"
            entries.append((p, rel))

    # 1. core/
    add_tree(APPLIANCE_ROOT / "core", "core")

    # 2. desktop/
    add_tree(APPLIANCE_ROOT / "desktop", "desktop")

    # 3. web/portal/
    add_tree(APPLIANCE_ROOT / "web" / "portal", "web/portal")

    # 4. scripts/sovereign_mcp.py
    mcp_script = REPO_ROOT / "scripts" / "sovereign_mcp.py"
    if mcp_script.exists():
        entries.append((mcp_script, "scripts/sovereign_mcp.py"))

    # 5. mcp/sovereign-vault/ (7 JSON schemas + instructions.md)
    mcp_schema_dir = APPLIANCE_ROOT / "core" / "mcp" / "schemas"
    user_mcp_dir = Path.home() / ".gemini" / "antigravity-cli" / "mcp" / "sovereign-vault"
    effective_mcp_dir = user_mcp_dir if user_mcp_dir.exists() else mcp_schema_dir
    for fname in REQUIRED_MCP_SCHEMAS:
        src_file = effective_mcp_dir / fname
        if not src_file.exists():
            src_file = mcp_schema_dir / fname
        if src_file.exists():
            entries.append((src_file, f"mcp/sovereign-vault/{fname}"))

    # 6. skills/manage-sovereign-vault/SKILL.md
    skill_path = REPO_ROOT / ".agents" / "skills" / "manage-sovereign-vault" / "SKILL.md"
    if skill_path.exists():
        entries.append((skill_path, "skills/manage-sovereign-vault/SKILL.md"))

    # 7. docs/manuals/ (All 15 Operator Manuals)
    add_tree(APPLIANCE_ROOT / "docs" / "manuals", "docs/manuals")

    # 8. tools/ (Lifecycle, Capsule, Packaging, and Indexing CLIs)
    add_tree(APPLIANCE_ROOT / "tools", "tools")

    # 9. install.sh, README.md, requirements.txt, pyproject.toml
    for root_file in ("install.sh", "README.md", "requirements.txt", "pyproject.toml"):
        rf = APPLIANCE_ROOT / root_file
        if rf.exists():
            entries.append((rf, root_file))

    return entries


def build_manifest(entries: List[Tuple[Path, str]]) -> Dict[str, Any]:
    """Computes SHA-256 checksums for every component and returns MANIFEST.json structure."""
    files_manifest: List[Dict[str, Any]] = []
    total_bytes = 0

    for src, rel in entries:
        digest = sha256_file(src)
        size = src.stat().st_size
        total_bytes += size
        files_manifest.append(
            {
                "path": rel,
                "sha256": digest,
                "size_bytes": size,
            }
        )

    manuals = [f["path"] for f in files_manifest if f["path"].startswith("docs/manuals/") and f["path"].endswith(".md") and not f["path"].endswith("README.md")]
    mcp_schemas = [f["path"] for f in files_manifest if f["path"].startswith("mcp/sovereign-vault/") and f["path"].endswith(".json")]

    return {
        "appliance": "Aegis Sovereign Knowledge Appliance",
        "version": RELEASE_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_files": len(files_manifest),
        "total_bytes": total_bytes,
        "operator_manuals_count": len(manuals),
        "mcp_v2_tool_schemas_count": len(mcp_schemas),
        "components": {
            "core": True,
            "desktop_nano_runner": True,
            "web_portal": any(f["path"] == "web/portal/index.html" for f in files_manifest),
            "sovereign_mcp_entrypoint": any(f["path"] == "scripts/sovereign_mcp.py" for f in files_manifest),
            "manage_sovereign_vault_skill": any(f["path"] == "skills/manage-sovereign-vault/SKILL.md" for f in files_manifest),
        },
        "files": files_manifest,
    }


def create_release_bundle(
    bundle_dir: Optional[Path] = None,
    create_tarball: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    entries = collect_bundle_entries()
    manifest = build_manifest(entries)

    if manifest["operator_manuals_count"] < 14:
        raise RuntimeError(f"Expected >= 14 operator manuals, found {manifest['operator_manuals_count']}")
    if manifest["mcp_v2_tool_schemas_count"] != 7:
        raise RuntimeError(f"Expected 7 MCP v2 JSON schemas, found {manifest['mcp_v2_tool_schemas_count']}")

    target_dir = bundle_dir or (APPLIANCE_ROOT / "dist" / f"aegis-sovereign-appliance-v{RELEASE_VERSION}")

    if dry_run:
        return {
            "mode": "dry-run",
            "target_dir": str(target_dir),
            "manifest": manifest,
        }

    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for src, rel in entries:
        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    manifest_path = target_dir / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    tarball_path: Optional[Path] = None
    if create_tarball:
        tarball_path = target_dir.parent / f"aegis-sovereign-package-v{RELEASE_VERSION}.tar.gz"
        with tarfile.open(tarball_path, "w:gz") as tf:
            tf.add(target_dir, arcname=f"aegis-sovereign-appliance-v{RELEASE_VERSION}")

    return {
        "mode": "bundle",
        "target_dir": str(target_dir),
        "manifest_path": str(manifest_path),
        "tarball_path": str(tarball_path) if tarball_path else None,
        "manifest": manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Aegis Sovereign Knowledge Appliance v2.1.0 release bundle.")
    parser.add_argument("--bundle-dir", type=str, default=None, help="Output directory for extracted release bundle")
    parser.add_argument("--no-tar", action="store_true", help="Skip creating .tar.gz archive")
    parser.add_argument("--dry-run", action="store_true", help="Validate components and output MANIFEST.json summary without writing bundle")
    args = parser.parse_args()

    out_dir = Path(args.bundle_dir).resolve() if args.bundle_dir else None
    result = create_release_bundle(
        bundle_dir=out_dir,
        create_tarball=not args.no_tar,
        dry_run=args.dry_run,
    )
    m = result["manifest"]
    print(
        f"[build_release_bundle] mode={result['mode']} version={m['version']} "
        f"files={m['total_files']} bytes={m['total_bytes']} "
        f"manuals={m['operator_manuals_count']} mcp_schemas={m['mcp_v2_tool_schemas_count']}"
    )
    if not args.dry_run:
        print(f"[build_release_bundle] MANIFEST: {result['manifest_path']}")
        if result.get("tarball_path"):
            print(f"[build_release_bundle] TARBALL:  {result['tarball_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
