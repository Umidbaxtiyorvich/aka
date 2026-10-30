// JARVIS — 3D Brain Mode + Graph Explorer Mode + Memory Explorer + Neural Activity.
// Hamma ma'lumot backend'dan: /api/brain/state, /api/kg/graph, /api/memory/*, jonli hodisalar /api/events/stream (SSE).
// 3D miya — protsedura yo'li bilan yaratilgan model (skaner qilingan anatomik model EMAS) va JARVIS modullarining vizual ifodasi.
"use strict";

// ---------------- Umumiy holat (rejimlar o'rtasida saqlanadi) ----------------
const BrainState = {
  mode: "brain", quality: (() => { try { return localStorage.getItem("brain_quality") || "medium"; } catch (e) { return "medium"; } })(),
  selected: null, filters: { categories: [], q: "", since: "", until: "", source: "", neighborsOnly: false, showEdges: true },
  focusRegion: null,
};
const CAT_STYLE = {
  memories: ["#22d3ee", "🧠"], knowledge: ["#3b82f6", "📘"], projects: ["#f59e0b", "📁"], files: ["#94a3b8", "📄"], tasks: ["#a855f7", "✅"],
  agents: ["#8b5cf6", "🤖"], conversations: ["#06b6d4", "💬"], decisions: ["#eab308", "⚖️"], skills: ["#10b981", "🛠"], errors: ["#ef4444", "⚠️"],
  solutions: ["#22c55e", "💡"], apis: ["#0ea5e9", "🔌"], instagram: ["#ec4899", "📸"], telegram: ["#38bdf8", "✈️"], business: ["#f97316", "📊"],
};
const CAT_REGION = { memories: "memory", knowledge: "memory", files: "memory", projects: "planning", tasks: "planning", solutions: "planning",
  agents: "agents", skills: "agents", business: "agents", conversations: "language", telegram: "language", decisions: "reasoning",
  apis: "reasoning", errors: "security", instagram: "creative" };
const REGION_CATS = { memory: ["memories", "knowledge", "files"], reasoning: ["decisions", "apis"], planning: ["projects", "tasks", "solutions"],
  language: ["conversations", "telegram"], vision: ["files"], creative: ["instagram"], agents: ["agents", "skills", "business"], security: ["errors"] };
const QUALITY = { low: { seg: [96, 64], neurons: 500, pixel: 1, maxNodes: 2000, glow: false },
  medium: { seg: [160, 112], neurons: 1400, pixel: 1.25, maxNodes: 5000, glow: true },
  high: { seg: [256, 180], neurons: 2800, pixel: 2, maxNodes: 10000, glow: true } };

