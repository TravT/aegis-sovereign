### Baseline detail (D0)

| scenario | wall s (min / med / max) | memory.peak MB (min / med / max) | peak - baseline MB | ru_maxrss MB | maxrss - baseline RSS MB | sampled anon peak - base MB | retained RSS MB | load 1m (med) | runs ok |
|---|---|---|---|---|---|---|---|---|---|
| S1 | 1.78 / 1.81 / 1.87 | 1025 / 1025 / 1026 | 1009 | 1040 | 1006 | 1003 | 18.5 | 1.77 | 5/5 |
| S2 | 3.48 / 3.50 / 3.65 | 1028 / 1028 / 1029 | 1012 | 1043 | 1010 | 1008 | 20.1 | 1.43 | 5/5 |
| S3 | 7.72 / 7.83 / 7.86 | 1029 / 1031 / 1031 | 1015 | 1044 | 1012 | 1009 | 18.9 | 1.51 | 5/5 |
| S4 | 1.67 / 1.83 / 2.26 | 1023 / 1023 / 1023 | 1007 | 1037 | 1004 | 1003 | 16.4 | 4.72 | 5/5 |
| S5 | 1.79 / 1.82 / 1.99 | 1025 / 1025 / 1026 | 1009 | 1039 | 1007 | 1001 | 19.5 | 3.81 | 5/5 |
| S6 | OOM-killed 5/5 | | | | | | | | 0/5 |
| S7 | 1.61 / 1.67 / 1.76 | 1023 / 1023 / 1023 | 1007 | 1037 | 1004 | 1000 | 15.5 | 6.38 | 5/5 |
| S8 | 15.89 / 16.10 / 16.24 | 82 / 82 / 82 | 65 | 98 | 65 | 65 | 35.2 | 2.67 | 5/5 |
| S8b | 0.00 / 0.00 / 0.00 | 17 / 17 / 17 | 0 | 34 | 1 | 0 | 0.7 | 1.78 | 5/5 |
| S9 | 7.68 / 7.72 / 7.95 | 1028 / 1031 / 1031 | 1015 | 1045 | 1012 | 1009 | 17.9 | 1.72 | 5/5 |
| S10 | 0.71 / 0.72 / 0.79 | 94 / 94 / 94 | 78 | 110 | 78 | 76 | 11.4 | 1.42 | 5/5 |

### Comparison (median wall time / median peak RSS above the pre-call baseline)

| scenario | D0 | D1 | D2 | D2i | D3 | D4 |
|---|---|---|---|---|---|---|
| S1 | 1.81 s / 1006 MB | 1.39 s / 361 MB | 5.08 s / 66 MB | 1.06 s / 28 MB | 1.05 s / 28 MB | 1.09 s / 28 MB |
| S2 | 3.50 s / 1010 MB | 2.82 s / 362 MB | 10.51 s / 70 MB | 2.18 s / 30 MB | 1.33 s / 28 MB | 1.33 s / 28 MB |
| S3 | 7.83 s / 1012 MB | 6.04 s / 360 MB | 31.63 s / 83 MB | 4.72 s / 28 MB | 1.13 s / 26 MB | 1.18 s / 26 MB |
| S4 | 1.83 s / 1004 MB | 1.28 s / 359 MB | 5.98 s / 83 MB | 1.10 s / 26 MB | 0.91 s / 26 MB | 0.86 s / 26 MB |
| S5 | 1.82 s / 1007 MB | 1.49 s / 361 MB | 5.16 s / 68 MB | 0.99 s / 28 MB | 1.00 s / 29 MB | 1.02 s / 29 MB |
| S6 | OOM-killed 5/5 | 3.40 s / 916 MB | 12.55 s / 230 MB | 2.75 s / 41 MB | 3.49 s / 55 MB | 2.95 s / 55 MB |
| S7 | 1.67 s / 1004 MB | 1.22 s / 359 MB | 4.97 s / 64 MB | 0.91 s / 26 MB | 0.86 s / 26 MB | 0.93 s / 26 MB |
| S8 | 16.10 s / 65 MB | - | - | - | - | - |
| S8b | 0.00 s / 1 MB | - | - | - | - | - |
| S9 | 7.72 s / 1012 MB | 6.06 s / 360 MB | 26.22 s / 82 MB | 4.41 s / 28 MB | 1.54 s / 26 MB | 1.41 s / 26 MB |
| S10 | 0.72 s / 78 MB | 0.71 s / 59 MB | 0.81 s / 59 MB | 0.73 s / 59 MB | 0.73 s / 59 MB | 0.71 s / 59 MB |

