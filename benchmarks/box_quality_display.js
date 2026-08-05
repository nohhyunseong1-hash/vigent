// benchmarks/box_quality_display.js — 박스 품질 하네스 Part B(표시 재생) 드라이버.
//
// 목적: vigent-core/static/vigent-box-display.js(BoxTracker, 미수정·재구현 금지)를 그대로 불러와,
//   Part A(검출 재생)가 만든 검출 시퀀스를 실제 도착 지연을 흉내낸 스케줄로 ingest() 하고,
//   rAF 60fps(기본)를 시뮬레이션해 매 렌더틱의 sample() 결과(표시 박스)를 그대로 JSON 출력한다.
//   표시 로직은 절대 건드리지 않는다 — 이 파일은 '틱을 흘려보내는 하네스'일 뿐이다.
//
// 사용: node box_quality_display.js <입력JSON경로>
//   입력: {render_fps, delay_ms, jitter_ms, exclude_class, seed, tracker_opts, frames:[{t_cap_ms, dets:[{cls,score,id,box:[x,y,w,h]}]}]}
//   출력(stdout): [{t_ms, vis:[{cls,tid,box,alpha}]}, ...]
'use strict';
const fs = require('fs');
const path = require('path');
const { BoxTracker } = require(path.join(__dirname, '..', 'vigent-core', 'static', 'vigent-box-display.js')).VigentBoxDisplay;

function makeRng(seed) {
  // 결정적 LCG + Box-Muller(가우시안 지터 근사). 재실행 재현성 확보용 — 암호학적 품질 불필요.
  let s = seed >>> 0 || 1;
  function u() { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; }
  return function gauss() {
    const u1 = Math.max(u(), 1e-9), u2 = u();
    return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  };
}

function main() {
  const inPath = process.argv[2];
  if (!inPath) { process.stderr.write('사용: node box_quality_display.js <입력JSON경로>\n'); process.exit(2); }
  const cfg = JSON.parse(fs.readFileSync(inPath, 'utf8'));
  const frames = cfg.frames || [];
  const renderFps = cfg.render_fps || 60;
  const delayMs = cfg.delay_ms || 0;
  const jitterMs = cfg.jitter_ms || 0;
  const gauss = makeRng(cfg.seed || 1);

  // 도착 스케줄: 캡처 시각(t_cap_ms) + 주입 지연(고정 delay + 가우시안 jitter, 0 하한) = 브라우저 ingest 시각.
  const arrivals = frames
    .map(f => ({ at: Math.max(f.t_cap_ms, f.t_cap_ms + delayMs + (jitterMs > 0 ? jitterMs * gauss() : 0)), dets: f.dets }))
    .sort((a, b) => a.at - b.at);

  const bt = new BoxTracker(Object.assign({ excludeClass: cfg.exclude_class || null }, cfg.tracker_opts || {}));
  const lastCap = frames.length ? frames[frames.length - 1].t_cap_ms : 0;
  const tEnd = lastCap + delayMs + Math.abs(jitterMs) * 3 + 500;   // 마지막 도착 이후 페이드아웃까지 여유
  const tickMs = 1000 / renderFps;

  const out = [];
  let ai = 0;
  for (let t = 0; t <= tEnd; t += tickMs) {
    while (ai < arrivals.length && arrivals[ai].at <= t) {
      bt.ingest(arrivals[ai].dets, arrivals[ai].at, arrivals[ai].at);   // 실제 도착 순간을 now 로(렌더틱 격자에 안 묶음)
      ai++;
    }
    const vis = bt.sample(t);
    out.push({ t_ms: t, vis: vis.map(v => ({ cls: v.cls, tid: v.tid, box: v.box, alpha: v.alpha })) });
  }
  process.stdout.write(JSON.stringify(out));
}

main();
