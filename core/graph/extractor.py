#!/usr/bin/env python3
"""
Relational Knowledge Graph Extractor for Aegis Sovereign Knowledge Appliance.
Extracts structured domain entities, technical infrastructure references,
financial/legal identifiers, and contextual relations from markdown documentation
and ingested OCR documents.

Invariants:
- Zero Plaintext Secrets.
- Local CPU execution using standard regex and rule-based parsing.
"""

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set


@dataclass
class ExtractedEntity:
    name: str
    entity_type: str
    normalized_name: str
    context: str = ""
    count: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedRelation:
    source: str
    target: str
    relation_type: str
    source_type: Optional[str] = None
    target_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    entities: List[ExtractedEntity]
    relations: List[ExtractedRelation]


# ==============================================================================
# Canonical Dictionaries
# ==============================================================================

KNOWN_SERVICES: Dict[str, List[str]] = {
    "traefik": ["traefik v3", "traefik-proxy", "traefik"],
    "qdrant": ["qdrant vector database", "qdrant"],
    "paperless": ["paperless-ngx", "paperless_ngx", "paperless"],
    "ollama": ["ollama"],
    "pihole": ["pi-hole", "pihole"],
    "nomad": ["nomad orchestrator", "nomad"],
    "homeassistant": ["home assistant", "home-assistant", "home_assistant", "homeassistant"],
    "jellyfin": ["jellyfin"],
    "sonarr": ["sonarr"],
    "radarr": ["radarr"],
    "prowlarr": ["prowlarr"],
    "qbittorrent": ["qbittorrent"],
    "netdata": ["netdata"],
    "uptime-kuma": ["uptime-kuma", "uptime kuma", "uptime_kuma"],
    "n8n": ["n8n"],
    "postgresql": ["postgresql", "postgres"],
    "mosquitto": ["mosquitto"],
    "zigbee2mqtt": ["zigbee2mqtt"],
    "glances": ["glances"],
    "filebrowser": ["filebrowser"],
    "tailscale": ["tailscale", "tailscaled"],
    "bazarr": ["bazarr"],
    "mergerfs": ["mergerfs"],
    "rclone": ["rclone"],
    "scrcpy": ["scrcpy"],
    "immich": ["immich"],
}

KNOWN_ORGANIZATIONS: Dict[str, List[str]] = {
    "Receita Federal": ["receita federal", "secretaria da receita federal", "dirpf", "irpf", "darf"],
    "Condomínio Barata Ribeiro": ["condomínio barata ribeiro", "condominio barata ribeiro", "barata ribeiro", "barata 726", "barata 301", "barata301"],
    "Light": ["light serviços de eletricidade", "light servicos de eletricidade", "light s.a.", "light", "conta de luz"],
    "Claro": ["claro s.a.", "claro"],
    "XP Investimentos": ["xp investimentos", "xp corretora", "fii xp malls", "xpml11", "xp cctvm"],
    "Clear Corretora": ["clear corretora", "clear cctvm"],
    "Nubank": ["nubank", "nu pagamentos", "nu financeiras"],
    "Itaú": ["banco itaú", "banco itau", "itaú unibanco", "itau unibanco"],
    "Bradesco": ["banco bradesco", "bradesco"],
    "Banco do Brasil": ["banco do brasil", "banco do brasil s.a."],
    "BTG Pactual": ["btg pactual", "btg"],
    "Prefeitura do Rio de Janeiro": ["prefeitura da cidade do rio de janeiro", "prefeitura do rio", "iptu"],
    "Dell Brasil": ["dell computadores", "dell brasil", "dell"],
}

KNOWN_DOCUMENT_TYPES: Dict[str, List[str]] = {
    "Declaração de Imposto de Renda": ["declaração de ajuste anual", "declaracao transmitida", "recibo de entrega da declaracao", "declaracao irpf", "dirpf", "irpf"],
    "Nota de Corretagem": ["nota de corretagem", "notacorretagem", "extrato de custódia", "extrato de custodia"],
    "Contrato de Locação": ["contrato de locação", "contrato de locacao", "contratolocacao", "locatário", "locatario", "locador"],
    "Fatura de Energia": ["conta de luz", "fatura de energia", "energia elétrica", "energia eletrica"],
    "Fatura de Telecomunicações": ["fatura claro", "claro fatura", "fatura tim", "fatura vivo"],
    "Comprovante de Pagamento": ["comprovante de pagamento", "comprovante pix", "recibo de pagamento"],
    "Boleto Bancário": ["boleto", "linha digitável", "linha digitavel", "ficha de compensação", "taxa condominial"],
    "Certificado": ["certificado nacional", "certificado de vacinação"],
}


