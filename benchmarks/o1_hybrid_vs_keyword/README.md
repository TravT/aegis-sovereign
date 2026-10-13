# O1: hybrid vs keyword-only on the vendor manuals

Measured on the live `sovereign_chunks` collection on 13 Oct 2026, right after the manuals were embedded (finding O1).

- **Queries**: the natural-language part of real vendor page titles, with the command code removed. 150 MML command pages and 50 alarm pages, random sample with seed 13.
- **Vendor wording**: the title words as they are (`display optical module information`).
- **Engineer wording**: the leading verb swapped for an everyday phrase (`display` becomes `show me the`, `list` becomes `what are the configured`, `remove` becomes `delete the`, and so on). Alarm titles have no verb, so they stay unchanged.
- **Hit**: the exact page (same `doc_identifier`) in the top k. Keyword-only = the same searcher with the dense leg returning nothing.

| Set | Mode | hit@1 | hit@5 | hit@10 | MRR@10 |
| :--- | :--- | ---: | ---: | ---: | ---: |
| MML, vendor wording (150) | keyword | 44.0% | 93.3% | 98.7% | 0.658 |
| | hybrid | 49.3% | 96.7% | 98.7% | 0.707 |
| MML, engineer wording (150) | keyword | 16.0% | 66.0% | 78.7% | 0.369 |
| | hybrid | 32.0% | 87.3% | 96.7% | 0.560 |
| Alarms (50) | keyword | 50.0% | 96.0% | 98.0% | 0.696 |
| | hybrid | 50.0% | 98.0% | 100.0% | 0.725 |

Hybrid ranked the target lower than keyword-only on 42 of 200 queries (vendor wording) and 27 of 200 (engineer wording). Synthetic paraphrases are a proxy, not real engineer questions.

Run (capped, read-only): `systemd-run --user --scope -p MemoryMax=3G -p CPUQuota=200% .venv/bin/python benchmarks/o1_hybrid_vs_keyword/eval_hybrid_vs_keyword.py 150 [para]`