### cgroup memory.peak, median MB (includes interpreter + imports, ~25 MB)

| scenario | D0 | D1 | D2 | D2i | D3 | D4 |
|---|---|---|---|---|---|---|
| S1 | 1025 | 379 | 83 | 45 | 45 | 45 |
| S2 | 1028 | 379 | 87 | 47 | 45 | 45 |
| S3 | 1031 | 377 | 100 | 45 | 43 | 43 |
| S4 | 1023 | 376 | 100 | 43 | 43 | 43 |
| S5 | 1025 | 379 | 85 | 45 | 46 | 46 |
| S6 | OOM-killed 5/5 | 936 | 248 | 58 | 72 | 73 |
| S7 | 1023 | 376 | 81 | 43 | 43 | 43 |
| S8 | 82 | - | - | - | - | - |
| S8b | 17 | - | - | - | - | - |
| S9 | 1031 | 378 | 99 | 45 | 43 | 43 |
| S10 | 94 | 76 | 76 | 76 | 76 | 76 |

### Per-call latency, median seconds (resolve_virtual_uri share in brackets)

| call | D0 | D1 | D2 | D2i | D3 | D4 |
|---|---|---|---|---|---|---|
| S1 preview ALM-20104 | 1.814 (1.557) | 1.389 (1.144) | 5.079 (4.833) | 1.058 (0.814) | 1.046 (0.806) | 1.091 (0.849) |
| S2 section=Procedure | 1.766 (1.516) | 1.436 (1.188) | 5.035 (4.793) | 1.094 (0.843) | 1.081 (0.824) | 1.065 (0.832) |
| S2 section=Possible Causes | 1.749 (1.499) | 1.384 (1.151) | 5.492 (5.242) | 1.105 (0.866) | 0.238 (0.000) | 0.248 (0.000) |
| S3 page 0 (char_offset=0) | 1.549 (1.543) | 1.229 (1.222) | 5.932 (5.926) | 0.914 (0.908) | 1.106 (1.100) | 1.176 (1.170) |
| S3 page 1 (char_offset=8000) | 1.546 (1.539) | 1.214 (1.208) | 5.847 (5.841) | 0.908 (0.901) | 0.006 (0.000) | 0.000 (0.000) |
| S3 page 2 (char_offset=16000) | 1.585 (1.579) | 1.178 (1.172) | 5.698 (5.692) | 0.909 (0.905) | 0.006 (0.000) | 0.000 (0.000) |
| S3 page 3 (char_offset=24000) | 1.542 (1.536) | 1.200 (1.194) | 5.921 (5.915) | 1.001 (0.994) | 0.006 (0.000) | 0.000 (0.000) |
| S3 page 4 (char_offset=32000) | 1.549 (1.542) | 1.233 (1.227) | 5.678 (5.669) | 0.964 (0.958) | 0.007 (0.000) | 0.000 (0.000) |
| S4a zip-in-zip (STORED inner) wsdl | 0.091 (0.089) | 0.004 (0.002) | 0.004 (0.002) | 0.004 (0.002) | 0.004 (0.002) | 0.004 (0.002) |
| S4b .hwics member at 94% of inner stream | 1.743 (1.742) | 1.277 (1.277) | 5.978 (5.978) | 1.091 (1.091) | 0.906 (0.906) | 0.859 (0.858) |
| S5a xlsx in ReleaseDoc zip | 0.119 (0.118) | 0.042 (0.040) | 0.039 (0.038) | 0.040 (0.038) | 0.038 (0.037) | 0.040 (0.039) |
| S5b docx in ReleaseDoc zip | 0.100 (0.100) | 0.023 (0.023) | 0.022 (0.022) | 0.023 (0.023) | 0.021 (0.021) | 0.022 (0.022) |
| S5c xlsx inside .hwics | 1.607 (1.603) | 1.422 (1.419) | 5.099 (5.095) | 0.927 (0.924) | 0.931 (0.928) | 0.951 (0.948) |
| S7a /archive/view ALM-20104 html | 1.557 (1.556) | 1.193 (1.192) | 4.945 (4.944) | 0.884 (0.883) | 0.839 (0.839) | 0.905 (0.904) |
| S7b /archive/view docx | 0.105 (0.105) | 0.022 (0.022) | 0.022 (0.022) | 0.022 (0.022) | 0.022 (0.022) | 0.023 (0.023) |
| S8a ingest --dry-run USC ReleaseDoc (142 MB) | 16.096 (0.000) | - | - | - | - | - |
| S8b ingest --dry-run USC product doc (330 MB; .hwics skipped) | 0.001 (0.000) | - | - | - | - | - |
| S9 #1 ALM-20104 (cold) | 1.541 (1.540) | 1.182 (1.182) | 4.897 (4.897) | 0.861 (0.861) | 0.914 (0.914) | 0.866 (0.866) |
| S9 #2 ALM-20104 (repeat) | 1.536 (1.536) | 1.198 (1.198) | 5.026 (5.025) | 0.880 (0.880) | 0.001 (0.000) | 0.000 (0.000) |
| S9 #3 ALM-20104 section=Procedure | 1.520 (1.520) | 1.174 (1.173) | 4.698 (4.698) | 0.862 (0.861) | 0.001 (0.000) | 0.000 (0.000) |
| S9 #4 other member, same archive (94%) | 1.555 (1.555) | 1.203 (1.203) | 5.549 (5.549) | 0.851 (0.850) | 0.552 (0.552) | 0.502 (0.502) |
| S9 #5 other member, same archive (97%, 550 KB) | 1.558 (1.551) | 1.234 (1.228) | 5.709 (5.703) | 0.928 (0.922) | 0.072 (0.066) | 0.065 (0.059) |
| S10 stream_archive listing UPCF ReleaseDoc (19 MB) | 0.717 (0.000) | 0.706 (0.000) | 0.806 (0.000) | 0.725 (0.000) | 0.733 (0.000) | 0.714 (0.000) |

