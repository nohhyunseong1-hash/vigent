/* VIGENT 측면 3D 스켈레톤 뷰 — 카메라 옆에 회전하는 3D 포즈(관절 신뢰도 색).
 * 사용: const v=Pose3D(canvas); 매 프레임 v.update(poseLandmarks);
 * 좌(파랑)·우(빨강) 구분, 관절은 신뢰도(visibility)로 빨강(낮음)→하늘(높음).
 * 깊이(z)로 거북목·앞뒤 자세를 옆에서 확인할 수 있다. (Three.js 필요)
 */
window.Pose3D = function (canvas) {
  if (typeof THREE === 'undefined') return null;
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(45, 1.2, 0.1, 100);
  cam.position.set(0, 0, 3);
  scene.add(new THREE.AmbientLight(0xffffff, 0.8));
  const grid = new THREE.GridHelper(2.4, 10, 0x2a3650, 0x1b2538);
  grid.position.y = -1.1; scene.add(grid);

  const L = [[11, 13], [13, 15], [11, 23], [23, 25], [25, 27]];   // 좌(파랑)
  const R = [[12, 14], [14, 16], [12, 24], [24, 26], [26, 28]];   // 우(빨강)
  const C = [[11, 12], [23, 24]];                                 // 중앙(흰)
  const ALL = [...L.map(b => [b, 0x4a90ff]), ...R.map(b => [b, 0xff5a4a]), ...C.map(b => [b, 0xdfe8ff])];
  const bgeo = new THREE.BufferGeometry();
  bgeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(ALL.length * 6), 3));
  bgeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(ALL.length * 6), 3));
  const blines = new THREE.LineSegments(bgeo, new THREE.LineBasicMaterial({ vertexColors: true, linewidth: 2 }));
  scene.add(blines);

  const JIDX = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
  const sph = {};
  for (const i of JIDX) {
    const s = new THREE.Mesh(new THREE.SphereGeometry(0.04, 12, 10), new THREE.MeshBasicMaterial({ color: 0x88aaff }));
    s.visible = false; scene.add(s); sph[i] = s;
  }
  let ang = 0.5;
  const confCol = v => { const c = new THREE.Color(); c.setHSL(0.0 + 0.58 * Math.min(1, Math.max(0, v)), 0.85, 0.55); return c; };
  function resize() { const w = canvas.clientWidth || 280, h = canvas.clientHeight || 240; renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); }

  function P(lm, i, c, sc) { const p = lm[i]; return [(p.x - c.x) * sc, -(p.y - c.y) * sc, -((p.z || 0) - c.z) * sc]; }

  return {
    update(lm) {
      resize();
      if (lm && lm[23] && lm[24] && lm[11] && lm[12]) {
        const c = { x: (lm[23].x + lm[24].x) / 2, y: (lm[23].y + lm[24].y) / 2, z: ((lm[23].z || 0) + (lm[24].z || 0)) / 2 };
        const sw = Math.hypot(lm[11].x - lm[12].x, lm[11].y - lm[12].y) || 0.2, sc = 1.4 / sw;
        for (const i of JIDX) {
          const p = lm[i], s = sph[i];
          if (!p || (p.visibility != null && p.visibility < 0.2)) { s.visible = false; continue; }
          const a = P(lm, i, c, sc); s.position.set(a[0], a[1], a[2]);
          s.material.color = confCol(p.visibility == null ? 1 : p.visibility); s.visible = true;
        }
        const pos = bgeo.attributes.position.array, col = bgeo.attributes.color.array; let n = 0;
        for (const [b, hex] of ALL) {
          const A = P(lm, b[0], c, sc), B = P(lm, b[1], c, sc), cc = new THREE.Color(hex);
          pos.set([A[0], A[1], A[2], B[0], B[1], B[2]], n * 6);
          col.set([cc.r, cc.g, cc.b, cc.r, cc.g, cc.b], n * 6); n++;
        }
        bgeo.attributes.position.needsUpdate = true; bgeo.attributes.color.needsUpdate = true;
      }
      ang += 0.004; const Rr = 3.0;        // 천천히 회전(3D 플롯 느낌)
      cam.position.set(Math.sin(ang) * Rr, 0.2, Math.cos(ang) * Rr); cam.lookAt(0, 0, 0);
      renderer.render(scene, cam);
    }
  };
};
