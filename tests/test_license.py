#!/usr/bin/env python3
"""
Comprehensive Automated Test Suite for Aegis Offline Cryptographic Licensing Engine.
Verifies Ed25519 signing, verification, tampering resistance, expiration, and PlanEnforcer integration.
"""

import base64
import datetime
import json
import tempfile
import time
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

# Ensure aegis-sovereign-appliance is in sys.path
repo_root = Path(__file__).resolve().parent.parent
import sys
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from core.license import (
    LicenseData,
    SovereignLicenseManager,
    LicenseError,
    LicenseExpiredError,
    InvalidLicenseSignatureError,
    LicenseTamperedError,
    LicenseNotFoundError,
)
from core.security import (
    PlanTier,
    PlanEnforcer,
    PlanLimitExceededError,
    FeatureNotAllowedError,
)


@pytest.fixture
def keypair():
    """Generates a fresh test Ed25519 keypair."""
    priv_pem, pub_pem = SovereignLicenseManager.generate_keypair()
    return priv_pem, pub_pem


@pytest.fixture
def sample_license_data():
    """Returns sample valid Pro tier license data."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return LicenseData(
        license_id="aegis-pro-test-001",
        customer_id="Acme Medical Diagnostics",
        plan_tier="pro",
        issued_at=now.isoformat(),
        expires_at=(now + datetime.timedelta(days=365)).isoformat(),
        max_seats=15,
        max_documents=None,
        features={
            "multimodal_clip": True,
            "raptor_synthesis": True,
            "gpu_delegation": True,
            "custom_ontology": False,
        },
    )


# ==============================================================================
# 1. Key Generation Tests
# ==============================================================================

def test_keypair_generation(keypair):
    """Verifies that generated keypairs conform to Ed25519 PKCS8 and SubjectPublicKeyInfo PEM formats."""
    priv_pem, pub_pem = keypair

    assert priv_pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    assert priv_pem.endswith(b"-----END PRIVATE KEY-----\n")
    assert pub_pem.startswith(b"-----BEGIN PUBLIC KEY-----")
    assert pub_pem.endswith(b"-----END PUBLIC KEY-----\n")

    # Ensure keys reload properly
    priv_obj = serialization.load_pem_private_key(priv_pem, password=None)
    pub_obj = serialization.load_pem_public_key(pub_pem)

    assert isinstance(priv_obj, ed25519.Ed25519PrivateKey)
    assert isinstance(pub_obj, ed25519.Ed25519PublicKey)


# ==============================================================================
# 2. License Signing and Verification Tests
# ==============================================================================

def test_license_signing_and_verification(keypair, sample_license_data):
    """Verifies that signed licenses can be verified and parsed accurately."""
    priv_pem, pub_pem = keypair

    token = SovereignLicenseManager.sign_license(sample_license_data, priv_pem)
    assert isinstance(token, str)
    assert len(token) > 100

    verified_data = SovereignLicenseManager.verify_license(token, pub_pem)

    assert verified_data.license_id == sample_license_data.license_id
    assert verified_data.customer_id == sample_license_data.customer_id
    assert verified_data.plan_tier == "pro"
    assert verified_data.max_seats == 15
    assert verified_data.max_documents is None
    assert verified_data.features["multimodal_clip"] is True
    assert verified_data.features["gpu_delegation"] is True
    assert verified_data.features["custom_ontology"] is False
    assert verified_data.is_expired() is False


def test_perpetual_license(keypair):
    """Verifies that a perpetual license (expires_at=None) verifies indefinitely."""
    priv_pem, pub_pem = keypair
    now = datetime.datetime.now(datetime.timezone.utc)

    lic = LicenseData(
        license_id="aegis-ent-perpetual",
        customer_id="National Archives",
        plan_tier="enterprise",
        issued_at=now.isoformat(),
        expires_at=None,
        max_seats=500,
        max_documents=None,
        features={
            "multimodal_clip": True,
            "raptor_synthesis": True,
            "gpu_delegation": True,
            "custom_ontology": True,
        },
    )

    token = SovereignLicenseManager.sign_license(lic, priv_pem)
    verified = SovereignLicenseManager.verify_license(token, pub_pem)

    assert verified.expires_at is None
    assert verified.is_expired() is False


# ==============================================================================
# 3. Tamper Resistance Tests
# ==============================================================================

def test_tamper_resistance_payload_modification(keypair, sample_license_data):
    """Verifies that tampering with any payload field triggers signature validation failure."""
    priv_pem, pub_pem = keypair

    token = SovereignLicenseManager.sign_license(sample_license_data, priv_pem)

    # Decode envelope
    raw_envelope = json.loads(base64.b64decode(token.encode('utf-8')).decode('utf-8'))

    # Maliciously escalate tier from pro to enterprise
    raw_envelope["payload"]["plan_tier"] = "enterprise"

    # Re-encode tampered envelope
    tampered_bytes = json.dumps(raw_envelope, sort_keys=True, separators=(',', ':')).encode('utf-8')
    tampered_token = base64.b64encode(tampered_bytes).decode('utf-8')

    with pytest.raises(InvalidLicenseSignatureError) as exc_info:
        SovereignLicenseManager.verify_license(tampered_token, pub_pem)

    assert "tampering detected" in str(exc_info.value).lower() or "verification failed" in str(exc_info.value).lower()


def test_tamper_resistance_signature_corruption(keypair, sample_license_data):
    """Verifies that modifying the cryptographic signature itself fails validation."""
    priv_pem, pub_pem = keypair

    token = SovereignLicenseManager.sign_license(sample_license_data, priv_pem)
    raw_envelope = json.loads(base64.b64decode(token.encode('utf-8')).decode('utf-8'))

    # Corrupt the signature bytes
    sig_bytes = bytearray(base64.b64decode(raw_envelope["signature"]))
    sig_bytes[0] ^= 0xFF
    raw_envelope["signature"] = base64.b64encode(bytes(sig_bytes)).decode('utf-8')

    corrupted_bytes = json.dumps(raw_envelope, sort_keys=True, separators=(',', ':')).encode('utf-8')
    corrupted_token = base64.b64encode(corrupted_bytes).decode('utf-8')

    with pytest.raises(InvalidLicenseSignatureError):
        SovereignLicenseManager.verify_license(corrupted_token, pub_pem)


def test_tamper_resistance_wrong_public_key(sample_license_data):
    """Verifies that verifying with a foreign public key fails."""
    priv_pem1, _ = SovereignLicenseManager.generate_keypair()
    _, pub_pem2 = SovereignLicenseManager.generate_keypair()

    token = SovereignLicenseManager.sign_license(sample_license_data, priv_pem1)

    with pytest.raises(InvalidLicenseSignatureError):
        SovereignLicenseManager.verify_license(token, pub_pem2)


def test_malformed_token_handling(keypair):
    """Verifies graceful rejection of malformed base64 or garbage tokens."""
    _, pub_pem = keypair

    with pytest.raises(InvalidLicenseSignatureError):
        SovereignLicenseManager.verify_license("not_base64_garbage!", pub_pem)

    with pytest.raises(InvalidLicenseSignatureError):
        SovereignLicenseManager.verify_license("", pub_pem)


# ==============================================================================
# 4. Expiration Tests
# ==============================================================================

def test_expiration_rejection(keypair):
    """Verifies that licenses with past expiration timestamps raise LicenseExpiredError."""
    priv_pem, pub_pem = keypair
    now = datetime.datetime.now(datetime.timezone.utc)
    past_date = now - datetime.timedelta(days=10)

    expired_license = LicenseData(
        license_id="aegis-expired-001",
        customer_id="Former Client",
        plan_tier="pro",
        issued_at=(now - datetime.timedelta(days=400)).isoformat(),
        expires_at=past_date.isoformat(),
        max_seats=5,
        max_documents=None,
    )

    token = SovereignLicenseManager.sign_license(expired_license, priv_pem)

    # Strict verification should fail with LicenseExpiredError
    with pytest.raises(LicenseExpiredError) as exc_info:
        SovereignLicenseManager.verify_license(token, pub_pem)

    assert "expired on" in str(exc_info.value)

    # Verification with check_expiry=False permits inspection
    inspected = SovereignLicenseManager.verify_license(token, pub_pem, check_expiry=False)
    assert inspected.license_id == "aegis-expired-001"
    assert inspected.is_expired() is True


# ==============================================================================
# 5. File I/O Tests
# ==============================================================================

def test_license_file_save_and_load(keypair, sample_license_data):
    """Verifies saving to and loading from `.aegis` files."""
    priv_pem, pub_pem = keypair
    token = SovereignLicenseManager.sign_license(sample_license_data, priv_pem)

    with tempfile.TemporaryDirectory() as tmp_dir:
        lic_file = Path(tmp_dir) / "test_client.aegis"
        SovereignLicenseManager.save_license_file(token, lic_file)

        assert lic_file.is_file()
        loaded = SovereignLicenseManager.load_license_file(lic_file, pub_pem)

        assert loaded.customer_id == sample_license_data.customer_id
        assert loaded.license_id == sample_license_data.license_id


def test_missing_license_file_raises(keypair):
    """Verifies that non-existent license paths raise LicenseNotFoundError."""
    _, pub_pem = keypair
    with pytest.raises(LicenseNotFoundError):
        SovereignLicenseManager.load_license_file("/non/existent/path/missing.aegis", pub_pem)


# ==============================================================================
# 6. PlanEnforcer Integration Tests
# ==============================================================================

def test_plan_enforcer_license_upgrade_from_free(keypair):
    """Verifies that applying a Pro license to a Free PlanEnforcer unlocks Pro capabilities."""
    priv_pem, pub_pem = keypair

    # Initial state: Free tier with 100 doc cap
    enforcer = PlanEnforcer(plan="free", current_doc_count=100)
    assert enforcer.can_ingest() is False
    assert enforcer.is_depth_allowed("deep_synthesis") is False
    assert enforcer.can_use_device("cuda") is False

    # Mint and apply a Pro license
    now = datetime.datetime.now(datetime.timezone.utc)
    pro_lic = LicenseData(
        license_id="aegis-pro-upgrade",
        customer_id="Scaling Law Firm",
        plan_tier="pro",
        issued_at=now.isoformat(),
        expires_at=(now + datetime.timedelta(days=365)).isoformat(),
        max_seats=20,
        max_documents=None,
        features={
            "multimodal_clip": True,
            "raptor_synthesis": True,
            "gpu_delegation": True,
            "custom_ontology": False,
        },
    )
    token = SovereignLicenseManager.sign_license(pro_lic, priv_pem)

    enforcer.load_license_token(token, pub_pem)

    # Post-upgrade verification
    assert enforcer.plan == PlanTier.PRO
    assert enforcer.max_documents is None
    assert enforcer.can_ingest() is True
    assert enforcer.is_depth_allowed("deep_synthesis") is True
    assert enforcer.can_use_device("cuda") is True
    assert enforcer.max_seats == 20


def test_plan_enforcer_feature_overrides(keypair):
    """Verifies that license-level feature flags strictly override tier defaults."""
    priv_pem, pub_pem = keypair
    now = datetime.datetime.now(datetime.timezone.utc)

    # Create a Pro license where GPU delegation is explicitly disabled,
    # but custom ontology (normally Enterprise-only) is enabled.
    lic = LicenseData(
        license_id="aegis-custom-pro",
        customer_id="Hybrid Enterprise Tenant",
        plan_tier="pro",
        issued_at=now.isoformat(),
        expires_at=(now + datetime.timedelta(days=365)).isoformat(),
        max_seats=10,
        max_documents=None,
        features={
            "multimodal_clip": True,
            "raptor_synthesis": True,
            "gpu_delegation": False,  # Disabled override
            "custom_ontology": True,   # Enabled override
        },
    )
    token = SovereignLicenseManager.sign_license(lic, priv_pem)

    enforcer = PlanEnforcer(plan="pro")
    enforcer.load_license_token(token, pub_pem)

    # GPU should be forbidden despite being on Pro tier
    assert enforcer.can_use_device("cuda") is False
    assert enforcer.is_feature_allowed("gpu_delegation") is False

    # Custom ontology should be unlocked despite not being Enterprise
    assert enforcer.is_feature_allowed("custom_ontology") is True
    assert enforcer.is_feature_allowed("custom_ontologies") is True


def test_plan_enforcer_custom_document_cap(keypair):
    """Verifies that custom document volume caps in licenses are enforced."""
    priv_pem, pub_pem = keypair
    now = datetime.datetime.now(datetime.timezone.utc)

    # Enterprise tier, but capped at 250 documents by license
    lic = LicenseData(
        license_id="aegis-ent-capped",
        customer_id="Pilot Program Org",
        plan_tier="enterprise",
        issued_at=now.isoformat(),
        expires_at=(now + datetime.timedelta(days=90)).isoformat(),
        max_seats=50,
        max_documents=250,
    )
    token = SovereignLicenseManager.sign_license(lic, priv_pem)

    enforcer = PlanEnforcer(plan="enterprise", current_doc_count=248)
    enforcer.load_license_token(token, pub_pem)

    assert enforcer.max_documents == 250
    assert enforcer.can_ingest() is True

    # Ingest 2 docs -> total 250
    enforcer.assert_can_ingest(count_to_add=2)

    # Attempt to ingest 3 docs -> total 251 > 250 -> should raise PlanLimitExceededError
    with pytest.raises(PlanLimitExceededError):
        enforcer.assert_can_ingest(count_to_add=3)


def test_plan_enforcer_from_license_file_initialization(keypair, sample_license_data):
    """Verifies instantiating PlanEnforcer directly from license file path."""
    priv_pem, pub_pem = keypair
    token = SovereignLicenseManager.sign_license(sample_license_data, priv_pem)

    with tempfile.TemporaryDirectory() as tmp_dir:
        lic_file = Path(tmp_dir) / "appliance.aegis"
        SovereignLicenseManager.save_license_file(token, lic_file)

        # Directly initialize enforcer with license path
        enforcer = PlanEnforcer(license=lic_file, public_key_pem=pub_pem)

        assert enforcer.plan == PlanTier.PRO
        assert enforcer.license.customer_id == sample_license_data.customer_id
        assert enforcer.can_use_device("cuda") is True


# ==============================================================================
# 7. Verification Performance Budget Benchmark (<1ms)
# ==============================================================================

def test_verification_latency_budget(keypair, sample_license_data):
    """Verifies that license verification finishes in well under 1ms (startup budget)."""
    priv_pem, pub_pem = keypair
    token = SovereignLicenseManager.sign_license(sample_license_data, priv_pem)

    # Warm up
    SovereignLicenseManager.verify_license(token, pub_pem)

    iterations = 50
    start = time.perf_counter()
    for _ in range(iterations):
        SovereignLicenseManager.verify_license(token, pub_pem)
    duration = time.perf_counter() - start

    avg_latency_ms = (duration / iterations) * 1000.0
    print(f"\n[BENCHMARK] Average Ed25519 offline license verification latency: {avg_latency_ms:.3f} ms")

    # Constraint: Must be strictly under 1.0 ms
    assert avg_latency_ms < 1.0, f"Verification too slow: {avg_latency_ms:.3f} ms >= 1.0 ms"
