/**
 * Aegis Sovereign Web Portal - small force layout for the flat layers (entity graph, wiki).
 *
 * Fruchterman-Reingold (repulsion k^2/d, attraction d^2/k, displacement capped by a cooling
 * temperature), 2D or 3D. Repulsion is exact for a node's own and neighbouring grid cells and uses
 * each far cell's centre of mass otherwise, so a step costs about nodes x cells instead of nodes^2.
 * The tree layer does not use this: its layout is computed on the server.
 */
(function () {
  "use strict";

  class GraphForce {
    /**
     * @param {Float32Array} pos  xyz per node, updated in place
     * @param {Uint32Array} edges node index pairs
     * @param {number} dims 2 or 3
     * @param {number} [k=42] ideal edge length
     */
    constructor(pos, edges, dims, k = 42) {
      this.pos = pos; this.edges = edges; this.dims = dims;
      this.n = pos.length / 3;
      this.k = (this.n < 35 && k === 42) ? 140 : k;       // ideal edge length (spacious breathing room for subgraphs)
      this.tick = 0;
      this.disp = new Float32Array(pos.length);
      const spread = Math.sqrt(this.n) * this.k * 0.9;
      this.temp = spread * 0.08; this.floor = 1.5;
      this.cellsPerAxis = dims === 3 ? 8 : 20;
      this.gravity = this.n < 35 ? 0.08 : 0.15;
      this.seed(spread);
    }

    /** Deterministic scatter (so the same graph settles into the same picture). */
    seed(spread) {
      let s = 1234567;
      const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
      for (let i = 0; i < this.n; i++) {
        this.pos[i * 3] = (rnd() - 0.5) * spread; this.pos[i * 3 + 1] = (rnd() - 0.5) * spread;
        this.pos[i * 3 + 2] = this.dims === 3 ? (rnd() - 0.5) * spread : 0;
      }
    }

    get done() { return this.temp < this.floor; }

    step() {
      const { pos, disp, n, dims, edges, k } = this, k2 = k * k, three = dims === 3, cpa = this.cellsPerAxis;
      let minx = 1e30, miny = 1e30, minz = 1e30, maxx = -1e30, maxy = -1e30, maxz = -1e30;
      for (let i = 0; i < n; i++) {
        const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2];
        if (x < minx) minx = x; if (x > maxx) maxx = x; if (y < miny) miny = y; if (y > maxy) maxy = y;
        if (z < minz) minz = z; if (z > maxz) maxz = z;
      }
      const ext = Math.max(maxx - minx, maxy - miny, three ? maxz - minz : 0, 1) * 1.0001, cell = ext / cpa;
      const zc = three ? cpa : 1, C = cpa * cpa * zc;
      const cellOf = new Int32Array(n), cnt = new Float32Array(C), sx = new Float32Array(C), sy = new Float32Array(C), sz = new Float32Array(C);
      for (let i = 0; i < n; i++) {
        const cx = Math.min(cpa - 1, Math.floor((pos[i * 3] - minx) / cell)), cy = Math.min(cpa - 1, Math.floor((pos[i * 3 + 1] - miny) / cell));
        const cz = three ? Math.min(cpa - 1, Math.floor((pos[i * 3 + 2] - minz) / cell)) : 0;
        const c = (cx * cpa + cy) * zc + cz; cellOf[i] = c;
        cnt[c]++; sx[c] += pos[i * 3]; sy[c] += pos[i * 3 + 1]; sz[c] += pos[i * 3 + 2];
      }
      const start = new Int32Array(C + 1); for (let c = 0; c < C; c++) start[c + 1] = start[c] + cnt[c];
      const fill = start.slice(0, C), members = new Int32Array(n);
      for (let i = 0; i < n; i++) members[fill[cellOf[i]]++] = i;
      const used = []; for (let c = 0; c < C; c++) if (cnt[c]) used.push(c);
      const U = used.length, ux = new Int32Array(U), uy = new Int32Array(U), uz = new Int32Array(U);
      const mx = new Float32Array(U), my = new Float32Array(U), mz = new Float32Array(U), mm = new Float32Array(U);
      for (let u = 0; u < U; u++) {                       // per used cell, once: grid coords and centre of mass
        const c = used[u]; uz[u] = c % zc; uy[u] = Math.floor(c / zc) % cpa; ux[u] = Math.floor(c / (zc * cpa));
        mm[u] = cnt[c]; mx[u] = sx[c] / cnt[c]; my[u] = sy[c] / cnt[c]; mz[u] = sz[c] / cnt[c];
      }

      disp.fill(0);
      for (let i = 0; i < n; i++) {                       // repulsion
        const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2], ci = cellOf[i];
        const icz = ci % zc, icy = Math.floor(ci / zc) % cpa, icx = Math.floor(ci / (zc * cpa));
        let fx = 0, fy = 0, fz = 0;
        for (let u = 0; u < U; u++) {
          const ddx = ux[u] - icx, ddy = uy[u] - icy, ddz = uz[u] - icz;
          if (ddx >= -1 && ddx <= 1 && ddy >= -1 && ddy <= 1 && ddz >= -1 && ddz <= 1) {
            const c = used[u];
            for (let q = start[c]; q < start[c + 1]; q++) {
              const j = members[q]; if (j === i) continue;
              const dx = x - pos[j * 3], dy = y - pos[j * 3 + 1], dz = z - pos[j * 3 + 2];
              const d2 = Math.max(dx * dx + dy * dy + dz * dz, 0.25), f = k2 / d2;
              fx += dx * f; fy += dy * f; fz += dz * f;
            }
          } else {
            const dx = x - mx[u], dy = y - my[u], dz = z - mz[u];
            const f = mm[u] * k2 / Math.max(dx * dx + dy * dy + dz * dz, 0.25);
            fx += dx * f; fy += dy * f; fz += dz * f;
          }
        }
        disp[i * 3] += fx; disp[i * 3 + 1] += fy; disp[i * 3 + 2] += fz;
      }
      for (let e = 0; e < edges.length; e += 2) {         // attraction along edges
        const i = edges[e], j = edges[e + 1];
        const dx = pos[i * 3] - pos[j * 3], dy = pos[i * 3 + 1] - pos[j * 3 + 1], dz = pos[i * 3 + 2] - pos[j * 3 + 2];
        const f = Math.sqrt(dx * dx + dy * dy + dz * dz) / k;
        disp[i * 3] -= dx * f; disp[i * 3 + 1] -= dy * f; disp[i * 3 + 2] -= dz * f;
        disp[j * 3] += dx * f; disp[j * 3 + 1] += dy * f; disp[j * 3 + 2] += dz * f;
      }
      const grav = this.gravity || 0.15;
      for (let i = 0; i < n; i++) {                       // gravity + capped move
        let dx = disp[i * 3] - pos[i * 3] * grav, dy = disp[i * 3 + 1] - pos[i * 3 + 1] * grav, dz = three ? disp[i * 3 + 2] - pos[i * 3 + 2] * grav : 0;
        const len = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (len > 0) { const s = Math.min(len, this.temp) / len; pos[i * 3] += dx * s; pos[i * 3 + 1] += dy * s; pos[i * 3 + 2] += dz * s; }
      }
      this.temp *= 0.975; this.tick++;
    }
  }

  window.AegisGraphForce = GraphForce;
})();