// ---------------- Kutubxonani kerak bo'lganda yuklash (8 GB RAM uchun) ----------------
let threeLoading = null;
function loadThree() {
  if (window.THREE && THREE.OrbitControls) return Promise.resolve(true);
  if (threeLoading) return threeLoading;
  const add = (src) => new Promise((ok, bad) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = () => bad(new Error(src)); document.head.appendChild(s); });
  threeLoading = add("/static/vendor/three/three.min.js").then(() => add("/static/vendor/three/OrbitControls.js")).then(() => true);
  return threeLoading;
}
function webglOK() {
  try { const c = document.createElement("canvas"); return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl"))); } catch (e) { return false; }
}

// ---------------- Jonli hodisalar (SSE) ----------------
const Live = {
  es: null, online: null, listeners: new Set(), counts: {}, log: [], lastSeq: 0,
  start() {
    if (this.es) return;
    try { this.es = new EventSource("/api/events/stream"); } catch (e) { this.set(false); return; }
    this.es.addEventListener("hello", () => this.set(true));
    this.es.addEventListener("ping", () => this.set(true));
    this.es.addEventListener("jarvis", (m) => { let e; try { e = JSON.parse(m.data); } catch (er) { return; }
      this.set(true); this.lastSeq = e.seq; this.counts[e.type] = (this.counts[e.type] || 0) + 1;
      this.log.unshift(e); if (this.log.length > 300) this.log.length = 300;
      this.listeners.forEach((f) => { try { f(e); } catch (er) { console.debug(er); } }); });
    this.es.onerror = () => this.set(false);           // EventSource o'zi qayta ulanadi
  },
  set(v) { if (this.online === v) return; this.online = v; document.querySelectorAll(".live-badge").forEach((b) => paintBadge(b)); this.listeners.forEach((f) => { try { f({ type: "_conn", online: v }); } catch (er) { /* */ } }); },
  on(f) { this.listeners.add(f); return () => this.listeners.delete(f); },
};
function paintBadge(b) {
  b.className = "live-badge " + (Live.online ? "on" : Live.online === false ? "off" : "wait");
  b.textContent = Live.online ? "● LIVE" : Live.online === false ? "● OFFLINE" : "● ulanmoqda…";
  b.title = Live.online ? "Backend hodisalari real vaqtda kelmoqda (SSE)" : "Backend bilan jonli aloqa yo'q — ko'rsatilgan ma'lumot oxirgi yuklangan holat";
}
const liveBadge = () => { const b = document.createElement("span"); paintBadge(b); return b.outerHTML; };

// Bo'lim almashganda 3D sahnalarni to'xtatish va xotirani bo'shatish
const VIZ = { items: new Set(), cleanup() { this.items.forEach((v) => { try { v.dispose(); } catch (e) { /* */ } }); this.items.clear(); } };
window.JARVIS_VIZ = VIZ;

// ---------------- Kichik shovqin funksiyasi (miya burmalari uchun) ----------------
const Noise = (() => {
  const p = new Uint8Array(512); let s = 1337;
  const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const perm = [...Array(256).keys()]; for (let i = 255; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [perm[i], perm[j]] = [perm[j], perm[i]]; }
  for (let i = 0; i < 512; i++) p[i] = perm[i & 255];
  const fade = (t) => t * t * t * (t * (t * 6 - 15) + 10), lerp = (t, a, b) => a + t * (b - a);
  const grad = (h, x, y, z) => { const u = (h & 15) < 8 ? x : y, v = (h & 15) < 4 ? y : (h & 15) === 12 || (h & 15) === 14 ? x : z; return ((h & 1) ? -u : u) + ((h & 2) ? -v : v); };
  function n3(x, y, z) {
    const X = Math.floor(x) & 255, Y = Math.floor(y) & 255, Z = Math.floor(z) & 255; x -= Math.floor(x); y -= Math.floor(y); z -= Math.floor(z);
    const u = fade(x), v = fade(y), w = fade(z), A = p[X] + Y, AA = p[A] + Z, AB = p[A + 1] + Z, B = p[X + 1] + Y, BA = p[B] + Z, BB = p[B + 1] + Z;
    return lerp(w, lerp(v, lerp(u, grad(p[AA], x, y, z), grad(p[BA], x - 1, y, z)), lerp(u, grad(p[AB], x, y - 1, z), grad(p[BB], x - 1, y - 1, z))),
      lerp(v, lerp(u, grad(p[AA + 1], x, y, z - 1), grad(p[BA + 1], x - 1, y, z - 1)), lerp(u, grad(p[AB + 1], x, y - 1, z - 1), grad(p[BB + 1], x - 1, y - 1, z - 1))));
  }
  // "Ridged" ko'p oktavali shovqin: tor qirralar (giruslar) va chuqur egatlar (sulkuslar)
  function ridged(x, y, z, oct = 4) { let a = 0, amp = 0.55, f = 1; for (let i = 0; i < oct; i++) { const r = 1 - Math.abs(n3(x * f, y * f, z * f)); a += r * r * amp; amp *= 0.5; f *= 2.03; } return a; }
  return { n3, ridged };
})();

function glowTexture(color = "#ffffff") {
  const c = document.createElement("canvas"); c.width = c.height = 64; const g = c.getContext("2d");
  const r = g.createRadialGradient(32, 32, 0, 32, 32, 32); r.addColorStop(0, color); r.addColorStop(0.25, color); r.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = r; g.fillRect(0, 0, 64, 64); const t = new THREE.CanvasTexture(c); return t;
}

// ================= 3D BRAIN =================
// Hudud markazlari (miya koordinatalarida: x — chap/o'ng, y — yuqori, z — old(+)/orqa(-))
const REGION_POS = {
  planning: [0.0, 0.62, 0.95], reasoning: [-0.42, 0.42, 0.98], language: [-1.12, -0.12, 0.42], memory: [0.95, -0.38, 0.05],
  vision: [0.0, 0.18, -1.22], creative: [0.9, 0.55, -0.25], agents: [-0.55, 0.88, -0.42], security: [0.0, -0.95, -0.72],
};

class Brain3D {
  constructor(host, onPick) { this.host = host; this.onPick = onPick; this.activity = {}; this.status = {}; this.disposed = false; this.fps = 0; this.lowFps = 0; }
  init(quality) {
    const q = QUALITY[quality] || QUALITY.medium, W = this.host.clientWidth || 800, H = this.host.clientHeight || 560;
    this.q = q;
    const r = this.renderer = new THREE.WebGLRenderer({ antialias: quality !== "low", alpha: true, preserveDrawingBuffer: false, powerPreference: "low-power" });
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, q.pixel)); r.setSize(W, H); this.host.appendChild(r.domElement);
    const sc = this.scene = new THREE.Scene(); sc.fog = new THREE.FogExp2(0x030712, 0.08);
    const cam = this.camera = new THREE.PerspectiveCamera(40, W / H, 0.1, 100); cam.position.set(2.7, 1.1, 2.6);
    const ctl = this.controls = new THREE.OrbitControls(cam, r.domElement); ctl.enableDamping = true; ctl.minDistance = 2.2; ctl.maxDistance = 9; ctl.autoRotate = true; ctl.autoRotateSpeed = 0.5;
    sc.add(new THREE.AmbientLight(0x6b7bb5, 0.55));
    const k = new THREE.DirectionalLight(0xbfd8ff, 1.1); k.position.set(3, 4, 2); sc.add(k);
    const rim = new THREE.PointLight(0x8b5cf6, 1.4, 12); rim.position.set(-3, 1, -3); sc.add(rim);
    const gold = new THREE.PointLight(0xf5c451, 0.7, 10); gold.position.set(2, -2, 3); sc.add(gold);
    this.root = new THREE.Group(); sc.add(this.root);
    this.buildCortex(q); this.buildCerebellum(q); this.buildStem(); this.buildNeurons(q); this.buildRegions();
    this.pulses = []; this.pulseTex = glowTexture("#ffffff");
    this.ray = new THREE.Raycaster(); this.mouse = new THREE.Vector2();
    this.onClick = (ev) => this.pick(ev); r.domElement.addEventListener("pointerdown", (e) => { this._down = [e.clientX, e.clientY]; });
    r.domElement.addEventListener("pointerup", (e) => { if (this._down && Math.hypot(e.clientX - this._down[0], e.clientY - this._down[1]) < 5) this.pick(e); });
    this.onResize = () => { const w = this.host.clientWidth, h = this.host.clientHeight; if (!w || !h) return; cam.aspect = w / h; cam.updateProjectionMatrix(); r.setSize(w, h); };
    window.addEventListener("resize", this.onResize);
    this.clock = new THREE.Clock(); this.frames = 0; this.fpsT = 0; this.loop = this.loop.bind(this); this.raf = requestAnimationFrame(this.loop);
    return this;
  }
  // Yarim shar: sfera → miya shakli (old peshona, chakka bo'lagi, tekis pastki qism, medial tekislik) + ridged shovqin bilan burmalar
  hemisphere(side, q) {
    const g = new THREE.SphereGeometry(1, q.seg[0], q.seg[1]), pos = g.attributes.position, col = new Float32Array(pos.count * 3), v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i);
      let x = v.x * 0.72, y = v.y * 0.78, z = v.z * 1.12;
      if (side * v.x < 0) x *= 0.32;                               // medial yuza (o'rta egat tomoni) tekis
      if (y < -0.18) y = -0.18 + (y + 0.18) * 0.55;                 // pastki qism tekisroq
      const temporal = Math.exp(-((v.y + 0.45) ** 2) / 0.05) * Math.exp(-((v.z - 0.15) ** 2) / 0.35);
      x += side * temporal * 0.14 * Math.max(0, side * v.x); y -= temporal * 0.06;   // chakka bo'lagi
      z += Math.max(0, v.z) * 0.06 * (1 - Math.abs(v.y));                           // peshona bo'lagi
      if (v.z < -0.55 && v.y < 0) y += (v.z + 0.55) * 0.25;                          // ensa pastida miyacha uchun joy
      const px = x * 5.2 + side * 7, py = y * 5.2, pz = z * 5.2;
      const ridge = Noise.ridged(px, py, pz, 4);                                     // 0..~1: yuqori — girus, past — sulkus
      const sulcusMain = Math.exp(-((v.z - 0.05 + v.y * 0.35) ** 2) / 0.0025) * (v.y > -0.1 ? 1 : 0);  // markaziy egat (Rolando)
      const lateral = Math.exp(-((v.y + 0.12 - v.z * 0.25) ** 2) / 0.002) * (side * v.x > 0.3 ? 1 : 0); // lateral (Silviy) egat
      const d = 0.085 * ridge - 0.07 * sulcusMain - 0.08 * lateral;
      const n = new THREE.Vector3(x, y, z).normalize();
      x += n.x * d; y += n.y * d; z += n.z * d;
      pos.setXYZ(i, x + side * 0.03, y, z);
      const shade = Math.min(1, Math.max(0, -0.15 + ridge * 1.35 - sulcusMain * 0.7 - lateral * 0.7));
      col[i * 3] = 0.16 + shade * 0.55; col[i * 3 + 1] = 0.22 + shade * 0.6; col[i * 3 + 2] = 0.42 + shade * 0.5;
    }
    g.setAttribute("color", new THREE.BufferAttribute(col, 3)); g.computeVertexNormals(); return g;
  }
  buildCortex(q) {
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.42, metalness: 0.18, transparent: true, opacity: 0.9,
      emissive: new THREE.Color(0x0b2a5a), emissiveIntensity: 0.45, depthWrite: true });
    this.cortexMat = mat; this.hemis = [];
    for (const side of [-1, 1]) {
      const m = new THREE.Mesh(this.hemisphere(side, q), mat); m.renderOrder = 2; this.root.add(m); this.hemis.push(m);
      if (q.glow) {   // neon qobiq (fresnelga o'xshash)
        const glow = new THREE.Mesh(m.geometry, new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.09, side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false }));
        glow.scale.setScalar(1.035); this.root.add(glow);
      }
    }
  }
  buildCerebellum(q) {
    const g = new THREE.SphereGeometry(1, Math.round(q.seg[0] * 0.6), Math.round(q.seg[1] * 0.6)), pos = g.attributes.position, v = new THREE.Vector3(), col = new Float32Array(pos.count * 3);
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i); const stripes = 0.5 + 0.5 * Math.sin(v.y * 38 + Noise.n3(v.x * 3, v.y * 3, v.z * 3) * 2.5);  // miyacha varaqchalari
      const s = 1 + 0.035 * stripes; pos.setXYZ(i, v.x * 0.62 * s, v.y * 0.34 * s - 0.62, v.z * 0.42 * s - 0.78);
      const c = 0.45 + stripes * 0.35; col[i * 3] = c * 0.85; col[i * 3 + 1] = c * 0.9; col[i * 3 + 2] = c * 1.15;
    }
    g.setAttribute("color", new THREE.BufferAttribute(col, 3)); g.computeVertexNormals();
    this.root.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, metalness: 0.1, transparent: true, opacity: 0.85, emissive: 0x2a1458, emissiveIntensity: 0.5 })));
  }
  buildStem() {
    const g = new THREE.CylinderGeometry(0.17, 0.11, 0.9, 24, 1); g.translate(0, -0.95, -0.38); g.rotateX(0.32);
    this.root.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0x5b6aa8, roughness: 0.5, transparent: true, opacity: 0.8, emissive: 0x1e1b4b, emissiveIntensity: 0.6 })));
  }
  inside(x, y, z) {   // taxminiy miya hajmi ichidami (ikki ellipsoid)
    for (const s of [-1, 1]) { const dx = (x - s * 0.42) / 0.62, dy = y / 0.74, dz = z / 1.08; if (dx * dx + dy * dy + dz * dz < 0.92 && (y > -0.2 || dy * dy < 0.4)) return true; }
    return false;
  }
  buildNeurons(q) {
    const N = q.neurons, pos = new Float32Array(N * 3), col = new Float32Array(N * 3), region = new Array(N), base = [];
    let n = 0, guard = 0; const keys = Object.keys(REGION_POS);
    while (n < N && guard++ < N * 30) {
      const x = (Math.random() * 2 - 1) * 1.1, y = (Math.random() * 2 - 1) * 0.85, z = (Math.random() * 2 - 1) * 1.15;
      if (!this.inside(x, y, z)) continue;
      let best = keys[0], bd = 1e9; for (const k of keys) { const p = REGION_POS[k], d = (p[0] - x) ** 2 + (p[1] - y) ** 2 + (p[2] - z) ** 2; if (d < bd) { bd = d; best = k; } }
      pos.set([x, y, z], n * 3); region[n] = best; const c = new THREE.Color(REGIONS_META[best]?.color || "#60a5fa").lerp(new THREE.Color("#dbeafe"), 0.35);
      col.set([c.r, c.g, c.b], n * 3); base.push(c); n++;
    }
    this.nN = n; this.nRegion = region; this.nBase = base;
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos.subarray(0, n * 3), 3)); g.setAttribute("color", new THREE.BufferAttribute(col.subarray(0, n * 3), 3));
    this.neuronGeo = g;
    // Neyronlar qobiq ichida — depthTest o'chiq, ichidan "porlab" ko'rinadi
    this.neurons = new THREE.Points(g, new THREE.PointsMaterial({ size: 0.04, map: glowTexture("#ffffff"), vertexColors: true, transparent: true, opacity: 0.75, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false }));
    this.neurons.renderOrder = 4;
    this.root.add(this.neurons);
    // Sinapslar: har neyron yaqin 2 ta neyron bilan (tasodifiy namunadan) — impulslar shu yo'llar bo'ylab harakatlanadi
    const P = g.attributes.position.array, edges = [], seg = [];
    for (let i = 0; i < n; i++) {
      let picks = 0;
      for (let t = 0; t < 24 && picks < 2; t++) {
        const j = (Math.random() * n) | 0; if (j === i) continue;
        const d = (P[i * 3] - P[j * 3]) ** 2 + (P[i * 3 + 1] - P[j * 3 + 1]) ** 2 + (P[i * 3 + 2] - P[j * 3 + 2]) ** 2;
        if (d < 0.09) { edges.push([i, j]); seg.push(P[i * 3], P[i * 3 + 1], P[i * 3 + 2], P[j * 3], P[j * 3 + 1], P[j * 3 + 2]); picks++; }
      }
    }
    this.edges = edges; this.edgeByRegion = {};
    edges.forEach((e, k) => { (this.edgeByRegion[region[e[0]]] = this.edgeByRegion[region[e[0]]] || []).push(k); });
    const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
    this.synapses = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.13, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false }));
    this.synapses.renderOrder = 3;
    this.root.add(this.synapses);
    this.newLinks = new THREE.Group(); this.root.add(this.newLinks);
  }
  buildRegions() {
    this.regionObjs = {};
    for (const [id, p] of Object.entries(REGION_POS)) {
      const meta = REGIONS_META[id] || { color: "#60a5fa", name: id };
      const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(meta.color), color: 0xffffff, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false }));
      spr.position.set(...p); spr.scale.setScalar(0.34); spr.renderOrder = 5; this.root.add(spr);
      const hit = new THREE.Mesh(new THREE.SphereGeometry(0.26, 12, 10), new THREE.MeshBasicMaterial({ visible: false })); hit.position.set(...p); hit.userData.region = id; this.root.add(hit);
      this.regionObjs[id] = { spr, hit, color: new THREE.Color(meta.color) };
    }
  }
  pick(ev) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.mouse.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
    this.ray.setFromCamera(this.mouse, this.camera);
    const hits = this.ray.intersectObjects(Object.values(this.regionObjs).map((o) => o.hit));
    if (hits.length) { const id = hits[0].object.userData.region; this.focus(id); this.onPick && this.onPick(id); }
  }
  focus(id) { this.focused = id; this.controls.autoRotate = false; this.stimulate(id, 0.8); }
  // Haqiqiy hodisa → hudud faolligi va impulslar
  stimulate(region, amount = 0.5, color) {
    if (!this.regionObjs[region]) return;
    this.activity[region] = Math.min(1.6, (this.activity[region] || 0) + amount);
    const list = this.edgeByRegion[region] || []; const n = Math.min(list.length, Math.round(4 + amount * 14));
    for (let i = 0; i < n; i++) this.spawnPulse(list[(Math.random() * list.length) | 0], color);
  }
  path(from, to, color) {   // xotiradan qidirish: Memory → Reasoning yo'li yoritiladi
    const a = new THREE.Vector3(...REGION_POS[from]), b = new THREE.Vector3(...REGION_POS[to]);
    for (let i = 0; i < 5; i++) this.pulses.push(this.makePulse(a.clone(), b.clone(), color || 0x67e8f9, 1.2 + i * 0.12, i * 0.08));
  }
  makePulse(a, b, color, dur = 0.9, delay = 0) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.pulseTex, color, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
    s.material.depthTest = false; s.renderOrder = 6; s.scale.setScalar(0.09); this.root.add(s); return { s, a, b, t: -delay, dur };
  }
  spawnPulse(k, color) {
    if (k === undefined || this.pulses.length > 400) return;
    const e = this.edges[k], P = this.neuronGeo.attributes.position.array;
    this.pulses.push(this.makePulse(new THREE.Vector3(P[e[0] * 3], P[e[0] * 3 + 1], P[e[0] * 3 + 2]), new THREE.Vector3(P[e[1] * 3], P[e[1] * 3 + 1], P[e[1] * 3 + 2]), color || 0xffffff, 0.5 + Math.random() * 0.6));
  }
  newSynapse(region) {   // yangi bilim saqlandi → yangi aloqa (oltin) paydo bo'ladi
    const idx = []; for (let i = 0; i < this.nN; i++) if (this.nRegion[i] === region) idx.push(i);
    if (idx.length < 2) return; const P = this.neuronGeo.attributes.position.array, i = idx[(Math.random() * idx.length) | 0], j = idx[(Math.random() * idx.length) | 0];
    const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(P[i * 3], P[i * 3 + 1], P[i * 3 + 2]), new THREE.Vector3(P[j * 3], P[j * 3 + 1], P[j * 3 + 2])]);
    const l = new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xf5c451, transparent: true, opacity: 1, blending: THREE.AdditiveBlending }));
    l.userData.born = this.clock.elapsedTime; this.newLinks.add(l);
    while (this.newLinks.children.length > 60) { const o = this.newLinks.children[0]; o.geometry.dispose(); o.material.dispose(); this.newLinks.remove(o); }
  }
  setStatus(regions) { regions.forEach((r) => { this.status[r.id] = r.status; }); }
  alarm(on) { this.alarmUntil = on ? this.clock.elapsedTime + 6 : 0; }
  loop() {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(this.loop);
    if (document.hidden) return;                                // yashirin tabda ishlamaydi
    const dt = Math.min(0.05, this.clock.getDelta()), t = this.clock.elapsedTime;
    this.frames++; this.fpsT += dt; if (this.fpsT >= 1) { this.fps = Math.round(this.frames / this.fpsT); this.frames = 0; this.fpsT = 0; this.lowFps = this.fps < 18 ? this.lowFps + 1 : 0; this.onFps && this.onFps(this.fps, this.lowFps); }
    const busy = Object.values(this.activity).reduce((a, b) => a + b, 0);
    this.root.scale.setScalar(1 + Math.sin(t * 0.9) * 0.006);  // sekin "nafas" (bezak, faoliyat ko'rsatkichi emas)
    this.cortexMat.emissiveIntensity = 0.45 + Math.min(0.6, busy * 0.25) + (this.alarmUntil > t ? 0.3 * Math.abs(Math.sin(t * 6)) : 0);
    this.cortexMat.emissive.setHex(this.alarmUntil > t ? 0x5a0b18 : 0x0b2a5a);
    for (const [id, o] of Object.entries(this.regionObjs)) {
      const a = this.activity[id] || 0; this.activity[id] = Math.max(0, a - dt * 0.45);
      const st = this.status[id], err = st === "error";
      o.spr.material.color.set(err ? 0xff4d6d : 0xffffff);
      o.spr.material.opacity = 0.35 + Math.min(0.65, a * 0.6) + (this.focused === id ? 0.3 : 0) + (err ? 0.25 * Math.abs(Math.sin(t * 4)) : 0);
      o.spr.scale.setScalar(0.3 + a * 0.22 + (this.focused === id ? 0.12 : 0));
    }
    // Neyron ranglari hudud faolligiga qarab yorishadi
    const C = this.neuronGeo.attributes.color.array;
    for (let i = 0; i < this.nN; i += 1) { const a = Math.min(1, this.activity[this.nRegion[i]] || 0), b = this.nBase[i]; C[i * 3] = b.r + a * 0.6; C[i * 3 + 1] = b.g + a * 0.6; C[i * 3 + 2] = b.b + a * 0.4; }
    this.neuronGeo.attributes.color.needsUpdate = true;
    this.synapses.material.opacity = 0.1 + Math.min(0.25, busy * 0.08);
    for (let i = this.pulses.length - 1; i >= 0; i--) {
      const p = this.pulses[i]; p.t += dt; const k = p.t / p.dur;
      if (k < 0) continue;
      if (k >= 1) { this.root.remove(p.s); p.s.material.dispose(); this.pulses.splice(i, 1); continue; }
      p.s.position.lerpVectors(p.a, p.b, k); p.s.material.opacity = Math.sin(k * Math.PI);
    }
    for (const l of this.newLinks.children) l.material.opacity = Math.max(0.25, 1 - (t - l.userData.born) * 0.15);
    this.controls.update(); this.renderer.render(this.scene, this.camera);
  }
  snapshot() { this.renderer.render(this.scene, this.camera); return this.renderer.domElement.toDataURL("image/png"); }
  dispose() {
    this.disposed = true; cancelAnimationFrame(this.raf); window.removeEventListener("resize", this.onResize);
    this.scene && this.scene.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) { (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m.map) m.map.dispose(); m.dispose(); }); } });
    this.controls && this.controls.dispose(); this.renderer && (this.renderer.dispose(), this.renderer.forceContextLoss && this.renderer.forceContextLoss());
    this.renderer && this.renderer.domElement.remove();
  }
}
let REGIONS_META = {};

