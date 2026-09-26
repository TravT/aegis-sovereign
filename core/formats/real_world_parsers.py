#!/usr/bin/env python3
"""
Real-World Enterprise & Homelab Structured Format Parsers.
Aegis Sovereign Knowledge Appliance.

Implements native zero-cloud parsers and GraphRAG + Prong-1 Router ingestors for:
1. NfeXmlParser: Brazilian SEFAZ NF-e v4.00 XML (<nfeProc> / <NFe>) with pharmaceutical
   batch traceability (<rastro>: nLote, qLote, dFab, dVal) and ANVISA registration (<med>: cProdANVISA).
   Enforces strict XXE / XML Entity Expansion rejection (<!ENTITY, SYSTEM, PUBLIC).
2. MboxEmailParser: RFC-5322 .eml and .mbox email thread archives with conversational
   GraphRAG threading (Message_B --[REPLIES_TO]--> Message_A, Sender --[EMAILED]--> Recipient)
   and cross-domain incident/alarm entity linking.
3. TabularCsvParser: Automatic delimiter-sniffing CSV/TSV parser for clinical longevity
   biomarker panels and ERP inventory logs, indexing high-signal identifiers into Prong 1 + Prong 2.
"""

from __future__ import annotations

import csv
import email
import email.policy
import email.utils
import hashlib
import html
import io
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from core.security import ClearanceLevel


class XmlSecurityError(ValueError):
    """Raised when an XML payload contains prohibited DTD/Entity declarations (XXE/Billion Laughs)."""


# Security Regex against XXE / Entity Expansion
_XXE_GUARD_RE = re.compile(
    r"<!ENTITY\b|<!DOCTYPE[^>]+(?:\bSYSTEM\b|\bPUBLIC\b|\[)",
    re.IGNORECASE | re.DOTALL,
)

