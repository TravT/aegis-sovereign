# Aegis Sovereign Knowledge Appliance

An air-gapped appliance that indexes a team's manuals and notes, answers questions about them with cited evidence, and lets people explore how the material connects. This file is the shared vocabulary of the portal, the API and the docs. It is a glossary only: decisions are in `docs/adrs/`.

## Language

### Asking and answering

**Prong 1**:
An exact lookup of an identifier (an alarm id, an MML command, a lot number), answered deterministically from the index without a language model.
_Avoid_: Fast path, direct search

**Prong 2**:
A natural-language question answered by retrieval across the whole index, with an extractive or generated summary.
_Avoid_: Neural search, AI mode

**Deep synthesis**:
A Prong 2 answer written by the **Local LLM** instead of extracted from the retrieved text. Available only while the Local LLM is on.
_Avoid_: Neural answer

**Citation**:
A passage from a **Document** that supports part of an answer, shown with its place in the **Package**.
_Avoid_: Source, reference

**Local LLM**:
The language model that runs on the appliance host. It is off by default and costs RAM and CPU while on.
_Avoid_: Engine, harness

### The indexed material

**Document**:
A file the appliance has read, such as a manual page, a workbook or a wiki note.
_Avoid_: Source file, asset

**Record**:
One indexed piece of a **Document**, the unit that search returns and **Clearance** is applied to.
_Avoid_: Chunk, row

**Package**:
A documentation set kept as its own tree, such as USC, UPCF or a release-notes set.
_Avoid_: Corpus, collection

**Topic**:
A node in a **Package** tree (a chapter, a page, a sheet) that holds one or more **Records**.
_Avoid_: Section, heading

**Entity**:
A named thing the manuals describe and connect, such as an alarm, an MML command, a KPI, a feature or a release.
_Avoid_: Object, term

**Layer**:
One of the views of the knowledge graph: the manual trees, the entities, or the wiki.
_Avoid_: Corpus, graph type

### Access and plans

**Clearance**:
The highest sensitivity level (public, internal, confidential, restricted) a viewer asks to see. It filters what the server returns; it is not a login.
_Avoid_: Permission, role, access level

**Plan**:
The commercial level of the license (FREE, PRO, ENTERPRISE) that decides which features are on.
_Avoid_: Tier, edition

**Deployment profile**:
The size the appliance is set up for: desktop, edge or datacenter. It sets chunk sizes and limits, never features.
_Avoid_: Tier, size class

### Looking after the index

**Vault**:
The set of databases and indexes on the appliance host that hold every **Record**, **Entity** and graph edge.
_Avoid_: Database, store

**Source folder**:
A folder the appliance watches and keeps indexed.
_Avoid_: Monitored directory, source, corpus path

**Re-sync**:
Reading a **Source folder** again so the **Vault** matches what is on disk now.
_Avoid_: Refresh, reindex

**Remove from index**:
Deletes the **Records** and graph edges that came from a **Source folder** from the **Vault**; the files on disk are never touched. It is permanent until the folder is indexed again.
_Avoid_: Purge, delete, wipe