def _get_context(text: str, start: int, end: int, window: int = 40) -> str:
    ctx_start = max(0, start - window)
    ctx_end = min(len(text), end + window)
    return text[ctx_start:ctx_end].replace("\n", " ").strip()


def extract_heuristic_organizations(title: str, content: str) -> List[ExtractedEntity]:
    """Infers organization and correspondent entities from document title and body text."""
    combined = f"{title}\n{content[:3000]}".lower()
    results: Dict[str, ExtractedEntity] = {}

    for canonical_name, aliases in KNOWN_ORGANIZATIONS.items():
        sorted_aliases = sorted(aliases, key=len, reverse=True)
        for alias in sorted_aliases:
            pattern = re.compile(r'\b' + re.escape(alias) + r'\b', re.IGNORECASE)
            match = pattern.search(combined)
            if match:
                results[canonical_name] = ExtractedEntity(
                    name=canonical_name,
                    entity_type="correspondent",
                    normalized_name=canonical_name.lower(),
                    context=f"Inferred organization: {canonical_name}"
                )
                break

    return list(results.values())


def extract_heuristic_document_types(title: str, content: str) -> List[ExtractedEntity]:
    """Infers document type categories from document title and body text."""
    combined = f"{title}\n{content[:2000]}".lower()
    results: Dict[str, ExtractedEntity] = {}

    for canonical_type, aliases in KNOWN_DOCUMENT_TYPES.items():
        sorted_aliases = sorted(aliases, key=len, reverse=True)
        for alias in sorted_aliases:
            pattern = re.compile(r'\b' + re.escape(alias) + r'\b', re.IGNORECASE)
            match = pattern.search(combined)
            if match:
                results[canonical_type] = ExtractedEntity(
                    name=canonical_type,
                    entity_type="document_type",
                    normalized_name=canonical_type.lower(),
                    context=f"Inferred document type: {canonical_type}"
                )
                break

    return list(results.values())


def extract_cpf(text: str) -> List[ExtractedEntity]:
    r"""
    Extracts Brazilian Individual Taxpayer Registry (CPF) numbers.
    Pattern: \d{3}\.\d{3}\.\d{3}-\d{2}
    """
    pattern = re.compile(r'\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b')
    results: Dict[str, ExtractedEntity] = {}

    for match in pattern.finditer(text):
        cpf = match.group(1)
        digits = re.sub(r'\D', '', cpf)
        if len(set(digits)) == 1:
            continue

        context = _get_context(text, match.start(), match.end())
        if cpf in results:
            results[cpf].count += 1
        else:
            results[cpf] = ExtractedEntity(
                name=cpf,
                entity_type="cpf",
                normalized_name=cpf,
                context=context,
                count=1,
                metadata={"digits": digits}
            )

    return list(results.values())


def extract_cnpj(text: str) -> List[ExtractedEntity]:
    r"""
    Extracts Brazilian Corporate Taxpayer Registry (CNPJ) numbers.
    Pattern: \d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}
    """
    pattern = re.compile(r'\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b')
    results: Dict[str, ExtractedEntity] = {}

    for match in pattern.finditer(text):
        cnpj = match.group(1)
        digits = re.sub(r'\D', '', cnpj)
        if len(set(digits)) == 1:
            continue

        context = _get_context(text, match.start(), match.end())
        if cnpj in results:
            results[cnpj].count += 1
        else:
            results[cnpj] = ExtractedEntity(
                name=cnpj,
                entity_type="cnpj",
                normalized_name=cnpj,
                context=context,
                count=1,
                metadata={"digits": digits}
            )

    return list(results.values())