// 2D zaxira rejimi (WebGL yo'q yoki FPS juda past): hududlar va faollik
class Brain2D {
  constructor(host, onPick) { this.host = host; this.onPick = onPick; this.activity = {}; this.status = {}; }
  init() {
    const c = this.c = document.createElement("canvas"); c.width = this.host.clientWidth || 800; c.height = this.host.clientHeight || 520; this.host.appendChild(c);
    this.g = c.getContext("2d"); c.onclick = (e) => { const r = c.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      for (const [id, p] of Object.entries(this.pos())) if (Math.hypot(p[0] - x, p[1] - y) < 34) { this.focused = id; this.onPick && this.onPick(id); } };
    this.loop = this.loop.bind(this); this.raf = requestAnimationFrame(this.loop); this.fps = 0; return this;
  }
  pos() { const W = this.c.width, H = this.c.height, o = {}; for (const [id, p] of Object.entries(REGION_POS)) o[id] = [W / 2 + p[2] * W * 0.3, H / 2 - p[1] * H * 0.36 + p[0] * 12]; return o; }
  stimulate(r, a = 0.5) { this.activity[r] = Math.min(1.6, (this.activity[r] || 0) + a); }
  path(a, b) { this.stimulate(a, 0.4); this.stimulate(b, 0.4); }
  newSynapse(r) { this.stimulate(r, 0.3); }
  setStatus(rs) { rs.forEach((r) => { this.status[r.id] = r.status; }); }
  focus(id) { this.focused = id; }
  alarm() {}
  loop() {
    this.raf = requestAnimationFrame(this.loop); const g = this.g, W = this.c.width, H = this.c.height; g.clearRect(0, 0, W, H);
    g.fillStyle = "rgba(59,130,246,.08)"; g.beginPath(); g.ellipse(W / 2, H / 2, W * 0.36, H * 0.38, 0, 0, 6.3); g.fill(); g.strokeStyle = "rgba(56,189,248,.35)"; g.stroke();
    for (const [id, p] of Object.entries(this.pos())) {
      const a = this.activity[id] || 0; this.activity[id] = Math.max(0, a - 0.01); const m = REGIONS_META[id] || {};
      g.fillStyle = this.status[id] === "error" ? "#ff4d6d" : m.color || "#60a5fa"; g.globalAlpha = 0.35 + Math.min(0.65, a); g.beginPath(); g.arc(p[0], p[1], 16 + a * 14 + (this.focused === id ? 6 : 0), 0, 6.3); g.fill();
      g.globalAlpha = 1; g.fillStyle = "#e2e8f0"; g.font = "12px Segoe UI"; g.textAlign = "center"; g.fillText(m.name || id, p[0], p[1] + 34);
    }
  }
  snapshot() { return this.c.toDataURL("image/png"); }
  dispose() { cancelAnimationFrame(this.raf); this.c.remove(); }
}

