#!/usr/bin/env python3
"""
Security Clearance Pre-Filtering Engine and Multi-Tier Resource Plan Enforcer.
Aegis Sovereign Knowledge Appliance.

Enforces Mandatory Access Control (MAC) at the retrieval level (Zero Post-Filtering)
and gates resource consumption, features, and document volume by plan tier.
"""

from pathlib import Path
from enum import IntEnum, Enum
from typing import List, Union, Optional, Set, Dict, Any

from .license import (
    LicenseData,
    SovereignLicenseManager,
    LicenseError,
    LicenseExpiredError,
    InvalidLicenseSignatureError,
    LicenseTamperedError,
    LicenseNotFoundError,
)


class ClearanceLevel(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3

    @classmethod
    def from_string(cls, val: Union[str, int, "ClearanceLevel"]) -> "ClearanceLevel":
        if isinstance(val, ClearanceLevel):
            return val
        if isinstance(val, int):
            try:
                return cls(val)
            except ValueError:
                raise ValueError(f"Invalid integer clearance level: {val}. Must be 0..3")
        if isinstance(val, str):
            clean = val.strip().lower()
            name_map = {
                "public": cls.PUBLIC,
                "0": cls.PUBLIC,
                "internal": cls.INTERNAL,
                "1": cls.INTERNAL,
                "confidential": cls.CONFIDENTIAL,
                "2": cls.CONFIDENTIAL,
                "restricted": cls.RESTRICTED,
                "top_secret": cls.RESTRICTED,
                "top-secret": cls.RESTRICTED,
                "secret": cls.RESTRICTED,
                "admin": cls.RESTRICTED,
                "max": cls.RESTRICTED,
                "3": cls.RESTRICTED,
            }
            if clean in name_map:
                return name_map[clean]
            raise ValueError(
                f"Unknown clearance level string: '{val}'. "
                f"Valid levels: 'public', 'internal', 'confidential', 'restricted'"
            )
        raise TypeError(f"Cannot parse clearance level from type: {type(val)}")

    @classmethod
    def get_authorized_levels(cls, user_level: Optional[Union[str, int, "ClearanceLevel"]] = None) -> List[int]:
        """
        Returns all clearance levels (integers) that a user with user_level is authorized to view.
        e.g., CONFIDENTIAL (2) -> [0, 1, 2] (PUBLIC, INTERNAL, CONFIDENTIAL).
        """
        if user_level is None:
            return [cls.PUBLIC.value]
        lvl = cls.from_string(user_level)
        return [item.value for item in cls if item.value <= lvl.value]

    def authorized_levels(self) -> List[int]:
        return [item.value for item in ClearanceLevel if item.value <= self.value]


class PlanTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"

    @classmethod
    def from_string(cls, val: Union[str, "PlanTier"]) -> "PlanTier":
        if isinstance(val, PlanTier):
            return val
        if isinstance(val, str):
            clean = val.strip().lower()
            if clean in ("free", "community"):
                return cls.FREE
            elif clean in ("pro", "professional"):
                return cls.PRO
            elif clean in ("enterprise", "ultimate", "sovereign"):
                return cls.ENTERPRISE
            raise ValueError(f"Unknown plan tier: '{val}'. Valid tiers: 'free', 'pro', 'enterprise'")
        raise TypeError(f"Cannot parse plan tier from type: {type(val)}")


class PlanLimitExceededError(PermissionError):
    """Raised when an operation exceeds the document volume cap of the plan tier."""
    pass


class FeatureNotAllowedError(PermissionError):
    """Raised when an operation attempts to access a feature not unlocked by the plan tier."""
    pass


class PlanEnforcer:
    """
    Enforces multi-tier resource limits and feature gating.

    Tier Specifications:
    - free:
        * Gated to Level 1 ('flash_needle')
        * CPU inference only
        * Document ingestion capped at 100 documents
    - pro:
        * Unlocks Level 2 ('relational_audit')
        * Unlocks Level 3 ('deep_synthesis' / RAPTOR)
        * Unlocks Multimodal CLIP ('include_visual_plates')
        * Unlimited document ingestion
    - enterprise:
        * Unlocks all above
        * Unlocks distributed cluster delegation
        * Unlimited document ingestion
    """

    VOLUME_CAPS: Dict[PlanTier, Optional[int]] = {
        PlanTier.FREE: 100,
        PlanTier.PRO: None,
        PlanTier.ENTERPRISE: None,
    }

    ALLOWED_DEPTHS: Dict[PlanTier, Set[str]] = {
        PlanTier.FREE: {"flash_needle"},
        PlanTier.PRO: {"flash_needle", "relational_audit", "deep_synthesis"},
        PlanTier.ENTERPRISE: {"flash_needle", "relational_audit", "deep_synthesis"},
    }

    ALLOWED_FEATURES: Dict[PlanTier, Set[str]] = {
        PlanTier.FREE: {"cpu_inference", "flash_needle"},
        PlanTier.PRO: {
            "cpu_inference",
            "cuda",
            "flash_needle",
            "relational_audit",
            "deep_synthesis",
            "raptor",
            "raptor_clustering",
            "graph_traversal",
            "multimodal_clip",
            "visual_plates",
        },
        PlanTier.ENTERPRISE: {
            "cpu_inference",
            "cuda",
            "flash_needle",
            "relational_audit",
            "deep_synthesis",
            "raptor",
            "raptor_clustering",
            "graph_traversal",
            "multimodal_clip",
            "visual_plates",
            "cluster_delegation",
            "distributed_cluster",
            "custom_ontologies",
        },
    }

    FEATURE_ALIASES: Dict[str, List[str]] = {
        "multimodal_clip": ["multimodal_clip", "visual_plates"],
        "raptor_synthesis": ["raptor_synthesis", "raptor", "raptor_clustering", "deep_synthesis"],
        "gpu_delegation": ["gpu_delegation", "cuda", "gpu", "cluster_delegation", "distributed_cluster"],
        "custom_ontology": ["custom_ontology", "custom_ontologies"],
    }

    def __init__(
        self,
        plan: Union[str, PlanTier] = PlanTier.FREE,
        tier: Optional[Union[str, PlanTier]] = None,
        current_doc_count: int = 0,
        license: Optional[Union[LicenseData, str, Path]] = None,
        public_key_pem: Optional[bytes] = None,
    ):
        chosen_plan = tier if tier is not None else plan
        self.plan = PlanTier.from_string(chosen_plan)
        self.current_doc_count = current_doc_count
        self.license: Optional[LicenseData] = None
        self._max_documents_override: Optional[int] = None
        self.max_seats: int = 1 if self.plan == PlanTier.FREE else (10 if self.plan == PlanTier.PRO else 100)

        if license is not None:
            if isinstance(license, LicenseData):
                self.apply_license(license)
            elif isinstance(license, (str, Path)):
                if public_key_pem is None:
                    raise ValueError("public_key_pem is required when initializing PlanEnforcer with a license string or file path")
                p = Path(license)
                if p.is_file():
                    self.load_license_file(p, public_key_pem)
                else:
                    self.load_license_token(str(license), public_key_pem)

    def apply_license(self, license_data: LicenseData) -> None:
        """Applies a validated LicenseData instance, overriding tier, volume caps, seats, and features."""
        self.license = license_data
        self.plan = PlanTier.from_string(license_data.plan_tier)
        self._max_documents_override = license_data.max_documents
        self.max_seats = license_data.max_seats

    def load_license_token(self, token: str, public_key_pem: bytes, check_expiry: bool = True) -> LicenseData:
        """Verifies and applies a signed base64 license token string."""
        license_data = SovereignLicenseManager.verify_license(token, public_key_pem, check_expiry=check_expiry)
        self.apply_license(license_data)
        return license_data

    def load_license_file(self, path: Union[str, Path], public_key_pem: bytes, check_expiry: bool = True) -> LicenseData:
        """Verifies and applies an offline license file from disk."""
        license_data = SovereignLicenseManager.load_license_file(path, public_key_pem, check_expiry=check_expiry)
        self.apply_license(license_data)
        return license_data

    @classmethod
    def from_license(cls, license_data: LicenseData, current_doc_count: int = 0) -> "PlanEnforcer":
        enforcer = cls(plan=license_data.plan_tier, current_doc_count=current_doc_count)
        enforcer.apply_license(license_data)
        return enforcer

    @classmethod
    def from_license_file(
        cls,
        path: Union[str, Path],
        public_key_pem: bytes,
        current_doc_count: int = 0,
        check_expiry: bool = True,
    ) -> "PlanEnforcer":
        data = SovereignLicenseManager.load_license_file(path, public_key_pem, check_expiry=check_expiry)
        return cls.from_license(data, current_doc_count=current_doc_count)

    @property
    def max_documents(self) -> Optional[int]:
        if self.license is not None:
            return self.license.max_documents
        return self.VOLUME_CAPS[self.plan]

    def can_use_device(self, device: str) -> bool:
        clean = device.strip().lower()
        if clean in ("cuda", "gpu", "mps"):
            if self.license and self.license.features:
                if "gpu_delegation" in self.license.features:
                    return bool(self.license.features["gpu_delegation"])
                if "cuda" in self.license.features:
                    return bool(self.license.features["cuda"])
            return self.plan in (PlanTier.PRO, PlanTier.ENTERPRISE)
        return True

    def can_ingest(self, current_doc_count: Optional[int] = None) -> bool:
        cap = self.max_documents
        if cap is None:
            return True
        count = self.current_doc_count if current_doc_count is None else current_doc_count
        return count < cap

    def assert_can_ingest(self, count_to_add: int = 1) -> None:
        cap = self.max_documents
        if cap is not None and (self.current_doc_count + count_to_add) > cap:
            raise PlanLimitExceededError(
                f"Document cap exceeded: {self.current_doc_count + count_to_add} > {cap}"
            )

    def validate_ingest(self, current_doc_count: int) -> None:
        if not self.can_ingest(current_doc_count):
            raise PlanLimitExceededError(
                f"Document ingestion cap reached for '{self.plan.value}' plan "
                f"({current_doc_count}/{self.max_documents} docs). "
                f"Upgrade to 'pro' or 'enterprise' for unlimited volume."
            )

    def is_depth_allowed(self, depth: str) -> bool:
        clean = depth.strip().lower()
        if self.license and self.license.features:
            if clean == "deep_synthesis" and "raptor_synthesis" in self.license.features:
                if not self.license.features["raptor_synthesis"]:
                    return False
                return True
            if clean == "relational_audit" and self.license.features.get("raptor_synthesis") is True:
                return True
        return clean in self.ALLOWED_DEPTHS[self.plan]

    def validate_depth(self, depth: str) -> None:
        clean = depth.strip().lower()
        if not self.is_depth_allowed(clean):
            raise FeatureNotAllowedError(
                f"Analytical depth '{depth}' is not available on '{self.plan.value}' plan. "
                f"Allowed depths: {sorted(list(self.ALLOWED_DEPTHS[self.plan]))}. "
                f"Upgrade to 'pro' to unlock Level 2 (relational_audit) and Level 3 (deep_synthesis)."
            )

    def assert_depth_allowed(self, depth: str) -> None:
        self.validate_depth(depth)

    def is_feature_allowed(self, feature: str) -> bool:
        clean = feature.strip().lower()
        if self.license and self.license.features:
            if clean in self.license.features:
                return bool(self.license.features[clean])
            for canonical, aliases in self.FEATURE_ALIASES.items():
                if clean == canonical or clean in aliases:
                    if canonical in self.license.features:
                        return bool(self.license.features[canonical])
                    for a in aliases:
                        if a in self.license.features:
                            return bool(self.license.features[a])
        return clean in self.ALLOWED_FEATURES[self.plan]

    def validate_feature(self, feature: str) -> None:
        clean = feature.strip().lower()
        if not self.is_feature_allowed(clean):
            raise FeatureNotAllowedError(
                f"Feature '{feature}' is not available on '{self.plan.value}' plan. "
                f"Upgrade to 'pro' or 'enterprise' to unlock this capability."
            )

    def assert_feature_allowed(self, feature: str) -> None:
        self.validate_feature(feature)
