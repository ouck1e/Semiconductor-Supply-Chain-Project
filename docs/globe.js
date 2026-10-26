// Stub so the ECharts world-map script hands its GeoJSON to us instead of to ECharts.
window.__worldGeo = null;
window.echarts = { registerMap: function (name, geo) { window.__worldGeo = geo; if (window.__onWorld) window.__onWorld(geo); } };
(function () {
  if (!window.THREE) { document.getElementById('status').textContent = '3D library failed to load'; return; }
  const T = THREE;
  const stage = document.getElementById('stage');
  const reduceMotion = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------- renderer / scene ----------
  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  stage.appendChild(renderer.domElement);
  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(40, 1, 0.1, 100);
  let camDist = 3.6;
  camera.position.set(0, 0, camDist);

  const globe = new T.Group();
  scene.add(globe);
  const R = 1;

  function ll2v(lat, lon, r) {
    const phi = (90 - lat) * Math.PI / 180, th = (lon + 180) * Math.PI / 180;
    return new T.Vector3(-r * Math.sin(phi) * Math.cos(th), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(th));
  }

  // Ocean sphere: dark with a soft fresnel rim
  const oceanMat = new T.ShaderMaterial({
    uniforms: {},
    vertexShader: `varying vec3 vN; varying vec3 vV;
      void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `varying vec3 vN; varying vec3 vV;
      void main(){ float f = pow(1.0 - max(dot(vN, vV), 0.0), 2.5);
        vec3 base = mix(vec3(0.043,0.051,0.063), vec3(0.102,0.122,0.149), vN.y*0.5+0.5);
        vec3 rim = mix(vec3(0.180,0.212,0.251), vec3(0.486,0.529,0.580), f);
        gl_FragColor = vec4(mix(base, rim, f*0.85), 1.0); }`
  });
  globe.add(new T.Mesh(new T.SphereGeometry(R, 96, 96), oceanMat));

  // Atmosphere halo (back-faced, additive)
  const atmo = new T.Mesh(new T.SphereGeometry(R * 1.18, 64, 64), new T.ShaderMaterial({
    side: T.BackSide, transparent: true, blending: T.AdditiveBlending, depthWrite: false,
    vertexShader: `varying vec3 vN; void main(){ vN = normalize(normalMatrix*normal); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
    fragmentShader: `varying vec3 vN; void main(){ float i = pow(0.72 - dot(vN, vec3(0.0,0.0,1.0)), 3.0); gl_FragColor = vec4(0.486,0.529,0.580,1.0)*i*1.1; }`
  }));
  scene.add(atmo);

  // Graticule (every 30°)
  (function () {
    const pts = [];
    for (let lat = -60; lat <= 60; lat += 30) for (let lon = -180; lon < 180; lon += 3) { pts.push(ll2v(lat, lon, R * 1.001), ll2v(lat, lon + 3, R * 1.001)); }
    for (let lon = -180; lon < 180; lon += 30) for (let lat = -90; lat < 90; lat += 3) { pts.push(ll2v(lat, lon, R * 1.001), ll2v(lat + 3, lon, R * 1.001)); }
    const g = new T.BufferGeometry().setFromPoints(pts);
    globe.add(new T.LineSegments(g, new T.LineBasicMaterial({ color: 0x7c8794, transparent: true, opacity: 0.12 })));
  })();

  // Body-axis lines through the poles etc. so X/Y/Z rotations read clearly
  (function () {
    const mk = (a, b, c) => { const g = new T.BufferGeometry().setFromPoints([a, b]); return new T.Line(g, new T.LineBasicMaterial({ color: c, transparent: true, opacity: 0.55 })); };
    globe.add(mk(new T.Vector3(0, -1.32, 0), new T.Vector3(0, 1.32, 0), 0xe6e9ee));
    // Fixed vertical reference (orbital-plane normal) so the tilt angle is visible
    const ref = mk(new T.Vector3(0, -1.32, 0), new T.Vector3(0, 1.32, 0), 0x7c8794);
    ref.material.opacity = 0.3; scene.add(ref);
  })();

  // ---------- land dots + borders from world GeoJSON ----------
  const dotMat = new T.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uSize: { value: 3.0 * renderer.getPixelRatio() }, uColor: { value: new T.Color(0xe6e9ee) } },
    vertexShader: `uniform float uSize; varying float vFace;
      void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0);
        vec3 n = normalize(normalMatrix*position); vFace = dot(n, normalize(-mv.xyz));
        gl_PointSize = uSize * (3.6 / -mv.z); gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 uColor; varying float vFace;
      void main(){ vec2 c = gl_PointCoord - 0.5; float d = length(c); if (d > 0.5) discard;
        float a = smoothstep(0.5, 0.2, d) * clamp(vFace*1.4+0.15, 0.0, 1.0);
        gl_FragColor = vec4(uColor, a); }`
  });
  let landDots = null, borders = null;

  function decodeRing(str, off, scale) {
    const out = []; let px = off[0], py = off[1];
    for (let i = 0; i < str.length; i += 2) {
      let x = str.charCodeAt(i) - 64, y = str.charCodeAt(i + 1) - 64;
      x = (x >> 1) ^ (-(x & 1)); y = (y >> 1) ^ (-(y & 1));
      x += px; y += py; px = x; py = y;
      out.push([x / scale, y / scale]);
    }
    return out;
  }
  function polygonsOf(geo) {
    const scale = geo.UTF8Scale || 1024, enc = !!geo.UTF8Encoding, polys = [];
    for (const f of geo.features || []) {
      const g = f.geometry; if (!g) continue;
      if (g.type === 'Polygon') polys.push(g.coordinates.map((r, i) => enc ? decodeRing(r, g.encodeOffsets[i], scale) : r));
      else if (g.type === 'MultiPolygon') g.coordinates.forEach((p, j) => polys.push(p.map((r, i) => enc ? decodeRing(r, g.encodeOffsets[j][i], scale) : r)));
    }
    return polys;
  }

  function buildLand(geo) {
    const polys = polygonsOf(geo);
    if (!polys.length) return false;
    // Rasterize land to an equirectangular mask
    const W = 2048, H = 1024, cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const cx = cv.getContext('2d', { willReadFrequently: true });
    cx.fillStyle = '#fff';
    for (const p of polys) {
      cx.beginPath();
      for (const ring of p) ring.forEach(([lon, lat], k) => {
        const x = (lon + 180) / 360 * W, y = (90 - lat) / 180 * H;
        k ? cx.lineTo(x, y) : cx.moveTo(x, y);
      });
      cx.fill('evenodd');
    }
    const mask = cx.getImageData(0, 0, W, H).data;
    // Fibonacci sphere sampling for even dot spacing
    const N = 60000, ga = Math.PI * (3 - Math.sqrt(5)), pos = [];
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2, lat = Math.asin(y) * 180 / Math.PI;
      let lon = ((ga * i) * 180 / Math.PI) % 360 - 180;
      const px = Math.min(W - 1, Math.floor((lon + 180) / 360 * W)), py = Math.min(H - 1, Math.floor((90 - lat) / 180 * H));
      if (mask[(py * W + px) * 4] > 128) { const v = ll2v(lat, lon, R * 1.004); pos.push(v.x, v.y, v.z); }
    }
    const g = new T.BufferGeometry();
    g.setAttribute('position', new T.Float32BufferAttribute(pos, 3));
    landDots = new T.Points(g, dotMat);
    globe.add(landDots);
    // Country outlines
    const seg = [];
    for (const p of polys) for (const ring of p) for (let k = 1; k < ring.length; k++) {
      const a = ring[k - 1], b = ring[k];
      if (Math.abs(a[0] - b[0]) > 180) continue;
      seg.push(ll2v(a[1], a[0], R * 1.003), ll2v(b[1], b[0], R * 1.003));
    }
    borders = new T.LineSegments(new T.BufferGeometry().setFromPoints(seg),
      new T.LineBasicMaterial({ color: 0x7c8794, transparent: true, opacity: 0.4 }));
    globe.add(borders);
    return true;
  }

  const statusEl = document.getElementById('status');
  function onWorld(geo) {
    try { statusEl.textContent = buildLand(geo) ? 'Live' : 'Map data empty'; }
    catch (e) { statusEl.textContent = 'Map failed to draw'; console.error(e); }
  }
  window.__onWorld = onWorld;
  if (window.__worldGeo) onWorld(window.__worldGeo);
  function loadMap(srcs) {
    if (!srcs.length) { statusEl.textContent = 'Map offline · grid only'; return; }
    const s = document.createElement('script');
    s.src = srcs[0];
    s.onerror = () => loadMap(srcs.slice(1));
    s.onload = () => { if (!window.__worldGeo) loadMap(srcs.slice(1)); };
    document.body.appendChild(s);
  }
  loadMap([
    'https://cdn.jsdelivr.net/npm/echarts@4.9.0/map/js/world.js',
    'https://unpkg.com/echarts@4.9.0/map/js/world.js'
  ]);

  // ---------- semiconductor trade flows (yellow arcs) ----------
  // Latest published figures as of Oct 2026. Trade statistics are released monthly or yearly with a lag,
  // so each flow carries its own period and source. status: ok | restricted (export controls/licensing) | disrupted
  const NODES = {
    ningbo:[29.87,121.55,'Ningbo, China'], china:[34.75,113.62,'China'], ganzhou:[25.83,114.93,'Ganzhou, China'],
    kachin:[25.90,98.40,'Kachin State, Myanmar'], mtweld:[-28.86,122.55,'Mount Weld, Australia'], kuantan:[3.97,103.38,'Kuantan, Malaysia'],
    mtpass:[35.48,-115.53,'Mountain Pass, USA'], shandong:[36.80,118.05,'Shandong, China'], yunnan:[23.88,100.09,'Yunnan, China'],
    sprucepine:[35.92,-82.06,'Spruce Pine, USA'], burghausen:[48.17,12.83,'Burghausen, Germany'], hemlock:[43.42,-84.02,'Hemlock, USA'],
    jpwafer:[37.13,140.21,'Japanese wafer makers'], raslaffan:[25.90,51.55,'Ras Laffan, Qatar'], odesa:[46.48,30.73,'Odesa, Ukraine'],
    veldhoven:[51.41,5.41,'Veldhoven, Netherlands'], oberkochen:[48.78,10.10,'Oberkochen, Germany'], sandiego:[32.90,-117.20,'San Diego, USA'],
    tokyo:[35.67,139.75,'Japan'], svalley:[37.37,-121.96,'United States'], singapore:[1.35,103.82,'Singapore'],
    shanghai:[31.20,121.60,'China'], hk:[22.32,114.17,'China & Hong Kong'], hsinchu:[24.78,121.00,'Taiwan'], tainan:[23.11,120.27,'Taiwan'],
    taoyuan:[24.99,121.30,'Taiwan'], pyeongtaek:[37.02,127.05,'South Korea'], icheon:[37.20,127.40,'South Korea'], seoul:[37.57,126.98,'South Korea'],
    hillsboro:[45.54,-122.96,'Hillsboro, USA'], penang:[5.30,100.28,'Malaysia'], kiryat:[31.61,34.77,'Israel'], leixlip:[53.36,-6.50,'Ireland'],
    germany:[50.11,8.68,'Germany'], bacninh:[21.19,106.07,'Vietnam'], usa:[39.00,-95.70,'United States'],
    guadalajara:[20.67,-103.35,'Mexico'], ashburn:[39.04,-77.49,'United States']
  };
  const STAGE_LABEL = { mat:'Raw materials', eq:'Equipment', chip:'Chips', sys:'Servers' };
  const SRC = {
    reuters:'China customs data via Reuters', silverado:'Silverado Policy Accelerator', trendforce:'TrendForce',
    caixin:'ASML results via Caixin', census:'US Census import data (HTS 8542)', mofa:'Korea trade ministry via JoongAng Daily',
    banamex:'Banamex / Mexico News Daily', moea:'Taiwan Ministry of Economic Affairs', mofcom:'China Ministry of Commerce via Reuters',
    techspot:'QatarEnergy / industry reports', csis:'CSIS “From Mine to Microchip”', industry:'Industry and company reports'
  };
  const FLOWS = [
    // Raw materials and inputs
    { st:'mat', f:'kachin', t:'ganzhou', item:'Heavy rare-earth ore', val:'Most of Myanmar’s output is refined in China', per:'Ongoing', s:'ok', w:1, src:'csis' },
    { st:'mat', f:'mtweld', t:'kuantan', item:'Rare-earth concentrate', val:'Shipped to Lynas’s separation plant in Malaysia', per:'Ongoing', s:'ok', w:1, src:'industry' },
    { st:'mat', f:'mtpass', t:'china', item:'Rare-earth concentrate', val:'MP Materials stopped shipping to China in April 2025', per:'Since Apr 2025', s:'disrupted', w:1, src:'industry' },
    { st:'mat', f:'ningbo', t:'germany', item:'Rare-earth magnets', val:'Largest destination; China exported 10,763 t in total (+8.2% y/y)', per:'Jan–Feb 2026', s:'restricted', w:2, src:'reuters' },
    { st:'mat', f:'ningbo', t:'seoul', item:'Rare-earth magnets', val:'Second-largest destination', per:'Jan–Feb 2026', s:'restricted', w:2, src:'reuters' },
    { st:'mat', f:'ningbo', t:'usa', item:'Rare-earth magnets', val:'994 t (−22.5% y/y)', per:'Jan–Feb 2026', s:'restricted', w:2, src:'reuters' },
    { st:'mat', f:'ningbo', t:'tokyo', item:'Rare-earth magnets', val:'444 t (+9.5% y/y)', per:'Jan–Feb 2026', s:'restricted', w:1, src:'reuters' },
    { st:'mat', f:'ningbo', t:'bacninh', item:'Rare-earth magnets', val:'A top-five destination', per:'Jan–Feb 2026', s:'restricted', w:1, src:'reuters' },
    { st:'mat', f:'shandong', t:'usa', item:'Gallium', val:'China makes ~98% of primary gallium. The US ban is suspended until Nov 27, 2026, but licenses are still required', per:'Through Nov 2026', s:'restricted', w:1, src:'mofcom' },
    { st:'mat', f:'shandong', t:'tokyo', item:'Gallium', val:'Feedstock for compound semiconductors; licensed exports', per:'Ongoing', s:'restricted', w:1, src:'mofcom' },
    { st:'mat', f:'yunnan', t:'usa', item:'Germanium', val:'US ban suspended until Nov 27, 2026; licenses still required', per:'Through Nov 2026', s:'restricted', w:1, src:'mofcom' },
    { st:'mat', f:'sprucepine', t:'jpwafer', item:'High-purity quartz', val:'Used for the crucibles that grow silicon crystals', per:'Ongoing', s:'ok', w:1, src:'csis' },
    { st:'mat', f:'burghausen', t:'jpwafer', item:'Hyperpure polysilicon', val:'Raw silicon for wafer makers', per:'Ongoing', s:'ok', w:1, src:'industry' },
    { st:'mat', f:'hemlock', t:'jpwafer', item:'Electronic-grade polysilicon', val:'Raw silicon for wafer makers', per:'Ongoing', s:'ok', w:1, src:'industry' },
    { st:'mat', f:'jpwafer', t:'hsinchu', item:'Silicon wafers', val:'Shin-Etsu and SUMCO make about half of the world’s wafers', per:'Ongoing', s:'ok', w:2, src:'industry' },
    { st:'mat', f:'jpwafer', t:'pyeongtaek', item:'Silicon wafers', val:'Wafers for Samsung and SK hynix fabs', per:'Ongoing', s:'ok', w:1, src:'industry' },
    { st:'mat', f:'jpwafer', t:'shanghai', item:'Silicon wafers', val:'Wafers for Chinese fabs', per:'Ongoing', s:'ok', w:1, src:'industry' },
    { st:'mat', f:'raslaffan', t:'pyeongtaek', item:'Helium', val:'Korea got ~65% of its helium from Qatar in 2025. Ras Laffan has been offline since Mar 2, 2026 (force majeure)', per:'Since Mar 2026', s:'disrupted', w:2, src:'techspot' },
    { st:'mat', f:'raslaffan', t:'hsinchu', item:'Helium', val:'Ras Laffan supplies nearly a third of world helium and is offline', per:'Since Mar 2026', s:'disrupted', w:1, src:'techspot' },
    { st:'mat', f:'odesa', t:'pyeongtaek', item:'Neon gas', val:'A major pre-war route for lithography-laser gas, now largely replaced', per:'Since 2022', s:'disrupted', w:1, src:'csis' },
    // Equipment
    { st:'eq', f:'oberkochen', t:'veldhoven', item:'EUV optics', val:'Zeiss builds the mirrors for every EUV machine', per:'Ongoing', s:'ok', w:1, src:'industry' },
    { st:'eq', f:'sandiego', t:'veldhoven', item:'EUV light sources', val:'Cymer (ASML) light-source modules', per:'Ongoing', s:'ok', w:1, src:'industry' },
    { st:'eq', f:'veldhoven', t:'shanghai', item:'Lithography machines (DUV only)', val:'China was 33% of ASML’s 2025 sales, its largest market. EUV sales are banned and ASML expects a decline in 2026', per:'2025', s:'restricted', w:3, src:'caixin' },
    { st:'eq', f:'veldhoven', t:'hsinchu', item:'EUV lithography machines', val:'TSMC’s leading-edge nodes depend on ASML EUV', per:'Ongoing', s:'ok', w:2, src:'industry' },
    { st:'eq', f:'veldhoven', t:'pyeongtaek', item:'EUV lithography machines', val:'For Samsung and SK hynix', per:'Ongoing', s:'ok', w:2, src:'industry' },
    { st:'eq', f:'veldhoven', t:'hillsboro', item:'High-NA EUV machines', val:'Intel took the first High-NA EUV tools', per:'Ongoing', s:'ok', w:1, src:'industry' },
    { st:'eq', f:'tokyo', t:'shanghai', item:'Chipmaking tools', val:'$14.3B in 2024 (30.4% of China’s imports, the largest source); $6.4B in 1H 2025. China’s tool imports hit a record $51.1B in 2025', per:'2024–1H 2025', s:'restricted', w:3, src:'trendforce' },
    { st:'eq', f:'svalley', t:'shanghai', item:'Chipmaking tools', val:'~9% of China’s 2025 tool imports, down from 23% in 2016', per:'2025', s:'restricted', w:2, src:'silverado' },
    { st:'eq', f:'singapore', t:'shanghai', item:'Chipmaking tools', val:'One of China’s four largest tool sources in 2025', per:'2025', s:'ok', w:2, src:'silverado' },
    // Chips
    { st:'chip', f:'tainan', t:'svalley', item:'Integrated circuits', val:'$7.41B, 37.3% of US chip imports (the largest source)', per:'Mar–Jul 2026', s:'ok', w:3, src:'census' },
    { st:'chip', f:'penang', t:'svalley', item:'Integrated circuits', val:'$2.70B, 13.6% of US chip imports', per:'Mar–Jul 2026', s:'ok', w:2, src:'census' },
    { st:'chip', f:'icheon', t:'svalley', item:'Integrated circuits', val:'$2.27B, 11.4% of US chip imports', per:'Mar–Jul 2026', s:'ok', w:2, src:'census' },
    { st:'chip', f:'kiryat', t:'svalley', item:'Integrated circuits', val:'$2.01B, 10.1% of US chip imports', per:'Mar–Jul 2026', s:'ok', w:2, src:'census' },
    { st:'chip', f:'leixlip', t:'svalley', item:'Integrated circuits', val:'$1.59B, 8.0% of US chip imports', per:'Mar–Jul 2026', s:'ok', w:2, src:'census' },
    { st:'chip', f:'icheon', t:'hk', item:'Memory chips', val:'$42.5B, 51.7% of Korea’s chip exports', per:'Jan–Nov 2024', s:'ok', w:3, src:'mofa' },
    { st:'chip', f:'icheon', t:'hsinchu', item:'HBM memory', val:'$18.5B (+119% y/y), mostly HBM paired with Nvidia GPUs at TSMC', per:'Jan–Nov 2024', s:'ok', w:3, src:'mofa' },
    { st:'chip', f:'pyeongtaek', t:'bacninh', item:'Chips for device assembly', val:'12.9% of Korea’s chip exports', per:'Jan–Nov 2024', s:'ok', w:2, src:'mofa' },
    { st:'chip', f:'hsinchu', t:'hk', item:'Chips and electronics', val:'$137.8B in export orders, all goods', per:'2025', s:'ok', w:3, src:'moea' },
    { st:'chip', f:'tainan', t:'penang', item:'Wafers for packaging', val:'Chips sent to Malaysia for assembly and test', per:'Ongoing', s:'ok', w:1, src:'industry' },
    // AI servers
    { st:'sys', f:'taoyuan', t:'ashburn', item:'AI servers', val:'$72.2B; 36% of US server imports in 1H 2026', per:'1H 2026', s:'ok', w:3, src:'banamex' },
    { st:'sys', f:'guadalajara', t:'ashburn', item:'AI servers', val:'$60.4B; nearly 40% of US server imports in Q2 2026, passing Taiwan', per:'1H 2026', s:'ok', w:3, src:'banamex' },
    { st:'sys', f:'taoyuan', t:'guadalajara', item:'Server components', val:'Taiwanese makers (Foxconn, Inventec) assemble in Mexico', per:'Ongoing', s:'ok', w:2, src:'banamex' }
  ];
  const STATUS_LABEL = { ok:'Flowing', restricted:'Under export controls', disrupted:'Disrupted' };

  const arcGroup = new T.Group(); globe.add(arcGroup);
  const flowGroups = { mat: new T.Group(), eq: new T.Group(), chip: new T.Group(), sys: new T.Group() };
  Object.values(flowGroups).forEach(g => arcGroup.add(g));
  const rings = [], flowTargets = [];
  const nodeGeo = new T.SphereGeometry(0.006, 10, 10), nodeMat = new T.MeshBasicMaterial({ color: 0xffd36b });
  const usedNodes = new Set(); FLOWS.forEach(fl => { usedNodes.add(fl.f); usedNodes.add(fl.t); });
  usedNodes.forEach(k => {
    const [lat, lon] = NODES[k], v = ll2v(lat, lon, R * 1.004);
    const m = new T.Mesh(nodeGeo, nodeMat); m.position.copy(v); arcGroup.add(m);
  });
  const arcMats = [];
  const arcVS = `attribute float t; varying float vT; void main(){ vT = t; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`;
  const arcFS = `uniform float uTime; uniform float uOff; uniform float uSpeed; uniform float uDash; uniform float uW; varying float vT;
        void main(){
          if (uDash > 0.5 && fract(vT*40.0) > 0.55) discard;
          float head = fract(uTime*uSpeed + uOff); float d = head - vT;
          float trail = d >= 0.0 ? exp(-d*9.0) : 0.0;
          trail *= (uDash > 0.5) ? 0.45 : 1.0;
          vec3 c = mix(vec3(1.0,0.55,0.35), vec3(1.0,0.85,0.45), trail);
          gl_FragColor = vec4(c, 0.05 + 0.05*uW + trail*(0.55 + 0.2*uW)); }`;
  FLOWS.forEach(fl => {
    const A = NODES[fl.f], B = NODES[fl.t];
    const va = ll2v(A[0], A[1], R), vb = ll2v(B[0], B[1], R);
    const ang = va.angleTo(vb), mid = va.clone().add(vb).normalize().multiplyScalar(R + 0.03 + ang * 0.2);
    const curve = new T.QuadraticBezierCurve3(va.clone().multiplyScalar(1.004), mid, vb.clone().multiplyScalar(1.004));
    const P = curve.getPoints(Math.max(30, Math.round(ang * 80))), g = new T.BufferGeometry().setFromPoints(P);
    g.setAttribute('t', new T.Float32BufferAttribute(P.map((_, i) => i / (P.length - 1)), 1));
    const dashed = fl.s !== 'ok';
    const mat = new T.ShaderMaterial({
      transparent: true, depthWrite: false, blending: T.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uOff: { value: Math.random() }, uSpeed: { value: (dashed ? 0.06 : 0.12) / (0.25 + ang) },
                  uDash: { value: dashed ? 1 : 0 }, uW: { value: fl.w } },
      vertexShader: arcVS, fragmentShader: arcFS
    });
    arcMats.push(mat);
    flowGroups[fl.st].add(new T.Line(g, mat));
    for (let i = 2; i <= 18; i++) flowTargets.push({ kind: 'flow', flow: fl, v: curve.getPoint(i / 20) });
  });

  // ---------- semiconductor supply-chain sites (red pins) ----------
  // cat: fab = fabs & packaging, mat = raw materials & inputs, hq = company headquarters & toolmakers
  // Status notes reflect public reporting as of Oct 2026.
  const SITES = [
    // Fabs, megafabs & packaging
    { cat:'fab', name:'TSMC Fab 18', place:'Tainan, Taiwan', lat:23.11, lon:120.27, note:'Gigafab producing TSMC’s 3 nm and 5 nm chips, including most leading-edge AI and phone processors.' },
    { cat:'fab', name:'TSMC Fab 15', place:'Taichung, Taiwan', lat:24.21, lon:120.62, note:'Gigafab for 7 nm-class and mature nodes.' },
    { cat:'fab', name:'TSMC Fab 22 · ASE', place:'Kaohsiung, Taiwan', lat:22.71, lon:120.30, note:'TSMC 2 nm production site; ASE, the world’s largest chip packaging and test company, is also based here.' },
    { cat:'fab', name:'TSMC Arizona (Fab 21)', place:'Phoenix, Arizona, USA', lat:33.75, lon:-112.12, note:'Phase 1 in volume production since 2025; more phases under construction.' },
    { cat:'fab', name:'JASM Kumamoto', place:'Kikuyo, Kumamoto, Japan', lat:32.88, lon:130.78, note:'TSMC joint venture with Sony and Denso. Fab 1 is producing; Fab 2 is delayed.' },
    { cat:'fab', name:'ESMC Dresden', place:'Dresden, Germany', lat:51.12, lon:13.73, note:'TSMC joint venture with Bosch, Infineon and NXP, under construction. Dresden is Europe’s largest chip cluster and also hosts GlobalFoundries and Infineon fabs.' },
    { cat:'fab', name:'Samsung Pyeongtaek', place:'Pyeongtaek, South Korea', lat:37.02, lon:127.05, note:'One of the world’s largest fab complexes, making memory and foundry chips.' },
    { cat:'fab', name:'Samsung Taylor', place:'Taylor, Texas, USA', lat:30.57, lon:-97.41, note:'Foundry fab in risk production; volume production reportedly slipping to 2027.' },
    { cat:'fab', name:'SK hynix Icheon & Yongin', place:'Gyeonggi, South Korea', lat:37.20, lon:127.40, note:'SK hynix HQ and DRAM/HBM fabs. A large new memory cluster is being built at Yongin.' },
    { cat:'fab', name:'SK hynix Cheongju', place:'Cheongju, South Korea', lat:36.64, lon:127.43, note:'NAND flash fabs and HBM packaging.' },
    { cat:'fab', name:'SK hynix Indiana', place:'West Lafayette, Indiana, USA', lat:40.43, lon:-86.91, note:'HBM advanced-packaging plant under construction.' },
    { cat:'fab', name:'Intel Ocotillo', place:'Chandler, Arizona, USA', lat:33.27, lon:-111.88, note:'Intel’s newest fabs, including Fab 52 for the Intel 18A process.' },
    { cat:'fab', name:'Intel Ronler Acres', place:'Hillsboro, Oregon, USA', lat:45.54, lon:-122.96, note:'Intel’s main R&D fab, where new process nodes are developed.' },
    { cat:'fab', name:'Intel Ohio One', place:'New Albany, Ohio, USA', lat:40.08, lon:-82.75, note:'Planned megafab with construction delayed into the 2030s.' },
    { cat:'fab', name:'Intel Leixlip', place:'Leixlip, Ireland', lat:53.36, lon:-6.50, note:'Intel’s main European fab.' },
    { cat:'fab', name:'Intel Kiryat Gat', place:'Kiryat Gat, Israel', lat:31.61, lon:34.77, note:'Intel high-volume fab.' },
    { cat:'fab', name:'Micron Boise', place:'Boise, Idaho, USA', lat:43.53, lon:-116.15, note:'Micron HQ, with a new DRAM megafab under construction.' },
    { cat:'fab', name:'Micron Clay megafab', place:'Clay, New York, USA', lat:43.17, lon:-76.17, note:'Planned memory megafab that broke ground in 2026.' },
    { cat:'fab', name:'GlobalFoundries Fab 8', place:'Malta, New York, USA', lat:42.97, lon:-73.76, note:'Largest US-owned foundry fab.' },
    { cat:'fab', name:'Texas Instruments Sherman', place:'Sherman, Texas, USA', lat:33.63, lon:-96.61, note:'300 mm analog-chip megafab complex.' },
    { cat:'fab', name:'Rapidus IIM-1', place:'Chitose, Hokkaido, Japan', lat:42.80, lon:141.65, note:'Japan’s state-backed 2 nm pilot fab.' },
    { cat:'fab', name:'Kioxia Yokkaichi', place:'Yokkaichi, Japan', lat:34.97, lon:136.60, note:'One of the world’s largest NAND flash sites.' },
    { cat:'fab', name:'SMIC Shanghai', place:'Shanghai, China', lat:31.20, lon:121.60, note:'China’s largest foundry.' },
    { cat:'fab', name:'YMTC', place:'Wuhan, China', lat:30.45, lon:114.42, note:'China’s leading NAND flash maker.' },
    { cat:'fab', name:'CXMT', place:'Hefei, China', lat:31.80, lon:117.20, note:'China’s leading DRAM maker.' },
    { cat:'fab', name:'Penang packaging hub', place:'Penang, Malaysia', lat:5.30, lon:100.28, note:'Major chip assembly and test hub, with plants run by Intel, AMD, Micron and others.' },
    // Raw materials & critical inputs
    { cat:'mat', name:'Bayan Obo', place:'Inner Mongolia, China', lat:41.78, lon:109.97, note:'The world’s largest rare-earth mine. China dominates both mining and refining of rare earths.' },
    { cat:'mat', name:'Ganzhou ionic clays', place:'Jiangxi, China', lat:25.83, lon:114.93, note:'Main source of heavy rare earths such as dysprosium and terbium, plus a large share of rare-earth refining.' },
    { cat:'mat', name:'Kachin rare earths', place:'Kachin State, Myanmar', lat:25.90, lon:98.40, note:'Major heavy-rare-earth mining region; most of its ore goes to China for refining.' },
    { cat:'mat', name:'Mountain Pass (MP Materials)', place:'California, USA', lat:35.48, lon:-115.53, note:'The only large-scale rare-earth mine in the US.' },
    { cat:'mat', name:'Mount Weld (Lynas)', place:'Western Australia', lat:-28.86, lon:122.55, note:'The largest rare-earth supplier outside China.' },
    { cat:'mat', name:'Lynas Kuantan', place:'Pahang, Malaysia', lat:3.97, lon:103.38, note:'Rare-earth separation plant that processes Mount Weld ore.' },
    { cat:'mat', name:'Spruce Pine quartz', place:'North Carolina, USA', lat:35.92, lon:-82.06, note:'Supplies most of the world’s high-purity quartz, used in the crucibles that grow silicon wafers.' },
    { cat:'mat', name:'Gallium refining', place:'Shandong, China', lat:36.80, lon:118.05, note:'China produces about 98% of the world’s primary gallium, which is now under export controls.' },
    { cat:'mat', name:'Germanium (Lincang)', place:'Yunnan, China', lat:23.88, lon:100.09, note:'Center of China’s germanium output, also under export controls.' },
    { cat:'mat', name:'Wacker Burghausen', place:'Bavaria, Germany', lat:48.17, lon:12.83, note:'Major maker of the hyperpure polysilicon used for wafers.' },
    { cat:'mat', name:'Hemlock Semiconductor', place:'Michigan, USA', lat:43.42, lon:-84.02, note:'The largest US producer of electronic-grade polysilicon.' },
    { cat:'mat', name:'Neon gas (Odesa)', place:'Odesa, Ukraine', lat:46.48, lon:30.73, note:'Ukraine supplied a large share of the semiconductor-grade neon used in lithography lasers before 2022.' },
    { cat:'mat', name:'Ras Laffan helium', place:'Qatar', lat:25.90, lon:51.55, note:'Produces nearly a third of world helium, which fabs use for cooling and process gases. Offline since Iranian drone strikes on Mar 2, 2026.' },
    // Company headquarters & equipment makers
    { cat:'hq', name:'TSMC HQ · Hsinchu', place:'Hsinchu, Taiwan', lat:24.78, lon:121.00, note:'Headquarters of the world’s largest foundry, inside Hsinchu Science Park.', companies:'TSMC, MediaTek, UMC' },
    { cat:'hq', name:'ASML', place:'Veldhoven, Netherlands', lat:51.41, lon:5.41, note:'The only maker of the EUV lithography machines every leading-edge fab needs.' },
    { cat:'hq', name:'Carl Zeiss SMT', place:'Oberkochen, Germany', lat:48.78, lon:10.10, note:'Builds the optics inside every ASML EUV machine.' },
    { cat:'hq', name:'Silicon Valley', place:'Santa Clara, California, USA', lat:37.37, lon:-121.96, note:'Home to Nvidia’s headquarters and the world’s densest cluster of chip designers and toolmakers.', companies:'Nvidia, AMD, Intel, Apple, Broadcom, Applied Materials, Lam Research, KLA' },
    { cat:'hq', name:'Qualcomm · Cymer', place:'San Diego, California, USA', lat:32.90, lon:-117.20, note:'Qualcomm HQ, plus Cymer, which makes the light sources for ASML’s machines.', companies:'Qualcomm, Cymer (ASML)' },
    { cat:'hq', name:'Samsung Electronics', place:'Suwon, South Korea', lat:37.26, lon:127.03, note:'Samsung Electronics HQ, next to its Hwaseong and Giheung fabs.' },
    { cat:'hq', name:'Tokyo equipment & materials', place:'Tokyo, Japan', lat:35.67, lon:139.75, note:'Headquarters of key toolmakers and wafer and chemical suppliers.', companies:'Tokyo Electron, Shin-Etsu, SUMCO, Advantest' },
    { cat:'hq', name:'Arm', place:'Cambridge, United Kingdom', lat:52.20, lon:0.13, note:'Designs the chip architecture used in nearly every smartphone and a growing share of servers.' },
    { cat:'hq', name:'Huawei · HiSilicon', place:'Shenzhen, China', lat:22.65, lon:114.06, note:'China’s leading chip designer.' },
    { cat:'hq', name:'Texas Instruments', place:'Dallas, Texas, USA', lat:32.91, lon:-96.75, note:'The largest analog-chip maker.' }
  ];
  const CAT_LABEL = { fab: 'Fab or packaging site', mat: 'Raw material or input', hq: 'Headquarters' };
  const pinGroups = { fab: new T.Group(), mat: new T.Group(), hq: new T.Group() };
  Object.values(pinGroups).forEach(g => globe.add(g));
  const PIN_RED = 0xff4a4a;
  const stalkGeo = new T.CylinderGeometry(0.0016, 0.0016, 0.05, 6); stalkGeo.translate(0, 0.025, 0);
  const headGeo = new T.SphereGeometry(0.0105, 14, 14); headGeo.translate(0, 0.055, 0);
  const stalkMat = new T.MeshBasicMaterial({ color: 0xc9cfd6 });
  const headMat = new T.MeshBasicMaterial({ color: PIN_RED });
  const UP = new T.Vector3(0, 1, 0);
  const pinTargets = [];
  SITES.forEach(s => {
    const n = ll2v(s.lat, s.lon, 1).normalize();
    const pin = new T.Group();
    pin.position.copy(n.clone().multiplyScalar(R * 1.002));
    pin.quaternion.setFromUnitVectors(UP, n);
    pin.add(new T.Mesh(stalkGeo, stalkMat), new T.Mesh(headGeo, headMat));
    pinGroups[s.cat].add(pin);
    pinTargets.push({ kind: 'pin', site: s, v: n.clone().multiplyScalar(R * 1.002 + 0.055) });
  });

  // ---------- risk layer: model exposure scores + Geopolitical Risk Index alerts ----------
  // Generated from phase3 outputs (exposure_scores_latest.csv) and fetch_gpr.py (gpr_monthly.csv).
  const RISK = /*RISK_JSON*/{"gprAsof":"2026-09","countries":{"Algeria":{"name":"Algeria","lat":28.0,"lon":2.6,"iso":null,"status":"normal"},"Brazil":{"name":"Brazil","lat":-14.2,"lon":-51.9,"iso":"BRA","proxy":false,"ratio":0.69,"latest":0.13,"spark":[0.09,0.21,0.09,0.19,0.05,0.09,0.1,0.07,0.09,0.1,0.11,0.09,0.13,0.09,0.09,0.18,0.09,0.18,0.09,0.11,0.09,0.07,0.03,0.13],"status":"normal"},"Canada":{"name":"Canada","lat":52.0,"lon":-106.0,"iso":"CAN","proxy":false,"ratio":0.94,"latest":0.6,"spark":[0.22,0.33,0.31,0.34,0.65,0.96,0.39,0.74,0.94,0.39,0.45,0.4,0.27,0.3,0.2,0.67,0.41,0.79,0.63,0.48,0.32,0.33,0.34,0.6],"status":"normal"},"China":{"name":"China","lat":35.0,"lon":104.0,"iso":"CHN","proxy":false,"ratio":1.07,"latest":1.19,"spark":[0.98,1.01,0.84,0.86,1.1,1.08,1.06,1.13,1.39,0.9,0.82,0.98,0.94,0.63,1.0,1.49,0.88,1.7,1.62,1.72,0.85,1.15,1.02,1.19],"status":"normal"},"France":{"name":"France","lat":46.6,"lon":2.4,"iso":"FRA","proxy":false,"ratio":0.66,"latest":0.63,"spark":[0.65,0.69,0.55,0.63,1.03,1.35,0.76,1.02,1.1,0.71,0.98,0.88,0.57,0.55,0.68,0.92,0.56,1.96,1.34,0.91,1.08,0.64,0.45,0.63],"status":"normal"},"Germany":{"name":"Germany","lat":51.2,"lon":10.4,"iso":"DEU","proxy":false,"ratio":0.7,"latest":0.49,"spark":[0.55,0.7,0.54,0.53,1.15,0.95,0.62,0.68,0.92,0.66,0.91,0.69,0.54,0.55,0.7,0.66,0.46,1.43,0.95,0.8,0.63,0.59,0.4,0.49],"status":"normal"},"Ireland":{"name":"Ireland","lat":53.2,"lon":-8.0,"iso":null,"status":"normal"},"Israel":{"name":"Israel","lat":31.0,"lon":34.9,"iso":"ISR","proxy":false,"ratio":0.83,"latest":1.61,"spark":[2.1,1.41,1.61,1.03,1.0,1.2,1.13,1.92,4.18,1.8,1.52,1.37,1.49,0.58,0.66,1.16,1.13,6.39,3.76,2.22,2.5,1.89,1.16,1.61],"status":"normal"},"Japan":{"name":"Japan","lat":36.2,"lon":138.3,"iso":"JPN","proxy":false,"ratio":0.97,"latest":0.24,"spark":[0.22,0.2,0.21,0.14,0.18,0.3,0.32,0.17,0.39,0.31,0.28,0.18,0.28,0.16,0.26,0.32,0.2,0.94,0.59,0.42,0.4,0.33,0.27,0.24],"status":"normal"},"Malaysia":{"name":"Malaysia","lat":4.2,"lon":101.9,"iso":"MYS","proxy":false,"ratio":0.82,"latest":0.02,"spark":[0.04,0.01,0.03,0.01,0.01,0.03,0.05,0.03,0.04,0.16,0.03,0.03,0.1,0.04,0.07,0.05,0.03,0.07,0.04,0.06,0.03,0.03,0.05,0.02],"status":"normal"},"Mexico":{"name":"Mexico","lat":23.6,"lon":-102.5,"iso":"MEX","proxy":false,"ratio":0.63,"latest":0.11,"spark":[0.13,0.15,0.16,0.34,0.46,0.43,0.22,0.19,0.2,0.1,0.1,0.19,0.29,0.23,0.1,0.34,0.28,0.25,0.15,0.26,0.11,0.11,0.17,0.11],"status":"normal"},"Other Asia, nes":{"name":"Taiwan","lat":23.7,"lon":121.0,"iso":"TWN","proxy":false,"ratio":0.96,"latest":0.26,"spark":[0.31,0.19,0.18,0.16,0.14,0.17,0.13,0.21,0.21,0.11,0.1,0.12,0.19,0.14,0.26,0.19,0.13,0.33,0.25,0.53,0.18,0.16,0.14,0.26],"status":"normal"},"Poland":{"name":"Poland","lat":52.0,"lon":19.1,"iso":"POL","proxy":false,"ratio":0.91,"latest":0.25,"spark":[0.19,0.13,0.08,0.16,0.4,0.4,0.11,0.19,0.17,0.11,0.17,0.46,0.28,0.25,0.24,0.19,0.13,0.17,0.2,0.21,0.12,0.13,0.16,0.25],"status":"normal"},"Portugal":{"name":"Portugal","lat":39.5,"lon":-8.0,"iso":"PRT","proxy":false,"ratio":0.89,"latest":0.02,"spark":[0.01,0.01,0.02,0.02,0.02,0.04,0.01,0.02,0.01,0.02,0.03,0.1,0.02,0.04,0.01,0.02,0.01,0.02,0.06,0.05,0.04,0.05,0.0,0.02],"status":"normal"},"Qatar":{"name":"Qatar","lat":25.3,"lon":51.2,"iso":"SAU","proxy":true,"ratio":2.01,"latest":0.92,"spark":[0.3,0.21,0.34,0.24,0.69,0.8,0.26,0.71,0.46,0.21,0.18,0.25,0.23,0.21,0.15,0.34,0.32,2.24,0.9,0.59,0.45,1.14,0.61,0.92],"status":"critical"},"Rep. of Korea":{"name":"South Korea","lat":36.5,"lon":127.9,"iso":"KOR","proxy":false,"ratio":0.89,"latest":0.28,"spark":[0.4,0.85,0.54,0.35,0.33,0.39,0.32,0.32,0.42,0.35,0.27,0.24,0.33,0.2,0.2,0.21,0.23,0.78,0.53,0.62,0.33,0.32,0.38,0.28],"status":"normal"},"Russian Federation":{"name":"Russia","lat":55.8,"lon":37.6,"iso":"RUS","proxy":false,"ratio":0.85,"latest":1.48,"spark":[1.37,1.97,2.3,1.13,1.95,2.47,1.53,1.51,2.18,1.39,1.71,1.42,1.51,1.28,1.7,1.89,1.3,2.5,1.72,1.65,1.3,1.51,1.23,1.48],"status":"normal"},"Singapore":{"name":"Singapore","lat":1.35,"lon":103.8,"iso":null,"status":"normal"},"Spain":{"name":"Spain","lat":40.2,"lon":-3.6,"iso":"ESP","proxy":false,"ratio":0.76,"latest":0.09,"spark":[0.1,0.13,0.06,0.11,0.13,0.13,0.08,0.19,0.27,0.1,0.16,0.19,0.18,0.16,0.08,0.23,0.13,0.52,0.38,0.4,0.16,0.13,0.17,0.09],"status":"normal"},"USA":{"name":"United States","lat":39.0,"lon":-98.0,"iso":"USA","proxy":false,"ratio":0.97,"latest":3.91,"spark":[3.03,3.17,3.29,2.75,3.54,4.51,3.52,4.13,5.66,3.17,3.4,3.07,3.75,2.63,3.25,4.55,3.12,8.68,6.61,5.28,4.6,4.23,3.23,3.91],"status":"normal"}},"pairs":[{"sup":"Qatar","imp":"Malaysia","mat":"Helium","share":0.465,"score":0.879,"asof":"2026-08","status":"critical"},{"sup":"Qatar","imp":"Japan","mat":"Helium","share":0.179,"score":0.842,"asof":"2026-08","status":"critical"},{"sup":"Poland","imp":"Germany","mat":"Helium","share":0.154,"score":0.841,"asof":"2026-08","status":"critical"},{"sup":"Algeria","imp":"Israel","mat":"Helium","share":0.703,"score":0.836,"asof":"2026-08","status":"critical"},{"sup":"Rep. of Korea","imp":"Singapore","mat":"Gallium (minor-metal code)","share":0.724,"score":0.784,"asof":"2026-03","status":"critical"},{"sup":"China","imp":"Germany","mat":"Neon & rare gases","share":0.494,"score":0.745,"asof":"2026-08","status":"critical"},{"sup":"USA","imp":"Germany","mat":"Gallium (minor-metal code)","share":0.106,"score":0.7,"asof":"2026-08","status":"critical"},{"sup":"China","imp":"Germany","mat":"Gallium (minor-metal code)","share":0.269,"score":0.651,"asof":"2026-08","status":"critical"},{"sup":"Qatar","imp":"USA","mat":"Helium","share":0.361,"score":0.418,"asof":"2026-07","status":"critical"},{"sup":"Singapore","imp":"China","mat":"Gallium (minor-metal code)","share":0.201,"score":0.36,"asof":"2024-12","status":"critical"},{"sup":"Qatar","imp":"Germany","mat":"Helium","share":0.577,"score":0.278,"asof":"2026-08","status":"critical"},{"sup":"Qatar","imp":"Singapore","mat":"Helium","share":0.963,"score":0.057,"asof":"2026-03","status":"critical"},{"sup":"Qatar","imp":"Rep. of Korea","mat":"Helium","share":0.63,"score":0.046,"asof":"2025-12","status":"critical"},{"sup":"Qatar","imp":"China","mat":"Helium","share":0.674,"score":0.037,"asof":"2024-12","status":"critical"},{"sup":"Other Asia, nes","imp":"Germany","mat":"Gallium (minor-metal code)","share":0.103,"score":0.342,"asof":"2026-08","status":"serious"},{"sup":"USA","imp":"Japan","mat":"Gallium (minor-metal code)","share":0.107,"score":0.331,"asof":"2026-08","status":"serious"},{"sup":"China","imp":"Malaysia","mat":"Neon & rare gases","share":0.205,"score":0.317,"asof":"2026-08","status":"serious"},{"sup":"Rep. of Korea","imp":"China","mat":"Gallium (minor-metal code)","share":0.546,"score":0.305,"asof":"2024-12","status":"serious"},{"sup":"Rep. of Korea","imp":"Singapore","mat":"Neon & rare gases","share":0.319,"score":0.3,"asof":"2026-03","status":"serious"},{"sup":"China","imp":"Israel","mat":"Neon & rare gases","share":0.186,"score":0.288,"asof":"2026-08","status":"serious"},{"sup":"Canada","imp":"Germany","mat":"Gallium (minor-metal code)","share":0.118,"score":0.275,"asof":"2026-08","status":"serious"},{"sup":"China","imp":"Malaysia","mat":"Gallium (minor-metal code)","share":0.336,"score":0.269,"asof":"2026-08","status":"serious"},{"sup":"Portugal","imp":"USA","mat":"Neon & rare gases","share":0.298,"score":0.266,"asof":"2026-07","status":"serious"},{"sup":"Brazil","imp":"China","mat":"Gallium (minor-metal code)","share":0.146,"score":0.263,"asof":"2024-12","status":"serious"},{"sup":"Malaysia","imp":"Singapore","mat":"Neon & rare gases","share":0.175,"score":0.254,"asof":"2026-03","status":"serious"},{"sup":"France","imp":"Rep. of Korea","mat":"Neon & rare gases","share":0.697,"score":0.251,"asof":"2025-12","status":"serious"},{"sup":"Canada","imp":"USA","mat":"Gallium (minor-metal code)","share":0.121,"score":0.247,"asof":"2026-07","status":"serious"},{"sup":"USA","imp":"Malaysia","mat":"Helium","share":0.532,"score":0.245,"asof":"2026-08","status":"serious"},{"sup":"USA","imp":"Israel","mat":"Hydrogen fluoride","share":0.551,"score":0.236,"asof":"2026-08","status":"serious"},{"sup":"Poland","imp":"Germany","mat":"Neon & rare gases","share":0.169,"score":0.233,"asof":"2026-08","status":"serious"},{"sup":"Japan","imp":"Malaysia","mat":"Gallium (minor-metal code)","share":0.409,"score":0.232,"asof":"2026-08","status":"serious"},{"sup":"Germany","imp":"USA","mat":"Neon & rare gases","share":0.197,"score":0.23,"asof":"2026-07","status":"serious"},{"sup":"China","imp":"Japan","mat":"Gallium (minor-metal code)","share":0.196,"score":0.223,"asof":"2026-08","status":"serious"},{"sup":"Brazil","imp":"USA","mat":"Gallium (minor-metal code)","share":0.143,"score":0.221,"asof":"2026-07","status":"serious"},{"sup":"USA","imp":"Germany","mat":"Helium","share":0.128,"score":0.206,"asof":"2026-08","status":"serious"},{"sup":"China","imp":"Rep. of Korea","mat":"Neon & rare gases","share":0.244,"score":0.203,"asof":"2025-12","status":"serious"},{"sup":"China","imp":"USA","mat":"Neon & rare gases","share":0.249,"score":0.199,"asof":"2026-07","status":"serious"},{"sup":"Other Asia, nes","imp":"USA","mat":"Gallium (minor-metal code)","share":0.14,"score":0.192,"asof":"2026-07","status":"serious"},{"sup":"Rep. of Korea","imp":"USA","mat":"Gallium (minor-metal code)","share":0.162,"score":0.188,"asof":"2026-07","status":"serious"},{"sup":"Rep. of Korea","imp":"Japan","mat":"Gallium (minor-metal code)","share":0.123,"score":0.186,"asof":"2026-08","status":"serious"},{"sup":"USA","imp":"Israel","mat":"Helium","share":0.288,"score":0.182,"asof":"2026-08","status":"serious"},{"sup":"Rep. of Korea","imp":"Germany","mat":"Gallium (minor-metal code)","share":0.108,"score":0.179,"asof":"2026-08","status":"serious"},{"sup":"Other Asia, nes","imp":"Ireland","mat":"Hydrogen fluoride","share":0.655,"score":0.17,"asof":"2026-08","status":"serious"},{"sup":"Japan","imp":"USA","mat":"Gallium (minor-metal code)","share":0.106,"score":0.166,"asof":"2026-07","status":"serious"},{"sup":"Other Asia, nes","imp":"Japan","mat":"Gallium (minor-metal code)","share":0.235,"score":0.157,"asof":"2026-08","status":"serious"},{"sup":"Algeria","imp":"Germany","mat":"Helium","share":0.141,"score":0.151,"asof":"2026-08","status":"serious"},{"sup":"Japan","imp":"Singapore","mat":"Hydrogen fluoride","share":0.134,"score":0.15,"asof":"2026-03","status":"warning"}]}/*END_RISK*/;
  const SEV = { critical: 0xd03b3b, serious: 0xec835a, warning: 0xfab219 };
  const SEV_LABEL = { critical: 'Critical', serious: 'Elevated', warning: 'Watch' };
  const SEV_ICON = { critical: '▲', serious: '◆', warning: '●' };
  const SEV_ORDER = { critical: 0, serious: 1, warning: 2 };
  const cname = k => (RISK.countries[k] || {}).name || k;
  // Transparent rules (see README): model score, or dependence on a supplier whose country risk is spiking.
  function pairStatus(p) {
    const r = (RISK.countries[p.sup] || {}).ratio || 1;
    if (p.score >= 0.35 || (r >= 1.75 && p.share >= 0.5) || (p.score >= 0.15 && r >= 1.5)) return 'critical';
    if (p.score >= 0.15 || (r >= 1.4 && p.share >= 0.2)) return 'serious';
    if (p.score >= 0.12) return 'warning';
    return null;
  }
  RISK.pairs.forEach(p => { p.status = pairStatus(p); });
  const riskPairs = RISK.pairs.filter(p => p.status).sort((a, b) => SEV_ORDER[a.status] - SEV_ORDER[b.status] || b.score - a.score);
  const riskGroup = new T.Group(); globe.add(riskGroup);
  const riskTargets = [], halos = [];
  // radar halos on every at-risk supply source. A country takes its worst level from either its own
  // risk-index spike or any alerted route it supplies (red = critical, orange = elevated, amber = watch).
  const worse = (a, b) => (!a || a === 'normal') ? b : (!b || b === 'normal') ? a : (SEV_ORDER[a] <= SEV_ORDER[b] ? a : b);
  Object.entries(RISK.countries).forEach(([key, c]) => {
    c.gprStatus = c.status || 'normal';
    c.status = riskPairs.filter(p => p.sup === key).reduce((s, p) => worse(s, p.status), c.gprStatus);
  });
  const PULSE = { critical: 0.6, serious: 0.45, warning: 0.35 };   // more urgent = faster sweep
  Object.entries(RISK.countries).forEach(([key, c]) => {
    if (!c.status || c.status === 'normal') return;
    const v = ll2v(c.lat, c.lon, R * 1.006);
    for (let k = 0; k < 2; k++) {
      const ring = new T.Mesh(new T.RingGeometry(0.03, 0.036, 48),
        new T.MeshBasicMaterial({ color: SEV[c.status], transparent: true, side: T.DoubleSide, depthWrite: false }));
      ring.position.copy(v); ring.lookAt(v.clone().multiplyScalar(2));
      ring.userData.phase = k * 0.5 + Math.random() * 0.2; ring.userData.speed = PULSE[c.status];
      riskGroup.add(ring); halos.push(ring);
    }
    const core = new T.Mesh(new T.RingGeometry(0.022, 0.026, 48),
      new T.MeshBasicMaterial({ color: SEV[c.status], side: T.DoubleSide, transparent: true, opacity: 0.9, depthWrite: false }));
    core.position.copy(v); core.lookAt(v.clone().multiplyScalar(2)); riskGroup.add(core);
    riskTargets.push({ kind: 'country', key, v: v.clone() });
  });
  // exposure arcs: supplier -> importer, colored by alert level, flying higher than the yellow trade flows
  const riskMats = [];
  riskPairs.forEach(p => {
    const A = RISK.countries[p.sup], B = RISK.countries[p.imp];
    const va = ll2v(A.lat, A.lon, R), vb = ll2v(B.lat, B.lon, R);
    const ang = va.angleTo(vb), mid = va.clone().add(vb).normalize().multiplyScalar(R + 0.1 + ang * 0.28);
    const curve = new T.QuadraticBezierCurve3(va.clone().multiplyScalar(1.006), mid, vb.clone().multiplyScalar(1.006));
    const P = curve.getPoints(Math.max(40, Math.round(ang * 90))), gm = new T.BufferGeometry().setFromPoints(P);
    gm.setAttribute('t', new T.Float32BufferAttribute(P.map((_, i) => i / (P.length - 1)), 1));
    const col = new T.Color(SEV[p.status]);
    const mat = new T.ShaderMaterial({
      transparent: true, depthWrite: false, blending: T.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uOff: { value: Math.random() }, uSpeed: { value: 0.18 / (0.25 + ang) },
                  uCol: { value: new T.Vector3(col.r, col.g, col.b) }, uBase: { value: p.status === 'warning' ? 0.12 : 0.28 } },
      vertexShader: `attribute float t; varying float vT; void main(){ vT = t; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
      fragmentShader: `uniform float uTime; uniform float uOff; uniform float uSpeed; uniform vec3 uCol; uniform float uBase; varying float vT;
        void main(){ float head = fract(uTime*uSpeed + uOff); float d = head - vT;
          float trail = d >= 0.0 ? exp(-d*7.0) : 0.0;
          gl_FragColor = vec4(uCol * (0.8 + trail*0.6), uBase + trail*0.9); }`
    });
    riskMats.push(mat);
    riskGroup.add(new T.Line(gm, mat));
    for (let i = 2; i <= 18; i++) riskTargets.push({ kind: 'risk', pair: p, v: curve.getPoint(i / 20) });
  });

  // ---------- news layer: stories from news_collector.py, one blue beacon per country ----------
  // NEWS is filled in by build_globe_news.py (from data/news/news_latest.json). "Load news file" in the
  // News tab reads a newer news_latest.json straight from your computer without republishing the page.
  const NEWS_EMBEDDED = {"items":[]};
  let NEWS = NEWS_EMBEDDED;
  try {
    const saved = JSON.parse(localStorage.getItem('orbit-news') || 'null');
    if (saved && saved.items) NEWS = saved;   // shown until data/news.json arrives
  } catch (e) { /* storage unavailable: use the embedded snapshot */ }
  const newsGroup = new T.Group(); globe.add(newsGroup);
  let newsTargets = [], newsByCountry = {};
  const beaconHead = new T.MeshBasicMaterial({ color: 0x5cc8ff });
  const beaconAlert = new T.MeshBasicMaterial({ color: 0xfab219 });
  const beaconStalk = new T.MeshBasicMaterial({ color: 0x5cc8ff, transparent: true, opacity: 0.55 });
  const headSphere = new T.SphereGeometry(0.009, 12, 12);
  function buildNews() {
    while (newsGroup.children.length) newsGroup.remove(newsGroup.children[0]);
    newsTargets = []; newsByCountry = {};
    for (const it of NEWS.items || []) {
      if (!it.country || it.lat == null) continue;
      const c = newsByCountry[it.country] || (newsByCountry[it.country] = { name: it.country, region: it.region, lat: it.lat, lon: it.lon, items: [], alerts: 0 });
      c.items.push(it); if (it.alert) c.alerts++;
    }
    Object.values(newsByCountry).forEach(c => {
      const n = ll2v(c.lat, c.lon, 1).normalize();
      // offset a little east so the beacon doesn't sit inside a risk halo at the same centroid
      const off = ll2v(c.lat - 0.8, c.lon + 2.2, 1).normalize();
      const h = 0.03 + 0.06 * Math.log10(1 + c.items.length);
      const g = new T.Group();
      g.position.copy(off.clone().multiplyScalar(R * 1.002)); g.quaternion.setFromUnitVectors(UP, off);
      const stalk = new T.Mesh(new T.CylinderGeometry(0.0022, 0.0022, h, 6), beaconStalk); stalk.position.y = h / 2;
      const head = new T.Mesh(headSphere, c.alerts ? beaconAlert : beaconHead); head.position.y = h;
      g.add(stalk, head); newsGroup.add(g);
      newsTargets.push({ kind: 'news', country: c, v: off.clone().multiplyScalar(R * 1.002 + h) });
    });
    const btn = document.getElementById('newsBtn');
    if (btn) btn.querySelector('i').textContent = Object.keys(newsByCountry).length;
  }
  buildNews();

  // Starfield (not rotated with globe)
  (function () {
    const n = 1400, p = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { const v = new T.Vector3().randomDirection ? new T.Vector3().randomDirection() : new T.Vector3(Math.random()-.5,Math.random()-.5,Math.random()-.5).normalize(); v.multiplyScalar(20 + Math.random() * 20); p.set([v.x, v.y, v.z], i * 3); }
    const g = new T.BufferGeometry(); g.setAttribute('position', new T.BufferAttribute(p, 3));
    scene.add(new T.Points(g, new T.PointsMaterial({ color: 0xe6e9ee, size: 0.06, transparent: true, opacity: 0.45, depthWrite: false })));
  })();

  // ---------- orientation state (quaternion) ----------
  const q = new T.Quaternion();
  // Earth's axial tilt: 23.44° between the spin axis and the orbital-plane normal (screen up).
  // The north pole leans to the right; auto-spin turns the globe west-to-east about that tilted pole.
  const EARTH_TILT = T.MathUtils.degToRad(23.44);
  const startEuler = new T.Euler(0, 0, -EARTH_TILT, 'XYZ');
  q.setFromEuler(startEuler);
  const vel = new T.Vector3(); // angular velocity in world axes (rad/frame)
  const AX = new T.Vector3(1, 0, 0), AY = new T.Vector3(0, 1, 0), AZ = new T.Vector3(0, 0, 1);
  const tmpQ = new T.Quaternion();
  function rotWorld(axis, ang) { if (!ang) return; tmpQ.setFromAxisAngle(axis, ang); q.premultiply(tmpQ); q.normalize(); }

  // ---------- sliders ----------
  const sl = { x: document.getElementById('rx'), y: document.getElementById('ry'), z: document.getElementById('rz') };
  const out = { x: document.getElementById('ox'), y: document.getElementById('oy'), z: document.getElementById('oz') };
  const eul = new T.Euler(0, 0, 0, 'XYZ');
  let sliderActive = false;
  function syncSliders() {
    eul.setFromQuaternion(q, 'XYZ');
    ['x', 'y', 'z'].forEach(a => {
      const d = Math.round(T.MathUtils.radToDeg(eul[a]));
      if (!sliderActive) sl[a].value = d;
      out[a].textContent = d + '°';
    });
  }
  function fromSliders() {
    q.setFromEuler(new T.Euler(T.MathUtils.degToRad(+sl.x.value), T.MathUtils.degToRad(+sl.y.value), T.MathUtils.degToRad(+sl.z.value), 'XYZ'));
    vel.set(0, 0, 0);
  }
  Object.values(sl).forEach(s => {
    s.addEventListener('input', () => { sliderActive = true; setSpin(false); fromSliders(); syncSliders(); });
    s.addEventListener('change', () => { sliderActive = false; });
    s.addEventListener('pointerup', () => { sliderActive = false; });
  });

  // ---------- buttons ----------
  const spinBtn = document.getElementById('spin');
  let autoSpin = !reduceMotion;
  function setSpin(v) { autoSpin = v; spinBtn.setAttribute('aria-pressed', String(v)); }
  setSpin(autoSpin);
  spinBtn.addEventListener('click', () => setSpin(!autoSpin));
  document.querySelectorAll('.chip[data-stage]').forEach(btn => {
    const st = btn.dataset.stage;
    btn.querySelector('i').textContent = FLOWS.filter(f => f.st === st).length;
    btn.addEventListener('click', () => {
      flowGroups[st].visible = !flowGroups[st].visible;
      btn.setAttribute('aria-pressed', String(flowGroups[st].visible));
      tip.hidden = true; sticky = false;
    });
  });
  document.querySelectorAll('.chip[data-cat]').forEach(btn => {
    const cat = btn.dataset.cat;
    btn.querySelector('i').textContent = SITES.filter(s => s.cat === cat).length;
    btn.addEventListener('click', () => {
      pinGroups[cat].visible = !pinGroups[cat].visible;
      btn.setAttribute('aria-pressed', String(pinGroups[cat].visible));
      tip.hidden = true; sticky = false;
    });
  });
  const riskBtn = document.getElementById('riskBtn');
  riskBtn.addEventListener('click', () => {
    riskGroup.visible = !riskGroup.visible; riskBtn.setAttribute('aria-pressed', String(riskGroup.visible));
    tip.hidden = true; sticky = false;
  });
  // spin the globe so a lat/lon faces the viewer, north kept up
  let focusQ = null;
  function focusOn(c) {
    const f = ll2v(c.lat, c.lon, 1).normalize();
    const n = new T.Vector3(0, 1, 0);
    const u = n.clone().sub(f.clone().multiplyScalar(n.dot(f))).normalize();
    const r = u.clone().cross(f);
    const m = new T.Matrix4().set(r.x, r.y, r.z, 0, u.x, u.y, u.z, 0, f.x, f.y, f.z, 0, 0, 0, 0, 1);
    focusQ = new T.Quaternion().setFromRotationMatrix(m);
    setSpin(false); vel.set(0, 0, 0);
    if (!riskGroup.visible) riskBtn.click();
  }
  document.getElementById('reset').addEventListener('click', () => { q.setFromEuler(startEuler); vel.set(0, 0, 0); camDist = 3.6; syncSliders(); });

  // ---------- pointer interaction ----------
  const pointers = new Map();
  let lastTwist = null, lastPinch = null, rollMode = false;
  stage.addEventListener('contextmenu', e => e.preventDefault());
  stage.addEventListener('pointerdown', e => {
    stage.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    rollMode = e.shiftKey || e.button === 2;
    stage.classList.add('dragging');
    setSpin(false); vel.set(0, 0, 0);
    lastTwist = lastPinch = null;
  });
  stage.addEventListener('pointermove', e => {
    const p = pointers.get(e.pointerId); if (!p) return;
    const k = 0.0055 * (camDist / 3.6);
    if (pointers.size === 1) {
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      if (rollMode || e.shiftKey) { vel.set(0, 0, -dx * k); rotWorld(AZ, -dx * k); }
      else { vel.set(dy * k, dx * k, 0); rotWorld(AY, dx * k); rotWorld(AX, dy * k); }
    }
    p.x = e.clientX; p.y = e.clientY;
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const ang = Math.atan2(b.y - a.y, b.x - a.x), dist = Math.hypot(b.x - a.x, b.y - a.y);
      if (lastTwist !== null) { let d = ang - lastTwist; if (d > Math.PI) d -= 2 * Math.PI; if (d < -Math.PI) d += 2 * Math.PI; rotWorld(AZ, -d); vel.set(0, 0, -d); }
      if (lastPinch) camDist = T.MathUtils.clamp(camDist * lastPinch / dist, 1.8, 8);
      lastTwist = ang; lastPinch = dist;
    }
    syncSliders();
  });
  function endPointer(e) {
    pointers.delete(e.pointerId);
    lastTwist = lastPinch = null;
    if (!pointers.size) stage.classList.remove('dragging');
  }
  // Tooltips: hover on desktop, tap on touch. Pins take priority over airports.
  const tip = document.getElementById('tip');
  const tmpV = new T.Vector3(), camDir = new T.Vector3();
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function nearest(list, cx, cy, radius) {
    const rect = stage.getBoundingClientRect();
    let best = null, bestD = radius;
    for (const m of list) {
      tmpV.copy(m.v).applyQuaternion(q);
      camDir.copy(camera.position).sub(tmpV);
      if (tmpV.dot(camDir) <= 0) continue; // far side of the globe
      tmpV.project(camera);
      const sx = (tmpV.x * 0.5 + 0.5) * rect.width, sy = (-tmpV.y * 0.5 + 0.5) * rect.height;
      const d = Math.hypot(sx - (cx - rect.left), sy - (cy - rect.top));
      if (d < bestD) { bestD = d; best = m; }
    }
    return best;
  }
  function pick(cx, cy, touch) {
    const r = touch ? 26 : 14;
    const pins = pinTargets.filter(p => pinGroups[p.site.cat].visible);
    const flows = flowTargets.filter(p => flowGroups[p.flow.st].visible);
    const risk = riskGroup.visible ? riskTargets : [];
    const news = newsGroup.visible ? newsTargets : [];
    return nearest(pins, cx, cy, r) || nearest(news, cx, cy, r) || nearest(risk.filter(x => x.kind === 'country'), cx, cy, r + 6)
      || nearest(risk.filter(x => x.kind === 'risk'), cx, cy, touch ? 18 : 9) || nearest(flows, cx, cy, touch ? 18 : 9);
  }
  function showTip(hit, cx, cy) {
    if (!hit) { tip.hidden = true; return; }
    if (hit.kind === 'pin') {
      const s = hit.site;
      tip.className = 'pin';
      tip.innerHTML = `<b>${esc(s.name)}</b><em>${CAT_LABEL[s.cat]}</em><small>${esc(s.place)}</small><div>${esc(s.note)}</div>` +
        (s.companies ? `<small>${esc(s.companies)}</small>` : '');
    } else if (hit.kind === 'news') {
      const c = hit.country;
      tip.className = 'pin newstip';
      const tops = topTopics(c.items, 3);
      const heads = c.items.slice().sort((a, b) => (b.alert - a.alert) || ((b.coverage || 1) - (a.coverage || 1)) || (b.score - a.score)).slice(0, 3)
        .map(it => `<small class="hl${it.alert ? ' alert' : ''}">${esc(it.title)}</small>`).join('');
      tip.innerHTML = `<b>${esc(c.name)}</b><em>News · ${c.items.length} ${c.items.length === 1 ? 'story' : 'stories'}` +
        `${c.alerts ? ` · <span style="color:var(--critical)">${c.alerts} alert${c.alerts > 1 ? 's' : ''}</span>` : ''}</em>` +
        (tops.length ? `<small>${esc(tops.join(' · '))}</small>` : '') + heads + `<small>Click to list every story</small>`;
    } else if (hit.kind === 'risk' || hit.kind === 'country') {
      tip.className = 'pin risktip';
      tip.innerHTML = hit.kind === 'risk' ? pairHTML(hit.pair) : countryHTML(hit.key);
    } else {
      const fl = hit.flow;
      tip.className = 'pin flowtip';
      tip.innerHTML = `<b>${esc(fl.item)}</b><em>${STAGE_LABEL[fl.st]} · <span class="st-${fl.s}">${STATUS_LABEL[fl.s]}</span></em>` +
        `<small>${esc(NODES[fl.f][2])} → ${esc(NODES[fl.t][2])}</small><div class="val">${esc(fl.val)}</div>` +
        `<small>${esc(fl.per)} · ${esc(SRC[fl.src])}</small>`;
    }
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(cx + 14, window.innerWidth - w - 8)) + 'px';
    tip.style.top = Math.max(8, Math.min(cy + 14, window.innerHeight - h - 8)) + 'px';
  }
  const pct = x => `${Math.round(x * 100)}%`;
  const ym = s => new Date(s + '-01T00:00:00').toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  function riskLine(key) {
    const c = RISK.countries[key];
    if (!c || !c.ratio) return '';
    const who = c.proxy ? 'Gulf risk index (Saudi Arabia as stand-in)' : `${c.name} risk index`;
    return `${who}: ${c.ratio.toFixed(1)}× its 2-year average`;
  }
  function spark(key) {
    const c = RISK.countries[key];
    if (!c || !c.spark) return '';
    const v = c.spark, W = 200, H = 34, mx = Math.max(...v), mn = Math.min(...v);
    const pts = v.map((y, i) => `${(i / (v.length - 1) * W).toFixed(1)},${(H - 3 - (y - mn) / (mx - mn || 1) * (H - 6)).toFixed(1)}`).join(' ');
    const col = c.gprStatus === 'normal' ? 'var(--dim)' : `var(--${c.gprStatus})`;
    const last = pts.split(' ').pop().split(',');
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-label="Risk index, last 24 months">` +
      `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5"/>` +
      `<circle cx="${last[0]}" cy="${last[1]}" r="2.5" fill="${col}"/></svg><small>Risk index, last 24 months to ${ym(RISK.gprAsof)}</small>`;
  }
  function sevTag(st) { return `<span class="sev s-${st}">${SEV_ICON[st]} ${SEV_LABEL[st]}</span>`; }
  function pairHTML(p) {
    return `<b>${esc(p.mat)}: ${esc(cname(p.sup))} → ${esc(cname(p.imp))}</b>${sevTag(p.status)}` +
      `<div>Model: ${pct(p.score)} chance of a >50% drop in volume within 3 months</div>` +
      `<small>${esc(cname(p.imp))} gets ${pct(p.share)} of its ${esc(p.mat.toLowerCase())} imports from ${esc(cname(p.sup))} · trade data to ${ym(p.asof)}</small>` +
      (riskLine(p.sup) ? `<small>${esc(riskLine(p.sup))}</small>` : '') + spark(p.sup) + relatedNews(p.sup, p.mat);
  }
  // news that names this supplier country and this material: the story behind a risk score
  const MAT_INPUT = m => /helium/i.test(m) ? 'helium' : /gallium/i.test(m) ? 'gallium' : /neon/i.test(m) ? 'neon' : /fluoride|HF/i.test(m) ? 'hydrogen fluoride' : null;
  function relatedNews(key, mat) {
    const name = cname(key), inp = mat ? MAT_INPUT(mat) : null;
    const hits = (NEWS.items || []).filter(it => (it.countries || [it.country]).includes(name) && (!inp || (it.inputs || []).includes(inp)))
      .sort((a, b) => (b.alert - a.alert) || (b.published > a.published ? 1 : -1)).slice(0, 2);
    return hits.length ? `<small>In the news:</small>` + hits.map(it => `<small class="hl${it.alert ? ' alert' : ''}">${esc(it.title)} · ${esc(ago(it.published))}</small>`).join('') : '';
  }
  function countryHTML(key) {
    const c = RISK.countries[key];
    const routes = riskPairs.filter(p => p.sup === key).map(p =>
      `<small>${SEV_ICON[p.status]} ${esc(p.mat)} → ${esc(cname(p.imp))}: ${pct(p.share)} of supply · model ${pct(p.score)}</small>`).join('');
    const why = riskLine(key) || 'Flagged by the supplier-drop model (no country risk index for here)';
    return `<b>${esc(c.name)}</b>${sevTag(c.status)}<div>${esc(why)}</div>` +
      (routes ? `<small>At-risk routes from here:</small>${routes}` : '') + spark(key) + relatedNews(key, null);
  }
  // risk monitor list
  (function () {
    const list = document.getElementById('riskList');
    const nCrit = riskPairs.filter(p => p.status === 'critical').length;
    document.getElementById('riskCount').textContent = nCrit ? `${nCrit} critical` : '';
    const latestTrade = riskPairs.reduce((m, p) => p.asof > m ? p.asof : m, '0000-00');
    document.getElementById('riskFoot').textContent =
      `Risk index to ${ym(RISK.gprAsof)} · trade data to ${ym(latestTrade)} (Korea Dec 2025, China Dec 2024) · model: phase 3 supplier-drop model`;
    riskPairs.slice(0, 8).forEach(p => {
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.className = `s-${p.status}`;
      b.innerHTML = `${sevTag(p.status)}<span class="t">${esc(p.mat)}: ${esc(cname(p.sup))} → ${esc(cname(p.imp))}</span>` +
        `<span class="d">${pct(p.share)} of supply · model ${pct(p.score)}${RISK.countries[p.sup].ratio >= 1.4 ? ` · risk ${RISK.countries[p.sup].ratio.toFixed(1)}×` : ''}</span>`;
      b.addEventListener('click', () => { focusOn(RISK.countries[p.sup]); });
      li.appendChild(b); list.appendChild(li);
    });
    const badge = document.getElementById('riskBadge');
    if (nCrit) { badge.textContent = nCrit; badge.hidden = false; }
    document.getElementById('riskFab').setAttribute('aria-label', nCrit ? `Open monitor, ${nCrit} critical` : 'Open monitor');
  })();
  // Collapsible corner panels: icon opens, chevron or Esc collapses. On phones only one is open at a time.
  const panelFabs = { ctrlBox: document.getElementById('ctrlFab'), riskBox: document.getElementById('riskFab') };
  function setPanelOpen(id, open) {
    document.getElementById(id).hidden = !open;
    panelFabs[id].hidden = open;
    panelFabs[id].setAttribute('aria-expanded', String(open));
    if (open && window.innerWidth <= 520) Object.keys(panelFabs).forEach(o => { if (o !== id) setPanelOpen(o, false); });
  }
  (function () {
    Object.entries(panelFabs).forEach(([id, b]) => b.addEventListener('click', () => {
      setPanelOpen(id, true); const c = document.querySelector(`#${id} .pclose`); if (c) c.focus();
    }));
    document.querySelectorAll('.pclose').forEach(b => b.addEventListener('click', () => {
      const id = b.dataset.target; setPanelOpen(id, false); panelFabs[id].focus();
    }));
    window.addEventListener('keydown', e => {
      if (e.key !== 'Escape') return;
      Object.keys(panelFabs).forEach(id => { if (!document.getElementById(id).hidden) { setPanelOpen(id, false); panelFabs[id].focus(); } });
    });
  })();
  // ---------- news panel: tabs, filters, list, load-from-file ----------
  function ago(iso) {
    if (!iso) return '';
    const t = Date.parse(iso.length === 17 ? iso.replace('Z', ':00Z') : iso);
    if (isNaN(t)) return iso;
    const h = (Date.now() - t) / 36e5;
    return h < 1 ? 'just now' : h < 24 ? `${Math.round(h)} h ago` : h < 24 * 14 ? `${Math.round(h / 24)} d ago`
      : new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  function topTopics(items, n) {
    const ct = {}; items.forEach(it => (it.topics || []).forEach(t => ct[t] = (ct[t] || 0) + 1));
    return Object.entries(ct).sort((a, b) => b[1] - a[1]).slice(0, n).map(x => x[0]);
  }
  const tabRisk = document.getElementById('tabRisk'), tabNews = document.getElementById('tabNews');
  const paneRisk = document.getElementById('paneRisk'), paneNews = document.getElementById('paneNews');
  function setTab(which) {
    const news = which === 'news';
    tabRisk.setAttribute('aria-selected', String(!news)); tabNews.setAttribute('aria-selected', String(news));
    paneRisk.hidden = news; paneNews.hidden = !news;
    try { localStorage.setItem('orbit-tab', which); } catch (e) {}
  }
  tabRisk.addEventListener('click', () => setTab('risk'));
  tabNews.addEventListener('click', () => setTab('news'));
  const fRegion = document.getElementById('fRegion'), fTopic = document.getElementById('fTopic');
  const fAlerts = document.getElementById('fAlerts'), fCountry = document.getElementById('fCountry');
  const newsList = document.getElementById('newsList'), newsFoot = document.getElementById('newsFoot');
  const nf = { region: '', topic: '', alerts: false, country: '' };
  function fillSelect(sel, label, values) {
    const cur = sel.value;
    sel.innerHTML = `<option value="">${label}</option>` + values.map(([v, n]) => `<option value="${esc(v)}">${esc(v)} (${n})</option>`).join('');
    sel.value = values.some(([v]) => v === cur) ? cur : '';
  }
  function refreshFilters() {
    const items = NEWS.items || [], reg = {}, top = {};
    items.forEach(it => { const r = it.region || 'Global'; reg[r] = (reg[r] || 0) + 1; (it.topics || []).forEach(t => top[t] = (top[t] || 0) + 1); });
    fillSelect(fRegion, 'All regions', Object.entries(reg).sort((a, b) => b[1] - a[1]));
    fillSelect(fTopic, 'All topics', Object.entries(top).sort((a, b) => b[1] - a[1]));
    document.getElementById('newsCount').textContent = items.length || '';
  }
  function renderNews() {
    const all = NEWS.items || [];
    const rows = all.filter(it => (!nf.region || (it.region || 'Global') === nf.region)
      && (!nf.topic || (it.topics || []).includes(nf.topic)) && (!nf.alerts || it.alert)
      && (!nf.country || it.country === nf.country || (it.countries || []).includes(nf.country)))
      .sort((a, b) => (b.published || '').localeCompare(a.published || '')).slice(0, 80);
    fCountry.hidden = !nf.country; fCountry.textContent = nf.country ? `${nf.country} ✕` : '';
    newsList.innerHTML = '';
    if (!all.length) {
      newsList.innerHTML = `<li style="border-left-color:var(--line)"><span class="news-empty">Loading the latest stories…</span></li>`;
    } else if (!rows.length) {
      newsList.innerHTML = `<li style="border-left-color:var(--line)"><span class="news-empty">No stories match these filters.</span></li>`;
    }
    rows.forEach(it => {
      const li = document.createElement('li'); if (it.alert) li.className = 'alert';
      const a = document.createElement('a'); a.href = it.url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = it.title;
      const m = document.createElement('div'); m.className = 'm';
      m.innerHTML = (it.alert ? `<span class="tag-alert">▲ Alert</span>` : '') +
        `<span>${esc(it.source || '')}${it.coverage > 1 ? ` <span title="${esc((it.outlets || []).join(', '))}">+${it.coverage - 1} more</span>` : ''} · ${esc(ago(it.published))}${it.lang && it.lang !== 'en' ? ' · ' + esc(it.lang.toUpperCase()) : ''}</span>` +
        ((it.topics || []).length ? `<span>${esc(it.topics.slice(0, 2).join(' · '))}</span>` : '') +
        (it.discussion ? `<a href="${esc(it.discussion)}" target="_blank" rel="noopener" style="font-size:10.5px;color:var(--dim)">discussion</a>` : '');
      if (it.country && newsByCountry[it.country]) {
        const b = document.createElement('button'); b.textContent = `◎ ${it.country}`; b.title = 'Spin the globe there';
        b.addEventListener('click', () => { focusOn(newsByCountry[it.country]); if (!newsGroup.visible) newsBtn.click(); });
        m.appendChild(b);
      }
      li.append(a, m); newsList.appendChild(li);
    });
    const when = NEWS.generated_at ? ago(NEWS.generated_at) : 'never';
    const src = NEWS.sources_total ? ` from ${NEWS.sources_ok} of ${NEWS.sources_total} sources` : '';
    newsFoot.innerHTML = `${all.length} stories over ${NEWS.window_days || 30} days${src} · collected ${esc(when)}` +
      (rows.length === 80 ? ' · showing the newest 80' : '') + `<button id="loadNews">Load news file</button>`;
    document.getElementById('loadNews').addEventListener('click', () => document.getElementById('newsFile').click());
  }
  function showNewsFor(country) {
    nf.country = country; nf.region = ''; fRegion.value = '';
    setPanelOpen('riskBox', true); setTab('news'); renderNews();
  }
  fRegion.addEventListener('change', () => { nf.region = fRegion.value; nf.country = ''; renderNews(); });
  fTopic.addEventListener('change', () => { nf.topic = fTopic.value; renderNews(); });
  fAlerts.addEventListener('click', () => { nf.alerts = !nf.alerts; fAlerts.setAttribute('aria-pressed', String(nf.alerts)); renderNews(); });
  fCountry.addEventListener('click', () => { nf.country = ''; renderNews(); });
  document.getElementById('newsFile').addEventListener('change', e => {
    const f = e.target.files && e.target.files[0]; if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      try {
        const d = JSON.parse(rd.result);
        if (!d || !Array.isArray(d.items)) throw new Error('not a news_latest.json file');
        if (Array.isArray(d.sources)) { d.sources_total = d.sources.length; d.sources_ok = d.sources.filter(s => s.status === 'ok').length; }
        NEWS = d;
        try { localStorage.setItem('orbit-news', JSON.stringify({ ...d, sources: undefined })); } catch (err) {}
        buildNews(); refreshFilters(); renderNews();
      } catch (err) { newsFoot.textContent = `Could not read that file: ${err.message}`; }
      e.target.value = '';
    };
    rd.readAsText(f);
  });
  const newsBtn = document.getElementById('newsBtn');
  newsBtn.addEventListener('click', () => {
    newsGroup.visible = !newsGroup.visible; newsBtn.setAttribute('aria-pressed', String(newsGroup.visible));
    tip.hidden = true; sticky = false;
  });
  refreshFilters(); renderNews();
  // Latest stories from the hourly collector (docs/data/news.json); re-checked every 10 minutes
  function applyNews(d) {
    if (!d || !Array.isArray(d.items)) return;
    if (NEWS && NEWS.generated_at && d.generated_at === NEWS.generated_at && NEWS.items.length) return;
    NEWS = d; buildNews(); refreshFilters(); renderNews();
  }
  function pullNews() { fetch('data/news.json', { cache: 'no-cache' }).then(r => r.ok ? r.json() : null).then(applyNews).catch(() => {}); }
  pullNews(); setInterval(pullNews, 10 * 60 * 1000);
  try { if (localStorage.getItem('orbit-tab') === 'news') setTab('news'); } catch (e) {}

  let sticky = false, downAt = null;
  stage.addEventListener('pointerdown', e => { downAt = { x: e.clientX, y: e.clientY }; });
  stage.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch' || sticky) return;
    if (pointers.size) { tip.hidden = true; return; }
    showTip(pick(e.clientX, e.clientY, false), e.clientX, e.clientY);
  });
  stage.addEventListener('pointerup', e => {
    if (!downAt || Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 6) { sticky = false; tip.hidden = true; return; }
    const hit = pick(e.clientX, e.clientY, e.pointerType === 'touch');
    sticky = !!hit;
    showTip(hit, e.clientX, e.clientY);
    if (hit && hit.kind === 'news') showNewsFor(hit.country.name);
  });
  stage.addEventListener('pointerleave', () => { if (!sticky) tip.hidden = true; });
  stage.addEventListener('pointerup', endPointer);
  stage.addEventListener('pointercancel', endPointer);
  // Plain wheel scrolls the page down to the tracker; Ctrl/Cmd + wheel (and trackpad pinch) zooms the globe
  stage.addEventListener('wheel', e => { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); camDist = T.MathUtils.clamp(camDist * Math.exp(e.deltaY * 0.001), 1.8, 8); }, { passive: false });
  let globeOnScreen = true;
  const globeSec = document.getElementById('globe');
  if ('IntersectionObserver' in window) new IntersectionObserver(es => { globeOnScreen = es[0].isIntersecting && es[0].intersectionRatio > 0.25; if (!globeOnScreen) { keys.clear(); tip.hidden = true; } }, { threshold: [0, 0.25, 0.5] }).observe(globeSec);


  // Keyboard
  const keys = new Set();
  window.addEventListener('keydown', e => {
    if (e.target && e.target.tagName === 'INPUT') return;
    if (!globeOnScreen) return;
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'q', 'e', 'Q', 'E'].includes(e.key)) { keys.add(e.key.toLowerCase()); setSpin(false); e.preventDefault(); }
  });
  window.addEventListener('keyup', e => keys.delete(e.key.toLowerCase()));

  // ---------- gizmo ----------
  const gz = document.getElementById('gizmo'), gctx = gz.getContext('2d');
  function drawGizmo() {
    const w = gz.width, h = gz.height, c = w / 2, L = w * 0.36;
    gctx.clearRect(0, 0, w, h);
    gctx.beginPath(); gctx.arc(c, c, w * 0.46, 0, Math.PI * 2);
    gctx.fillStyle = 'rgba(26,31,38,0.7)'; gctx.fill();
    gctx.strokeStyle = 'rgba(124,135,148,0.35)'; gctx.lineWidth = 2; gctx.stroke();
    const axes = [['X', new T.Vector3(1, 0, 0), '#ff6b6b'], ['Y', new T.Vector3(0, 1, 0), '#7ee08a'], ['Z', new T.Vector3(0, 0, 1), '#6aa8ff']]
      .map(([n, v, col]) => [n, v.applyQuaternion(q), col]).sort((a, b) => a[1].z - b[1].z);
    gctx.font = '600 22px "Chakra Petch", system-ui, sans-serif'; gctx.textAlign = 'center'; gctx.textBaseline = 'middle';
    for (const [n, v, col] of axes) {
      const x = c + v.x * L, y = c - v.y * L, front = v.z >= 0;
      gctx.globalAlpha = front ? 1 : 0.45;
      gctx.strokeStyle = col; gctx.lineWidth = 4;
      gctx.beginPath(); gctx.moveTo(c, c); gctx.lineTo(x, y); gctx.stroke();
      gctx.beginPath(); gctx.arc(x, y, 13, 0, Math.PI * 2); gctx.fillStyle = col; gctx.fill();
      gctx.fillStyle = '#0B0D10'; gctx.fillText(n, x, y + 1);
    }
    gctx.globalAlpha = 1;
  }

  // ---------- resize / loop ----------
  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = w + 'px'; renderer.domElement.style.height = h + 'px';
    camera.aspect = w / h;
    // Keep the whole globe visible on tall phone screens
    camera.fov = w / h < 0.8 ? 40 / Math.max(w / h, 0.45) * 0.8 : 40;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize); resize();

  const clock = new T.Clock();
  let syncTick = 0;
  function frame() {
    if (!globeOnScreen) { clock.getDelta(); requestAnimationFrame(frame); return; }
    const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
    const ks = 1.6 * dt;
    if (keys.has('arrowleft')) rotWorld(AY, -ks);
    if (keys.has('arrowright')) rotWorld(AY, ks);
    if (keys.has('arrowup')) rotWorld(AX, -ks);
    if (keys.has('arrowdown')) rotWorld(AX, ks);
    if (keys.has('q')) rotWorld(AZ, ks);
    if (keys.has('e')) rotWorld(AZ, -ks);
    if (!pointers.size) {
      if (vel.lengthSq() > 1e-8) { rotWorld(AX, vel.x); rotWorld(AY, vel.y); rotWorld(AZ, vel.z); vel.multiplyScalar(0.94); }
      if (autoSpin) {
        // spin around the globe's own polar axis
        const pole = new T.Vector3(0, 1, 0).applyQuaternion(q);
        rotWorld(pole, 0.12 * dt); // positive = west-to-east, counterclockwise seen from above the North Pole
      }
    }
    if (focusQ) {
      if (pointers.size) focusQ = null;
      else { q.slerp(focusQ, 1 - Math.pow(0.002, dt)); if (q.angleTo(focusQ) < 0.002) { q.copy(focusQ); focusQ = null; } syncSliders(); }
    }
    globe.quaternion.copy(q);
    camera.position.z += (camDist - camera.position.z) * 0.12;
    arcMats.forEach(m => m.uniforms.uTime.value = t);
    riskMats.forEach(m => m.uniforms.uTime.value = t);
    halos.forEach(h => { const p = (t * h.userData.speed + h.userData.phase) % 1; h.scale.setScalar(1 + p * 1.6); h.material.opacity = 0.8 * (1 - p); });
    rings.forEach(r => { const p = (t * 0.6 + r.userData.phase) % 1; r.scale.setScalar(r.userData.s * (1 + p * 2.2)); r.material.opacity = 1 - p; });
    if ((autoSpin || vel.lengthSq() > 1e-8 || keys.size) && ++syncTick % 3 === 0) syncSliders();
    drawGizmo();
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  syncSliders();
  frame();
})();
