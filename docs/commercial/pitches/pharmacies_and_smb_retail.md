# Aegis Sovereign Appliance: Pharmacies, Compounding Labs & SMB Retail
**Vertical Solution Brief — Drogarias, Farmácias de Manipulação (RDC 67/2007) & High-Velocity SMB Operations**

---

## 1. The Vertical Dilemma: The Compliance, Speed & Margin Crisis in Retail & Compounding Pharmacies

Retail pharmacies (*Drogarias*), compounding laboratories (*Farmácias de Manipulação* under ANVISA **RDC 67/2007**), and specialized multi-branch SMB retailers operate under severe regulatory and operational pressure:

1. **ANVISA & SNGPC Regulatory Exposure (*Portaria SVS/MS nº 344/98* & *RDC 22/2014*)**:
   - Controlled psychotropic and retinoid lists (**Lista A1/A2/A3 Yellow**, **Lista B1/B2 Blue**, **Lista C1/C2/C5 White Two-Copy**, and **Antimicrobials RDC 471/2021**) require strict prescription verification, batch (*lote*) traceability, and 7-day SNGPC XML ledger reconciliation. A single mismatch between physical inventory, XML supplier invoices (*NF-e*), and retained prescriptions triggers sanitary interdiction and heavy fines.
2. **Counter & Lab Latency Kills Conversion**:
   - When a pharmacist at the counter or a compounding technician in the lab needs to verify an excipient incompatibility, pediatric dosage limit, or **POP (*Procedimento Operacional Padrão*)**, searching across 3,000+ PDFs, supplier *Laudos de Análise* (Certificates of Analysis), and regulatory manuals takes 4 to 8 minutes—stalling customer service.
3. **Zero Budget for Complex IT or Cloud Token Bleed**:
   - Small and medium pharmacies cannot afford R$ 5.000/month in cloud AI subscriptions, nor can they risk uploading patient prescriptions containing CPFs, CID-10 codes, and physician CRMs to external cloud LLMs (**LGPD Art. 11 — Dados Sensíveis de Saúde**). Furthermore, internet outages must **never** paralyze counter lookups or compounding verification.

---

## 2. The Sovereign Solution: Instant `<2ms` Deterministic Lookup + Local AI Summary Engine

The **Aegis Sovereign Appliance (SMB & Pharmacy Edition)** turns any existing back-office Windows/Linux PC (Tier 1 Serverless Desktop) or a dedicated **R$ 1.800 Turnkey Mini-PC** (Tier 2 Edge Box) into an air-gapped, zero-latency regulatory, clinical, and fiscal brain.

```
[XML NF-e + Receitas + POPs + Laudos PDF] ──► [Zero-Copy Watchdog / Drop-Zone]
                                                       │
       ┌───────────────────────────────────────────────┴───────────────────────────────────────────────┐
       ▼                                                                                               ▼
[Prong 1: Deterministic Fast-Path (<2ms)]                                     [Prong 2: Hybrid Clinical & Local LLM Engine]
• Exact Lote ID (e.g., LOTE-202609B)                                          • Drug-Drug & Excipient Incompatibility
• ANVISA MS Registry (1.xxxx.xxxx.xxx-x)                                      • ANVISA RDC 67/2007 & POP Synthesis
• NF-e Chave de Acesso (44 digits) & CNPJ                                     • Grounded Local 3B/14B Fast Summary
• Zero LLM Hallucination / 0 Cloud Tokens                                     • Mandatory Citation Footnotes & Page Jump
```

### Key Architectural Advantages for Pharmacies & SMBs
- **Two-Pronged Intent Router (`ADR-06`)**:
  - **Prong 1 (`<2ms` Deterministic Fast-Path)**: Typing a batch code (`LOTE-88412`), ANVISA registration number, physician `CRM-SP 123456`, customer `CPF`, or `NF-e` invoice number bypasses neural embeddings completely and hits the SQLite B-Tree + FTS5 index in **under 2 milliseconds**—returning the exact invoice, Certificate of Analysis (*Laudo*), and prescription record with **zero hallucination risk**.
  - **Prong 2 (Hybrid Clinical & Regulatory Synthesis)**: Asking *"Qual o limite máximo de dispensação de Clonazepam Lista B1 para 60 dias e qual POP aplicável?"* retrieves the exact ANVISA Portaria 344/98 article and internal POP, generating a **2-second grounded Portuguese summary** via the on-device Local LLM (`NanoRunner` / Ollama) with clickable page citations.
- **Zero-Friction 60-Second Onboarding (`ADR-08`)**:
  - Auto-discovers the pharmacy's existing `NF-e` XML folders, `Laudos_Fornecedores/`, and `POPs_Vigilancia_Sanitaria/` in-place (`O_RDONLY`) without duplicating files or slowing down point-of-sale (POS/PDV) terminals (`IDLE_PRIORITY_CLASS` CPU throttling).

