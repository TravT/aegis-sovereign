#!/usr/bin/env python3
"""
Aegis Sovereign Knowledge Appliance — Offline License Generator & Operations CLI.

Authoritative CLI utility for Sales Engineering and Operations to:
1. Generate air-gapped Ed25519 asymmetric keypairs.
2. Mint cryptographically signed offline `.aegis` license certificates.
3. Inspect and verify offline license tokens without network connectivity.

Usage:
  # Generate Ed25519 signing keypair:
  python3 tools/license_generator.py --gen-keys

  # Mint a 365-day Pro license:
  python3 tools/license_generator.py --customer "Hospital Network" --tier pro --days 365 --output hospital.aegis

  # Mint a Perpetual Enterprise license with custom seat & document caps:
  python3 tools/license_generator.py --customer "State Ministry of Health" --tier enterprise --perpetual --seats 250 --max-docs 5000000 --output gov.aegis

  # Inspect an existing license file:
  python3 tools/license_generator.py --inspect hospital.aegis

  # Verify an existing license file with public key:
  python3 tools/license_generator.py --verify hospital.aegis --public-key public_key.pem
"""

import argparse
import datetime
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to sys.path to access core module
repo_root = Path(__file__).resolve().parent.parent
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


def get_default_features_for_tier(tier: str) -> Dict[str, bool]:
    clean = tier.strip().lower()
    if clean in ("enterprise", "ultimate", "sovereign"):
        return {
            "multimodal_clip": True,
            "raptor_synthesis": True,
            "gpu_delegation": True,
            "custom_ontology": True,
        }
    elif clean in ("pro", "professional"):
        return {
            "multimodal_clip": True,
            "raptor_synthesis": True,
            "gpu_delegation": True,
            "custom_ontology": False,
        }
    else:  # free / community
        return {
            "multimodal_clip": False,
            "raptor_synthesis": False,
            "gpu_delegation": False,
            "custom_ontology": False,
        }


def get_default_seats_for_tier(tier: str) -> int:
    clean = tier.strip().lower()
    if clean in ("enterprise", "ultimate", "sovereign"):
        return 100
    elif clean in ("pro", "professional"):
        return 10
    return 1


def get_default_max_docs_for_tier(tier: str) -> Optional[int]:
    clean = tier.strip().lower()
    if clean in ("free", "community"):
        return 100
    return None


def find_key_file(specified_path: Optional[str], default_names: list[str]) -> Optional[Path]:
    if specified_path:
        p = Path(specified_path)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Key file not found at specified path: {specified_path}")

    # Check common locations
    candidates = [Path.cwd(), Path.cwd() / "keys", repo_root / "keys", repo_root]
    for d in candidates:
        for name in default_names:
            candidate = d / name
            if candidate.is_file():
                return candidate
    return None


def cmd_gen_keys(args: argparse.Namespace) -> int:
    key_dir = Path(args.key_dir) if args.key_dir else Path.cwd()
    key_dir.mkdir(parents=True, exist_ok=True)

    priv_path = Path(args.private_key_out) if args.private_key_out else key_dir / "private_key.pem"
    pub_path = Path(args.public_key_out) if args.public_key_out else key_dir / "public_key.pem"

    if priv_path.exists() and not args.force:
        print(f"[-] Error: Private key already exists at {priv_path}. Use --force to overwrite.", file=sys.stderr)
        return 1
    if pub_path.exists() and not args.force:
        print(f"[-] Error: Public key already exists at {pub_path}. Use --force to overwrite.", file=sys.stderr)
        return 1

    private_pem, public_pem = SovereignLicenseManager.generate_keypair()
    priv_path.write_bytes(private_pem)
    # Set private key file permissions strictly to 0600
    priv_path.chmod(0o600)
    pub_path.write_bytes(public_pem)

    print("================================================================================")
    print("🏛️  Aegis Sovereign Appliance — Ed25519 Keypair Generated Successfully")
    print("================================================================================")
    print(f"Private Key (KEEP SECRET, 0600): {priv_path.resolve()}")
    print(f"Public Key  (EMBED IN APPLIANCE): {pub_path.resolve()}")
    print("Zero-cloud egress guarantee: Keep private_key.pem air-gapped on sales ops machine.")
    return 0