// ================= GRAPH EXPLORER (3D nuqtalar buluti) =================
const LAYOUT_WORKER = `
let N=0,pos,vel,edges,cat,centers,deg,running=false;
onmessage=(m)=>{const d=m.data;if(d.type==='init'){N=d.n;pos=new Float32Array(d.pos);vel=new Float32Array(N*3);edges=new Int32Array(d.edges);cat=new Int32Array(d.cat);centers=d.centers;deg=new Float32Array(N);for(let e=0;e<edges.length;e++)deg[edges[e]]++;iterate(d.iters||260);}
 if(d.type==='stop'){running=false;}};
// Kuchlar: itarilish (tasodifiy namunalar bilan taxminiy, O(N*S)), aloqa prujinalari (dam olish uzunligi L), kategoriya markaziga zaif tortilish
function iterate(total){running=true;let it=0;const S=Math.min(24,Math.max(6,N-1)),KR=1400*N/S,L=16,KS=0.035,KC=0.006;
 const step=()=>{if(!running)return;const t0=Date.now();
  while(it<total&&Date.now()-t0<40){const cool=Math.max(0.05,1-it/total);
   for(let i=0;i<N;i++){let fx=0,fy=0,fz=0;const ix=i*3;
    for(let t=0;t<S;t++){const j=(Math.random()*N)|0;if(j===i)continue;const jx=j*3;const dx=pos[ix]-pos[jx],dy=pos[ix+1]-pos[jx+1],dz=pos[ix+2]-pos[jx+2];const d2=dx*dx+dy*dy+dz*dz+1;const f=KR/(d2*N);fx+=dx*f;fy+=dy*f;fz+=dz*f;}
    const c=centers[cat[i]];fx+=(c[0]-pos[ix])*KC;fy+=(c[1]-pos[ix+1])*KC;fz+=(c[2]-pos[ix+2])*KC;
    vel[ix]+=fx;vel[ix+1]+=fy;vel[ix+2]+=fz;}
   for(let e=0;e<edges.length;e+=2){const a=edges[e]*3,b=edges[e+1]*3;const dx=pos[b]-pos[a],dy=pos[b+1]-pos[a+1],dz=pos[b+2]-pos[a+2];const d=Math.sqrt(dx*dx+dy*dy+dz*dz)+0.01;const f=(d-L)/d*KS/Math.max(1,Math.min(deg[a/3],deg[b/3]));
    vel[a]+=dx*f;vel[a+1]+=dy*f;vel[a+2]+=dz*f;vel[b]-=dx*f;vel[b+1]-=dy*f;vel[b+2]-=dz*f;}
   const cap=6*cool;for(let i=0;i<N*3;i++){let v=vel[i]*0.5;v=v>cap?cap:v<-cap?-cap:v;pos[i]+=v;vel[i]=v;}
   it++;}
  postMessage({type:'pos',pos:pos,done:it>=total});if(it<total)setTimeout(step,0);else running=false;};step();}
`;

