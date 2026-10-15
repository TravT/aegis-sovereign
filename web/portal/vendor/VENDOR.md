# Vendored front-end libraries

The portal is air-gapped (no CDN at run time), so these ship inside the image, pinned.
Fetched from the npm registry on 2026-10-14; each tarball matched the registry's `dist.integrity` (sha512) before extraction.
`tests/test_portal_rendering_r12.py` checks the sha256 values below.

| Library | Version | License | File | sha256 |
| :--- | :--- | :--- | :--- | :--- |
| Mermaid | 12.2.0 | MIT | `mermaid-12.2.0/mermaid.min.js` | `a8a6a6f805b074a8261a2825c86f99c8054acb3b35f50bb7e24a4f9f2c3c3b9f` |
| KaTeX | 0.19.0 | MIT | `katex-0.19.0/katex.min.js` | `103a53763cc033bba8d175bf3f0ba597c3505c9b6747dd3f2c7bc2a6bfcc8ae7` |
| KaTeX | 0.19.0 | MIT | `katex-0.19.0/katex.min.css` | `d4ab5b8ee16989b070cdb0ea24bd6ad48fc8df1b787f280f29d3ae4f959f2c00` |

Only the `woff2` KaTeX fonts are kept: `katex.min.css` lists `woff2` first, and every browser the portal targets loads it.
Mermaid (5.5 MB) is loaded only when a document contains a diagram.

To upgrade: download the new tarball, check `dist.integrity`, replace the directory (new version in the path), update this table and the test.