def cmd_mint_license(args: argparse.Namespace) -> int:
    if not args.customer:
        print("[-] Error: --customer is required to mint a license.", file=sys.stderr)
        return 1

    tier = args.tier.lower()
    if tier not in ("free", "pro", "enterprise"):
        print(f"[-] Error: Invalid tier '{tier}'. Must be 'free', 'pro', or 'enterprise'.", file=sys.stderr)
        return 1

    # Locate private key
    priv_key_path = find_key_file(args.private_key, ["private_key.pem", "ed25519_private.pem"])
    if not priv_key_path:
        print("[-] Error: Private key file not found. Run --gen-keys or specify --private-key <path>", file=sys.stderr)
        return 1

    priv_key_bytes = priv_key_path.read_bytes()

    # Determine dates
    now = datetime.datetime.now(datetime.timezone.utc)
    issued_at = now.isoformat()

    if args.perpetual:
        expires_at = None
    elif args.expires_at:
        try:
            exp_dt = datetime.datetime.fromisoformat(args.expires_at)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
            expires_at = exp_dt.isoformat()
        except ValueError as e:
            print(f"[-] Error parsing --expires-at ISO timestamp: {e}", file=sys.stderr)
            return 1
    else:
        days = int(args.days)
        exp_dt = now + datetime.timedelta(days=days)
        expires_at = exp_dt.isoformat()

    # Determine seats & docs
    seats = int(args.seats) if args.seats is not None else get_default_seats_for_tier(tier)
    max_docs = int(args.max_docs) if args.max_docs is not None else get_default_max_docs_for_tier(tier)

    # Features
    features = get_default_features_for_tier(tier)
    if args.features:
        pairs = args.features.split(",")
        for pair in pairs:
            if "=" in pair:
                k, v = pair.split("=", 1)
                features[k.strip()] = v.strip().lower() in ("true", "1", "yes", "on")

    # Command line feature toggle overrides
    if args.enable_gpu:
        features["gpu_delegation"] = True
    if args.disable_gpu:
        features["gpu_delegation"] = False
    if args.enable_multimodal:
        features["multimodal_clip"] = True
    if args.disable_multimodal:
        features["multimodal_clip"] = False
    if args.enable_raptor:
        features["raptor_synthesis"] = True
    if args.disable_raptor:
        features["raptor_synthesis"] = False
    if args.enable_ontology:
        features["custom_ontology"] = True
    if args.disable_ontology:
        features["custom_ontology"] = False

    lic_id = args.license_id or f"aegis-{tier[:3]}-{uuid.uuid4().hex[:12]}"

    license_data = LicenseData(
        license_id=lic_id,
        customer_id=args.customer,
        plan_tier=tier,
        issued_at=issued_at,
        expires_at=expires_at,
        max_seats=seats,
        max_documents=max_docs,
        features=features,
    )

    signed_token = SovereignLicenseManager.sign_license(license_data, priv_key_bytes)

    out_path = Path(args.output) if args.output else Path(f"{lic_id}.aegis")
    SovereignLicenseManager.save_license_file(signed_token, out_path)

    print("================================================================================")
    print("📜  Aegis Sovereign Appliance — Offline License Minted Successfully")
    print("================================================================================")
    print(f"License ID   : {lic_id}")
    print(f"Customer     : {args.customer}")
    print(f"Plan Tier    : {tier.upper()}")
    print(f"Issued At    : {issued_at}")
    print(f"Expires At   : {expires_at or 'PERPETUAL (Never Expires)'}")
    print(f"Max Seats    : {seats}")
    print(f"Max Docs     : {'Unlimited' if max_docs is None else f'{max_docs:,} documents'}")
    print("Features     :")
    for feat_k, feat_v in sorted(features.items()):
        status_icon = "✅" if feat_v else "❌"
        print(f"  {status_icon} {feat_k}: {feat_v}")
    print(f"\nLicense File : {out_path.resolve()}")
    print(f"Token Length : {len(signed_token)} characters (Base64 Ed25519 signed)")
    return 0


def cmd_verify_license(args: argparse.Namespace) -> int:
    lic_path = Path(args.verify)
    if not lic_path.is_file():
        print(f"[-] Error: License file not found: {lic_path}", file=sys.stderr)
        return 1

    pub_key_path = find_key_file(args.public_key, ["public_key.pem", "ed25519_public.pem"])
    if not pub_key_path:
        print("[-] Error: Public key file not found. Specify --public-key <path>", file=sys.stderr)
        return 1

    pub_key_bytes = pub_key_path.read_bytes()

    try:
        data = SovereignLicenseManager.load_license_file(lic_path, pub_key_bytes)
        print("================================================================================")
        print("🔒 Cryptographic Verification: PASSED (Ed25519 Signature Valid)")
        print("================================================================================")
        print(json.dumps(data.to_dict(), indent=2))
        return 0
    except LicenseTamperedError as e:
        print(f"❌ TAMPER DETECTED: {e}", file=sys.stderr)
        return 2
    except LicenseExpiredError as e:
        print(f"⚠️  LICENSE EXPIRED: {e}", file=sys.stderr)
        return 3
    except InvalidLicenseSignatureError as e:
        print(f"❌ INVALID SIGNATURE: {e}", file=sys.stderr)
        return 4
    except Exception as e:
        print(f"[-] Verification Error: {e}", file=sys.stderr)
        return 5


