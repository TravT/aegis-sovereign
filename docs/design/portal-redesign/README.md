# Portal redesign prototypes (ADR-15)

Three static, mock-data prototypes of a mobile-first portal: **A** (search-first app shell, chosen), **B** (command bar with an answer log), **C** (graph-first with a results sheet). No build step, no external requests.

```bash
cd docs/design/portal-redesign/prototype
python3 -m http.server 8850 --bind 127.0.0.1      # or --bind <tailnet address> to try it on a phone
# then open http://127.0.0.1:8850/index.html?variant=A   (B, C)
```

The graph screen is a static picture standing in for the WebGL explorer (`web/portal/js/graph_*.js`). Screenshots and capture scripts are kept out of git in `studies/2026-10-01/portal-redesign/` (gitignored). The decision and the plan are in ADR-15 and the wiki study notes (`docs/wiki/projects/aegis/studies/` in Enterprise_Hub).