### Equivalence vs D0

- D1|S1: IDENTICAL
- D1|S10: IDENTICAL
- D1|S2: IDENTICAL
- D1|S3: IDENTICAL
- D1|S4: IDENTICAL
- D1|S5: IDENTICAL
- D1|S6: no D0 reference (D0 failed or not run)
- D1|S7: IDENTICAL
- D1|S9: IDENTICAL
- D2i|S1: IDENTICAL
- D2i|S10: IDENTICAL
- D2i|S2: IDENTICAL
- D2i|S3: IDENTICAL
- D2i|S4: IDENTICAL
- D2i|S5: IDENTICAL
- D2i|S6: no D0 reference (D0 failed or not run)
- D2i|S7: IDENTICAL
- D2i|S9: IDENTICAL
- D2|S1: IDENTICAL
- D2|S10: IDENTICAL
- D2|S2: IDENTICAL
- D2|S3: IDENTICAL
- D2|S4: IDENTICAL
- D2|S5: IDENTICAL
- D2|S6: no D0 reference (D0 failed or not run)
- D2|S7: IDENTICAL
- D2|S9: IDENTICAL
- D3|S1: IDENTICAL
- D3|S10: IDENTICAL
- D3|S2: IDENTICAL
- D3|S3: IDENTICAL
- D3|S4: IDENTICAL
- D3|S5: IDENTICAL
- D3|S6: no D0 reference (D0 failed or not run)
- D3|S7: IDENTICAL
- D3|S9: IDENTICAL
- D4|S1: IDENTICAL
- D4|S10: IDENTICAL
- D4|S2: IDENTICAL
- D4|S3: IDENTICAL
- D4|S4: IDENTICAL
- D4|S5: IDENTICAL
- D4|S6: no D0 reference (D0 failed or not run)
- D4|S7: IDENTICAL
- D4|S9: IDENTICAL