def extract_monetary_amounts(text: str) -> List[ExtractedEntity]:
    """
    Extracts Brazilian Real monetary amounts (R$ X,XX).
    Handles thousands separators and spaces (e.g. R$ 1.250,50, R$100,00, R$ 0,50).
    """
    pattern = re.compile(r'(?:R\$\s*|BRL\s*)(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})\b')
    results: Dict[str, ExtractedEntity] = {}

    for match in pattern.finditer(text):
        num_str = match.group(1).strip()
        canonical_name = f"R$ {num_str}"
        try:
            float_val = float(num_str.replace(".", "").replace(",", "."))
        except ValueError:
            continue

        context = _get_context(text, match.start(), match.end())
        if canonical_name in results:
            results[canonical_name].count += 1
        else:
            results[canonical_name] = ExtractedEntity(
                name=canonical_name,
                entity_type="monetary",
                normalized_name=canonical_name,
                context=context,
                count=1,
                metadata={"value": float_val, "currency": "BRL"}
            )

    return list(results.values())


def extract_dates(text: str) -> List[ExtractedEntity]:
    """
    Extracts dates in ISO (YYYY-MM-DD) and Brazilian (DD/MM/YYYY) formats.
    Normalizes both into ISO 8601 YYYY-MM-DD.
    """
    results: Dict[str, ExtractedEntity] = {}

    # ISO format: YYYY-MM-DD
    iso_pattern = re.compile(r'\b(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b')
    for match in iso_pattern.finditer(text):
        y, m, d = match.group(1), match.group(2), match.group(3)
        try:
            valid_date = datetime.date(int(y), int(m), int(d))
            iso_str = valid_date.isoformat()
        except ValueError:
            continue

        context = _get_context(text, match.start(), match.end())
        raw_name = match.group(0)
        if iso_str in results:
            results[iso_str].count += 1
        else:
            results[iso_str] = ExtractedEntity(
                name=raw_name,
                entity_type="date",
                normalized_name=iso_str,
                context=context,
                count=1
            )

    # Brazilian format: DD/MM/YYYY
    br_pattern = re.compile(r'\b(0[1-9]|[12]\d|3[01])/(0[1-9]|1[0-2])/(\d{4})\b')
    for match in br_pattern.finditer(text):
        d, m, y = match.group(1), match.group(2), match.group(3)
        try:
            valid_date = datetime.date(int(y), int(m), int(d))
            iso_str = valid_date.isoformat()
        except ValueError:
            continue

        context = _get_context(text, match.start(), match.end())
        raw_name = match.group(0)
        if iso_str in results:
            results[iso_str].count += 1
        else:
            results[iso_str] = ExtractedEntity(
                name=raw_name,
                entity_type="date",
                normalized_name=iso_str,
                context=context,
                count=1
            )

    return list(results.values())


def extract_adr_references(text: str) -> List[ExtractedEntity]:
    """
    Extracts Architectural Decision Record references (ADR-XX).
    """
    pattern = re.compile(r'\bADR-(\d+)\b', re.IGNORECASE)
    results: Dict[str, ExtractedEntity] = {}

    for match in pattern.finditer(text):
        num = int(match.group(1))
        normalized = f"ADR-{num:02d}"
        raw_name = match.group(0).upper()
        context = _get_context(text, match.start(), match.end())

        if normalized in results:
            results[normalized].count += 1
        else:
            results[normalized] = ExtractedEntity(
                name=raw_name,
                entity_type="adr",
                normalized_name=normalized,
                context=context,
                count=1,
                metadata={"adr_number": num}
            )

    return list(results.values())


def extract_prj_references(text: str) -> List[ExtractedEntity]:
    """
    Extracts Project references (PRJ-XX).
    """
    pattern = re.compile(r'\bPRJ-(\d+)\b', re.IGNORECASE)
    results: Dict[str, ExtractedEntity] = {}

    for match in pattern.finditer(text):
        num = int(match.group(1))
        normalized = f"PRJ-{num:02d}"
        raw_name = match.group(0).upper()
        context = _get_context(text, match.start(), match.end())

        if normalized in results:
            results[normalized].count += 1
        else:
            results[normalized] = ExtractedEntity(
                name=raw_name,
                entity_type="prj",
                normalized_name=normalized,
                context=context,
                count=1,
                metadata={"prj_number": num}
            )

    return list(results.values())


