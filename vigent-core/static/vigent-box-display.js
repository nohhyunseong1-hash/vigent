// vigent-box-display.js — 검증된 박스 표시 스택(추적·One-Euro·속도외삽·dedup·페이드)
// index_local.html(safety-local, 2.1~2.2: 빠름 표시오차 p50 6.6→4.4px)에서 '순수 이동' 추출한 공용 모듈.
// 파라미터·동작 불변. 신규 화면은 반드시 이 모듈만 사용(재구현 금지 — ONBOARDING §4).
//
// 사용:
//   var bt = new VigentBoxDisplay.BoxTracker({excludeClass:'person'});   // person 은 스켈레톤 담당(옵션)
//   var bt2 = new VigentBoxDisplay.BoxTracker({noAnchorClass:'person', anchor:true});  // person 도 트랙+표시하되 앵커(MediaPipe 1인)는 금지(옵션)
//   // 새 검출 배치 수신 시(1회):  dets=[{cls,score,id,box:[x,y,w,h]}]  box=소스 프레임 픽셀, id=서버 트랙id(없으면 -1)
//   bt.ingest(dets, backendBoostAt);
//   // 매 렌더 프레임:  vis=[{cls,score,tid,box:[x,y,w,h],alpha}]  (One-Euro+외삽+dedup+fade 적용)
//   var vis = bt.sample(Date.now());
//   // 페이지가 vis 를 자기 좌표변환(mediaRect/flip)·색으로 그린다. 드로잉은 페이지 담당.
(function (global) {
  function iou(a, b) {   // [x,y,w,h]
    var ix = Math.max(0, Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0]));
    var iy = Math.max(0, Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]));
    var inter = ix * iy, uni = a[2] * a[3] + b[2] * b[3] - inter;
    return uni > 0 ? inter / uni : 0;
  }

  function BoxTracker(opts) {
    opts = opts || {};
    // One-Euro 튜닝값(fast 클립 기준 — 스켈레톤 0.7/1.5 에서 상향). 파라미터로 주입 가능하나 기본=검증값.
    this.OE_MC = opts.OE_MC != null ? opts.OE_MC : 1.0;
    this.OE_BETA = opts.OE_BETA != null ? opts.OE_BETA : 3.0;
    this.OE_DC = opts.OE_DC != null ? opts.OE_DC : 1.0;
    this.excludeClass = opts.excludeClass != null ? String(opts.excludeClass).toLowerCase() : null;
    // 이 클래스는 트랙에는 포함(One-Euro+id외삽 정상 적용)하되 모션 앵커에는 절대 안 태운다(옵션, 기본 off).
    //   앵커는 MediaPipe 랜드마크(1인) 기준이라, 이 클래스를 앵커에 태우면 다인 상황에서 엉뚱한 사람 위치로
    //   끌려가는 결함이 재발한다(2026-08, safety-local person 박스에서 실제 발생 확인).
    this.noAnchorClass = opts.noAnchorClass != null ? String(opts.noAnchorClass).toLowerCase() : null;
    this.extrapCap = opts.extrapCap != null ? opts.extrapCap : 0.6;   // 속도외삽 상한(갱신간격 비율). 기본 0.6=safety-local 검증값.
    // 3.13: 모션 앵커링(옵션, 기본 off). on 이면 서버 박스를 페이지가 준 30fps 앵커(머리/몸통 랜드마크)에
    //   태워 rAF 마다 이동 → 검출 종단지연·방향전환 외삽실패를 상쇄. 판정은 서버 데이터라 표시만 영향(규칙6).
    this.anchor = !!opts.anchor;
    this.anchorLatency = opts.anchorLatency != null ? opts.anchorLatency : 180;   // 검출 종단지연(ms) 추정 — 검출 프레임 시점 앵커에 오프셋을 잡아 지연 제거
    this._anchor = null;     // 최신 앵커: {head:[x,y], torso:[x,y], scale, ok} (박스와 같은 좌표계=소스 픽셀)
    this._aHist = [];        // 앵커 히스토리 [{t, a}] — 최근 ~700ms(검출 프레임 시점 조회용)
    this.tracks = [];
    this.prevUpdateAt = 0;
  }

  // 페이지가 rAF 마다 최신 앵커(MediaPipe 랜드마크에서 산출)를 주입. null/ok:false 면 자동 폴백(트윈+외삽).
  BoxTracker.prototype.setAnchor = function (a, nowMs) {
    this._anchor = a;
    if (this.anchor && a) {
      var t = nowMs != null ? nowMs : Date.now();
      this._aHist.push({ t: t, a: a });
      var cut = t - 700;
      while (this._aHist.length > 2 && this._aHist[0].t < cut) this._aHist.shift();
    }
  };

  BoxTracker.prototype._anchorAt = function (targetT) {   // 히스토리에서 targetT 에 가장 가까운 앵커(검출 프레임 시점)
    var h = this._aHist, best = this._anchor, bd = 1e15;
    for (var i = 0; i < h.length; i++) { var d = Math.abs(h[i].t - targetT); if (d < bd) { bd = d; best = h[i].a; } }
    return best;
  };

  BoxTracker.prototype._linkAnchor = function (atT) {   // 서버 갱신 시점에만: 각 박스를 '검출 프레임 시점' 앵커점에 연결+오프셋 저장(지연 제거·드리프트 리셋)
    var A = this._anchorAt((atT != null ? atT : Date.now()) - this.anchorLatency);   // 검출은 ~latency 전 프레임 → 그때 앵커 기준
    var ok = this.anchor && A && A.ok;
    var noAnchor = this.noAnchorClass;
    this.tracks.forEach(function (t) {
      if (!ok || (noAnchor && String(t.cls).toLowerCase() === noAnchor)) { t.aType = null; return; }
      var cx = t.box[0] + t.box[2] / 2, cy = t.box[1] + t.box[3] / 2;
      var dh = Math.hypot(cx - A.head[0], cy - A.head[1]);
      var dtq = Math.hypot(cx - A.torso[0], cy - A.torso[1]);
      var near = Math.min(dh, dtq) <= (A.scale * 2.5 || 1e9);   // 사람 근처 박스만 앵커(스케일=어깨폭 기준)
      if (near) { t.aType = dh <= dtq ? 'head' : 'torso'; var ap = dh <= dtq ? A.head : A.torso; t.aOff = [cx - ap[0], cy - ap[1]]; t.aScale = A.scale; }
      else { t.aType = null; }
    });
  };

  BoxTracker.prototype._boxAt = function (t, now) {   // 표시 박스: 앵커 연결돼 있고 앵커 유효하면 앵커 이동, 아니면 트윈+외삽(폴백)
    var A = this._anchor;
    if (this.anchor && A && A.ok && t.aType && t.aScale) {
      var ap = t.aType === 'head' ? A.head : A.torso;
      var sr = A.scale / t.aScale;                    // 앵커 스케일 변화(멀어짐/가까워짐) → 박스 크기도 비례
      var w = t.box[2] * sr, h = t.box[3] * sr;
      var cx = ap[0] + t.aOff[0] * sr, cy = ap[1] + t.aOff[1] * sr;
      return [cx - w / 2, cy - h / 2, w, h];
    }
    return this._dispBox(t, now);
  };

  BoxTracker.prototype._oe1 = function (s, v, dt) {   // 스칼라 One-Euro(속도↑→컷오프↑→즉각추종, 느리면 강평활)
    var MC = this.OE_MC, BETA = this.OE_BETA, DC = this.OE_DC;
    var al = function (c) { var tau = 1 / (2 * Math.PI * c); return 1 / (1 + tau / dt); };
    if (s.x === undefined) { s.x = v; s.dx = 0; return v; }
    var dv = (v - s.x) / dt; s.dx = s.dx + al(DC) * (dv - s.dx);
    var cut = MC + BETA * Math.abs(s.dx); s.x = s.x + al(cut) * (v - s.x); return s.x;
  };

  BoxTracker.prototype._oeBox = function (t, det, cg) {   // 4좌표 One-Euro + (id 트랙) 속도(최근 3갱신 가중, 외삽용)
    var dt = (cg || 150) / 1000; if (!t.oe) t.oe = [{}, {}, {}, {}];
    var nb = [this._oe1(t.oe[0], det.box[0], dt), this._oe1(t.oe[1], det.box[1], dt),
              this._oe1(t.oe[2], det.box[2], dt), this._oe1(t.oe[3], det.box[3], dt)];
    if (t.tid >= 0 && t.box) {
      var d = [(nb[0] - t.box[0]) / cg, (nb[1] - t.box[1]) / cg, (nb[2] - t.box[2]) / cg, (nb[3] - t.box[3]) / cg];
      t.dhist = (t.dhist || []).concat([d]).slice(-3);
      var hs = t.dhist, ws = 0, vv = [0, 0, 0, 0];
      for (var m = 0; m < hs.length; m++) { var wt = m + 1; ws += wt; for (var cc = 0; cc < 4; cc++) vv[cc] += hs[m][cc] * wt; }
      t.vel = [vv[0] / ws, vv[1] / ws, vv[2] / ws, vv[3] / ws];
    }
    return nb;
  };

  BoxTracker.prototype._dispBox = function (t, now) {   // 표시 = 필터박스 + (id 트랙) 속도 외삽(캡 60%). 폴백(id=-1)은 외삽 없음.
    if (t.tid >= 0 && t.vel) {
      var dt = Math.min(now - t.t0, this.extrapCap * (t.gap || 350));
      return [t.box[0] + t.vel[0] * dt, t.box[1] + t.vel[1] * dt, t.box[2] + t.vel[2] * dt, t.box[3] + t.vel[3] * dt];
    }
    return t.box.slice();
  };

  // 새 배치 수신 시: id(tid) 우선 매칭 → 없으면 클래스+IoU>0.3 폴백. 사라진 id 트랙 즉시 drop, fallback 미매칭 페이드아웃.
  BoxTracker.prototype.ingest = function (dets, at, nowMs) {
    var now = (nowMs != null ? nowMs : Date.now());
    var gap = this.prevUpdateAt ? (at - this.prevUpdateAt) : 0;
    var cg = gap > 0 ? Math.max(300, Math.min(1200, gap)) : 350;   // 클램프한 갱신간격
    this.prevUpdateAt = at;
    var self = this, ex = this.excludeClass;
    var incoming = (dets || [])
      .filter(function (d) { return !(ex && String(d.cls || '').toLowerCase() === ex); })
      .map(function (d) { return { tid: (d.id == null ? -1 : d.id), cls: d.cls || '', score: d.score || 0, box: [d.box[0], d.box[1], d.box[2], d.box[3]] }; });
    var tracks = this.tracks, n = tracks.length, used = new Array(n).fill(false);
    function upd(t, det) { t.box = self._oeBox(t, det, cg); t.score = det.score; t.t0 = now; t.gap = cg; t.alive = true; }
    function mk(det) { var t = { tid: det.tid, cls: det.cls, score: det.score, t0: now, gap: cg, alpha: 0, alive: true }; t.box = self._oeBox(t, det, cg); return t; }
    incoming.forEach(function (det) {   // 1차: id 매칭(tid>=0)
      if (det.tid < 0) return;
      for (var i = 0; i < n; i++) { if (!used[i] && tracks[i].tid === det.tid) { used[i] = true; upd(tracks[i], det); det._done = true; return; } }
      tracks.push(mk(det)); det._done = true;
    });
    incoming.forEach(function (det) {   // 2차: id 없음(-1) → 클래스+IoU>0.3 폴백(id 트랙과는 매칭 금지)
      if (det._done) return;
      var bi = -1, best = 0.3;
      for (var i = 0; i < n; i++) {
        if (used[i] || tracks[i].tid >= 0 || String(tracks[i].cls).toLowerCase() !== det.cls.toLowerCase()) continue;
        var v = iou(tracks[i].box, det.box); if (v > best) { best = v; bi = i; }
      }
      if (bi >= 0) { used[bi] = true; upd(tracks[bi], det); } else tracks.push(mk(det));
    });
    for (var i = 0; i < n; i++) { if (!used[i]) { if (tracks[i].tid >= 0) tracks[i].drop = true; else tracks[i].alive = false; } }
    if (this.anchor) this._linkAnchor(at);   // 3.13: 갱신 시점에만 박스↔앵커 재연결(검출프레임 시점 기준 → 지연 제거·드리프트 방지)
  };

  // 매 렌더: 페이드 갱신 + 외삽 표시박스 + 같은클래스 중복 억제(IoU≥0.40·면적비≤2 OR 포함비≥0.70). 억제된 트랙도 상태 유지(승자 소실 시 복귀).
  BoxTracker.prototype.sample = function (now) {
    var vis = [];
    this.tracks.forEach(function (t) {
      if (t.drop) return;
      t.alpha += t.alive ? 0.2 : -0.08;                 // 페이드인 ≤100ms, 아웃(fallback)
      if (t.alpha <= 0) return;
      if (t.alpha > 1) t.alpha = 1;
      vis.push({ t: t, box: this._boxAt(t, now) });   // 표시=앵커(on) 또는 외삽(폴백)
    }, this);
    for (var ai = 0; ai < vis.length; ai++) {
      if (vis[ai].sup) continue;
      for (var bi = ai + 1; bi < vis.length; bi++) {
        if (vis[bi].sup) continue;
        if (String(vis[ai].t.cls).toLowerCase() !== String(vis[bi].t.cls).toLowerCase()) continue;
        var A = vis[ai].box, B = vis[bi].box, aa = A[2] * A[3], ab = B[2] * B[3];
        var ratio = (aa > 0 && ab > 0) ? Math.max(aa / ab, ab / aa) : 9;
        var ix = Math.max(0, Math.min(A[0] + A[2], B[0] + B[2]) - Math.max(A[0], B[0]));
        var iy = Math.max(0, Math.min(A[1] + A[3], B[1] + B[3]) - Math.max(A[1], B[1]));
        var contain = (ix * iy) / Math.max(1, Math.min(aa, ab));
        if ((iou(A, B) >= 0.40 && ratio <= 2) || contain >= 0.70) {
          if ((vis[ai].t.score || 0) >= (vis[bi].t.score || 0)) vis[bi].sup = true;
          else { vis[ai].sup = true; break; }
        }
      }
    }
    var kept = [], out = [];
    vis.forEach(function (v) {
      kept.push(v.t);                                   // 억제된 것도 tracks 에 유지
      if (v.sup) return;
      out.push({ cls: v.t.cls, score: v.t.score, tid: v.t.tid, box: v.box, alpha: v.t.alpha });
    });
    this.tracks = kept;
    return out;
  };

  global.VigentBoxDisplay = { BoxTracker: BoxTracker, iou: iou };
})(typeof window !== 'undefined' ? window : this);