class GraphView {
  constructor(host, ui) { this.host = host; this.ui = ui; this.nodes = []; this.edges = []; this.index = new Map(); this.adj = new Map(); this.disposed = false; this.highlight = null; }
  init(quality) {
    const W = this.host.clientWidth || 900, H = this.host.clientHeight || 600, q = QUALITY[quality] || QUALITY.medium; this.q = q;
    const r = this.renderer = new THREE.WebGLRenderer({ antialias: quality !== "low", alpha: true, preserveDrawingBuffer: true, powerPreference: "low-power" });
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, q.pixel)); r.setSize(W, H); this.host.appendChild(r.domElement);
    this.scene = new THREE.Scene(); this.camera = new THREE.PerspectiveCamera(55, W / H, 0.1, 4000); this.camera.position.set(0, 0, 260);
    this.controls = new THREE.OrbitControls(this.camera, r.domElement); this.controls.enableDamping = true; this.controls.zoomSpeed = 1.2; this.controls.screenSpacePanning = true;
    this.labels = document.createElement("div"); this.labels.className = "kg-labels"; this.host.appendChild(this.labels);
    this.ray = new THREE.Raycaster(); this.ray.params.Points.threshold = 2.2; this.mouse = new THREE.Vector2();
    r.domElement.addEventListener("pointerdown", (e) => { this._down = [e.clientX, e.clientY]; });
    r.domElement.addEventListener("pointerup", (e) => { if (this._down && Math.hypot(e.clientX - this._down[0], e.clientY - this._down[1]) < 5) this.pickAt(e, true); else this._userMoved = true; });
    r.domElement.addEventListener("wheel", () => { this._userMoved = true; }, { passive: true });
    r.domElement.addEventListener("pointermove", (e) => { this._hoverEv = e; });
    this.onResize = () => { const w = this.host.clientWidth, h = this.host.clientHeight; if (!w || !h) return; this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); r.setSize(w, h); };
    window.addEventListener("resize", this.onResize);
    this.tex = glowTexture("#ffffff"); this.clock = new THREE.Clock(); this.frames = 0; this.fpsT = 0; this.fps = 0;
    this.loop = this.loop.bind(this); this.raf = requestAnimationFrame(this.loop); return this;
  }
  setData(nodes, edges, keepPositions) {
    const old = keepPositions ? new Map(this.nodes.map((n) => [n.id, n])) : new Map();
    this.nodes = nodes; this.index = new Map(nodes.map((n, i) => [n.id, i]));
    this.edges = edges.filter((e) => this.index.has(e.s) && this.index.has(e.t));
    this.adj = new Map(); this.edges.forEach((e) => { (this.adj.get(e.s) || this.adj.set(e.s, []).get(e.s)).push(e); (this.adj.get(e.t) || this.adj.set(e.t, []).get(e.t)).push(e); });
    const cats = Object.keys(CAT_STYLE), centers = cats.map((c, i) => { const a = (i / cats.length) * Math.PI * 2, b = (i % 3 - 1) * 0.6; return [Math.cos(a) * 120, Math.sin(b) * 60, Math.sin(a) * 120]; });
    const pos = new Float32Array(nodes.length * 3), catIdx = new Int32Array(nodes.length);
    nodes.forEach((n, i) => { const ci = Math.max(0, cats.indexOf(n.cat)); catIdx[i] = ci; const o = old.get(n.id);
      if (o && o.p) pos.set(o.p, i * 3); else { const c = centers[ci]; pos.set([c[0] + (Math.random() - 0.5) * 70, c[1] + (Math.random() - 0.5) * 70, c[2] + (Math.random() - 0.5) * 70], i * 3); } });
    this.pos = pos; this.buildObjects();
    if (this.worker) this.worker.terminate();
    try {
      this.worker = new Worker(URL.createObjectURL(new Blob([LAYOUT_WORKER], { type: "application/javascript" })));
      const ed = new Int32Array(this.edges.length * 2); this.edges.forEach((e, k) => { ed[k * 2] = this.index.get(e.s); ed[k * 2 + 1] = this.index.get(e.t); });
      this._fitted = false;
      this.worker.onmessage = (m) => { if (m.data.type === "pos") { this.pos.set(m.data.pos); this.updatePositions(); if (m.data.done || !this._fitted) this.fit(!this._fitted || !this._userMoved); this._fitted = true; } };
      this.worker.postMessage({ type: "init", n: nodes.length, pos: pos.buffer.slice(0), edges: ed.buffer, cat: catIdx.buffer, centers, iters: keepPositions ? 80 : (nodes.length > 4000 ? 160 : 260) }, []);
    } catch (e) { this.updatePositions(); }
  }
  buildObjects() {
    ["points", "lines", "selLines"].forEach((k) => { if (this[k]) { this.scene.remove(this[k]); this[k].geometry.dispose(); this[k].material.dispose(); this[k] = null; } });
    const n = this.nodes.length, col = new Float32Array(n * 3), size = new Float32Array(n);
    this.nodes.forEach((nd, i) => { const c = new THREE.Color((CAT_STYLE[nd.cat] || ["#94a3b8"])[0]); col.set([c.r, c.g, c.b], i * 3); size[i] = 3.5 + Math.min(12, Math.sqrt(nd.degree || 0) * 1.8); });
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(this.pos, 3)); g.setAttribute("color", new THREE.BufferAttribute(col, 3)); g.setAttribute("size", new THREE.BufferAttribute(size, 1));
    this.baseColors = col.slice();
    const mat = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { map: { value: this.tex }, scale: { value: (this.host.clientHeight || 600) / 2 } },
      vertexShader: "attribute float size; varying vec3 vC; void main(){ vC=color; vec4 mv=modelViewMatrix*vec4(position,1.0); gl_PointSize=size*(300.0/-mv.z); gl_Position=projectionMatrix*mv; }",
      fragmentShader: "uniform sampler2D map; varying vec3 vC; void main(){ vec4 t=texture2D(map, gl_PointCoord); if(t.a<0.05) discard; gl_FragColor=vec4(vC,1.0)*t; }", vertexColors: true });
    this.points = new THREE.Points(g, mat); this.scene.add(this.points);
    const lp = new Float32Array(this.edges.length * 6), lc = new Float32Array(this.edges.length * 6);
    this.edges.forEach((e, k) => { const a = this.index.get(e.s), b = this.index.get(e.t); lc.set(col.subarray(a * 3, a * 3 + 3), k * 6); lc.set(col.subarray(b * 3, b * 3 + 3), k * 6 + 3); });
    const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.BufferAttribute(lp, 3)); lg.setAttribute("color", new THREE.BufferAttribute(lc, 3));
    this.lines = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false }));
    this.lines.visible = BrainState.filters.showEdges; this.scene.add(this.lines); this.updatePositions();
  }
  updatePositions() {
    if (!this.points) return; this.points.geometry.attributes.position.needsUpdate = true;
    const lp = this.lines.geometry.attributes.position.array, P = this.pos;
    this.edges.forEach((e, k) => { const a = this.index.get(e.s) * 3, b = this.index.get(e.t) * 3; lp[k * 6] = P[a]; lp[k * 6 + 1] = P[a + 1]; lp[k * 6 + 2] = P[a + 2]; lp[k * 6 + 3] = P[b]; lp[k * 6 + 4] = P[b + 1]; lp[k * 6 + 5] = P[b + 2]; });
    this.lines.geometry.attributes.position.needsUpdate = true; this.points.geometry.computeBoundingSphere(); this.nodes.forEach((n, i) => { n.p = [P[i * 3], P[i * 3 + 1], P[i * 3 + 2]]; });
    if (this.highlight) this.applyHighlight();
  }
  fit(force) {   // kamerani butun grafga moslash (foydalanuvchi o'zi aylantirgan bo'lsa — faqat birinchi marta)
    if (!force || !this.points) return; const s = this.points.geometry.boundingSphere; if (!s) return;
    this.controls.target.copy(s.center); const d = Math.max(40, s.radius / Math.tan((this.camera.fov * Math.PI) / 360) * 1.05);
    this.camera.position.copy(s.center).add(new THREE.Vector3(0.35, 0.25, 1).normalize().multiplyScalar(d)); this.camera.far = d * 6; this.camera.updateProjectionMatrix();
  }
  pickAt(ev, select) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.mouse.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
    this.ray.setFromCamera(this.mouse, this.camera); this.ray.params.Points.threshold = Math.max(1.2, this.camera.position.length() / 120);
    const h = this.points ? this.ray.intersectObject(this.points) : [];
    const node = h.length ? this.nodes[h[0].index] : null;
    if (select) { if (node) this.select(node.id); } else this.hover = node;
    return node;
  }
  select(id, fly = true) {
    const i = this.index.get(id); if (i === undefined) return false; const n = this.nodes[i];
    BrainState.selected = { id: n.id, type: n.type, ref: n.ref, cat: n.cat, label: n.label };
    this.highlight = { center: id, set: this.neighborhood(id, 1), path: null }; this.applyHighlight();
    if (fly && n.p) { this.controls.target.set(...n.p); }
    this.ui.onSelect && this.ui.onSelect(n, (this.adj.get(id) || []).map((e) => ({ rel: e.rel, other: this.nodes[this.index.get(e.s === id ? e.t : e.s)] })));
    return true;
  }
  neighborhood(id, depth) { const set = new Set([id]); let fr = [id]; for (let d = 0; d < depth; d++) { const nx = []; fr.forEach((x) => (this.adj.get(x) || []).forEach((e) => { const o = e.s === x ? e.t : e.s; if (!set.has(o)) { set.add(o); nx.push(o); } })); fr = nx; } return set; }
  showPath(ids) { this.highlight = { center: ids[0], set: new Set(ids), path: ids }; this.applyHighlight(); }
  applyHighlight() {
    const col = this.points.geometry.attributes.color.array, base = this.baseColors, hl = this.highlight, only = BrainState.filters.neighborsOnly;
    for (let i = 0; i < this.nodes.length; i++) { const inSet = !hl || hl.set.has(this.nodes[i].id), f = inSet ? 1 : (only ? 0 : 0.12); col[i * 3] = base[i * 3] * f; col[i * 3 + 1] = base[i * 3 + 1] * f; col[i * 3 + 2] = base[i * 3 + 2] * f; }
    this.points.geometry.attributes.color.needsUpdate = true;
    const lc = this.lines.geometry.attributes.color.array;
    this.edges.forEach((e, k) => { const on = !hl || (hl.set.has(e.s) && hl.set.has(e.t)), f = on ? 1 : (only ? 0 : 0.05);
      const a = this.index.get(e.s) * 3, b = this.index.get(e.t) * 3; for (let j = 0; j < 3; j++) { lc[k * 6 + j] = base[a + j] * f; lc[k * 6 + 3 + j] = base[b + j] * f; } });
    this.lines.geometry.attributes.color.needsUpdate = true; this.lines.material.opacity = hl ? 0.6 : 0.22;
  }
  clearHighlight() { this.highlight = null; this.applyHighlight(); }
  setEdges(v) { if (this.lines) this.lines.visible = v; }
  loop() {
    if (this.disposed) return; this.raf = requestAnimationFrame(this.loop); if (document.hidden) return;
    const dt = this.clock.getDelta(); this.frames++; this.fpsT += dt; if (this.fpsT >= 1) { this.fps = Math.round(this.frames / this.fpsT); this.frames = 0; this.fpsT = 0; this.ui.onFps && this.ui.onFps(this.fps); }
    if (this.highlight && this.lines) this.lines.material.opacity = 0.45 + 0.25 * Math.sin(this.clock.elapsedTime * 3);   // tanlangan aloqalar "oqadi"
    if (this._hoverEv && this.frames % 3 === 0) { this.pickAt(this._hoverEv, false); this._hoverEv = null; }
    this.controls.update(); this.renderer.render(this.scene, this.camera); if (this.frames % 2 === 0) this.drawLabels();
  }
  drawLabels() {
    const W = this.host.clientWidth, H = this.host.clientHeight, v = new THREE.Vector3(), want = [];
    const top = this._top || (this._top = [...this.nodes].sort((a, b) => b.degree - a.degree).slice(0, 18).map((n) => n.id));
    if (this.hover) want.push(this.hover.id); if (this.highlight) want.push(this.highlight.center, ...[...this.highlight.set].slice(0, 30)); top.forEach((id) => want.push(id));
    const html = []; const seen = new Set(), cells = new Set();
    for (const id of want) { if (seen.has(id)) continue; seen.add(id); const i = this.index.get(id); if (i === undefined) continue; const n = this.nodes[i]; if (!n.p) continue;
      v.set(...n.p).project(this.camera); if (v.z > 1) continue; const x = (v.x * 0.5 + 0.5) * W, y = (-v.y * 0.5 + 0.5) * H; if (x < 0 || y < 0 || x > W || y > H) continue;
      const cell = `${Math.round(x / 150)}:${Math.round(y / 20)}`; if (cells.has(cell) && !(this.hover && this.hover.id === id)) continue; cells.add(cell);
      html.push(`<div class="kg-l${this.hover && this.hover.id === id ? " hov" : ""}" style="left:${x}px;top:${y}px;color:${(CAT_STYLE[n.cat] || ["#cbd5e1"])[0]}">${esc((CAT_STYLE[n.cat] || ["", ""])[1])} ${esc(n.label.slice(0, 34))}</div>`); }
    this.labels.innerHTML = html.join("");
  }
  exportPNG() { this.renderer.render(this.scene, this.camera); return this.renderer.domElement.toDataURL("image/png"); }
  exportSVG() {
    const W = this.host.clientWidth, H = this.host.clientHeight, v = new THREE.Vector3(), xy = new Map();
    this.camera.updateMatrixWorld(); this.camera.updateProjectionMatrix();
    this.nodes.forEach((n) => { if (!n.p) return; v.set(...n.p).project(this.camera); if (v.z < 1) xy.set(n.id, [(v.x * 0.5 + 0.5) * W, (-v.y * 0.5 + 0.5) * H]); });
    const lines = this.lines.visible ? this.edges.slice(0, 8000).map((e) => { const a = xy.get(e.s), b = xy.get(e.t); return a && b ? `<line x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}"/>` : ""; }).join("") : "";
    const dots = this.nodes.slice(0, 10000).map((n) => { const p = xy.get(n.id); return p ? `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="${(1.5 + Math.min(6, Math.sqrt(n.degree || 0))).toFixed(1)}" fill="${(CAT_STYLE[n.cat] || ["#94a3b8"])[0]}"><title>${esc(n.label)}</title></circle>` : ""; }).join("");
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><rect width="100%" height="100%" fill="#030712"/><g stroke="#3b82f6" stroke-opacity=".25" stroke-width=".6">${lines}</g><g>${dots}</g></svg>`;
  }
  dispose() {
    this.disposed = true; cancelAnimationFrame(this.raf); window.removeEventListener("resize", this.onResize); if (this.worker) this.worker.terminate();
    this.scene && this.scene.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    this.tex && this.tex.dispose(); this.controls && this.controls.dispose(); this.renderer && (this.renderer.dispose(), this.renderer.forceContextLoss && this.renderer.forceContextLoss(), this.renderer.domElement.remove());
    this.labels && this.labels.remove();
  }
}

// ================= HUB: 🧠 3D BRAIN MODE / 🌐 GRAPH EXPLORER MODE =================
function download(name, href) { const a = document.createElement("a"); a.href = href; a.download = name; document.body.appendChild(a); a.click(); a.remove(); }

async function renderBrainHub(v, mode, preset) {
  if (mode) BrainState.mode = mode;
  if (preset) BrainState.filters.categories = preset;
  Live.start();
  v.innerHTML = `<div class="neo">
    <div class="neo-top"><div class="seg"><button data-mode="brain" class="${BrainState.mode === "brain" ? "on" : ""}">🧠 3D BRAIN MODE</button><button data-mode="graph" class="${BrainState.mode === "graph" ? "on" : ""}">🌐 GRAPH EXPLORER MODE</button></div>
      <div class="neo-tools">${liveBadge()}<span class="fps" id="fps">FPS —</span>
        <select id="qual" title="Grafika sifati">${["low", "medium", "high"].map((k) => `<option value="${k}" ${BrainState.quality === k ? "selected" : ""}>${{ low: "Low", medium: "Medium", high: "High" }[k]}</option>`).join("")}</select>
        <button class="ghost" id="shot" title="PNG">PNG</button><button class="ghost" id="svg" title="SVG (faqat graf)">SVG</button><button class="ghost" id="fs">⛶ To'liq ekran</button></div></div>
    <div class="neo-body"><div class="neo-stage" id="stage"><div class="neo-msg" id="stmsg">Yuklanmoqda…</div></div>
      <aside class="neo-side" id="side"></aside></div>
    <div class="neo-foot muted" id="foot"></div></div>`;
  const stage = $("#stage"), side = $("#side"), foot = $("#foot");
  let viz = null, unsub = null, stTimer = null, brainState = null, gen = 0, dead = false;   // gen: eskirgan async natijalarni tashlash
  const setFps = (f, low) => { const el = $("#fps"); el.textContent = `FPS ${f}`; el.className = "fps " + (f < 20 ? "bad" : f < 40 ? "warn" : "ok");
    if (low >= 6 && BrainState.mode === "brain" && !(viz instanceof Brain2D)) { mountBrain(true); } };
  const cleanup = () => { gen++; if (viz) { viz.dispose(); VIZ.items.delete(viz); viz = null; } if (unsub) { unsub(); unsub = null; } clearInterval(stTimer); stage.querySelectorAll("canvas,.kg-labels").forEach((x) => x.remove()); };
  VIZ.items.add({ dispose: () => { dead = true; cleanup(); } });

  async function loadState() {
    try { brainState = await api("/api/brain/state"); if (dead) return; REGIONS_META = Object.fromEntries(brainState.regions.map((r) => [r.id, r])); if (viz && viz.setStatus) viz.setStatus(brainState.regions); renderRegionList(); }
    catch (e) { Live.set(false); }
  }
  function renderRegionList() {
    if (BrainState.mode !== "brain" || !brainState || side.dataset.detail) return;
    side.innerHTML = `<h3>Miya hududlari</h3><p class="muted small">Har hudud — JARVIS dasturiy modullarining vizual ifodasi (biologik simulyatsiya emas). Bosing — holati ochiladi.</p>
      ${brainState.regions.map((r) => `<div class="reg" data-reg="${r.id}"><i style="background:${r.color}"></i><b>${esc(r.name)}</b><span class="st ${r.status}">${esc({ idle: "tinch", active: "faol", error: "xato" }[r.status] || r.status)}</span></div>`).join("")}
      <div class="muted small" style="margin-top:10px">Faol AI so'rovlar: <b>${brainState.events.active.ai}</b> · vazifalar: <b>${brainState.events.active.tasks}</b></div>`;
  }
  async function regionDetail(id) {
    side.dataset.detail = id; side.scrollTop = 0;
    let r; try { r = await api(`/api/brain/region/${id}`); } catch (e) { side.innerHTML = `<div class="bad">${esc(e.message)}</div>`; return; }
    side.innerHTML = `<button class="ghost small" id="back">← Hududlar</button><h3 style="margin-top:8px"><i class="dot" style="background:${r.color}"></i> ${esc(r.name)}</h3><div class="muted">${esc(r.uz)} · modullar: ${r.modules.map(esc).join(", ")}</div>
      <div style="margin:8px 0">Holat: <span class="st ${r.status}">${esc(r.status)}</span>${r.model ? ` · model: <b>${esc(r.model)}</b>` : ""} · xatolar (24s): ${r.errors_24h}</div>
      ${["memories", "conflicts", "graph_nodes", "pending_approvals", "dag_running"].filter((k) => r[k] !== undefined).map((k) => `<div class="kv"><span>${esc({ memories: "xotiralar", conflicts: "ziddiyatlar", graph_nodes: "graf tugunlari", pending_approvals: "kutilayotgan tasdiqlar", dag_running: "ishlayotgan graflar" }[k])}</span><b>${esc(r[k])}</b></div>`).join("")}
      <h4>Agentlar</h4>${r.agents.length ? r.agents.map((a) => `<div class="kv"><span>${esc(a.title)}</span><span class="st ${a.status === "running" ? "active" : a.status === "error" ? "error" : "idle"}">${esc(a.status)}</span></div>`).join("") : '<div class="muted small">—</div>'}
      <h4>Faol vazifalar</h4>${r.active_tasks.length ? r.active_tasks.map((t) => `<div class="small">#${t.id} ${esc(t.title)}</div>`).join("") : '<div class="muted small">yo\'q</div>'}
      <h4>Oxirgi ishlar</h4>${r.recent_actions.length ? r.recent_actions.map((a) => `<div class="small"><span class="muted">${esc(a.ts.slice(5, 16))}</span> ${esc(a.action)}</div>`).join("") : '<div class="muted small">yo\'q</div>'}
      <div class="row" style="margin-top:10px"><button id="ingraph">🌐 Graph'da ko'rish</button></div>`;
    $("#back").onclick = () => { delete side.dataset.detail; renderRegionList(); };
    $("#ingraph").onclick = () => { BrainState.filters.categories = REGION_CATS[id] || []; BrainState.focusRegion = id; switchMode("graph"); };
  }
  const OFFLINE = '<span class="bad">OFFLINE — backend bilan jonli aloqa yo\'q. Ko\'rsatilgan holat oxirgi yuklangan ma\'lumot; hodisa animatsiyalari kelmaydi.</span> ';
  let note = "";
  const setFoot = (html) => { note = html; foot.innerHTML = (Live.online === false ? OFFLINE : "") + note; };
  function onEvent(e) {
    if (e.type === "_conn") { setFoot(note); return; }
    if (BrainState.mode === "brain" && viz && viz.stimulate) {
      const reg = brainState ? brainState.agent_region : {};
      if (e.type === "ai.start") { viz.stimulate("reasoning", 0.6, 0x93c5fd); viz.stimulate("language", 0.4, 0x67e8f9); }
      else if (e.type === "ai.end") viz.stimulate("language", e.ok ? 0.3 : 0.6, e.ok ? 0x67e8f9 : 0xff4d6d);
      else if (e.type === "memory.search") { viz.stimulate("memory", 0.5, 0x22d3ee); viz.path("memory", "reasoning", 0x22d3ee); }
      else if (e.type === "memory.add") { viz.stimulate("memory", 0.7, 0xf5c451); viz.newSynapse("memory"); }
      else if (e.type === "task.start" || e.type === "task.end") viz.stimulate(reg[e.agent] || "agents", e.type === "task.start" ? 0.6 : 0.3, e.status === "failed" ? 0xff4d6d : 0xc4b5fd);
      else if (e.type === "error") { viz.stimulate("security", 0.9, 0xff4d6d); viz.alarm(true); }
      else if (e.type === "approval") viz.stimulate("security", 0.6, 0xf5c451);
      else if (e.type === "kg.link") viz.stimulate("memory", 0.15, 0xf5c451);
    }
    if (BrainState.mode === "graph" && (e.type === "memory.add" || e.type === "kg.link")) graphRefreshSoon();
    if (["task.start", "task.end", "error", "approval"].includes(e.type)) { clearTimeout(onEvent._t); onEvent._t = setTimeout(loadState, 800); }
  }

  async function mountBrain(force2D) {
    cleanup(); const my = gen; stage.querySelector("#stmsg").textContent = "3D miya yuklanmoqda…"; stage.querySelector("#stmsg").hidden = false;
    await loadState();
    const ok3d = !force2D && webglOK() && await loadThree().then(() => true, () => false);
    if (my !== gen || dead) return;
    const pick = (id) => regionDetail(id);
    viz = ok3d ? new Brain3D(stage, pick).init(BrainState.quality) : new Brain2D(stage, pick).init();
    if (viz.onFps !== undefined || ok3d) viz.onFps = setFps;
    stage.querySelector("#stmsg").hidden = true; VIZ.items.add(viz);
    if (brainState) viz.setStatus(brainState.regions);
    if (BrainState.focusRegion) { viz.focus(BrainState.focusRegion); regionDetail(BrainState.focusRegion); }
    setFoot(ok3d ? '<span class="muted">3D miya protsedura yo\'li bilan yaratilgan model (skaner qilingan anatomik model emas). Yorug\'lik impulslari faqat haqiqiy backend hodisalarida paydo bo\'ladi; sekin pulsatsiya — bezak.</span>'
      : '<span class="warn">2D rejim: ' + (force2D ? "past FPS sababli" : "WebGL mavjud emas") + ". Hududlar va faollik baribir haqiqiy hodisalardan.</span>");
    unsub = Live.on(onEvent); stTimer = setInterval(loadState, 10000);
  }

  // --- Graph Explorer ---
  let gTimer = null; const graphRefreshSoon = () => { clearTimeout(gTimer); gTimer = setTimeout(() => loadGraph(true), 2500); };
  function graphSide() {
    const f = BrainState.filters; side.scrollTop = 0;
    side.innerHTML = `<h3>Graph Explorer</h3><div class="row"><input id="gq" placeholder="Global qidiruv…" value="${esc(f.q)}"><button id="gsearch">🔍</button></div>
      <div class="cats">${Object.entries(CAT_STYLE).map(([k, [c, ic]]) => `<label class="cat"><input type="checkbox" data-cat="${k}" ${!f.categories.length || f.categories.includes(k) ? "checked" : ""}><i style="background:${c}"></i>${ic} ${esc(k)}</label>`).join("")}</div>
      <div class="row small"><button class="ghost small" id="call">hammasi</button><button class="ghost small" id="cnone">hech biri</button></div>
      <label class="small">Sana: dan</label><input id="gsince" type="date" value="${esc(f.since)}"><label class="small">gacha</label><input id="guntil" type="date" value="${esc(f.until)}">
      <label class="small">Manba</label><input id="gsrc" placeholder="masalan: chat, pytest, https://…" value="${esc(f.source)}">
      <label class="small"><input type="checkbox" id="gnb" ${f.neighborsOnly ? "checked" : ""}> Faqat tanlanganga bog'langanlar</label>
      <label class="small"><input type="checkbox" id="ged" ${f.showEdges ? "checked" : ""}> Aloqalarni ko'rsatish</label>
      <div class="row"><button id="gapply">Qo'llash</button><button class="ghost" id="grefresh">⟳ Yangilash</button></div>
      <div id="gcount" class="muted small"></div><div id="gdetail"></div>`;
    const read = () => { f.q = $("#gq").value.trim(); f.since = $("#gsince").value; f.until = $("#guntil").value; f.source = $("#gsrc").value.trim();
      const all = [...side.querySelectorAll("[data-cat]")]; const on = all.filter((x) => x.checked).map((x) => x.dataset.cat); f.categories = on.length === all.length ? [] : on; };
    $("#gapply").onclick = () => { read(); loadGraph(false); }; $("#gsearch").onclick = () => { read(); loadGraph(false); }; $("#grefresh").onclick = () => loadGraph(false);
    $("#gq").onkeydown = (e) => { if (e.key === "Enter") { read(); loadGraph(false); } };
    $("#call").onclick = () => side.querySelectorAll("[data-cat]").forEach((x) => { x.checked = true; }); $("#cnone").onclick = () => side.querySelectorAll("[data-cat]").forEach((x) => { x.checked = false; });
    $("#gnb").onchange = (e) => { f.neighborsOnly = e.target.checked; if (viz && viz.applyHighlight) viz.applyHighlight(); };
    $("#ged").onchange = (e) => { f.showEdges = e.target.checked; viz && viz.setEdges && viz.setEdges(f.showEdges); };
  }
  let pathA = null;
  function showDetail(n, rels) {
    const box = $("#gdetail"); const [c, ic] = CAT_STYLE[n.cat] || ["#94a3b8", "•"];
    box.innerHTML = `<div class="detail"><div class="small muted">${ic} ${esc(n.cat)} · ${esc(n.type)}#${esc(n.ref)}</div><h4 style="color:${c}">${esc(n.label)}</h4>
      <div class="kv"><span>Aloqalar</span><b>${n.degree}</b></div><div class="kv"><span>Manba</span><span>${esc(n.source || "—")}</span></div>
      <div class="kv"><span>Sana</span><span>${esc(n.observed_at || "—")}</span></div><div class="kv"><span>Holat</span>${n.verified ? '<span class="st idle">tekshirilgan</span>' : '<span class="st warn">tekshirilmagan</span>'}</div>
      <div class="row small" style="margin-top:8px">${n.section ? `<a href="#${esc(n.section)}"><button class="ghost small">Bo'limga o'tish</button></a>` : ""}<button class="ghost small" id="to3d">🧠 3D'da</button>
        <button class="ghost small" id="pa">${pathA ? "Yo'l oxiri" : "Yo'l boshi"}</button>${pathA ? '<button class="ghost small" id="pclear">✕</button>' : ""}</div>
      <h4>Bog'lanishlar</h4><div class="rels">${rels.slice(0, 60).map((r) => r.other ? `<a class="rel" data-nid="${r.other.id}">${esc((CAT_STYLE[r.other.cat] || ["", "•"])[1])} <span class="muted">${esc(r.rel)}</span> ${esc(r.other.label.slice(0, 40))}</a>` : "").join("") || '<span class="muted small">yo\'q</span>'}</div></div>`;
    box.querySelectorAll("[data-nid]").forEach((a) => { a.onclick = () => viz.select(Number(a.dataset.nid)); });
    $("#to3d").onclick = () => { BrainState.focusRegion = CAT_REGION[n.cat] || "memory"; switchMode("brain"); };
    $("#pa").onclick = async () => { if (!pathA) { pathA = n.id; showDetail(n, rels); return; }
      try { const p = await api(`/api/kg/path?a=${pathA}&b=${n.id}`); const ids = [...new Set(p.flatMap((x) => [x.src_id, x.dst_id]))]; if (!ids.length) throw new Error("Bu ikki tugun orasida yo'l topilmadi (6 qadamgacha)");
        viz.showPath(ids); $("#gcount").innerHTML = `Yo'l: ${ids.length} tugun`; } catch (e) { $("#gcount").innerHTML = `<span class="bad">${esc(e.message)}</span>`; } pathA = null; };
    const pc = $("#pclear"); if (pc) pc.onclick = () => { pathA = null; viz.clearHighlight(); showDetail(n, rels); };
  }
  async function loadGraph(incremental) {
    if (!viz || !viz.setData) return; const my = gen;
    const f = BrainState.filters, cap = (QUALITY[BrainState.quality] || QUALITY.medium).maxNodes, page = Math.min(2000, cap);
    const qs = (off) => `/api/kg/graph?limit=${page}&offset=${off}&categories=${encodeURIComponent(f.categories.join(","))}&q=${encodeURIComponent(f.q)}&since=${encodeURIComponent(f.since)}&until=${encodeURIComponent(f.until)}&source=${encodeURIComponent(f.source)}`;
    let nodes = [], edges = [], total = 0, off = 0;
    $("#gcount").innerHTML = '<span class="muted">Yuklanmoqda…</span>';
    try {
      do { const g = await api(qs(off)); total = g.total; nodes = nodes.concat(g.nodes); edges = edges.concat(g.edges); off += g.limit;
        $("#gcount").innerHTML = `Yuklandi: <b>${nodes.length}</b> / ${total} tugun${total > cap ? ` (sifat chegarasi ${cap})` : ""}`;
        if (!g.has_more || nodes.length >= cap) break; } while (true);
    } catch (e) { $("#gcount").innerHTML = `<span class="bad">${esc(e.message)}</span>`; return; }
    if (my !== gen || dead || !viz || !viz.setData) return;
    const seen = new Set(); edges = edges.filter((e) => { const k = e.s + ":" + e.t + ":" + e.rel; if (seen.has(k)) return false; seen.add(k); return true; });
    viz.setData(nodes, edges, incremental); viz._top = null;
    $("#gcount").innerHTML = `Ko'rsatilmoqda: <b>${nodes.length}</b> tugun · ${edges.length} aloqa · jami ${total}`;
    stage.querySelector("#stmsg").hidden = nodes.length > 0; if (!nodes.length) { stage.querySelector("#stmsg").textContent = "Filtrga mos tugun yo'q. Graf bo'sh bo'lsa: Knowledge Graph → 'qayta qurish'."; }
    if (BrainState.selected && viz.index.has(BrainState.selected.id)) setTimeout(() => viz.select(BrainState.selected.id), 300);
  }
  async function mountGraph() {
    cleanup(); const my = gen; graphSide(); const msg = stage.querySelector("#stmsg"); msg.hidden = false; msg.textContent = "Graf yuklanmoqda…";
    if (!webglOK() || !(await loadThree().then(() => true, () => false))) { msg.textContent = "WebGL mavjud emas — Graph Explorer uchun 'Knowledge Graph' (2D) bo'limidan foydalaning."; return; }
    if (my !== gen || dead) return;
    viz = new GraphView(stage, { onSelect: showDetail, onFps: (f) => setFps(f, 0) }).init(BrainState.quality); VIZ.items.add(viz);
    setFoot('<span class="muted">Har tugun — JARVIS bazasidagi haqiqiy yozuv (xotira, vazifa, agent, xato, taklif…). Sichqoncha: aylantirish · g\'ildirak: zoom · o\'ng tugma: siljitish.</span>');
    await loadGraph(false); if (my !== gen || dead) return; unsub = Live.on(onEvent);
    if (BrainState.focusRegion && !BrainState.selected) $("#gcount").insertAdjacentHTML("beforeend", ` · <span class="muted">hudud: ${esc(BrainState.focusRegion)}</span>`);
  }
  function switchMode(m) {
    BrainState.mode = m; v.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === m)); delete side.dataset.detail;
    if (m === "brain") mountBrain(false); else mountGraph();
    try { const h = location.hash.slice(1); if (["brain", "graph"].includes(h) || !h) { history.replaceState(null, "", "#" + (m === "brain" ? "brain" : "graph"));
        document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.id === (m === "brain" ? "brain" : "graph")));
        $("#title").textContent = m === "brain" ? "🧠 3D Brain Mode" : "🌐 Graph Explorer Mode"; } } catch (e) { /* */ }
  }
  v.querySelectorAll("[data-mode]").forEach((b) => { b.onclick = () => switchMode(b.dataset.mode); });
  side.addEventListener("click", (e) => { const r = e.target.closest("[data-reg]"); if (r) { if (viz && viz.focus) viz.focus(r.dataset.reg); regionDetail(r.dataset.reg); } });
  $("#qual").onchange = (e) => { BrainState.quality = e.target.value; try { localStorage.setItem("brain_quality", BrainState.quality); } catch (er) { /* */ } switchMode(BrainState.mode); };
  $("#fs").onclick = () => { const el = v.querySelector(".neo"); (document.fullscreenElement ? document.exitFullscreen() : el.requestFullscreen && el.requestFullscreen()).catch(() => {}); setTimeout(() => viz && viz.onResize && viz.onResize(), 300); };
  $("#shot").onclick = () => { if (!viz) return; const url = viz.exportPNG ? viz.exportPNG() : viz.snapshot(); download(`jarvis-${BrainState.mode}.png`, url); };
  $("#svg").onclick = () => { if (!viz || !viz.exportSVG) { foot.innerHTML = '<span class="muted">SVG eksport faqat Graph Explorer rejimida.</span>'; return; }
    download("jarvis-graph.svg", URL.createObjectURL(new Blob([viz.exportSVG()], { type: "image/svg+xml" }))); };
  switchMode(BrainState.mode);
}