def extract_services(text: str) -> List[ExtractedEntity]:
    """
    Extracts known infrastructure services and normalizes them into canonical identifiers.
    """
    results: Dict[str, ExtractedEntity] = {}

    for canonical_name, aliases in KNOWN_SERVICES.items():
        sorted_aliases = sorted(aliases, key=len, reverse=True)
        for alias in sorted_aliases:
            pattern = re.compile(rf'\b{re.escape(alias)}\b', re.IGNORECASE)
            match = pattern.search(text)
            if match:
                raw_name = match.group(0)
                context = _get_context(text, match.start(), match.end())
                if canonical_name in results:
                    results[canonical_name].count += 1
                else:
                    results[canonical_name] = ExtractedEntity(
                        name=raw_name,
                        entity_type="service",
                        normalized_name=canonical_name,
                        context=context,
                        count=1
                    )
                break

    return list(results.values())


def extract_ips_and_ports(text: str) -> Tuple[List[ExtractedEntity], List[ExtractedEntity], List[ExtractedRelation]]:
    """
    Extracts network IP addresses and ports.
    Disambiguates timestamps and creates (ip, "has_port", port) relations.
    """
    ips: Dict[str, ExtractedEntity] = {}
    ports: Dict[str, ExtractedEntity] = {}
    relations: List[ExtractedRelation] = []

    # 1. IP:Port combinations
    ip_port_pattern = re.compile(
        r'\b((?:192\.168\.\d{1,3}\.\d{1,3})|(?:100\.\d{1,3}\.\d{1,3}\.\d{1,3})|(?:127\.0\.0\.1)|(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3})):(\d{2,5})\b'
    )
    for match in ip_port_pattern.finditer(text):
        ip_str = match.group(1)
        port_str = match.group(2)
        port_num = int(port_str)
        if 1 <= port_num <= 65535:
            ctx = _get_context(text, match.start(), match.end())
            if ip_str not in ips:
                ips[ip_str] = ExtractedEntity(name=ip_str, entity_type="ip", normalized_name=ip_str, context=ctx)
            else:
                ips[ip_str].count += 1

            if port_str not in ports:
                ports[port_str] = ExtractedEntity(name=port_str, entity_type="port", normalized_name=port_str, context=ctx)
            else:
                ports[port_str].count += 1

            relations.append(ExtractedRelation(
                source=ip_str,
                target=port_str,
                relation_type="has_port",
                source_type="ip",
                target_type="port"
            ))

    # 2. Standalone IPs
    ip_pattern = re.compile(
        r'\b((?:192\.168\.\d{1,3}\.\d{1,3})|(?:100\.\d{1,3}\.\d{1,3}\.\d{1,3})|(?:127\.0\.0\.1)|(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}))\b'
    )
    for match in ip_pattern.finditer(text):
        ip_str = match.group(1)
        octets = [int(o) for o in ip_str.split(".")]
        if all(0 <= o <= 255 for o in octets):
            if ip_str not in ips:
                ctx = _get_context(text, match.start(), match.end())
                ips[ip_str] = ExtractedEntity(name=ip_str, entity_type="ip", normalized_name=ip_str, context=ctx)
            else:
                ips[ip_str].count += 1

    # 3. Standalone Ports
    standalone_port_pattern = re.compile(
        r'(?:(?<=\s)|(?<=^)|(?<=[\(\[,])):(?P<p1>[1-9]\d{1,4})\b|(?:\bport\s+|\bporta\s+)(?P<p2>[1-9]\d{1,4})\b'
    )
    for match in standalone_port_pattern.finditer(text):
        port_val = match.group('p1') or match.group('p2')
        if not port_val:
            continue
        port_num = int(port_val)
        if not (1 <= port_num <= 65535):
            continue

        start_idx = match.start()
        end_idx = match.end()
        pre = text[max(0, start_idx - 3):start_idx]
        post = text[end_idx:min(len(text), end_idx + 3)]
        if re.search(r'\d{1,2}:$', pre) or re.search(r'^:\d{2}', post):
            continue

        if port_val not in ports:
            ctx = _get_context(text, start_idx, end_idx)
            ports[port_val] = ExtractedEntity(name=port_val, entity_type="port", normalized_name=port_val, context=ctx)
        else:
            ports[port_val].count += 1

    return list(ips.values()), list(ports.values()), relations


