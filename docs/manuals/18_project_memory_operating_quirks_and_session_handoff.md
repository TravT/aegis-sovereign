---
title: "Manual 18: Project Memory, Operating Quirks & Session Handoff"
category: operations
type: documentation
node: homelab
domain: ai-data
tags:
  - homelab/appliance
  - product/appliance
  - operations/lifecycle
  - operations/runbook
status: active
last_reviewed: 2026-09-30
aliases:
  - Manual 18 Operating Quirks
  - Aegis Project Memory
  - Aegis Gotchas
---

# Manual 18: Project Memory, Operating Quirks & Session Handoff

What a new engineer (or a new agent session) needs that the code and ADRs don't say: where things really live, the quirks that cost time, and the recipes that proved safe. Decisions are in the ADRs ([ADR-12](../adrs/ADR-12-Pluggable-Structure-Extraction-Tier-Size-Policy-and-Search-Time-Deduplication.md), [ADR-13](../adrs/ADR-13-File-Type-Handlers-Conformance-Gate-and-Tiered-Fidelity-Ingestion.md)); how-tos are Manuals [15](15_server_deployment_lifecycle_purge_and_harness_guide.md), [16](16_structure_extraction_tier_profiles_and_adding_a_format.md) and [17](17_file_type_handlers_conformance_gate_and_ingestion_modes.md). Roadmap: Phases 11-14 of the master plan (currently kept under `~/.gemini/antigravity-cli/brain/*/sovereign_appliance_master_architecture_and_execution_plan.md`; moving it into the repo is Task 14.10).

## 1. Where things really live

| Thing | Location / fact |
| :--- | :--- |
| Live vault | `docs/.aegis_vault/sovereign_router.db` (SQLite WAL, ≈600 MB). `sovereign_huawei_router.db` is only a **symlink** to it. Graph DBs: `sovereign_graph.db`, `sovereign_huawei_graph.db` |
| Service | Nomad job `aegis-sovereign` (groups `appliance` + `watcher`, three tasks, **one image**), port 8765, `rag.home.arpa`. Health checks + `auto_revert` are on |
| MCP `sovereign-vault` | `scripts/sovereign_mcp.py`, registered in both agy and Claude Code. It runs **on the host, in-process, from the working tree** of `dev/aegis-sovereign-appliance`: a change to `core/` reaches agents on the next MCP restart with no image; the container only serves HTTP (`/router/query`, `/query`, portal). Running MCP sessions keep old code until restarted |
| Appliance repo | `dev/aegis-sovereign-appliance` is its **own git repo** (remote `TravT/aegis-sovereign`), ignored by Enterprise_Hub. Pushing `main` triggers `docker-publish.yml`, which publishes `ghcr.io/travt/aegis-sovereign` |
| Doc mirrors | Manuals/ADRs exist twice: appliance repo `docs/manuals/`, `docs/adrs/` and the wiki `docs/wiki/appliance/`, `docs/wiki/projects/aegis/adrs/` (**copies**; wiki links are relative to the wiki). Appliance ADR-NN has an alias ADR-(NN+34) symlink. Update both, then `python3 scripts/wiki_lint.py` |
| Safety artifacts | `~/.local/share/aegis-migration-backup/`: pre-change DB copies (≈600 MB each; prune after a week), `rollback.sh`, `rollback_ingest.py`, `rollback_deploy.sh`, the old job file |

## 2. Quirks that cost time

**Data and SQLite**
- `sovereign_inspect_archive` with `purge_prefix` / `relocate_prefix` **mutates the index**. Never use it for read-only work.
- Chunks of one section share a `topic_id` and are all `native`; a container topic (a file whose content lives in sheet/heading children) can have no native of its own. Do not assert "one native per topic" for chunked files.
- `INSERT OR IGNORE` does not deduplicate rows whose primary key contains NULL (a root edge has `parent = NULL`): use `WHERE NOT EXISTS (... parent IS ?)`.
- The FTS5 `integrity-check` is an INSERT: it needs a writable connection (it changes nothing).
- A big UPDATE leaves the WAL near 480 MB until the service checkpoints; that is normal.
- Two indexers still write records without `topic_id` / `record_kind` and one uses `INSERT OR REPLACE`, which blanks them: re-run the ADR-12 runner after re-indexing.

**Containers and deploys**
- Images are pinned `name:tag@sha256:...`. `docker pull name:tag@digest` does **not** move a local `name:tag` if the image is already present: `docker tag name@digest name:tag` and compare image IDs before deploying (and in any rollback). Runbook section 19.
- Run long deploy scripts with `nohup ... &` and poll the log; never split apply / verify / cancel over separate tool calls (a dead-man timer fired between them once and rolled the vault back).
- In zsh write `${IMG}:latest`: a bare `$IMG:latest` triggers the `:l` lowercase modifier.
- `ansible-playbook ... --tags docker` runs every job; only changed ones actually update.

**Git and tests**
- The Enterprise_Hub git user is "Antigravity". Commit as yourself (`git -c user.name=... -c user.email=...`), stage **explicit paths**, and never stage another agent's uncommitted files (currently the `manage-adb` skill edits).
- Scan outgoing commits for secrets before any push (patterns plus the vault values from `scripts/get_secret.py`); Enterprise_Hub pushes use the token-safe recipe in ADR-37 / the project memory.
- Known-red baseline in the appliance repo: 5 failed + 4 errors (`test_benchmark_multitier` x5, `test_desktop` x2, `test_real_world_parsers::test_mcp_7_tools_benchmark_artifacts_exist_and_valid`, `test_telemetry_and_blueprint`). Four more (`test_anti_loop_and_packaging`) fail only when the repo is not at `Enterprise_Hub/dev/aegis-sovereign-appliance`. The packaging test asserts an **exact** manual count: update it when you add a manual.
- The GitHub CI workflow has been red for a long time for a pre-existing reason (two tests need local files); the image build is separate and works.
- Verify your verification: two "unchanged" checks once proved nothing (string vs integer keys). Make a check fail on purpose at least once.

**Antigravity (agy)**
- Headless `agy -p` auto-denies MCP calls unless `permissions.allow` holds `mcp(<server>/<tool>)` (the bare server name does not match). Prefer a narrow rule over `--dangerously-skip-permissions`.
- `agy -p --conversation <id>` appends steps to a stored conversation, but a UI that already has it open will not show them and may later collide. Bounded review prompts (specific ids, a tool-call cap, a word cap) cost about a third of open-ended research.
- agy has a usage quota; work continues without it, and its earlier plans are superseded by this repo's docs.

## 3. The safe-change recipe (proved on the vault and on the image)

1. Snapshot / backup (`sqlite3 db ".backup ..."`, or the SQLite backup API); dry-run first.
2. Write the rollback and **test it on a copy** (it must restore the exact prior state).
3. One script: arm a generous dead-man timer (`systemd-run --user --on-active=45..90min`) → apply → run every verification check → cancel the timer **only if all pass**.
4. Verification covers: nothing outside the intended set changed, structural invariants, FTS integrity, new content searchable, service health, and a real MCP query.
5. Commit only your own paths; update the docs in the same change; lint.

## 4. Session handoff convention

A handoff document lives in the OS temp directory (not the workspace), states the next session's purpose, points to the artifacts above instead of repeating them, lists suggested skills, and carries no secrets. Durable state belongs in this manual, the ADRs, the master plan and the per-user project memory (`MEMORY.md` index), never only in a handoff.