# Identifier extraction patterns across email threads and CSV rows
_INCIDENT_RE = re.compile(r"\b((?:INC|TCK|SEC|CHG)-\d{2,8}(?:-[A-Z0-9]{1,8})?)\b", re.IGNORECASE)
_ALARM_RE = re.compile(r"\b(ALM-\d{4,6})\b", re.IGNORECASE)
_MML_RE = re.compile(r"\b((?:ADD|MOD|RMV|LST|DSP|SET|ACT|DEA|PING|TRC)\s+[A-Z0-9_]{3,20})\b")
_CPF_RE = re.compile(r"\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b")
_CNPJ_RE = re.compile(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b")
_CID10_RE = re.compile(r"(?:(?i:\bCID[-\s]*10?:?\s*([A-TV-Z]\d{2}(?:\.\d)?)\b)|\b([A-TV-Z]\d{2}\.\d)(?!\.\d)\b)")
_LOTE_RE = re.compile(r"\b(LOTE[-:\s]+([A-Z0-9][A-Z0-9\-]{3,20}))\b", re.IGNORECASE)
_CRM_RE = re.compile(r"\b(CRM[-/\s]*[A-Z]{2}[\s-]*\d{4,7})\b", re.IGNORECASE)


def _local_tag(tag: str) -> str:
    """Strip XML namespace URI `{http://...}local` -> `local`."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _format_cnpj(raw: str) -> str:
    digits = re.sub(r"[^\d]", "", raw or "")
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:14]}"
    return raw.strip()


def _format_cpf(raw: str) -> str:
    digits = re.sub(r"[^\d]", "", raw or "")
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}"
    return raw.strip()


def _format_anvisa_ms(raw: str) -> Optional[str]:
    """Convert 13-digit ANVISA cProdANVISA (e.g. 1023504910024) to MS 1.0235.0491.002-4."""
    digits = re.sub(r"[^\d]", "", raw or "")
    if len(digits) == 13 and digits.startswith("1"):
        return f"{digits[0]}.{digits[1:5]}.{digits[5:9]}.{digits[9:12]}-{digits[12]}"
    return None


# ===========================================================================
# 1. Brazilian SEFAZ NF-e v4.00 XML Parser (<nfeProc> / <NFe> + <rastro>/<med>)
# ===========================================================================
@dataclass
class NfeRastroSpec:
    """Pharmaceutical / Lot traceability block (<rastro>) from SEFAZ NF-e v4.00."""

    n_lote: str
    q_lote: float
    d_fab: str
    d_val: str
    c_agreg: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nLote": self.n_lote,
            "qLote": self.q_lote,
            "dFab": self.d_fab,
            "dVal": self.d_val,
            "cAgreg": self.c_agreg,
        }


@dataclass
class NfeMedSpec:
    """ANVISA medication block (<med>) from SEFAZ NF-e v4.00."""

    c_prod_anvisa: str
    formatted_ms: Optional[str]
    v_pmc: float
    x_motivo_isencao: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cProdANVISA": self.c_prod_anvisa,
            "formatted_ms": self.formatted_ms,
            "vPMC": self.v_pmc,
            "xMotivoIsencao": self.x_motivo_isencao,
        }


@dataclass
class NfeItemSpec:
    """Line item (<det nItem="..."><prod>) from SEFAZ NF-e v4.00."""

    n_item: int
    c_prod: str
    x_prod: str
    ncm: str
    cfop: str
    u_com: str
    q_com: float
    v_un_com: float
    v_prod: float
    rastros: List[NfeRastroSpec] = field(default_factory=list)
    med: Optional[NfeMedSpec] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nItem": self.n_item,
            "cProd": self.c_prod,
            "xProd": self.x_prod,
            "NCM": self.ncm,
            "CFOP": self.cfop,
            "uCom": self.u_com,
            "qCom": self.q_com,
            "vUnCom": self.v_un_com,
            "vProd": self.v_prod,
            "rastro": [r.to_dict() for r in self.rastros],
            "med": self.med.to_dict() if self.med else None,
        }


@dataclass
class NfeInvoiceRecord:
    """Parsed representation of a Brazilian SEFAZ NF-e v4.00 electronic invoice."""

    chave_acesso: str
    numero_nf: str
    serie: str
    data_emissao: str
    natureza_operacao: str
    emitente: Dict[str, str]
    destinatario: Dict[str, str]
    itens: List[NfeItemSpec]
    totais: Dict[str, float]
    batches_extracted: List[str]
    anvisa_registrations: List[str]
    parse_latency_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chave_acesso": self.chave_acesso,
            "numero_nf": self.numero_nf,
            "serie": self.serie,
            "data_emissao": self.data_emissao,
            "natureza_operacao": self.natureza_operacao,
            "emitente": self.emitente,
            "destinatario": self.destinatario,
            "itens": [i.to_dict() for i in self.itens],
            "totais": self.totais,
            "batches_extracted": self.batches_extracted,
            "anvisa_registrations": self.anvisa_registrations,
            "parse_latency_ms": round(self.parse_latency_ms, 3),
        }


class NfeXmlParser:
    """Safe, namespace-resilient parser for Brazilian SEFAZ NF-e v4.00 XML documents."""

    @staticmethod
    def _read_xml_text(xml_source: Union[str, bytes, Path]) -> str:
        if isinstance(xml_source, Path):
            return xml_source.read_text(encoding="utf-8")
        if isinstance(xml_source, bytes):
            return xml_source.decode("utf-8", errors="replace")
        if isinstance(xml_source, str):
            stripped = xml_source.strip()
            if not stripped.startswith("<") and Path(stripped).is_file():
                return Path(stripped).read_text(encoding="utf-8")
            return xml_source
        raise TypeError(f"Unsupported xml_source type: {type(xml_source)}")

    @staticmethod
    def _find_child(parent: Optional[ET.Element], tag_name: str) -> Optional[ET.Element]:
        if parent is None:
            return None
        for child in parent:
            if _local_tag(child.tag) == tag_name:
                return child
        return None

    @staticmethod
    def _find_children(parent: Optional[ET.Element], tag_name: str) -> List[ET.Element]:
        if parent is None:
            return []
        return [child for child in parent if _local_tag(child.tag) == tag_name]

    @classmethod
    def _child_text(cls, parent: Optional[ET.Element], tag_name: str, default: str = "") -> str:
        node = cls._find_child(parent, tag_name)
        if node is not None and node.text:
            return node.text.strip()
        return default

    @classmethod
    def _child_float(cls, parent: Optional[ET.Element], tag_name: str, default: float = 0.0) -> float:
        raw = cls._child_text(parent, tag_name, "")
        if not raw:
            return default
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            return default

    def parse_xml(self, xml_source: Union[str, bytes, Path]) -> NfeInvoiceRecord:
        """Parse SEFAZ NF-e v4.00 XML after verifying absence of XXE / Entity Expansion."""
        t0 = time.perf_counter()
        xml_text = self._read_xml_text(xml_source)

        # 1. XXE & Entity Expansion Guard
        if _XXE_GUARD_RE.search(xml_text):
            raise XmlSecurityError(
                "Prohibited XML DTD/Entity declaration detected (<!ENTITY, SYSTEM, or PUBLIC). "
                "Rejected by Aegis Sovereign XML Security Guard."
            )

        root = ET.fromstring(xml_text)

        # Locate <infNFe> and optional <protNFe> regardless of <nfeProc> or <NFe> wrapper
        inf_nfe: Optional[ET.Element] = None
        prot_nfe: Optional[ET.Element] = None
        for elem in root.iter():
            ltag = _local_tag(elem.tag)
            if ltag == "infNFe" and inf_nfe is None:
                inf_nfe = elem
            elif ltag == "protNFe" and prot_nfe is None:
                prot_nfe = elem

        if inf_nfe is None:
            raise ValueError("Invalid NF-e XML: missing <infNFe> element.")

        # Extract 44-digit Chave de Acesso
        chave_acesso = ""
        if prot_nfe is not None:
            inf_prot = self._find_child(prot_nfe, "infProt")
            chave_acesso = self._child_text(inf_prot, "chNFe", "")
        if not chave_acesso:
            raw_id = inf_nfe.attrib.get("Id", "")
            if raw_id.upper().startswith("NFE"):
                chave_acesso = re.sub(r"[^\d]", "", raw_id[3:])
            else:
                chave_acesso = re.sub(r"[^\d]", "", raw_id)

        ide = self._find_child(inf_nfe, "ide")
        numero_nf = self._child_text(ide, "nNF", "")
        serie = self._child_text(ide, "serie", "1")
        data_emissao = self._child_text(ide, "dhEmi", "") or self._child_text(ide, "dEmi", "")
        natureza_operacao = self._child_text(ide, "natOp", "")

        # Emitter (<emit>)
        emit = self._find_child(inf_nfe, "emit")
        ender_emit = self._find_child(emit, "enderEmit")
        emit_cnpj_raw = self._child_text(emit, "CNPJ", "")
        emitente = {
            "CNPJ": emit_cnpj_raw,
            "CNPJ_formatted": _format_cnpj(emit_cnpj_raw),
            "xNome": self._child_text(emit, "xNome", ""),
            "xFant": self._child_text(emit, "xFant", ""),
            "IE": self._child_text(emit, "IE", ""),
            "UF": self._child_text(ender_emit, "UF", ""),
            "xMun": self._child_text(ender_emit, "xMun", ""),
        }

        # Recipient (<dest>)
        dest = self._find_child(inf_nfe, "dest")
        ender_dest = self._find_child(dest, "enderDest")
        dest_cnpj_raw = self._child_text(dest, "CNPJ", "")
        dest_cpf_raw = self._child_text(dest, "CPF", "")
        destinatario = {
            "CNPJ": dest_cnpj_raw,
            "CPF": dest_cpf_raw,
            "tax_id_formatted": _format_cnpj(dest_cnpj_raw) if dest_cnpj_raw else _format_cpf(dest_cpf_raw),
            "xNome": self._child_text(dest, "xNome", ""),
            "UF": self._child_text(ender_dest, "UF", ""),
        }

        # Items (<det>)
        itens: List[NfeItemSpec] = []
        batches_extracted: List[str] = []
        anvisa_registrations: List[str] = []

        for idx, det in enumerate(self._find_children(inf_nfe, "det"), start=1):
            n_item_str = det.attrib.get("nItem", str(idx))
            try:
                n_item = int(n_item_str)
            except ValueError:
                n_item = idx

            prod = self._find_child(det, "prod")
            if prod is None:
                continue

            rastros: List[NfeRastroSpec] = []
            for r_node in self._find_children(prod, "rastro"):
                n_lote = self._child_text(r_node, "nLote", "")
                r_spec = NfeRastroSpec(
                    n_lote=n_lote,
                    q_lote=self._child_float(r_node, "qLote", 0.0),
                    d_fab=self._child_text(r_node, "dFab", ""),
                    d_val=self._child_text(r_node, "dVal", ""),
                    c_agreg=self._child_text(r_node, "cAgreg", ""),
                )
                rastros.append(r_spec)
                if n_lote and n_lote not in batches_extracted:
                    batches_extracted.append(n_lote)

            med_node = self._find_child(prod, "med")
            med_spec: Optional[NfeMedSpec] = None
            if med_node is not None:
                c_anvisa = self._child_text(med_node, "cProdANVISA", "")
                fmt_ms = _format_anvisa_ms(c_anvisa)
                med_spec = NfeMedSpec(
                    c_prod_anvisa=c_anvisa,
                    formatted_ms=fmt_ms,
                    v_pmc=self._child_float(med_node, "vPMC", 0.0),
                    x_motivo_isencao=self._child_text(med_node, "xMotivoIsencao", ""),
                )
                if c_anvisa and c_anvisa not in anvisa_registrations:
                    anvisa_registrations.append(c_anvisa)

            itens.append(
                NfeItemSpec(
                    n_item=n_item,
                    c_prod=self._child_text(prod, "cProd", ""),
                    x_prod=self._child_text(prod, "xProd", ""),
                    ncm=self._child_text(prod, "NCM", ""),
                    cfop=self._child_text(prod, "CFOP", ""),
                    u_com=self._child_text(prod, "uCom", ""),
                    q_com=self._child_float(prod, "qCom", 0.0),
                    v_un_com=self._child_float(prod, "vUnCom", 0.0),
                    v_prod=self._child_float(prod, "vProd", 0.0),
                    rastros=rastros,
                    med=med_spec,
                )
            )

        # Totals (<total><ICMSTot>)
        total_node = self._find_child(inf_nfe, "total")
        icms_tot = self._find_child(total_node, "ICMSTot")
        totais = {
            "vBC": self._child_float(icms_tot, "vBC", 0.0),
            "vICMS": self._child_float(icms_tot, "vICMS", 0.0),
            "vPIS": self._child_float(icms_tot, "vPIS", 0.0),
            "vCOFINS": self._child_float(icms_tot, "vCOFINS", 0.0),
            "vProd": self._child_float(icms_tot, "vProd", 0.0),
            "vNF": self._child_float(icms_tot, "vNF", 0.0),
        }

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return NfeInvoiceRecord(
            chave_acesso=chave_acesso,
            numero_nf=numero_nf,
            serie=serie,
            data_emissao=data_emissao,
            natureza_operacao=natureza_operacao,
            emitente=emitente,
            destinatario=destinatario,
            itens=itens,
            totais=totais,
            batches_extracted=batches_extracted,
            anvisa_registrations=anvisa_registrations,
            parse_latency_ms=elapsed_ms,
        )

    def ingest_nfe(
        self,
        xml_source: Union[str, bytes, Path],
        router: Optional[Any] = None,
        graph_store: Optional[Any] = None,
        clearance_level: Union[str, int, ClearanceLevel] = ClearanceLevel.RESTRICTED,
    ) -> Dict[str, Any]:
        """Parse NF-e v4.00 XML and index Chave de Acesso, CNPJ, <rastro> nLote, and <med> cProdANVISA
        into SovereignQueryRouter (Prong 1) and SQLite GraphStore (GraphRAG edges).
        """
        t0 = time.perf_counter()
        record = self.parse_xml(xml_source)
        clr_obj = ClearanceLevel.from_string(clearance_level)
        clr_int = clr_obj.value

        indexed_router_records = 0
        indexed_graph_edges = 0
        searchable_chunks: List[Dict[str, Any]] = []

        emit_name = record.emitente.get("xNome") or "Emitente NF-e"
        emit_cnpj_fmt = record.emitente.get("CNPJ_formatted") or record.emitente.get("CNPJ", "")
        emit_cnpj_raw = record.emitente.get("CNPJ", "")
        dest_name = record.destinatario.get("xNome") or "Destinatario NF-e"
        dest_tax_id = record.destinatario.get("tax_id_formatted") or record.destinatario.get("CNPJ") or record.destinatario.get("CPF", "")

        items_summary_lines = []
        for item in record.itens:
            lote_parts = [f"{r.n_lote} (Fab:{r.d_fab}, Val:{r.d_val}, Qtd:{r.q_lote})" for r in item.rastros]
            lote_str = ", ".join(lote_parts) if lote_parts else "N/A"
            anvisa_str = (
                f"{item.med.c_prod_anvisa} (MS {item.med.formatted_ms})"
                if item.med and item.med.formatted_ms
                else (item.med.c_prod_anvisa if item.med else "N/A")
            )
            items_summary_lines.append(
                f"Item {item.n_item}: {item.x_prod} (cProd={item.c_prod}, NCM={item.ncm}, CFOP={item.cfop}) | "
                f"Qtd={item.q_com} {item.u_com} x R$ {item.v_un_com:.2f} = R$ {item.v_prod:.2f} | "
                f"Lote=<rastro>: {lote_str} | ANVISA=<med>: {anvisa_str}"
            )

        invoice_summary_text = (
            f"[SEFAZ NF-e v4.00 Chave {record.chave_acesso}] NF #{record.numero_nf} Série {record.serie} "
            f"({record.natureza_operacao}) | Emissão: {record.data_emissao}\n"
            f"Emitente: {emit_name} (CNPJ: {emit_cnpj_fmt}, UF: {record.emitente.get('UF', '')})\n"
            f"Destinatário: {dest_name} (Doc: {dest_tax_id}, UF: {record.destinatario.get('UF', '')})\n"
            f"Totais ICMS/NF: vBC=R$ {record.totais['vBC']:.2f}, vICMS=R$ {record.totais['vICMS']:.2f}, "
            f"vPIS=R$ {record.totais['vPIS']:.2f}, vCOFINS=R$ {record.totais['vCOFINS']:.2f}, "
            f"vNF=R$ {record.totais['vNF']:.2f}\n"
            + "\n".join(items_summary_lines)
        )

        searchable_chunks.append({
            "title": f"NF-e {record.numero_nf} - {emit_name} (Chave {record.chave_acesso})",
            "file_path": f"sefaz://nfe/{record.chave_acesso}.xml",
            "heading": f"SEFAZ NF-e v4.00 #{record.numero_nf}",
            "score": 0.96,
            "rrf_score": 0.033,
            "text": invoice_summary_text,
        })

        if router is not None:
            # 1. Index by 44-digit Chave de Acesso
            if record.chave_acesso:
                router.index_document(
                    doc_identifier=record.chave_acesso,
                    title=f"DANFE / NF-e v4.00 #{record.numero_nf} ({emit_name})",
                    content=invoice_summary_text,
                    clearance_level=clr_obj,
                    metadata=record.to_dict(),
                )
                indexed_router_records += 1

            # 2. Index by Emitter CNPJ (raw digits & formatted)
            for cnpj_id in {emit_cnpj_raw, emit_cnpj_fmt}:
                if cnpj_id:
                    router.index_document(
                        doc_identifier=cnpj_id,
                        title=f"Emitente NF-e #{record.numero_nf}: {emit_name} ({emit_cnpj_fmt})",
                        content=invoice_summary_text,
                        clearance_level=clr_obj,
                        metadata={"entity_type": "emitente_nfe", "chave_acesso": record.chave_acesso},
                    )
                    indexed_router_records += 1

            # 3. Index each Item's Pharmaceutical Batch (<rastro> nLote) & ANVISA MS (<med> cProdANVISA)
            for item in record.itens:
                for rastro in item.rastros:
                    lote_id = rastro.n_lote
                    lote_code_short = re.sub(r"^LOTE[-:\s]*", "", lote_id, flags=re.IGNORECASE).strip()
                    lote_content = (
                        f"[Rastreabilidade Farmacêutica SEFAZ <rastro> Lote: {lote_id}] "
                        f"Produto: {item.x_prod} (cProd={item.c_prod}, NCM={item.ncm}) | "
                        f"Fabricação (dFab): {rastro.d_fab} | Validade (dVal): {rastro.d_val} | "
                        f"Quantidade Lote (qLote): {rastro.q_lote} {item.u_com} | "
                        f"Registro ANVISA (<med> cProdANVISA): "
                        f"{item.med.c_prod_anvisa if item.med else 'N/A'} "
                        f"({('MS ' + item.med.formatted_ms) if (item.med and item.med.formatted_ms) else ''}) | "
                        f"NF-e Chave: {record.chave_acesso} | Emitente: {emit_name} ({emit_cnpj_fmt})"
                    )
                    for lid in {lote_id, lote_code_short}:
                        if lid:
                            router.index_document(
                                doc_identifier=lid,
                                title=f"Lote Farmacêutico {lote_id}: {item.x_prod}",
                                content=lote_content,
                                clearance_level=clr_obj,
                                metadata={
                                    "entity_type": "pharma_lote",
                                    "nLote": lote_id,
                                    "dFab": rastro.d_fab,
                                    "dVal": rastro.d_val,
                                    "qLote": rastro.q_lote,
                                    "cProdANVISA": item.med.c_prod_anvisa if item.med else None,
                                    "chave_acesso": record.chave_acesso,
                                },
                            )
                            indexed_router_records += 1

                if item.med and item.med.c_prod_anvisa:
                    anvisa_ids = {item.med.c_prod_anvisa}
                    if item.med.formatted_ms:
                        anvisa_ids.add(item.med.formatted_ms)
                        anvisa_ids.add(f"MS {item.med.formatted_ms}")
                    for aid in anvisa_ids:
                        router.index_document(
                            doc_identifier=aid,
                            title=f"Registro ANVISA {item.med.c_prod_anvisa}: {item.x_prod}",
                            content=invoice_summary_text,
                            clearance_level=clr_obj,
                            metadata={
                                "entity_type": "anvisa_registration",
                                "cProdANVISA": item.med.c_prod_anvisa,
                                "formatted_ms": item.med.formatted_ms,
                                "chave_acesso": record.chave_acesso,
                            },
                        )
                        indexed_router_records += 1

        # Populate GraphRAG edges (`Emitter_CNPJ --[ISSUED_NFE]--> chNFe --[CONTAINS_LOTE]--> nLote`)
        if graph_store is not None:
            entities_list: List[Dict[str, Any]] = [
                {
                    "name": record.chave_acesso,
                    "entity_type": "nfe_invoice",
                    "normalized_name": record.chave_acesso.lower(),
                    "context": f"NF-e #{record.numero_nf} ({record.natureza_operacao}) vNF=R$ {record.totais['vNF']:.2f}",
                    "clearance_level": clr_int,
                },
                {
                    "name": emit_cnpj_fmt or emit_name,
                    "entity_type": "organization_cnpj",
                    "normalized_name": (emit_cnpj_fmt or emit_name).lower(),
                    "context": f"Emitente NF-e: {emit_name}",
                    "clearance_level": clr_int,
                },
                {
                    "name": emit_name,
                    "entity_type": "organization",
                    "normalized_name": emit_name.lower(),
                    "context": f"CNPJ {emit_cnpj_fmt}",
                    "clearance_level": clr_int,
                },
            ]
            relations_list: List[Dict[str, Any]] = [
                {
                    "source": emit_cnpj_fmt or emit_name,
                    "target": record.chave_acesso,
                    "relation_type": "ISSUED_NFE",
                    "source_type": "organization_cnpj",
                    "target_type": "nfe_invoice",
                    "clearance_level": clr_int,
                },
                {
                    "source": emit_name,
                    "target": emit_cnpj_fmt or emit_name,
                    "relation_type": "HAS_CNPJ",
                    "source_type": "organization",
                    "target_type": "organization_cnpj",
                    "clearance_level": clr_int,
                },
            ]

            if dest_tax_id:
                entities_list.append({
                    "name": dest_tax_id,
                    "entity_type": "recipient_tax_id",
                    "normalized_name": dest_tax_id.lower(),
                    "context": f"Destinatário: {dest_name}",
                    "clearance_level": clr_int,
                })
                relations_list.append({
                    "source": record.chave_acesso,
                    "target": dest_tax_id,
                    "relation_type": "BILLED_TO",
                    "source_type": "nfe_invoice",
                    "target_type": "recipient_tax_id",
                    "clearance_level": clr_int,
                })

            for item in record.itens:
                for rastro in item.rastros:
                    entities_list.append({
                        "name": rastro.n_lote,
                        "entity_type": "pharma_lote",
                        "normalized_name": rastro.n_lote.lower(),
                        "context": f"{item.x_prod} (Fab: {rastro.d_fab}, Val: {rastro.d_val}, Qtd: {rastro.q_lote})",
                        "clearance_level": clr_int,
                    })
                    relations_list.append({
                        "source": record.chave_acesso,
                        "target": rastro.n_lote,
                        "relation_type": "CONTAINS_LOTE",
                        "source_type": "nfe_invoice",
                        "target_type": "pharma_lote",
                        "clearance_level": clr_int,
                    })
                    relations_list.append({
                        "source": emit_cnpj_fmt or emit_name,
                        "target": rastro.n_lote,
                        "relation_type": "SUPPLIED_LOTE",
                        "source_type": "organization_cnpj",
                        "target_type": "pharma_lote",
                        "clearance_level": clr_int,
                    })
                    if item.med and item.med.c_prod_anvisa:
                        entities_list.append({
                            "name": item.med.c_prod_anvisa,
                            "entity_type": "anvisa_registration",
                            "normalized_name": item.med.c_prod_anvisa.lower(),
                            "context": f"ANVISA MS {item.med.formatted_ms or item.med.c_prod_anvisa} - {item.x_prod}",
                            "clearance_level": clr_int,
                        })
                        relations_list.append({
                            "source": rastro.n_lote,
                            "target": item.med.c_prod_anvisa,
                            "relation_type": "REGISTERED_ANVISA",
                            "source_type": "pharma_lote",
                            "target_type": "anvisa_registration",
                            "clearance_level": clr_int,
                        })

            graph_store.index_document(
                corpus="sefaz_nfe_v400",
                doc_identifier=record.chave_acesso,
                title=f"NF-e #{record.numero_nf} - {emit_name}",
                url=f"sefaz://nfe/{record.chave_acesso}.xml",
                entities=entities_list,
                relations=relations_list,
                clearance_level=clr_int,
            )
            indexed_graph_edges += len(relations_list)

        return {
            "status": "success",
            "chave_acesso": record.chave_acesso,
            "batches_extracted": record.batches_extracted,
            "anvisa_registrations": record.anvisa_registrations,
            "indexed_router_records": indexed_router_records,
            "indexed_graph_edges": indexed_graph_edges,
            "searchable_chunks": searchable_chunks,
            "record": record,
            "ingest_latency_ms": (time.perf_counter() - t0) * 1000.0,
        }


# ===========================================================================
# 2. RFC-5322 .eml and .mbox Email Thread Parser
# ===========================================================================
@dataclass
class EmailMessageRecord:
    """Parsed RFC-5322 Email Message with headers, body, attachments, and extracted IDs."""

    message_id: str
    in_reply_to: Optional[str]
    references: List[str]
    sender: str
    sender_email: str
    recipients: List[str]
    subject: str
    date: str
    body_text: str
    attachment_filenames: List[str]
    extracted_identifiers: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "in_reply_to": self.in_reply_to,
            "references": self.references,
            "sender": self.sender,
            "sender_email": self.sender_email,
            "recipients": self.recipients,
            "subject": self.subject,
            "date": self.date,
            "body_text": self.body_text,
            "attachment_filenames": self.attachment_filenames,
            "extracted_identifiers": self.extracted_identifiers,
        }


class MboxEmailParser:
    """RFC-5322 .eml and .mbox email thread parser with conversational GraphRAG edge builder."""

    @staticmethod
    def _clean_msg_id(raw_id: Optional[str]) -> str:
        if not raw_id:
            return ""
        return raw_id.strip().strip("<>").strip()

    @classmethod
    def _extract_identifiers_from_text(cls, text: str) -> List[str]:
        found: List[str] = []
        for pattern in (_INCIDENT_RE, _ALARM_RE, _MML_RE, _LOTE_RE):
            for m in pattern.finditer(text):
                tok = re.sub(r"\s+", " ", m.group(1).strip().upper())
                if tok not in found:
                    found.append(tok)
        return found

    @classmethod
    def _parse_email_message(cls, msg: email.message.Message, idx: int = 1) -> EmailMessageRecord:
        raw_msg_id = msg.get("Message-ID") or f"<msg-{idx}@sovereign.local>"
        message_id = cls._clean_msg_id(raw_msg_id)
        raw_reply = msg.get("In-Reply-To")
        in_reply_to = cls._clean_msg_id(raw_reply) if raw_reply else None

        refs_raw = msg.get("References") or ""
        references = [
            cls._clean_msg_id(tok)
            for tok in re.findall(r"<[^>]+>|[^\s]+", refs_raw)
            if cls._clean_msg_id(tok)
        ]

        from_hdr = str(msg.get("From", ""))
        _, sender_email = email.utils.parseaddr(from_hdr)
        sender = sender_email or from_hdr.strip()

        to_hdr = str(msg.get("To", ""))
        cc_hdr = str(msg.get("Cc", ""))
        all_addrs = email.utils.getaddresses([to_hdr, cc_hdr])
        recipients = [addr for _, addr in all_addrs if addr]

        subject = str(msg.get("Subject", "(No Subject)")).strip()
        date_str = str(msg.get("Date", "")).strip()

        body_parts: List[str] = []
        html_parts: List[str] = []
        attachments: List[str] = []

        if msg.is_multipart():
            for part in msg.walk():
                cdisp = str(part.get("Content-Disposition", ""))
                fname = part.get_filename()
                if fname:
                    attachments.append(str(fname))
                    continue
                if "attachment" in cdisp.lower():
                    continue
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
                    elif isinstance(payload, str):
                        body_parts.append(payload)
                elif ctype == "text/html":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        html_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
                    elif isinstance(payload, str):
                        html_parts.append(payload)
        else:
            ctype = msg.get_content_type()
            payload = msg.get_payload(decode=True)
            decoded = ""
            if isinstance(payload, bytes):
                decoded = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            elif isinstance(payload, str):
                decoded = payload
            if ctype == "text/html":
                html_parts.append(decoded)
            elif decoded:
                body_parts.append(decoded)

        if not body_parts and html_parts:
            for hpart in html_parts:
                cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", hpart, flags=re.IGNORECASE | re.DOTALL)
                cleaned = re.sub(r"<[^>]+>", " ", cleaned)
                cleaned = html.unescape(re.sub(r"\s+", " ", cleaned)).strip()
                if cleaned:
                    body_parts.append(cleaned)

        body_text = "\n".join(p.strip() for p in body_parts if p.strip())
        combined_text = f"{subject}\n{body_text}"
        extracted_ids = cls._extract_identifiers_from_text(combined_text)

        return EmailMessageRecord(
            message_id=message_id,
            in_reply_to=in_reply_to,
            references=references,
            sender=sender,
            sender_email=sender_email or sender,
            recipients=recipients,
            subject=subject,
            date=date_str,
            body_text=body_text,
            attachment_filenames=attachments,
            extracted_identifiers=extracted_ids,
        )

    def parse_eml(self, eml_source: Union[str, bytes, Path]) -> EmailMessageRecord:
        """Parse a single RFC-5322 .eml message from bytes, string, or file path (O_RDONLY)."""
        if isinstance(eml_source, Path):
            fd = os.open(str(eml_source), os.O_RDONLY)
            try:
                with os.fdopen(fd, "rb") as f:
                    raw_bytes = f.read()
            except Exception:
                os.close(fd)
                raise
        elif isinstance(eml_source, bytes):
            raw_bytes = eml_source
        elif isinstance(eml_source, str):
            if "\n" not in eml_source and Path(eml_source).is_file():
                return self.parse_eml(Path(eml_source))
            raw_bytes = eml_source.encode("utf-8")
        else:
            raise TypeError(f"Unsupported eml_source type: {type(eml_source)}")

        msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
        return self._parse_email_message(msg, idx=1)

    def parse_mbox(self, mbox_source: Union[str, bytes, Path]) -> List[EmailMessageRecord]:
        """
        Parse an RFC-5322 / RFC-4155 .mbox archive 100% in-memory (O_RDONLY)
        with zero temporary disk files and zero lock files (ADR-07 / ADR-37 compliant).
        """
        if isinstance(mbox_source, Path) and mbox_source.is_file():
            fd = os.open(str(mbox_source), os.O_RDONLY)
            try:
                with os.fdopen(fd, "rb") as f:
                    raw_bytes = f.read()
            except Exception:
                os.close(fd)
                raise
        elif isinstance(mbox_source, bytes):
            raw_bytes = mbox_source
        elif isinstance(mbox_source, str):
            if "\n" not in mbox_source and Path(mbox_source).is_file():
                return self.parse_mbox(Path(mbox_source))
            raw_bytes = mbox_source.encode("utf-8")
        else:
            raise TypeError(f"Unsupported mbox_source type: {type(mbox_source)}")

        # Split in-memory on RFC-4155 mbox envelope lines (`From <sender> <timestamp>`)
        chunks = re.split(rb"(?:\r?\n|^)From [^\r\n]+\r?\n", raw_bytes)
        records: List[EmailMessageRecord] = []
        for raw_chunk in chunks:
            stripped = raw_chunk.strip()
            if not stripped:
                continue
            msg = email.message_from_bytes(stripped, policy=email.policy.default)
            if not msg.keys() and not msg.get_payload():
                continue
            records.append(self._parse_email_message(msg, idx=len(records) + 1))
        return records

    def ingest_mailbox(
        self,
        source: Union[str, bytes, Path],
        router: Optional[Any] = None,
        graph_store: Optional[Any] = None,
        clearance_level: Union[str, int, ClearanceLevel] = ClearanceLevel.INTERNAL,
    ) -> Dict[str, Any]:
        """Parse .mbox or .eml thread and index messages + conversational edges into Router & GraphStore."""
        t0 = time.perf_counter()
        if isinstance(source, Path) and source.suffix.lower() == ".eml":
            messages = [self.parse_eml(source)]
        else:
            messages = self.parse_mbox(source)
            if not messages:
                messages = [self.parse_eml(source)]

        clr_obj = ClearanceLevel.from_string(clearance_level)
        clr_int = clr_obj.value

        indexed_router_records = 0
        indexed_graph_edges = 0
        searchable_chunks: List[Dict[str, Any]] = []

        for msg in messages:
            summary_text = (
                f"[Email Message-ID: {msg.message_id}] Subject: {msg.subject} | Date: {msg.date}\n"
                f"From: {msg.sender_email} -> To: {', '.join(msg.recipients)}\n"
                f"In-Reply-To: {msg.in_reply_to or 'None'} | Attachments: {', '.join(msg.attachment_filenames) or 'None'}\n"
                f"Body:\n{msg.body_text}"
            )
            searchable_chunks.append({
                "title": f"Email: {msg.subject} ({msg.sender_email})",
                "file_path": f"mbox://{msg.message_id}",
                "heading": msg.subject,
                "score": 0.91,
                "rrf_score": 0.029,
                "text": summary_text,
            })

            if router is not None:
                router.index_document(
                    doc_identifier=msg.message_id,
                    title=f"Email Thread: {msg.subject}",
                    content=summary_text,
                    clearance_level=clr_obj,
                    metadata=msg.to_dict(),
                )
                indexed_router_records += 1

                # Index incident tickets (e.g. INC-2026-8841) into Prong 1 router
                for ext_id in msg.extracted_identifiers:
                    if ext_id.startswith(("INC-", "TCK-", "SEC-", "CHG-")):
                        router.index_document(
                            doc_identifier=ext_id,
                            title=f"Incident Thread {ext_id}: {msg.subject}",
                            content=summary_text,
                            clearance_level=clr_obj,
                            metadata={"message_id": msg.message_id, "extracted_id": ext_id},
                        )
                        indexed_router_records += 1

            if graph_store is not None:
                entities: List[Dict[str, Any]] = [
                    {
                        "name": msg.message_id,
                        "entity_type": "email_message",
                        "normalized_name": msg.message_id.lower(),
                        "context": f"{msg.subject} ({msg.date})",
                        "clearance_level": clr_int,
                    },
                    {
                        "name": msg.sender_email,
                        "entity_type": "email_participant",
                        "normalized_name": msg.sender_email.lower(),
                        "context": f"Sender of {msg.message_id}",
                        "clearance_level": clr_int,
                    },
                ]
                relations: List[Dict[str, Any]] = []

                # Thread reply edges: Message_B --[REPLIES_TO]--> Message_A
                if msg.in_reply_to:
                    entities.append({
                        "name": msg.in_reply_to,
                        "entity_type": "email_message",
                        "normalized_name": msg.in_reply_to.lower(),
                        "context": f"Parent message of {msg.message_id}",
                        "clearance_level": clr_int,
                    })
                    relations.append({
                        "source": msg.message_id,
                        "target": msg.in_reply_to,
                        "relation_type": "REPLIES_TO",
                        "source_type": "email_message",
                        "target_type": "email_message",
                        "clearance_level": clr_int,
                    })

                # Sender --[EMAILED]--> Recipient
                for rcpt in msg.recipients:
                    entities.append({
                        "name": rcpt,
                        "entity_type": "email_participant",
                        "normalized_name": rcpt.lower(),
                        "context": f"Recipient of {msg.message_id}",
                        "clearance_level": clr_int,
                    })
                    relations.append({
                        "source": msg.sender_email,
                        "target": rcpt,
                        "relation_type": "EMAILED",
                        "source_type": "email_participant",
                        "target_type": "email_participant",
                        "clearance_level": clr_int,
                    })

                # Cross-domain links between Email, Incident Ticket (INC-2026-8841), Alarm (ALM-26235), and MML
                for ext_id in msg.extracted_identifiers:
                    etype = (
                        "telecom_alarm"
                        if ext_id.startswith("ALM-")
                        else ("mml_command" if " " in ext_id else "incident_ticket")
                    )
                    entities.append({
                        "name": ext_id,
                        "entity_type": etype,
                        "normalized_name": ext_id.lower(),
                        "context": f"Referenced in email {msg.message_id}: {msg.subject}",
                        "clearance_level": clr_int,
                    })
                    relations.append({
                        "source": msg.message_id,
                        "target": ext_id,
                        "relation_type": "MENTIONS_ENTITY",
                        "source_type": "email_message",
                        "target_type": etype,
                        "clearance_level": clr_int,
                    })

                # Also link incident tickets directly to alarms/MML commands mentioned in the same message
                incidents = [x for x in msg.extracted_identifiers if x.startswith(("INC-", "TCK-"))]
                others = [x for x in msg.extracted_identifiers if not x.startswith(("INC-", "TCK-"))]
                for inc in incidents:
                    for other in others:
                        relations.append({
                            "source": inc,
                            "target": other,
                            "relation_type": "CORRELATED_WITH",
                            "source_type": "incident_ticket",
                            "target_type": "telecom_alarm" if other.startswith("ALM-") else "mml_command",
                            "clearance_level": clr_int,
                        })

                graph_store.index_document(
                    corpus="rfc5322_mbox",
                    doc_identifier=msg.message_id,
                    title=msg.subject,
                    url=f"mbox://{msg.message_id}",
                    entities=entities,
                    relations=relations,
                    clearance_level=clr_int,
                )
                indexed_graph_edges += len(relations)

        return {
            "status": "success",
            "messages_count": len(messages),
            "messages": [m.to_dict() for m in messages],
            "indexed_router_records": indexed_router_records,
            "indexed_graph_edges": indexed_graph_edges,
            "searchable_chunks": searchable_chunks,
            "ingest_latency_ms": (time.perf_counter() - t0) * 1000.0,
        }


# ===========================================================================
# 3. Tabular CSV / TSV Clinical & Inventory Log Parser
# ===========================================================================
@dataclass
class TabularRecordChunk:
    """High-signal row chunk extracted from a clinical or inventory CSV/TSV file."""

    row_index: int
    primary_identifier: str
    secondary_identifiers: List[str]
    row_dict: Dict[str, str]
    formatted_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row_index": self.row_index,
            "primary_identifier": self.primary_identifier,
            "secondary_identifiers": self.secondary_identifiers,
            "row_dict": self.row_dict,
            "formatted_text": self.formatted_text,
        }


class TabularCsvParser:
    """Automatic delimiter-sniffing CSV/TSV parser for clinical longevity panels & ERP inventory exports."""

    @staticmethod
    def _read_text(csv_source: Union[str, bytes, Path]) -> str:
        if isinstance(csv_source, Path):
            return csv_source.read_text(encoding="utf-8")
        if isinstance(csv_source, bytes):
            return csv_source.decode("utf-8", errors="replace")
        if isinstance(csv_source, str):
            if "\n" not in csv_source and Path(csv_source).is_file():
                return Path(csv_source).read_text(encoding="utf-8")
            return csv_source
        raise TypeError(f"Unsupported csv_source type: {type(csv_source)}")

    @staticmethod
    def _sniff_delimiter(sample: str) -> str:
        try:
            dialect = csv.Sniffer().sniff(sample[:4096], delimiters=",;\t|")
            return dialect.delimiter
        except Exception:
            first_line = sample.splitlines()[0] if sample.splitlines() else ""
            for cand in ("\t", ";", ",", "|"):
                if cand in first_line:
                    return cand
            return ","

    @classmethod
    def _extract_row_identifiers(cls, row_dict: Dict[str, str]) -> Tuple[str, List[str]]:
        row_str = " | ".join(f"{k}: {v}" for k, v in row_dict.items() if v)
        ids: List[str] = []

        for m in _CPF_RE.finditer(row_str):
            ids.append(m.group(1))
        for m in _CNPJ_RE.finditer(row_str):
            ids.append(m.group(1))
        for m in _CID10_RE.finditer(row_str):
            code = (m.group(1) or m.group(2)).upper()
            ids.append(code)
            ids.append(f"CID-10 {code}")
        for m in _CRM_RE.finditer(row_str):
            ids.append(m.group(1).upper())
        for m in _LOTE_RE.finditer(row_str):
            ids.append(m.group(1).upper())

        # Check explicit ID columns (patient_id, sample_id, sku, lote)
        for col_key, val in row_dict.items():
            if not val:
                continue
            low_k = col_key.lower()
            if any(k in low_k for k in ("cpf", "cnpj", "patient_id", "sample_id", "sku", "lote", "cid")):
                clean_v = val.strip()
                if clean_v and clean_v not in ids:
                    ids.append(clean_v)

        primary = (
            ids[0]
            if ids
            else f"ROW-{hashlib.sha256(row_str.encode('utf-8')).hexdigest()[:10].upper()}"
        )
        secondary = [i for i in ids[1:] if i != primary]
        return primary, secondary

    def parse_tabular(
        self,
        csv_source: Union[str, bytes, Path],
        source_name: str = "tabular_export.csv",
    ) -> Dict[str, Any]:
        """Parse CSV/TSV with delimiter sniffing and convert rows into Prong 1 + Prong 2 chunks."""
        t0 = time.perf_counter()
        raw_text = self._read_text(csv_source)
        delimiter = self._sniff_delimiter(raw_text)

        reader = csv.DictReader(io.StringIO(raw_text), delimiter=delimiter)
        headers = list(reader.fieldnames or [])
        chunks: List[TabularRecordChunk] = []

        for idx, row in enumerate(reader, start=1):
            clean_row = {str(k).strip(): str(v or "").strip() for k, v in row.items() if k is not None}
            if not any(clean_row.values()):
                continue
            primary_id, secondary_ids = self._extract_row_identifiers(clean_row)
            kv_pairs = " | ".join(f"{k}={v}" for k, v in clean_row.items() if v)
            formatted_text = f"[{source_name} Row #{idx} | ID={primary_id}] {kv_pairs}"
            chunks.append(
                TabularRecordChunk(
                    row_index=idx,
                    primary_identifier=primary_id,
                    secondary_identifiers=secondary_ids,
                    row_dict=clean_row,
                    formatted_text=formatted_text,
                )
            )

        return {
            "source_name": source_name,
            "detected_delimiter": delimiter,
            "headers": headers,
            "row_count": len(chunks),
            "chunks": chunks,
            "parse_latency_ms": (time.perf_counter() - t0) * 1000.0,
        }

    def ingest_tabular(
        self,
        csv_source: Union[str, bytes, Path],
        router: Optional[Any] = None,
        graph_store: Optional[Any] = None,
        source_name: str = "clinical_longevity_panel.csv",
        clearance_level: Union[str, int, ClearanceLevel] = ClearanceLevel.RESTRICTED,
    ) -> Dict[str, Any]:
        """Parse CSV/TSV and index high-signal rows into SovereignQueryRouter (Prong 1) & GraphStore."""
        t0 = time.perf_counter()
        parsed = self.parse_tabular(csv_source, source_name=source_name)
        clr_obj = ClearanceLevel.from_string(clearance_level)
        clr_int = clr_obj.value

        indexed_router_records = 0
        indexed_graph_edges = 0
        searchable_chunks: List[Dict[str, Any]] = []

        for chunk in parsed["chunks"]:
            searchable_chunks.append({
                "title": f"{source_name} Record: {chunk.primary_identifier}",
                "file_path": f"tabular://{source_name}#row-{chunk.row_index}",
                "heading": f"Row {chunk.row_index} ({chunk.primary_identifier})",
                "score": 0.93,
                "rrf_score": 0.031,
                "text": chunk.formatted_text,
            })

            if router is not None:
                all_ids = [chunk.primary_identifier] + chunk.secondary_identifiers
                for ident in all_ids:
                    router.index_document(
                        doc_identifier=ident,
                        title=f"Clinical/Inventory Record ({source_name}): {chunk.primary_identifier}",
                        content=chunk.formatted_text,
                        clearance_level=clr_obj,
                        metadata=chunk.to_dict(),
                    )
                    # Also index normalized CPF/CNPJ digits so Prong 1 B-Tree hits directly
                    digits_only = re.sub(r"[^\d]", "", ident)
                    if len(digits_only) in (11, 14) and digits_only != ident:
                        router.index_document(
                            doc_identifier=digits_only,
                            title=f"Clinical/Inventory Record ({source_name}): {chunk.primary_identifier}",
                            content=chunk.formatted_text,
                            clearance_level=clr_obj,
                            metadata=chunk.to_dict(),
                        )
                    indexed_router_records += 1

            if graph_store is not None:
                entities = [
                    {
                        "name": chunk.primary_identifier,
                        "entity_type": "tabular_primary_entity",
                        "normalized_name": chunk.primary_identifier.lower(),
                        "context": chunk.formatted_text[:240],
                        "clearance_level": clr_int,
                    }
                ]
                relations = []
                for sec_id in chunk.secondary_identifiers:
                    entities.append({
                        "name": sec_id,
                        "entity_type": "clinical_or_inventory_code",
                        "normalized_name": sec_id.lower(),
                        "context": f"Linked to {chunk.primary_identifier} in {source_name}",
                        "clearance_level": clr_int,
                    })
                    relations.append({
                        "source": chunk.primary_identifier,
                        "target": sec_id,
                        "relation_type": "ASSOCIATED_CODE",
                        "source_type": "tabular_primary_entity",
                        "target_type": "clinical_or_inventory_code",
                        "clearance_level": clr_int,
                    })
                graph_store.index_document(
                    corpus="tabular_csv",
                    doc_identifier=f"{source_name}#row-{chunk.row_index}",
                    title=f"{source_name} Row {chunk.row_index} ({chunk.primary_identifier})",
                    url=f"tabular://{source_name}#row-{chunk.row_index}",
                    entities=entities,
                    relations=relations,
                    clearance_level=clr_int,
                )
                indexed_graph_edges += len(relations)

        return {
            "status": "success",
            "source_name": source_name,
            "detected_delimiter": parsed["detected_delimiter"],
            "row_count": parsed["row_count"],
            "indexed_router_records": indexed_router_records,
            "indexed_graph_edges": indexed_graph_edges,
            "searchable_chunks": searchable_chunks,
            "ingest_latency_ms": (time.perf_counter() - t0) * 1000.0,
        }