def extract_wiki_entities(
    file_path: str,
    frontmatter: Dict[str, Any],
    content: str
) -> ExtractionResult:
    """
    Extracts entities and relational links from a markdown document.
    Processes YAML frontmatter tags/aliases, content regex entities, and markdown links.
    """
    entities: List[ExtractedEntity] = []
    relations: List[ExtractedRelation] = []
    doc_identifier = file_path

    # 1. Frontmatter Tags
    raw_tags = frontmatter.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    for tag in raw_tags:
        clean_tag = str(tag).strip()
        if clean_tag:
            entities.append(ExtractedEntity(
                name=clean_tag,
                entity_type="tag",
                normalized_name=clean_tag.lower(),
                context=f"Frontmatter tag in {file_path}"
            ))
            relations.append(ExtractedRelation(
                source=doc_identifier,
                target=clean_tag.lower(),
                relation_type="tagged",
                source_type="document",
                target_type="tag"
            ))

    # 2. Markdown Links: [Title](target.md)
    link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+\.md)\)')
    seen_links: Set[str] = set()
    for match in link_pattern.finditer(content):
        label = match.group(1).strip()
        target_md = match.group(2).strip()
        target_stem = Path(target_md).name
        if target_stem not in seen_links:
            seen_links.add(target_stem)
            entities.append(ExtractedEntity(
                name=target_stem,
                entity_type="wiki_link",
                normalized_name=target_stem.lower(),
                context=_get_context(content, match.start(), match.end()),
                metadata={"label": label, "target_path": target_md}
            ))
            relations.append(ExtractedRelation(
                source=doc_identifier,
                target=target_stem.lower(),
                relation_type="links_to",
                source_type="document",
                target_type="wiki_link"
            ))

    # 3. Content Regex Extractors
    cpfs = extract_cpf(content)
    cnpjs = extract_cnpj(content)
    amounts = extract_monetary_amounts(content)
    dates = extract_dates(content)
    adrs = extract_adr_references(content)
    prjs = extract_prj_references(content)
    services = extract_services(content)
    ips, ports, ip_port_rels = extract_ips_and_ports(content)

    entities.extend(cpfs)
    entities.extend(cnpjs)
    entities.extend(amounts)
    entities.extend(dates)
    entities.extend(adrs)
    entities.extend(prjs)
    entities.extend(services)
    entities.extend(ips)
    entities.extend(ports)
    relations.extend(ip_port_rels)

    # 4. Document-to-entity relations
    for adr in adrs:
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=adr.normalized_name,
            relation_type="references",
            source_type="document",
            target_type="adr"
        ))
    for prj in prjs:
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=prj.normalized_name,
            relation_type="references",
            source_type="document",
            target_type="prj"
        ))
    for svc in services:
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=svc.normalized_name,
            relation_type="references",
            source_type="document",
            target_type="service"
        ))
    for ip in ips:
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=ip.normalized_name,
            relation_type="mentions",
            source_type="document",
            target_type="ip"
        ))

    # 5. Service <-> IP and Service <-> Port Relations
    for svc in services:
        for ip in ips:
            relations.append(ExtractedRelation(
                source=svc.normalized_name,
                target=ip.normalized_name,
                relation_type="runs_on",
                source_type="service",
                target_type="ip"
            ))
        for port in ports:
            relations.append(ExtractedRelation(
                source=svc.normalized_name,
                target=port.normalized_name,
                relation_type="uses_port",
                source_type="service",
                target_type="port"
            ))

    return ExtractionResult(entities=entities, relations=relations)