---

## 3. High-Value Pharmacy & SMB Workflows

| Workflow | Traditional Manual Process | With Aegis Sovereign Appliance | Measurable Impact |
| :--- | :--- | :--- | :--- |
| **1. SNGPC & Portaria 344/98 Prescription Audit** | Pharmacist manually cross-checks Lista A/B/C1 retention rules, max treatment days (30 vs 60 days), and batch numbers against PDFs. | Type drug name or Lista code (`Lista B1`). Instant `<2ms` rules card + local LLM checklist of mandatory fields (CRM, UF, data, endereço). | **90% faster counter verification; 0 SNGPC audit rejections.** |
| **2. Compounding Lab (*Farmácia de Manipulação*) Laudo & Formula Check** | Lab tech searches shared folders for supplier Certificate of Analysis (*Laudo de Análise*) and *Ficha de Pesagem* excipient pH compatibility. | Scan or type `Lote` barcode (`L2409-A`). Instant split-screen view of supplier *Laudo* purity, expiration date, and RDC 67/2007 POP. | **Saves 12+ hours/week in lab QA; instant ANVISA inspection readiness.** |
| **3. Automated XML Invoice (*NF-e*) & Price/Tax Reconciliation** | Back-office clerk manually compares distributor *NF-e* XMLs, ICMS-ST tax substitution codes (CEST/NCM), and purchase orders. | Drop XMLs/PDFs into watch folder. GraphRAG (`ADR-04`) automatically maps `Fornecedor -> NF-e -> Lote -> Valor` and flags price/tax anomalies. | **Eliminates overpayment & fiscal fines; 100% offline audit trail.** |
| **4. Instant Staff Onboarding & POP Compliance** | New attendants interrupt senior pharmacists dozens of times per day for standard procedures, storage temperatures (thermolabile 2°C–8°C), and returns. | Staff queries `Alt + Space` Spotlight HUD in natural Portuguese: *"Como proceder no recebimento de insulinas termolábeis?"* | **Senior pharmacist time reclaimed for high-margin clinical care.** |

---

## 4. Security, LGPD & Sanitary Inspection Proof

- **100% LGPD Art. 11 Safe Harbor**: Patient CPFs, medical prescriptions, and health history never leave the pharmacy's physical building. Zero cloud API calls, zero OpenAI/Anthropic data exposure.
- **Role-Based Mandatory Access Control (`ADR-05`)**:
  - `PUBLIC (0)` / `INTERNAL (1)`: Counter attendants access POPs, *bulários*, and general inventory specs.
  - `CONFIDENTIAL (2)`: Responsible Pharmacists (*Farmacêutico RT*) access controlled substance ledgers (Portaria 344/98) and patient histories.
  - `RESTRICTED (3)`: Store Owners access financial margins, payroll, DRE, and supplier contract rebates.
- **Epistemic Refusal Guardrail (`ADR-09`)**: If a query asks about a dosage or compound not present in the verified *Formulário Nacional* or internal POPs (confidence `<35%`), the local LLM strictly refuses to guess and displays the verbatim source documents.

---

## 5. Commercial Packaging & Accessible SMB Pricing

Designed specifically for high ROI and rapid adoption across single pharmacies, compounding labs, and multi-store retail chains:

| Package Tier | Target Client Profile | Deployment Footprint | Commercial Pricing (BRL / USD) |
| :--- | :--- | :--- | :--- |
| **Tier 1: Aegis Balcão & RT (Software License)** | Independent Pharmacies, Small Compounding Labs, Accounting/Retail SMBs (1–3 terminals) | Installs directly as a silent background service on existing Windows 10/11 PC (`<1.2 GB RAM`). Zero extra hardware needed. | **R$ 290 / month** ($59/mo) or **R$ 2.900 / year** (Includes automated POP & ANVISA grammar pack) |
| **Tier 2: Aegis Appliance Box (Turnkey Mini-PC)** | Flagship Compounding Pharmacies (*Manipulação*), Multi-Branch Drogarias (up to 15 counter/lab seats on LAN) | Pre-configured fanless Intel i5/N100 Mini-PC (16GB RAM, 1TB NVMe RAID/Backup). Plugs into pharmacy router in 5 minutes. | **R$ 3.490 one-time hardware + setup** + **R$ 490 / month** support & regulatory update feed |
| **Tier 3: Rede Farmacêutica Fleet** | Regional Pharmacy Chains (5 to 50+ branches) with centralized purchasing & RT oversight | Encrypted `.sovereign-capsule` (`ADR-08`) distributes updated POPs and price tables from HQ to all branches overnight. | **Custom Fleet Agreement** (typically pays for itself in <45 days by preventing a single ANVISA/SNGPC fine or distributor billing error) |
