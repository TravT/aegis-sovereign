# U8: calibrated confidence for hybrid hits

Measured on the live `sovereign_chunks` collection (EmbeddingGemma 768-d + BM25) on 13 Oct 2026, for finding U8: correct answers showed `Confidence: LOW_UNVERIFIED (0.03)` because the RRF score was displayed as a confidence. RRF (k=60) is rank-based: about 0.033 for any first hit.

- **In-domain**: 80 engineer-worded MML titles (same rewording as the O1 A/B, seed 7, so the curve is not fitted to the A/B sample).
- **Off-topic**: 30 questions the manuals cannot answer (cooking, sport, consumer IT).
- **Signal**: the best dense cosine among the top 5 fused hits, and whether a hit is in both legs' top 10.

| Group | Queries | Best cosine min | p10 | median | p90 | max | Both legs agree |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| In-domain, right command in top 5 | 77 | 0.761 | 0.775 | 0.810 | 0.840 | 0.863 | 72 |
| In-domain, right command missed | 3 | 0.756 | | 0.766 | | 0.817 | 3 |
| Off-topic | 30 | 0.547 | 0.561 | 0.596 | 0.674 | 0.762 | 6 |

The cosine separates the groups; rank agreement alone does not (6 of 30 off-topic queries agree).

**Curve** (`core/search/confidence.py`): cosine 0.60 → 0.00, 0.70 → 0.35 (the refusal floor), 0.78 → 0.75, 0.86 → 0.95, linear in between. A hit BM25 did not find is capped at 0.74 (never HIGH); a keyword-only hit gets 0.30. Unmeasured dimensions (256-d wiki, 384-d MiniLM) use rank agreement only: 0.60 when both legs have it in their top 10, else 0.40.

With this curve all 80 in-domain queries clear the 0.35 floor (weakest: 0.63; 66 of 80 reach HIGH, 0.75 or more) and 28 of 30 off-topic queries fall below it (the exceptions: "list the docker containers", 0.762, and "set up a kubernetes ingress controller", 0.711; none reaches HIGH, the highest is 0.66). The floor stays at 0.35. The RRF score still orders the results; only the confidence changed, so the O1 A/B numbers cannot move.

Run (capped, read-only): `systemd-run --user --scope -p MemoryMax=3G -p CPUQuota=200% .venv/bin/python benchmarks/u8_confidence_calibration/collect_signals.py 80 > signals.jsonl`. Raw output of the 13 Oct run: `signals_2026-10-13.jsonl`.