def extract_paperless_entities(
    doc_id: int,
    title: str,
    correspondent: str,
    doc_type: str,
    tags: List[str],
    content: str
) -> ExtractionResult:
    """
    Extracts entities and relational links from an ingested document (OCR/PDF).
    """
    entities: List[ExtractedEntity] = []
    relations: List[ExtractedRelation] = []
    doc_identifier = str(doc_id)

    # 1. Correspondent
    if correspondent and correspondent.strip():
        corr_clean = correspondent.strip()
        entities.append(ExtractedEntity(
            name=corr_clean,
            entity_type="correspondent",
            normalized_name=corr_clean.lower(),
            context=f"Correspondent of doc {doc_id}: {title}"
        ))
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=corr_clean,
            relation_type="issued_by",
            source_type="document",
            target_type="correspondent"
        ))

    # 2. Document Type
    if doc_type and doc_type.strip():
        dt_clean = doc_type.strip()
        entities.append(ExtractedEntity(
            name=dt_clean,
            entity_type="document_type",
            normalized_name=dt_clean.lower(),
            context=f"Document type of {doc_id}"
        ))
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=dt_clean,
            relation_type="is_type",
            source_type="document",
            target_type="document_type"
        ))

    # Inferred Organizations & Document Types
    inferred_orgs = extract_heuristic_organizations(title, content)
    for org in inferred_orgs:
        if not any(e.normalized_name == org.normalized_name and e.entity_type == "correspondent" for e in entities):
            entities.append(org)
            relations.append(ExtractedRelation(
                source=doc_identifier,
                target=org.name,
                relation_type="issued_by",
                source_type="document",
                target_type="correspondent"
            ))

    inferred_dts = extract_heuristic_document_types(title, content)
    for dt in inferred_dts:
        if not any(e.normalized_name == dt.normalized_name and e.entity_type == "document_type" for e in entities):
            entities.append(dt)
            relations.append(ExtractedRelation(
                source=doc_identifier,
                target=dt.name,
                relation_type="is_type",
                source_type="document",
                target_type="document_type"
            ))

    # 3. Tags
    if tags:
        for tag in tags:
            tag_clean = tag.strip()
            if tag_clean:
                entities.append(ExtractedEntity(
                    name=tag_clean,
                    entity_type="tag",
                    normalized_name=tag_clean.lower(),
                    context=f"Tag for {doc_id}"
                ))
                relations.append(ExtractedRelation(
                    source=doc_identifier,
                    target=tag_clean,
                    relation_type="tagged",
                    source_type="document",
                    target_type="tag"
                ))

    # Combine text for regex entity extraction
    full_text = f"{title}\n{content}"
    cpfs = extract_cpf(full_text)
    cnpjs = extract_cnpj(full_text)
    amounts = extract_monetary_amounts(full_text)
    dates = extract_dates(full_text)
    ips, ports, ip_port_rels = extract_ips_and_ports(full_text)
    services = extract_services(full_text)

    entities.extend(cpfs)
    entities.extend(cnpjs)
    entities.extend(amounts)
    entities.extend(dates)
    entities.extend(ips)
    entities.extend(ports)
    entities.extend(services)
    relations.extend(ip_port_rels)

    # Document-level relations
    for cpf in cpfs:
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=cpf.name,
            relation_type="mentions_cpf",
            source_type="document",
            target_type="cpf"
        ))
    for cnpj in cnpjs:
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=cnpj.name,
            relation_type="mentions_cnpj",
            source_type="document",
            target_type="cnpj"
        ))
    for amt in amounts:
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=amt.name,
            relation_type="has_amount",
            source_type="document",
            target_type="monetary"
        ))
    for dt in dates:
        relations.append(ExtractedRelation(
            source=doc_identifier,
            target=dt.normalized_name,
            relation_type="has_date",
            source_type="document",
            target_type="date"
        ))

    # Cross-entity relations
    if correspondent and correspondent.strip():
        corr_clean = correspondent.strip()
        for cnpj in cnpjs:
            relations.append(ExtractedRelation(
                source=corr_clean,
                target=cnpj.name,
                relation_type="has_cnpj",
                source_type="correspondent",
                target_type="cnpj"
            ))
        for cpf in cpfs:
            relations.append(ExtractedRelation(
                source=cpf.name,
                target=corr_clean,
                relation_type="associated_with",
                source_type="cpf",
                target_type="correspondent"
            ))
        for amt in amounts:
            relations.append(ExtractedRelation(
                source=corr_clean,
                target=amt.name,
                relation_type="billed_amount",
                source_type="correspondent",
                target_type="monetary"
            ))

    return ExtractionResult(entities=entities, relations=relations)