def cmd_inspect_license(args: argparse.Namespace) -> int:
    import base64
    lic_path = Path(args.inspect)
    if not lic_path.is_file():
        print(f"[-] Error: License file not found: {lic_path}", file=sys.stderr)
        return 1

    raw_token = lic_path.read_text(encoding="utf-8").strip()
    try:
        envelope_bytes = base64.b64decode(raw_token.encode('utf-8'))
        envelope = json.loads(envelope_bytes.decode('utf-8'))
        print("================================================================================")
        print(f"📋 Inspected License Envelope: {lic_path.name}")
        print("================================================================================")
        print(f"Algorithm : {envelope.get('algorithm', 'Ed25519')}")
        print(f"Version   : {envelope.get('version', 1)}")
        print("\nPayload:")
        print(json.dumps(envelope.get("payload", {}), indent=2))
        print(f"\nSignature : {envelope.get('signature', '')[:32]}... (truncated)")
        return 0
    except Exception as e:
        print(f"[-] Failed to decode license envelope: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aegis Sovereign Knowledge Appliance Offline License Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_argument_group("Operations")
    group.add_argument("--gen-keys", action="store_true", help="Generate Ed25519 private and public keypair")
    group.add_argument("--verify", type=str, metavar="PATH", help="Verify a signed .aegis license file")
    group.add_argument("--inspect", type=str, metavar="PATH", help="Inspect .aegis license payload without verifying")

    key_group = parser.add_argument_group("Key Options")
    key_group.add_argument("--key-dir", type=str, help="Directory to save or locate keys")
    key_group.add_argument("--private-key", type=str, help="Path to Ed25519 private key PEM")
    key_group.add_argument("--public-key", type=str, help="Path to Ed25519 public key PEM")
    key_group.add_argument("--private-key-out", type=str, help="Output path for generated private key")
    key_group.add_argument("--public-key-out", type=str, help="Output path for generated public key")
    key_group.add_argument("--force", action="store_true", help="Overwrite existing key files if generating")

    mint_group = parser.add_argument_group("Minting Parameters")
    mint_group.add_argument("--customer", "--customer-id", type=str, help="Customer or organization name")
    mint_group.add_argument("--tier", "--plan", type=str, default="pro", choices=["free", "pro", "enterprise"], help="Plan tier (free, pro, enterprise)")
    mint_group.add_argument("--license-id", type=str, help="Custom license ID string")
    mint_group.add_argument("--days", type=int, default=365, help="Validity period in days from now (default: 365)")
    mint_group.add_argument("--expires-at", type=str, help="Explicit ISO8601 expiration date")
    mint_group.add_argument("--perpetual", action="store_true", help="Issue perpetual license (no expiry)")
    mint_group.add_argument("--seats", type=int, help="Maximum seats")
    mint_group.add_argument("--max-docs", type=int, help="Document volume limit (leave empty for tier default)")
    mint_group.add_argument("--features", type=str, help="Comma-separated key=val feature flags")
    mint_group.add_argument("--output", "-o", type=str, help="Target output file path (e.g. license.aegis)")

    # Direct feature toggles
    feat_group = parser.add_argument_group("Feature Toggles")
    feat_group.add_argument("--enable-gpu", action="store_true", help="Enable GPU delegation")
    feat_group.add_argument("--disable-gpu", action="store_true", help="Disable GPU delegation")
    feat_group.add_argument("--enable-multimodal", action="store_true", help="Enable Multimodal CLIP visual plates")
    feat_group.add_argument("--disable-multimodal", action="store_true", help="Disable Multimodal CLIP")
    feat_group.add_argument("--enable-raptor", action="store_true", help="Enable RAPTOR hierarchical synthesis")
    feat_group.add_argument("--disable-raptor", action="store_true", help="Disable RAPTOR hierarchical synthesis")
    feat_group.add_argument("--enable-ontology", action="store_true", help="Enable custom ontologies")
    feat_group.add_argument("--disable-ontology", action="store_true", help="Disable custom ontologies")

    args = parser.parse_args()

    if args.gen_keys:
        return cmd_gen_keys(args)
    elif args.verify:
        return cmd_verify_license(args)
    elif args.inspect:
        return cmd_inspect_license(args)
    elif args.customer:
        return cmd_mint_license(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