// ================= MEMORY EXPLORER =================
async function renderMemoryExplorer(v) {
  const cats = await api("/api/memory/categories");
  let kind = "", q = "", status = "";
  v.innerHTML = `<div class="mx"><aside class="card mx-cats"><h3>Toifalar</h3><a data-k="" class="on">Hammasi</a>${cats.map((c) => `<a data-k="${c.kind}">${esc(c.label)}<span>${c.count}</span></a>`).join("")}
      <h4>Holat</h4><a data-s="">barchasi</a><a data-s="conflict">⚠ ziddiyatlar</a><div class="row" style="margin-top:10px"><a href="/api/memory/export" download="jarvis_memory.json"><button class="ghost small">Eksport (JSON)</button></a></div></aside>
    <section><div class="card"><div class="row"><input id="mq" placeholder="Xotiradan qidirish…"><button id="mgo">Qidirish</button></div>
      <details><summary class="muted">➕ Yangi ma'lumot (Memory Connection Engine)</summary><input id="nt" placeholder="Nomi (ixtiyoriy)" style="margin-top:6px"><textarea id="nc" placeholder="Mazmuni (parol/token yozmang)"></textarea>
        <div class="row" style="margin-top:6px"><input id="np" placeholder="loyiha (ixtiyoriy)"><button class="ghost" id="nan">Tahlil qilish</button><button id="nsv">Saqlash</button></div><div id="nres"></div></details></div>
      <div class="card" style="margin-top:12px" id="mlist"></div><div class="card" style="margin-top:12px" id="msug"></div></section>
    <aside class="card mx-detail" id="mdet"><span class="muted">Xotirani tanlang — batafsil ma'lumot, tahrirlash va bog'langan xotiralar shu yerda.</span></aside></div>`;
  const load = async () => {
    const rows = await api(`/api/memory/explore?kind=${kind}&q=${encodeURIComponent(q)}&status=${status}`);
    $("#mlist").innerHTML = rows.length ? `<table><tr><th>nomi</th><th>toifa</th><th>ishonchlilik</th><th>manba</th><th>yaratilgan</th><th>yangilangan</th></tr>${rows.map((r) => `<tr data-m="${r.id}" style="cursor:pointer">
      <td><b>${esc(r.name)}</b>${r.status === "conflict" ? ' <span class="pill warn">⚠ ziddiyat</span>' : ""}<div class="muted small">${esc(r.content.slice(0, 90))}</div></td><td>${esc(r.category)}</td><td>${esc(r.reliability)}</td>
      <td class="small">${esc(r.reference || r.source)}</td><td class="small">${esc(r.created_at)}</td><td class="small">${esc(r.updated_at || "")}</td></tr>`).join("")}</table>` : '<span class="muted">Topilmadi</span>';
  };
  const loadSug = async () => {
    const [s, d] = await Promise.all([api("/api/memory/suggestions"), api("/api/memory/duplicates")]);
    $("#msug").innerHTML = `<h3>Aloqa takliflari (tasdiqingiz bilan)</h3>${s.length ? s.map((x) => `<div class="row small"><span>#${x.src} «${esc(x.src_content.slice(0, 50))}» ↔ #${x.dst} «${esc(x.dst_content.slice(0, 50))}» <span class="muted">${Math.round(x.score * 100)}%</span></span>
      <button class="small" data-acc="${x.id}">Bog'lash</button><button class="ghost small" data-rej="${x.id}">Rad</button></div>`).join("") : '<div class="muted small">Taklif yo\'q</div>'}
      <h3 style="margin-top:12px">Takroriy xotiralar</h3>${d.length ? table(d.map((x) => ({ qoldiriladi: "#" + x.keep, takror: "#" + x.duplicate, "o'xshashlik": Math.round(x.score * 100) + "%", mazmun: x.content })), ["qoldiriladi", "takror", "o'xshashlik", "mazmun"]) + '<div class="muted small">O\'chirish faqat siz tanlaganda: takrorni ochib, "O\'chirish" ni bosing.</div>' : '<div class="muted small">Takror topilmadi</div>'}`;
  };
  const detail = async (id) => {
    const [m, rel, prov] = await Promise.all([api(`/api/memory/explore?q=&limit=1000`).then((r) => r.find((x) => x.id === id)), api(`/api/memory/${id}/related`), api(`/api/memory/${id}/provenance`).catch(() => null)]);
    if (!m) { $("#mdet").innerHTML = '<span class="muted">Topilmadi</span>'; return; }
    $("#mdet").innerHTML = `<h3>#${m.id} ${esc(m.name)}</h3><div class="muted small">${esc(m.category)} · ${esc(m.reliability)} · ishonch ${m.confidence}</div>
      ${m.status === "conflict" ? '<div class="warnbox small">⚠ Bu xotira boshqa yozuv bilan zid. Avtomatik birlashtirilmaydi — qaysi biri to\'g\'riligini o\'zingiz tanlang.</div>' : ""}
      <label>Nomi</label><input id="et" value="${esc(m.title || "")}"><label>Toifa</label><select id="ek">${cats.map((c) => `<option value="${c.kind}" ${c.kind === m.kind ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select>
      <label>Mazmuni</label><textarea id="ec">${esc(m.content)}</textarea>
      <div class="kv"><span>Manba</span><span>${esc(m.reference || m.source)}</span></div><div class="kv"><span>Yaratilgan</span><span>${esc(m.created_at)}</span></div><div class="kv"><span>Oxirgi yangilanish</span><span>${esc(m.updated_at || "—")}</span></div>
      <div class="row" style="margin-top:8px"><button id="esv">Saqlash</button><button class="ghost" id="eg">🌐 Graph'da</button><button class="danger" id="edel">O'chirish</button></div><div id="emsg"></div>
      <h4>Bog'langan xotiralar</h4>${rel.length ? rel.map((r) => `<a class="rel" data-m="${r.id}">#${r.id} ${esc(r.label)} <span class="muted">(${esc(r.via)})</span></a>`).join("") : '<div class="muted small">yo\'q</div>'}
      ${prov ? `<details><summary class="muted small">Provenance</summary><pre>${esc(JSON.stringify(prov, null, 1))}</pre></details>` : ""}`;
    $("#esv").onclick = async () => { try { await api(`/api/memory/${id}`, { method: "PUT", body: { content: $("#ec").value, title: $("#et").value, kind: $("#ek").value } }); $("#emsg").innerHTML = '<span class="ok">Saqlandi</span>'; load(); } catch (e) { fail($("#emsg"), e); } };
    $("#edel").onclick = async () => { if (!confirm(`#${id} xotira butunlay o'chirilsinmi? Bu qaytarilmaydi (zaxira nusxadan tashqari).`)) return;
      try { await api(`/api/memory/${id}`, { method: "DELETE" }); $("#mdet").innerHTML = '<span class="ok">O\'chirildi</span>'; load(); loadSug(); } catch (e) { fail($("#emsg"), e); } };
    $("#eg").onclick = async () => { try { const n = await api(`/api/kg/find?type=memory&ref=${id}`); BrainState.selected = { id: n.id }; BrainState.filters.categories = []; location.hash = "graph"; } catch (e) { fail($("#emsg"), e); } };
  };
  v.onclick = async (e) => {
    const k = e.target.closest("[data-k]"), s = e.target.closest("[data-s]"), r = e.target.closest("[data-m]"), d = e.target.dataset;
    if (k) { kind = k.dataset.k; v.querySelectorAll("[data-k]").forEach((x) => x.classList.toggle("on", x === k)); load(); }
    if (s) { status = s.dataset.s; load(); }
    if (r) detail(Number(r.dataset.m));
    try { if (d.acc) { await post(`/api/memory/suggestions/${d.acc}`, { accept: true }); loadSug(); } if (d.rej) { await post(`/api/memory/suggestions/${d.rej}`, { accept: false }); loadSug(); } } catch (er) { alert(er.message); }
  };
  $("#mgo").onclick = () => { q = $("#mq").value.trim(); load(); }; $("#mq").onkeydown = (e) => { if (e.key === "Enter") { q = $("#mq").value.trim(); load(); } };
  const body = () => ({ text: $("#nc").value, title: $("#nt").value || null, project: $("#np").value || null });
  $("#nan").onclick = async () => { try { const a = await post("/api/memory/analyze", body());
    $("#nres").innerHTML = `<div class="small">Tur: <b>${esc(a.kind)}</b> · loyihalar: ${a.projects.map(esc).join(", ") || "—"}${a.duplicate_of ? ` · <span class="warn">takror: #${a.duplicate_of}</span>` : ""}${a.conflicts.length ? ` · <span class="warn">ziddiyat: ${a.conflicts.map((x) => "#" + x).join(", ")}</span>` : ""}</div>
      <div class="small">Avtomatik bog'lanadi: ${a.auto_links.map((x) => "#" + x).join(", ") || "—"} · taklif: ${a.suggested_links.map((x) => "#" + x).join(", ") || "—"}</div>`; } catch (e) { fail($("#nres"), e); } };
  $("#nsv").onclick = async () => { try { const r = await post("/api/memory/ingest", body()); $("#nres").innerHTML = r.duplicate ? `<span class="warn">${esc(r.note)}</span>` : `<span class="ok">Saqlandi #${r.memory.id} (${esc(r.memory.kind)})</span>`; load(); loadSug(); } catch (e) { fail($("#nres"), e); } };
  load(); loadSug();
}

// ================= NEURAL ACTIVITY (jonli hodisalar jurnali) =================
const EVENT_UZ = { "ai.start": "AI javob tayyorlamoqda", "ai.end": "AI javobi tayyor", "memory.search": "Xotiradan qidirildi", "memory.add": "Yangi xotira saqlandi",
  "task.start": "Vazifa boshlandi", "task.end": "Vazifa tugadi", error: "Xato", approval: "Tasdiq so'raldi", "kg.link": "Yangi bilim aloqasi", system: "Tizim" };
async function renderNeural(v) {
  Live.start();
  const snap = await api("/api/events/recent");
  if (!Live.log.length) Live.log = snap.events.slice().reverse();
  v.innerHTML = `<div class="card"><div class="row" style="justify-content:space-between"><h3 style="margin:0">Neural Activity</h3>${liveBadge()}</div>
    <p class="muted small">Faqat backend'dan kelgan haqiqiy hodisalar (SSE). Hodisa bo'lmasa — tizim tinch holatda. Faol: AI <b id="na">${snap.active.ai}</b> · vazifalar <b id="nt">${snap.active.tasks}</b></p>
    <div class="grid" id="ncount"></div></div><div class="card" style="margin-top:12px"><table id="nlog"></table></div>`;
  const draw = () => {
    const c = {}; Live.log.forEach((e) => { c[e.type] = (c[e.type] || 0) + 1; });
    $("#ncount").innerHTML = Object.keys(EVENT_UZ).map((k) => `<div class="card"><div class="muted small">${esc(EVENT_UZ[k])}</div><div class="big">${c[k] || 0}</div></div>`).join("");
    $("#nlog").innerHTML = `<tr><th>vaqt</th><th>hodisa</th><th>tafsilot</th></tr>` + Live.log.slice(0, 120).map((e) => `<tr><td class="small">${esc(new Date(e.ts * 1000).toLocaleTimeString())}</td><td>${esc(EVENT_UZ[e.type] || e.type)}</td>
      <td class="small muted">${esc(Object.entries(e).filter(([k]) => !["seq", "ts", "type"].includes(k)).map(([k, x]) => `${k}: ${Array.isArray(x) ? x.slice(0, 6).join(",") : x}`).join(" · "))}</td></tr>`).join("");
  };
  draw(); let t = null; const off = Live.on(() => { clearTimeout(t); t = setTimeout(() => { if (!$("#nlog").isConnected) { off(); return; } draw(); }, 300); });
  VIZ.items.add({ dispose: off });
}

// Dashboard uchun ixcham ko'rinish
async function brainCompact(el) {
  try { const s = await api("/api/brain/state");
    el.innerHTML = `<div class="neo-mini"><div class="row" style="justify-content:space-between"><b>🧠 JARVIS Brain</b>${liveBadge()}</div>
      <div class="mini-regs">${s.regions.map((r) => `<span title="${esc(r.uz)}: ${esc(r.status)}"><i style="background:${r.status === "error" ? "#ef4444" : r.color};opacity:${r.status === "idle" ? 0.45 : 1}"></i>${esc(r.name.replace(" Center", ""))}</span>`).join("")}</div>
      <div class="row" style="margin-top:8px"><a href="#brain"><button class="small">🧠 3D Brain</button></a><a href="#graph"><button class="ghost small">🌐 Graph Explorer</button></a></div></div>`;
    Live.start();
  } catch (e) { el.innerHTML = ""; }
}
