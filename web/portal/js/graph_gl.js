/**
 * Aegis Sovereign Web Portal - WebGL graph renderer (no third-party code, air-gapped).
 *
 * One pipeline for 2D and 3D: nodes are GL points, edges are GL lines that share the node buffers
 * (an index buffer of node pairs), so ~45k nodes and ~45k edges stay interactive on an office
 * laptop. 2D uses an orthographic camera (pan, zoom); 3D an orbit camera (rotate, pan, zoom).
 * Positions come from the server (tree layer) or from graph_force.js (entity and wiki layers).
 *
 * Node flags (Uint8): 0 normal, 1 dimmed (filtered out), 2 highlighted, 3 selected.
 */
(function () {
  "use strict";

  const VS_POINTS = `#version 300 es
in vec3 aPos; in vec3 aColor; in float aSize; in float aFlag;
uniform mat4 uMVP; uniform float uScale; uniform float uPersp; uniform float uDpr;
out vec3 vColor; out float vFlag;
void main() {
  vec4 p = uMVP * vec4(aPos, 1.0);
  gl_Position = p;
  float atten = uPersp > 0.5 ? clamp(uScale / max(p.w, 0.0001), 0.3, 7.0) : uScale;
  float boost = aFlag > 2.5 ? 2.2 : (aFlag > 1.5 ? 1.6 : 1.0);
  gl_PointSize = max(2.0, aSize * atten * boost) * uDpr;
  vColor = aColor; vFlag = aFlag;
}`;
  const FS_POINTS = `#version 300 es
precision mediump float;
in vec3 vColor; in float vFlag;
out vec4 outColor;
void main() {
  vec2 c = gl_PointCoord * 2.0 - 1.0;
  float d = dot(c, c);
  if (d > 1.0) discard;
  float edge = smoothstep(1.0, 0.7, d);
  bool dim = vFlag > 0.5 && vFlag < 1.5;
  vec3 col = vColor;
  if (vFlag > 2.5) col = d < 0.35 ? vec3(1.0) : mix(col, vec3(1.0), 0.5);
  outColor = vec4(col, (dim ? 0.10 : 0.96) * edge);
}`;
  const VS_LINES = `#version 300 es
in vec3 aPos; in vec3 aColor; in float aFlag;
uniform mat4 uMVP; uniform float uAlpha; uniform vec4 uTint;
out vec4 vColor;
void main() {
  gl_Position = uMVP * vec4(aPos, 1.0);
  float a = (aFlag > 0.5 && aFlag < 1.5) ? uAlpha * 0.15 : uAlpha;
  vColor = uTint.a > 0.0 ? vec4(uTint.rgb, uTint.a) : vec4(aColor, a);
}`;
  const FS_LINES = `#version 300 es
precision mediump float;
in vec4 vColor; out vec4 outColor;
void main() { outColor = vColor; }`;

  // ---- tiny mat4 helpers (column-major) ------------------------------------------------------
  const mul = (a, b) => {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s;
    }
    return o;
  };
  const perspective = (fovy, aspect, near, far) => {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far), o = new Float32Array(16);
    o[0] = f / aspect; o[5] = f; o[10] = (far + near) * nf; o[11] = -1; o[14] = 2 * far * near * nf; return o;
  };
  const ortho = (hw, hh, near, far) => {
    const o = new Float32Array(16);
    o[0] = 1 / hw; o[5] = 1 / hh; o[10] = -2 / (far - near); o[14] = -(far + near) / (far - near); o[15] = 1; return o;
  };
  const lookAt = (eye, target, up) => {
    let zx = eye[0] - target[0], zy = eye[1] - target[1], zz = eye[2] - target[2];
    let l = Math.hypot(zx, zy, zz) || 1; zx /= l; zy /= l; zz /= l;
    let xx = up[1] * zz - up[2] * zy, xy = up[2] * zx - up[0] * zz, xz = up[0] * zy - up[1] * zx;
    let xl = Math.hypot(xx, xy, xz);
    if (xl < 0.0001) {
      const fallbackUp = [0, 1, 0];
      xx = fallbackUp[1] * zz - fallbackUp[2] * zy;
      xy = fallbackUp[2] * zx - fallbackUp[0] * zz;
      xz = fallbackUp[0] * zy - fallbackUp[1] * zx;
      xl = Math.hypot(xx, xy, xz) || 1;
    }
    xx /= xl; xy /= xl; xz /= xl;
    const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
    const o = new Float32Array(16);
    o[0] = xx; o[1] = yx; o[2] = zx; o[4] = xy; o[5] = yy; o[6] = zy; o[8] = xz; o[9] = yz; o[10] = zz;
    o[12] = -(xx * eye[0] + xy * eye[1] + xz * eye[2]);
    o[13] = -(yx * eye[0] + yy * eye[1] + yz * eye[2]);
    o[14] = -(zx * eye[0] + zy * eye[1] + zz * eye[2]); o[15] = 1; return o;
  };

  function compile(gl, type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  function program(gl, vs, fs) {
    const p = gl.createProgram();
    gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs)); gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return p;
  }

  class GraphGL {
    /**
     * @param {HTMLCanvasElement} canvas
     * @param {{background?: number[], onHover?: Function, onClick?: Function, onDblClick?: Function, onView?: Function}} opts
     */
    constructor(canvas, opts = {}) {
      this.canvas = canvas;
      this.opts = opts;
      const gl = canvas.getContext("webgl2", { antialias: true, alpha: false, preserveDrawingBuffer: false });
      if (!gl) throw new Error("WebGL2 is not available in this browser");
      this.gl = gl;
      this.bg = opts.background || [0.02, 0.03, 0.05];
      this.pPoints = program(gl, VS_POINTS, FS_POINTS);
      this.pLines = program(gl, VS_LINES, FS_LINES);
      this.buf = { pos: gl.createBuffer(), color: gl.createBuffer(), size: gl.createBuffer(),
                   flag: gl.createBuffer(), edges: gl.createBuffer(), hot: gl.createBuffer() };
      this.vaoPoints = gl.createVertexArray(); this.vaoLines = gl.createVertexArray(); this.vaoHot = gl.createVertexArray();
      this.n = 0; this.edgeCount = 0; this.hotCount = 0;
      this.pos = new Float32Array(0); this.flags = new Uint8Array(0);
      this.mode = "2d";
      this.cam2 = { cx: 0, cy: 0, scale: 1, fit: 1 };
      this.cam3 = { tx: 0, ty: 0, tz: 0, r: 1000, yaw: 0.8, pitch: 0.5, fit: 1000 };
      this.edgeAlpha = 0.16;
      this.dirty = true; this.frames = 0; this.mvp = new Float32Array(16);
      // slow devices (software GL): hide a dense edge set while the user drags or zooms, redraw when idle
      this.interacting = false; this.slow = false; this._ema = 0; this._lastDraw = 0; this._idle = null;
      this._bindPointer();
      this._ro = new ResizeObserver(() => { this._resize(); this.requestRender(); });
      this._ro.observe(canvas.parentElement || canvas);
      this._resize();
      const loop = () => { if (this.dirty) { this.dirty = false; this.draw(); } this._raf = requestAnimationFrame(loop); };
      loop();
    }

    destroy() { cancelAnimationFrame(this._raf); this._ro.disconnect(); }
    requestRender() { this.dirty = true; }

    _resize() {
      const c = this.canvas, dpr = Math.min(window.devicePixelRatio || 1, 2);
      const box = (c.parentElement || c).getBoundingClientRect();
      const w = Math.max(1, Math.floor(box.width)), h = Math.max(1, Math.floor(box.height));
      this.dpr = dpr; this.w = w; this.h = h;
      c.width = Math.floor(w * dpr); c.height = Math.floor(h * dpr);
      c.style.width = w + "px"; c.style.height = h + "px";
    }

    /** Upload the graph. pos: Float32Array(3n), color: Float32Array(3n), size: Float32Array(n), edges: Uint32Array(2m). */
    setData({ pos, color, size, edges }) {
      const gl = this.gl;
      this.n = size.length; this.edgeCount = edges.length / 2;
      this.pos = pos; this.flags = new Uint8Array(this.n);
      gl.bindVertexArray(this.vaoPoints);
      this._attr("aPos", this.buf.pos, pos, 3);
      this._attr("aColor", this.buf.color, color, 3);
      this._attr("aSize", this.buf.size, size, 1);
      this._attr("aFlag", this.buf.flag, this.flags, 1, gl.UNSIGNED_BYTE);
      gl.bindVertexArray(this.vaoLines);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.pos); this._pointer(this.pLines, "aPos", 3);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.color); this._pointer(this.pLines, "aColor", 3);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.flag); this._pointer(this.pLines, "aFlag", 1, gl.UNSIGNED_BYTE);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.buf.edges);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, edges, gl.STATIC_DRAW);
      gl.bindVertexArray(this.vaoHot);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.pos); this._pointer(this.pLines, "aPos", 3);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.color); this._pointer(this.pLines, "aColor", 3);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.flag); this._pointer(this.pLines, "aFlag", 1, gl.UNSIGNED_BYTE);
      gl.bindVertexArray(null);
      this.hotCount = 0;
      this.requestRender();
    }

    /** Upload ``data`` to ``buffer`` and bind it to the points program's attribute ``name``. */
    _attr(name, buffer, data, size, type) {
      const gl = this.gl;
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
      this._pointer(this.pPoints, name, size, type);
    }
    _pointer(prog, name, size, type) {
      const gl = this.gl, loc = gl.getAttribLocation(prog, name);
      if (loc < 0) return;
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, type || gl.FLOAT, false, 0, 0);
    }

    /** Positions changed in place (force layout): re-upload them. */
    updatePositions() {
      const gl = this.gl;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.pos); gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.pos);
      this.requestRender();
    }
    setColors(color) {
      const gl = this.gl;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.color); gl.bufferSubData(gl.ARRAY_BUFFER, 0, color);
      this.requestRender();
    }
    setFlags(flags) {
      const gl = this.gl; this.flags = flags;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.flag); gl.bufferSubData(gl.ARRAY_BUFFER, 0, flags);
      this.requestRender();
    }
    /** Edges (node index pairs) drawn on top in the accent colour, e.g. those of the selected node. */
    setHotEdges(pairs) {
      const gl = this.gl;
      gl.bindVertexArray(this.vaoHot);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.buf.hot);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, pairs, gl.DYNAMIC_DRAW);
      gl.bindVertexArray(null);
      this.hotCount = pairs.length / 2; this.requestRender();
    }

    setMode(mode) { this.mode = mode; this.requestRender(); this._emitView(); }

    /** Frame the graph (2D: bounding box of x,y; 3D: distance to the farthest node). ``robust``
     *  ignores the outermost 1% so a few far-flung nodes do not shrink the picture. */
    fit(robust) {
      const p = this.pos, n = this.n; if (!n) return;
      const xs = new Float32Array(n), ys = new Float32Array(n), rs = new Float32Array(n);
      for (let i = 0; i < n; i++) { xs[i] = p[i * 3]; ys[i] = p[i * 3 + 1]; rs[i] = Math.hypot(p[i * 3], p[i * 3 + 1], p[i * 3 + 2]); }
      const q = (a, f) => { if (!robust) return f < 0.5 ? a.reduce((m, v) => Math.min(m, v), 1e30) : a.reduce((m, v) => Math.max(m, v), -1e30); const b = a.slice().sort(); return b[Math.min(n - 1, Math.max(0, Math.floor(f * (n - 1))))]; };
      const minx = q(xs, 0.01 * (robust ? 1 : 0)), maxx = q(xs, robust ? 0.99 : 1), miny = q(ys, 0.01 * (robust ? 1 : 0)), maxy = q(ys, robust ? 0.99 : 1);
      const far = Math.max(1, q(rs, robust ? 0.99 : 1));
      const c2 = this.cam2, c3 = this.cam3;
      c2.cx = (minx + maxx) / 2; c2.cy = (miny + maxy) / 2;
      c2.scale = c2.fit = Math.min(this.w / Math.max(1, maxx - minx), this.h / Math.max(1, maxy - miny)) * 0.92;
      c3.tx = c3.ty = c3.tz = 0; c3.r = c3.fit = far * 2.6;
      this.requestRender(); this._emitView();
    }

    matrix() {
      const aspect = this.w / this.h;
      if (this.mode === "2d") {
        const c = this.cam2;
        const vp = ortho(this.w / (2 * c.scale), this.h / (2 * c.scale), -1, 1);
        const t = new Float32Array(16); t[0] = t[5] = t[10] = t[15] = 1; t[12] = -c.cx; t[13] = -c.cy;
        return mul(vp, t);
      }
      const c = this.cam3;
      const eye = [c.tx + c.r * Math.cos(c.pitch) * Math.cos(c.yaw),
                   c.ty + c.r * Math.cos(c.pitch) * Math.sin(c.yaw),
                   c.tz + c.r * Math.sin(c.pitch)];
      return mul(perspective(0.9, aspect, c.r * 0.01, c.r * 30), lookAt(eye, [c.tx, c.ty, c.tz], [0, 0, 1]));
    }

    /** Mark the view as being manipulated; a full redraw follows shortly after the last input. */
    _touch() {
      this.interacting = true;
      clearTimeout(this._idle);
      this._idle = setTimeout(() => { this.interacting = false; this._ema = 0; this.requestRender(); }, 180);
    }

    draw() {
      const gl = this.gl, t0 = performance.now();
      if (this.interacting && this._lastDraw) {        // frame interval while interacting decides "slow"
        this._ema = this._ema * 0.7 + (t0 - this._lastDraw) * 0.3;
        this.slow = this._ema > 45;
      }
      this._lastDraw = t0;
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.clearColor(this.bg[0], this.bg[1], this.bg[2], 1); gl.clear(gl.COLOR_BUFFER_BIT);
      if (!this.n) return;
      gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.disable(gl.DEPTH_TEST);
      this.mvp = this.matrix();
      const persp = this.mode === "3d" ? 1 : 0;
      const scale = persp ? this.cam3.fit : Math.pow(Math.max(this.cam2.scale / this.cam2.fit, 0.05), 0.55);
      const liteEdges = this.interacting && this.slow && this.edgeCount > 8000;
      if (this.edgeCount && !liteEdges) {
        gl.useProgram(this.pLines);
        gl.uniformMatrix4fv(gl.getUniformLocation(this.pLines, "uMVP"), false, this.mvp);
        gl.uniform1f(gl.getUniformLocation(this.pLines, "uAlpha"), this.edgeAlpha);
        gl.uniform4f(gl.getUniformLocation(this.pLines, "uTint"), 0, 0, 0, 0);
        gl.bindVertexArray(this.vaoLines);
        gl.drawElements(gl.LINES, this.edgeCount * 2, gl.UNSIGNED_INT, 0);
      }
      gl.useProgram(this.pPoints);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.pPoints, "uMVP"), false, this.mvp);
      gl.uniform1f(gl.getUniformLocation(this.pPoints, "uScale"), scale);
      gl.uniform1f(gl.getUniformLocation(this.pPoints, "uPersp"), persp);
      gl.uniform1f(gl.getUniformLocation(this.pPoints, "uDpr"), this.dpr);
      gl.bindVertexArray(this.vaoPoints);
      gl.drawArrays(gl.POINTS, 0, this.n);
      if (this.hotCount) {
        gl.useProgram(this.pLines);
        gl.uniformMatrix4fv(gl.getUniformLocation(this.pLines, "uMVP"), false, this.mvp);
        gl.uniform4f(gl.getUniformLocation(this.pLines, "uTint"), 1.0, 0.86, 0.35, 0.9);
        gl.bindVertexArray(this.vaoHot);
        gl.drawElements(gl.LINES, this.hotCount * 2, gl.UNSIGNED_INT, 0);
      }
      gl.bindVertexArray(null);
      this.frames++; this.lastDrawMs = performance.now() - t0;
      this._emitView();
    }

    /** Screen position (CSS px) and view depth of node i under the current camera, or null if behind. */
    project(i, out) {
      const m = this.mvp, p = this.pos, x = p[i * 3], y = p[i * 3 + 1], z = p[i * 3 + 2];
      const w = m[3] * x + m[7] * y + m[11] * z + m[15];
      if (w <= 0) return null;
      const cx = (m[0] * x + m[4] * y + m[8] * z + m[12]) / w, cy = (m[1] * x + m[5] * y + m[9] * z + m[13]) / w;
      out.x = (cx * 0.5 + 0.5) * this.w; out.y = (1 - (cy * 0.5 + 0.5)) * this.h; out.w = w;
      return out;
    }

    /** The nearest visible node within radius px of (px, py), preferring the one closest to the camera. */
    pick(px, py, radius = 9) {
      const out = { x: 0, y: 0, w: 0 }; let best = -1, bestScore = 1e30;
      for (let i = 0; i < this.n; i++) {
        if (this.flags[i] === 1) continue;
        if (!this.project(i, out)) continue;
        const dx = out.x - px, dy = out.y - py, d = dx * dx + dy * dy;
        if (d > radius * radius) continue;
        const score = d + (this.mode === "3d" ? out.w * 1e-3 : 0);
        if (score < bestScore) { bestScore = score; best = i; }
      }
      return best;
    }

    /** Move the camera so node i is centred (keeps the zoom). */
    focusOn(i) {
      const p = this.pos;
      this.cam2.cx = p[i * 3]; this.cam2.cy = p[i * 3 + 1];
      this.cam3.tx = p[i * 3]; this.cam3.ty = p[i * 3 + 1]; this.cam3.tz = p[i * 3 + 2];
      this.requestRender();
    }
    zoomBy(f) {
      if (this.mode === "2d") this.cam2.scale = Math.min(this.cam2.fit * 400, Math.max(this.cam2.fit * 0.5, this.cam2.scale * f));
      else this.cam3.r = Math.min(this.cam3.fit * 4, Math.max(this.cam3.fit * 0.002, this.cam3.r / f));
      this.requestRender();
    }
    _emitView() { if (this.opts.onView) this.opts.onView(this); }

    // ---- input ---------------------------------------------------------------------------------
    _bindPointer() {
      const c = this.canvas, pointers = new Map(); let moved = 0, lastTap = 0;
      c.style.touchAction = "none";
      const rect = () => c.getBoundingClientRect();
      c.addEventListener("pointerdown", (e) => {
        this._touch();
        c.setPointerCapture(e.pointerId); pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, button: e.button, shift: e.shiftKey });
        moved = 0;
      });
      c.addEventListener("pointermove", (e) => {
        const prev = pointers.get(e.pointerId);
        if (!prev) {
          const r = rect(), i = this.pick(e.clientX - r.left, e.clientY - r.top);
          if (i !== this._hover) { this._hover = i; if (this.opts.onHover) this.opts.onHover(i, e); c.style.cursor = i >= 0 ? "pointer" : "grab"; }
          return;
        }
        const dx = e.clientX - prev.x, dy = e.clientY - prev.y; moved += Math.abs(dx) + Math.abs(dy);
        this._touch();
        if (pointers.size === 2) {                       // pinch: zoom, and pan by the centroid
          const [a, b] = [...pointers.values()];
          const before = Math.hypot(a.x - b.x, a.y - b.y);
          prev.x = e.clientX; prev.y = e.clientY;
          const [a2, b2] = [...pointers.values()];
          const after = Math.hypot(a2.x - b2.x, a2.y - b2.y);
          if (before > 0) this.zoomBy(after / before);
          this._pan(dx / 2, dy / 2);
        } else {
          prev.x = e.clientX; prev.y = e.clientY;
          if (this.mode === "3d" && prev.button === 0 && !prev.shift) {
            this.cam3.yaw -= dx * 0.006;
            this.cam3.pitch = Math.max(-1.46, Math.min(1.46, this.cam3.pitch + dy * 0.006));
            this.requestRender();
          } else this._pan(dx, dy);
        }
      });
      const up = (e) => {
        const was = pointers.get(e.pointerId); pointers.delete(e.pointerId);
        if (was && moved < 5 && e.type === "pointerup") {
          const r = rect(), i = this.pick(e.clientX - r.left, e.clientY - r.top, 12), now = performance.now();
          if (now - lastTap < 320 && i >= 0 && this.opts.onDblClick) this.opts.onDblClick(i, e);
          else if (this.opts.onClick) this.opts.onClick(i, e);
          lastTap = now;
        }
      };
      c.addEventListener("pointerup", up); c.addEventListener("pointercancel", up);
      c.addEventListener("contextmenu", (e) => e.preventDefault());
      c.addEventListener("wheel", (e) => {
        e.preventDefault();
        this._touch();
        const f = Math.exp(-e.deltaY * 0.0015);
        if (this.mode === "2d") {                        // zoom about the cursor
          const r = rect(), cam = this.cam2;
          const wx = cam.cx + (e.clientX - r.left - this.w / 2) / cam.scale, wy = cam.cy - (e.clientY - r.top - this.h / 2) / cam.scale;
          this.zoomBy(f);
          cam.cx = wx - (e.clientX - r.left - this.w / 2) / cam.scale; cam.cy = wy + (e.clientY - r.top - this.h / 2) / cam.scale;
        } else this.zoomBy(f);
        this.requestRender();
      }, { passive: false });
    }
    _pan(dx, dy) {
      if (this.mode === "2d") { this.cam2.cx -= dx / this.cam2.scale; this.cam2.cy += dy / this.cam2.scale; }
      else {
        const c = this.cam3, k = c.r * 0.0016;
        const rx = -Math.sin(c.yaw), ry = Math.cos(c.yaw);              // camera right
        const ux = -Math.sin(c.pitch) * Math.cos(c.yaw), uy = -Math.sin(c.pitch) * Math.sin(c.yaw), uz = Math.cos(c.pitch); // camera up
        c.tx -= (rx * dx - ux * dy) * k;
        c.ty -= (ry * dx - uy * dy) * k;
        c.tz += (uz * dy) * k;
      }
      this.requestRender();
    }
  }

  window.AegisGraphGL = GraphGL;
})();
