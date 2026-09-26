#!/usr/bin/env python3
"""
Task 7.3: Synthetic Multi-Tier Benchmark Dataset Generator.
Aegis Sovereign Knowledge Appliance.

Generates deterministic, multi-format synthetic benchmark corpora across four
high-compliance enterprise verticals:
  1. Pharmacy (`LOTE-...`, `Portaria 344/98`, ANVISA controlled substance logs)
  2. Medical (`CID-10`, `CRM-SP`, ICU clinical discharge & protocol records)
  3. Telco (`3GPP TS 38.331`, `ALM-26235`, O-RAN / gNodeB hardware fault logs)
  4. Legal & Tax (`CNPJ`, `DARF`, `CPF`, judicial notices & corporate governance)

Supports three appliance licensing tiers (`free`, `pro`, `enterprise`):
  - `free`: Up to 100 documents across the 4 core domains + Prong 1/2 needle manifest.
  - `pro`: 5,000-document tier profile including `.hdx` & `.zip` virtual archive bundles
           and relational GraphRAG ground-truth edges.
  - `enterprise`: 25,000-document tier profile with stress-test multi-hop needles and
                  high-density archival containers.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import random
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


TIER_PROFILES: Dict[str, Dict[str, Any]] = {
    "free": {
        "tier_capacity": 100,
        "default_sample_count": 20,
        "include_archives": False,
        "include_graph_edges": False,
        "stress_test_needles": False,
    },
    "pro": {
        "tier_capacity": 5000,
        "default_sample_count": 32,
        "include_archives": True,
        "include_graph_edges": True,
        "stress_test_needles": False,
    },
    "enterprise": {
        "tier_capacity": 25000,
        "default_sample_count": 48,
        "include_archives": True,
        "include_graph_edges": True,
        "stress_test_needles": True,
    },
}


@dataclass
class GeneratedDocumentRecord:
    """Metadata and ground-truth identifiers for a single synthetic document."""

    doc_id: str
    filename: str
    domain: str
    file_format: str
    sha256: str
    exact_identifiers: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "domain": self.domain,
            "format": self.file_format,
            "sha256": self.sha256,
            "exact_identifiers": list(self.exact_identifiers),
            "entities": list(self.entities),
        }


class SyntheticCorpusGenerator:
    """
    Deterministic multi-tier benchmark dataset generator for POC evaluations
    and CI/CD regression benchmarking.
    """

    DOMAINS: List[str] = ["pharmacy", "medical", "telco", "legal_tax"]

    def __init__(self, seed: int = 42) -> None:
        self.seed = int(seed)
        self._rng = random.Random(self.seed)

    def _generate_domain_content(
        self,
        index: int,
        domain: str,
        tier: str,
    ) -> Dict[str, Any]:
        """Generates realistic domain text, exact identifiers, entities, and graph edges."""
        doc_id = f"DOC-{tier.upper()}-{index:05d}"

        if domain == "pharmacy":
            lote_id = f"LOTE-2026-{1000 + index:04d}X"
            anvisa_reg = f"MS-1.{1045 + (index % 800):04d}.{200 + (index % 700):03d}.001-{index % 9}"
            lab_name = f"BioFarma Soberana Laboratórios S.A. (Unidade {(index % 5) + 1})"
            substance = ["Clonazepam 2mg", "Morfina 10mg/mL", "Fentanila 0.05mg/mL", "Metilfenidato 10mg"][
                index % 4
            ]
            content = (
                f"BOLETIM DE RASTREABILIDADE E CONTROLE FARMACÊUTICO — {doc_id}\n"
                f"REGIME REGULATÓRIO: Portaria 344/98 (Lista A1/B1 - Psicotrópicos e Entorpecentes)\n"
                f"LABORATÓRIO FABRICANTE: {lab_name}\n"
                f"PRINCÍPIO ATIVO CONTROLADO: {substance}\n"
                f"IDENTIFICADOR DE LOTE INDUSTRIAL: {lote_id}\n"
                f"REGISTRO SANITÁRIO ANVISA: {anvisa_reg}\n"
                f"PARECER TÉCNICO DE QUALIDADE: Lote {lote_id} aprovado em ensaio de pureza cromatográfica "
                f"HPLC (99.84%) em conformidade estrita com a Portaria 344/98 da ANVISA. "
                f"Retenção obrigatória de receituário de controle especial por 2 (dois) anos.\n"
            )
            exact_ids = [lote_id, "Portaria 344/98", anvisa_reg]
            entities = [lab_name, substance, lote_id]
            edges = [
                {
                    "source": lab_name,
                    "target": lote_id,
                    "relation": "MANUFACTURED_BATCH",
                    "doc_id": doc_id,
                    "domain": domain,
                },
                {
                    "source": lote_id,
                    "target": "Portaria 344/98",
                    "relation": "GOVERNED_BY_REGULATION",
                    "doc_id": doc_id,
                    "domain": domain,
                },
            ]
            needle_q = f"Qual é o parecer técnico e o princípio ativo do lote {lote_id} sob a Portaria 344/98?"
            analytical_q = (
                f"Sintetize as exigências de retenção e conformidade cromatográfica da Portaria 344/98 "
                f"aplicáveis ao fabricante {lab_name}."
            )
            primary_id = lote_id
            id_type = "PHARMACY_BATCH_LOT"

        elif domain == "medical":
            cid_code = f"CID-10: I{20 + (index % 60):02d}.{index % 9}"
            crm_code = f"CRM-SP {110000 + index * 7}"
            physician = f"Dra. Helena Vasconcelos ({crm_code})"
            hospital = f"Hospital Sírio-Paulista — UTI Cardiológica Setor {(index % 4) + 1}"
            protocol_id = f"PROT-UTI-{202600 + index}"
            content = (
                f"PRONTUÁRIO DE ALTA E INTERVENÇÃO CLÍNICA — {doc_id}\n"
                f"UNIDADE HOSPITALAR: {hospital}\n"
                f"MÉDICO RESPONSÁVEL: {physician} | Registro Profissional: {crm_code}\n"
                f"DIAGNÓSTICO PRINCIPAL PADRONIZADO: {cid_code} (Síndrome Coronariana Aguda / Monitoramento)\n"
                f"PROTOCOLO ASSISTENCIAL: {protocol_id}\n"
                f"CONDUTA CLÍNICA: Paciente submetido a estabilização hemodinâmica segundo {protocol_id}, "
                f"com classificação diagnóstica {cid_code} atestada por {crm_code}. "
                f"Prescrição hospitalar auditada sem interações medicamentosas adversas.\n"
            )
            exact_ids = [cid_code, crm_code, protocol_id]
            entities = [physician, hospital, cid_code]
            edges = [
                {
                    "source": physician,
                    "target": hospital,
                    "relation": "ATTENDING_PHYSICIAN_AT",
                    "doc_id": doc_id,
                    "domain": domain,
                },
                {
                    "source": physician,
                    "target": cid_code,
                    "relation": "DIAGNOSED_CONDITION",
                    "doc_id": doc_id,
                    "domain": domain,
                },
            ]
            needle_q = f"Qual foi a conduta clínica atestada pelo registro {crm_code} para o diagnóstico {cid_code}?"
            analytical_q = (
                f"Como o protocolo {protocol_id} no {hospital} relaciona o diagnóstico {cid_code} "
                f"à estabilização hemodinâmica?"
            )
            primary_id = crm_code
            id_type = "MEDICAL_COUNCIL_ID"

        elif domain == "telco":
            alarm_id = f"ALM-{26235 + index}"
            spec_id = "3GPP TS 38.331"
            node_id = f"gNodeB-SP-NR{400 + index:03d}"
            hex_code = f"0x7F{index + 16:02X}A9C0"
            content = (
                f"TELEMETRIA DE INFRAESTRUTURA 5G SA / O-RAN — {doc_id}\n"
                f"ELEMENTO DE REDE: {node_id} | ESPECIFICAÇÃO BASE: {spec_id} (v17.4.0 RRC)\n"
                f"CÓDIGO DE ALARME CRÍTICO: {alarm_id} | REGISTRADOR DE FALHA: {hex_code}\n"
                f"DESCRIÇÃO DO EVENTO: Oscilação de sincronismo PTP IEEE 1588v2 detectada na interface eCPRI "
                f"do {node_id}, disparando o alarme {alarm_id} ({hex_code}).\n"
                f"PROCEDIMENTO DE MITIGAÇÃO ({spec_id}): Executar RRCReconfiguration com handover automático "
                f"para portadora n78 adjacente e recalibrar PLL do transceptor óptico.\n"
            )
            exact_ids = [alarm_id, spec_id, hex_code, node_id]
            entities = [node_id, alarm_id, spec_id]
            edges = [
                {
                    "source": node_id,
                    "target": alarm_id,
                    "relation": "EMITTED_CRITICAL_ALARM",
                    "doc_id": doc_id,
                    "domain": domain,
                },
                {
                    "source": alarm_id,
                    "target": spec_id,
                    "relation": "REMEDIATED_BY_SPEC",
                    "doc_id": doc_id,
                    "domain": domain,
                },
            ]
            needle_q = f"Qual é o procedimento de mitigação segundo {spec_id} para o alarme {alarm_id} ({hex_code})?"
            analytical_q = (
                f"Analise o impacto da oscilação PTP IEEE 1588v2 no elemento {node_id} e a transição "
                f"RRCReconfiguration prevista na norma {spec_id}."
            )
            primary_id = alarm_id
            id_type = "TELCO_ALARM_ID"

        else:  # legal_tax
            cnpj_branch = f"{12 + (index % 80):02d}.{345 + (index % 600):03d}.{678 + (index % 300):03d}/0001-{10 + (index % 89):02d}"
            darf_code = f"DARF-{5952 + index}"
            cpf_code = f"{111 + (index % 800):03d}.{222 + (index % 700):03d}.{333 + (index % 600):03d}-{10 + (index % 89):02d}"
            company = f"Vanguard Soberana Participações {index:03d} S.A."
            amount_val = 125000.00 + (index * 1750.50)
            content = (
                f"INSTRUMENTO DE AUDITORIA FISCAL E GOVERNANÇA SOCIETÁRIA — {doc_id}\n"
                f"CONTRIBUINTE / ENTIDADE: {company} | CNPJ: {cnpj_branch}\n"
                f"REPRESENTANTE LEGAL: CPF {cpf_code}\n"
                f"GUIA DE RECOLHIMENTO TRIBUTÁRIO: Código {darf_code} (Retenção CSRF / IRPJ)\n"
                f"VALOR CONSOLIDADO AUDITADO: R$ {amount_val:,.2f}\n"
                f"FUNDAMENTAÇÃO LEGAL: Comprovada a quitação integral do documento {darf_code} referente ao "
                f"CNPJ {cnpj_branch}, extinguindo a exigibilidade do crédito tributário nos termos do Art. 156 do CTN.\n"
            )
            exact_ids = [cnpj_branch, darf_code, cpf_code]
            entities = [company, cnpj_branch, darf_code]
            edges = [
                {
                    "source": company,
                    "target": cnpj_branch,
                    "relation": "REGISTERED_CNPJ",
                    "doc_id": doc_id,
                    "domain": domain,
                },
                {
                    "source": company,
                    "target": darf_code,
                    "relation": "SETTLED_TAX_VOUCHER",
                    "doc_id": doc_id,
                    "domain": domain,
                },
            ]
            needle_q = f"Qual é o valor consolidado e o status do código {darf_code} vinculado ao CNPJ {cnpj_branch}?"
            analytical_q = (
                f"Explique a extinção de exigibilidade tributária da sociedade {company} ({cnpj_branch}) "
                f"mediante liquidação do documento {darf_code}."
            )
            primary_id = cnpj_branch
            id_type = "TAX_CNPJ_ID"

        return {
            "doc_id": doc_id,
            "domain": domain,
            "content": content,
            "exact_identifiers": exact_ids,
            "entities": entities,
            "edges": edges,
            "prong1_needle": {
                "query": needle_q,
                "identifier": primary_id,
                "identifier_type": id_type,
                "expected_doc_id": doc_id,
                "expected_route": "PRONG_1_EXACT_LEXICAL",
                "domain": domain,
            },
            "prong2_query": {
                "query": analytical_q,
                "expected_doc_ids": [doc_id],
                "expected_route": "PRONG_2_HYBRID_SEMANTIC",
                "domain": domain,
                "requires_graph_hop": tier in ("pro", "enterprise"),
            },
        }

    def _create_archive_bundles(
        self,
        output_dir: Path,
        tier: str,
        generated_records: List[GeneratedDocumentRecord],
    ) -> List[Dict[str, Any]]:
        """Creates `.hdx` and `.zip` container bundles for `pro` and `enterprise` tiers."""
        archives_dir = output_dir / "archives"
        archives_dir.mkdir(parents=True, exist_ok=True)

        bundles: List[Dict[str, Any]] = []
        hdx_path = archives_dir / f"aegis_{tier}_telco_library.hdx"
        zip_path = archives_dir / f"aegis_{tier}_compliance_vault.zip"

        # 1. Build .hdx container (Huawei / 3GPP style XML/HTML technical archive)
        with zipfile.ZipFile(hdx_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for idx in range(1, 5):
                entry_name = f"3gpp_rrc_topics/topic_ALM_{29000 + idx}.html"
                html_body = (
                    f"<html><head><title>3GPP TS 38.331 Fault ALM-{29000 + idx}</title></head>"
                    f"<body><h1>Hardware Alarm ALM-{29000 + idx}</h1>"
                    f"<p>Deterministic recovery procedure for gNodeB unit {idx} under 3GPP TS 38.331.</p>"
                    f"</body></html>"
                )
                zf.writestr(entry_name, html_body.encode("utf-8"))

        bundles.append(
            {
                "archive_path": str(hdx_path.relative_to(output_dir)),
                "format": "hdx",
                "entry_count": 4,
                "sha256": hashlib.sha256(hdx_path.read_bytes()).hexdigest(),
            }
        )

        # 2. Build .zip container (Multi-domain regulatory snapshot)
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for rec in generated_records[:4]:
                src_file = output_dir / rec.filename
                if src_file.is_file():
                    zf.write(src_file, arcname=f"bundled/{Path(rec.filename).name}")

        bundles.append(
            {
                "archive_path": str(zip_path.relative_to(output_dir)),
                "format": "zip",
                "entry_count": min(4, len(generated_records)),
                "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
            }
        )

        return bundles

    def generate(
        self,
        output_dir: Union[str, Path],
        tier: str = "free",
        count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generates a synthetic multi-format dataset and writes `manifest.json`.

        Args:
            output_dir: Target directory where files and `manifest.json` will be written.
            tier: Appliance tier ('free', 'pro', 'enterprise').
            count: Optional document count override (defaults to tier sample count for fast execution).

        Returns:
            Dict[str, Any]: Parsed contents of `manifest.json`.
        """
        normalized_tier = str(tier).strip().lower()
        if normalized_tier not in TIER_PROFILES:
            raise ValueError(
                f"Invalid tier '{tier}'. Supported tiers: {sorted(TIER_PROFILES.keys())}"
            )

        profile = TIER_PROFILES[normalized_tier]
        doc_count = int(count) if count is not None else int(profile["default_sample_count"])
        if doc_count < 4:
            doc_count = 4

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        docs_dir = out_path / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)

        records: List[GeneratedDocumentRecord] = []
        graph_edges: List[Dict[str, Any]] = []
        prong1_needles: List[Dict[str, Any]] = []
        prong2_queries: List[Dict[str, Any]] = []

        formats = ["txt", "md", "json"]

        for i in range(doc_count):
            domain = self.DOMAINS[i % len(self.DOMAINS)]
            fmt = formats[i % len(formats)]
            payload = self._generate_domain_content(index=i + 1, domain=domain, tier=normalized_tier)
            doc_id = payload["doc_id"]

            rel_filename = f"documents/{domain}_{doc_id.lower()}.{fmt}"
            abs_file = out_path / rel_filename

            if fmt == "json":
                serialized = json.dumps(
                    {
                        "doc_id": doc_id,
                        "domain": domain,
                        "tier": normalized_tier,
                        "exact_identifiers": payload["exact_identifiers"],
                        "entities": payload["entities"],
                        "body": payload["content"],
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8")
            elif fmt == "md":
                md_text = (
                    f"# {doc_id} — Domain: {domain.upper()}\n\n"
                    f"**Identifiers**: `{', '.join(payload['exact_identifiers'])}`\n\n"
                    f"```text\n{payload['content']}```\n"
                )
                serialized = md_text.encode("utf-8")
            else:
                serialized = payload["content"].encode("utf-8")

            abs_file.write_bytes(serialized)
            digest = hashlib.sha256(serialized).hexdigest()

            rec = GeneratedDocumentRecord(
                doc_id=doc_id,
                filename=rel_filename,
                domain=domain,
                file_format=fmt,
                sha256=digest,
                exact_identifiers=payload["exact_identifiers"],
                entities=payload["entities"],
            )
            records.append(rec)

            if profile["include_graph_edges"]:
                graph_edges.extend(payload["edges"])

            prong1_needles.append(payload["prong1_needle"])
            prong2_queries.append(payload["prong2_query"])

        archives: List[Dict[str, Any]] = []
        if profile["include_archives"]:
            archives = self._create_archive_bundles(out_path, normalized_tier, records)

        # Add stress-test needle metadata for Enterprise tier
        stress_needles: List[Dict[str, Any]] = []
        if profile["stress_test_needles"]:
            stress_needles = [
                {
                    "stress_id": f"STRESS-ENT-{idx:03d}",
                    "target_scale_documents": profile["tier_capacity"],
                    "latency_sla_ms": 5.0,
                    "needle": prong1_needles[idx % len(prong1_needles)],
                }
                for idx in range(min(10, len(prong1_needles)))
            ]

        manifest: Dict[str, Any] = {
            "schema_version": "2.0.0",
            "tier": normalized_tier,
            "tier_capacity": profile["tier_capacity"],
            "seed": self.seed,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_generated_files": len(records) + len(archives),
            "document_count": len(records),
            "domains": list(self.DOMAINS),
            "documents": [r.to_dict() for r in records],
            "archives": archives,
            "graph_ground_truth_edges": graph_edges,
            "prong1_exact_needles": prong1_needles,
            "prong2_analytical_queries": prong2_queries,
            "enterprise_stress_needles": stress_needles,
        }

        manifest_path = out_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aegis Sovereign Appliance — Synthetic Multi-Tier Benchmark Dataset Generator"
    )
    parser.add_argument(
        "--tier",
        choices=["free", "pro", "enterprise"],
        default="free",
        help="Target appliance tier profile (free=100, pro=5000, enterprise=25000)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Destination directory for generated synthetic files and manifest.json",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Optional override for number of physical document files generated",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic PRNG seed (default: 42)",
    )
    args = parser.parse_args(argv)

    generator = SyntheticCorpusGenerator(seed=args.seed)
    manifest = generator.generate(
        output_dir=args.output_dir,
        tier=args.tier,
        count=args.count,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "tier": manifest["tier"],
                "tier_capacity": manifest["tier_capacity"],
                "document_count": manifest["document_count"],
                "archives_count": len(manifest["archives"]),
                "prong1_needles": len(manifest["prong1_exact_needles"]),
                "prong2_queries": len(manifest["prong2_analytical_queries"]),
                "manifest_path": str(Path(args.output_dir) / "manifest.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
