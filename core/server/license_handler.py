"""
Cryptographic Platform License & AI Harness Manager.
Validates Ed25519 cryptographic platform licenses, dynamically manages PlanEnforcer tiers,
and generates ready-to-use client snippets for Antigravity, Claude Code, Cursor, Windsurf, and Cline.
"""

import datetime
import hashlib
import json
import logging
from typing import Dict, Any, Tuple

from ..license import LicenseData, SovereignLicenseManager
from ..security import PlanEnforcer
from .constants import ACTIVE_LICENSE_FILE, LICENSE_KEYS_FILE

logger = logging.getLogger("sovereign_server.license")


class LicenseHandler:
    """Manages local Ed25519 cryptographic license lifecycle and AI harness configurations."""

    @staticmethod
    def ensure_ed25519_keypair() -> Tuple[bytes, bytes]:
        try:
            if LICENSE_KEYS_FILE.exists():
                kdata = json.loads(LICENSE_KEYS_FILE.read_text(encoding="utf-8"))
                return (
                    kdata["private_key_pem"].encode("utf-8"),
                    kdata["public_key_pem"].encode("utf-8"),
                )
        except Exception:
            pass
        priv_pem, pub_pem = SovereignLicenseManager.generate_keypair()
        try:
            LICENSE_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
            LICENSE_KEYS_FILE.write_text(
                json.dumps(
                    {
                        "private_key_pem": priv_pem.decode("utf-8"),
                        "public_key_pem": pub_pem.decode("utf-8"),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass
        return priv_pem, pub_pem

    @staticmethod
    def build_ai_harness_snippets(plan_tier_str: str) -> Dict[str, Dict[str, str]]:
        mcp_script = "/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/core/mcp/server.py"
        python_bin = "/home/tlima/Enterprise_Hub/.venv/bin/python3"
        return {
            "antigravity": {
                "name": "Google Antigravity (agy)",
                "badge": "Native 7-Tool MCP v2",
                "config_path": "~/.gemini/antigravity-cli/mcp/sovereign-vault/mcp_config.json",
                "snippet": json.dumps(
                    {
                        "mcpServers": {
                            "sovereign-vault": {
                                "command": python_bin,
                                "args": [mcp_script],
                                "env": {
                                    "SOVEREIGN_PLAN_TIER": plan_tier_str,
                                    "SOVEREIGN_VAULT_DIR": "/home/tlima/Enterprise_Hub/docs/.aegis_vault",
                                },
                            }
                        }
                    },
                    indent=2,
                ),
            },
            "claude_code": {
                "name": "Claude Code CLI",
                "badge": "One-Command Registration",
                "config_path": "~/.claude.json",
                "snippet": f"claude mcp add sovereign-vault -- {python_bin} {mcp_script}",
            },
            "claude_desktop": {
                "name": "Claude Desktop",
                "badge": "Desktop MCP Bridge",
                "config_path": "~/.config/Claude/claude_desktop_config.json",
                "snippet": json.dumps(
                    {
                        "mcpServers": {
                            "sovereign-vault": {
                                "command": python_bin,
                                "args": [mcp_script],
                            }
                        }
                    },
                    indent=2,
                ),
            },
            "cursor": {
                "name": "Cursor IDE",
                "badge": "Project .cursor/mcp.json",
                "config_path": ".cursor/mcp.json",
                "snippet": json.dumps(
                    {
                        "mcpServers": {
                            "aegis-sovereign-vault": {
                                "command": python_bin,
                                "args": [mcp_script],
                            }
                        }
                    },
                    indent=2,
                ),
            },
            "windsurf": {
                "name": "Windsurf (Codeium)",
                "badge": "Cascade MCP Config",
                "config_path": "~/.codeium/windsurf/mcp_config.json",
                "snippet": json.dumps(
                    {
                        "mcpServers": {
                            "sovereign-vault": {
                                "command": python_bin,
                                "args": [mcp_script],
                            }
                        }
                    },
                    indent=2,
                ),
            },
            "cline": {
                "name": "Continue.dev / Cline",
                "badge": "VS Code MCP Extension",
                "config_path": "cline_mcp_settings.json",
                "snippet": json.dumps(
                    {
                        "mcpServers": {
                            "sovereign-vault": {
                                "command": python_bin,
                                "args": [mcp_script],
                                "disabled": False,
                                "autoApprove": [
                                    "sovereign_route_and_analyze",
                                    "sovereign_inspect_archive",
                                    "sovereign_get_entity_dossier",
                                ],
                            }
                        }
                    },
                    indent=2,
                ),
            },
        }

    @classmethod
    def get_license_status(cls, manager: Any) -> Dict[str, Any]:
        priv_pem, pub_pem = cls.ensure_ed25519_keypair()
        pub_fp = hashlib.sha256(pub_pem).hexdigest()[:32]

        active_meta = None
        if ACTIVE_LICENSE_FILE.exists():
            try:
                active_meta = json.loads(ACTIVE_LICENSE_FILE.read_text(encoding="utf-8"))
            except Exception:
                active_meta = None

        if not active_meta or not active_meta.get("license_token"):
            return cls.attach_license(
                manager,
                {
                    "tier": manager.plan_enforcer.plan.value,
                    "organization": "Enterprise Hub Homelab (Dell Latitude 7390)",
                    "customer_id": "LIC-AEGIS-ENT-2026",
                },
            )

        token = active_meta["license_token"]
        verified_data = SovereignLicenseManager.verify_license(token, pub_pem, check_expiry=False)
        tier_up = verified_data.plan_tier.upper()

        all_features = [
            "Prong 1 B-Tree/FTS5",
            "Prong 2 Hybrid ONNX",
            "SQLite WAL GraphRAG",
            "RAPTOR Hierarchical Tree",
            "Zero-Copy Archive Streamer",
        ]
        if tier_up == "FREE":
            unlocked = ["Prong 1 B-Tree/FTS5", "Zero-Copy Archive Streamer"]
        elif tier_up == "PRO":
            unlocked = ["Prong 1 B-Tree/FTS5", "Prong 2 Hybrid ONNX", "SQLite WAL GraphRAG", "Zero-Copy Archive Streamer"]
        else:
            unlocked = all_features

        return {
            "status": "active",
            "tier": tier_up,
            "plan_tier": verified_data.plan_tier,
            "license_id": verified_data.license_id,
            "customer_id": verified_data.customer_id,
            "organization": active_meta.get("organization", "Enterprise Hub Homelab"),
            "issued_at": verified_data.issued_at,
            "expires_at": verified_data.expires_at or "2029-12-31T23:59:59+00:00",
            "max_documents": verified_data.max_documents,
            "signature_verified": True,
            "algorithm": "Ed25519",
            "public_key_fingerprint": f"ed25519:{pub_fp}",
            "hardware_fingerprint": "homelab-dell-7390-aegis-v2",
            "license_token": token,
            "unlocked_features": unlocked,
            "ai_harnesses": cls.build_ai_harness_snippets(manager.plan_enforcer.plan.value),
        }

    @classmethod
    def attach_license(cls, manager: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
        priv_pem, pub_pem = cls.ensure_ed25519_keypair()
        pub_fp = hashlib.sha256(pub_pem).hexdigest()[:32]

        raw_token = (payload.get("license_token") or payload.get("token") or "").strip()
        organization = payload.get("organization") or "Enterprise Hub Homelab (Dell Latitude 7390)"

        if raw_token:
            verified = SovereignLicenseManager.verify_license(raw_token, pub_pem, check_expiry=False)
            token = raw_token
        else:
            req_tier = str(payload.get("tier") or payload.get("plan_tier") or "enterprise").strip().lower()
            if req_tier not in ("free", "pro", "enterprise"):
                req_tier = "enterprise"
            cust_id = payload.get("customer_id") or f"LIC-AEGIS-{req_tier.upper()}-2026"
            lic_data = LicenseData(
                license_id=f"AEGIS-ED25519-{req_tier.upper()}-01",
                customer_id=cust_id,
                plan_tier=req_tier,
                issued_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                expires_at="2029-12-31T23:59:59+00:00",
                max_seats=64 if req_tier == "enterprise" else (10 if req_tier == "pro" else 1),
                max_documents=None if req_tier in ("pro", "enterprise") else 2500,
                features={
                    "multimodal_clip": req_tier in ("pro", "enterprise"),
                    "raptor_synthesis": req_tier == "enterprise",
                    "gpu_delegation": req_tier in ("pro", "enterprise"),
                    "custom_ontology": req_tier == "enterprise",
                },
            )
            token = SovereignLicenseManager.sign_license(lic_data, priv_pem)
            verified = SovereignLicenseManager.verify_license(token, pub_pem, check_expiry=False)

        with manager._lock:
            manager.plan_enforcer = PlanEnforcer(verified.plan_tier)
            manager.router.plan_enforcer = manager.plan_enforcer
            manager.condenser.plan_enforcer = manager.plan_enforcer

        active_record = {
            "organization": organization,
            "customer_id": verified.customer_id,
            "tier": verified.plan_tier.upper(),
            "license_token": token,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        try:
            ACTIVE_LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
            ACTIVE_LICENSE_FILE.write_text(json.dumps(active_record, indent=2), encoding="utf-8")
        except Exception:
            pass

        tier_up = verified.plan_tier.upper()
        all_features = [
            "Prong 1 B-Tree/FTS5",
            "Prong 2 Hybrid ONNX",
            "SQLite WAL GraphRAG",
            "RAPTOR Hierarchical Tree",
            "Zero-Copy Archive Streamer",
        ]
        if tier_up == "FREE":
            unlocked = ["Prong 1 B-Tree/FTS5", "Zero-Copy Archive Streamer"]
        elif tier_up == "PRO":
            unlocked = ["Prong 1 B-Tree/FTS5", "Prong 2 Hybrid ONNX", "SQLite WAL GraphRAG", "Zero-Copy Archive Streamer"]
        else:
            unlocked = all_features

        return {
            "status": "attached",
            "tier": tier_up,
            "plan_tier": verified.plan_tier,
            "license_id": verified.license_id,
            "customer_id": verified.customer_id,
            "organization": organization,
            "issued_at": verified.issued_at,
            "expires_at": verified.expires_at or "2029-12-31T23:59:59+00:00",
            "signature_verified": True,
            "algorithm": "Ed25519",
            "public_key_fingerprint": f"ed25519:{pub_fp}",
            "hardware_fingerprint": "homelab-dell-7390-aegis-v2",
            "license_token": token,
            "unlocked_features": unlocked,
            "ai_harnesses": cls.build_ai_harness_snippets(verified.plan_tier),
        }
