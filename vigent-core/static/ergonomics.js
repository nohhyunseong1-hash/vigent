/* VIGENT 에르고노믹스(인간공학) 채점기 — 공유 모듈(safety·office·sports 공용)
 *
 * 입력: MediaPipe Pose 33점 랜드마크(정규화 좌표 {x,y,visibility})
 * 처리: 목·허리·어깨 각도 계산 → 임계값(vision.yaml ergonomics)과 비교 → 점수·등급·코칭
 * 출력: {ok, angles:{neck,trunk,shoulder}, level:'good|warn|bad', score, feedback:[...]}
 *
 * 설계: 테마=설정 — 임계값은 vision.yaml 의 ergonomics 블록에서 주입(setConfig).
 * 한계(정직): 단일 카메라 2D 라 정면뷰에선 전방 거북목 측정이 제한적 → '참고용 선별'.
 */
(function (global) {
  const DEG = 180 / Math.PI;
  // MediaPipe Pose 인덱스
  const L = { nose: 0, earL: 7, earR: 8, shL: 11, shR: 12, hipL: 23, hipR: 24 };

  // 기본 임계값(vision.yaml 없을 때 폴백)
  const DEFAULT = {
    framework: "RULA",
    joints: {
      neck: { good: 15, warn: 25 },     // 목 전방/기울기(도)
      trunk: { good: 10, warn: 20 },    // 허리 굽힘(도)
      shoulder: { good: 8, warn: 15 },  // 어깨 좌우 높이차(도)
    },
    hold_sec: 5,
    coaching: true,
  };

  function mid(a, b) { return a && b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : (a || b); }
  function vis(p) { return p && (p.visibility == null ? 1 : p.visibility) >= 0.3; }
  // 두 점을 잇는 벡터가 '수직(위)'에서 벗어난 각도(도). 0=완전 수직.
  function angleFromVertical(lower, upper) {
    const dx = upper.x - lower.x, dy = upper.y - lower.y; // 화면좌표(y는 아래로 증가)
    return Math.abs(Math.atan2(dx, -dy)) * DEG;
  }
  // 두 점을 잇는 선이 '수평'에서 벗어난 각도(도). 0=수평(어깨 양쪽 같은 높이).
  function tiltFromHorizontal(a, b) {
    return Math.abs(Math.atan2(b.y - a.y, b.x - a.x)) * DEG;
  }

  const Ergo = {
    config: JSON.parse(JSON.stringify(DEFAULT)),
    setConfig(c) { if (c && c.joints) this.config = Object.assign({}, DEFAULT, c); },

    score(lm) {
      if (!lm || lm.length < 25) return { ok: false, reason: "포즈 없음" };
      const shL = lm[L.shL], shR = lm[L.shR], hipL = lm[L.hipL], hipR = lm[L.hipR];
      const earL = lm[L.earL], earR = lm[L.earR];
      if (!vis(shL) || !vis(shR)) return { ok: false, reason: "어깨 미검출" };

      const shM = mid(shL, shR);
      const hipM = (vis(hipL) || vis(hipR)) ? mid(hipL, hipR) : null;
      const earM = (vis(earL) || vis(earR)) ? mid(earL, earR) : null;

      const J = this.config.joints;
      const angles = {};
      const feedback = [];
      let pts = 0, n = 0;

      // 목(거북목/고개 숙임): 어깨중점 → 귀중점 이 수직에서 벗어난 정도
      if (earM) {
        const a = angleFromVertical(shM, earM); angles.neck = +a.toFixed(1);
        const lv = a <= J.neck.good ? 0 : a <= J.neck.warn ? 1 : 2; pts += lv; n++;
        if (lv === 2) feedback.push({ joint: "목", level: "bad", msg: "거북목/고개 숙임이 큽니다. 모니터를 눈높이로 올리고 턱을 살짝 당기세요." });
        else if (lv === 1) feedback.push({ joint: "목", level: "warn", msg: "목이 약간 앞으로 나왔습니다. 화면을 눈높이로 맞추세요." });
      }
      // 허리(굽힘/구부정): 엉덩이중점 → 어깨중점 이 수직에서 벗어난 정도
      if (hipM) {
        const a = angleFromVertical(hipM, shM); angles.trunk = +a.toFixed(1);
        const lv = a <= J.trunk.good ? 0 : a <= J.trunk.warn ? 1 : 2; pts += lv; n++;
        if (lv === 2) feedback.push({ joint: "허리", level: "bad", msg: "허리가 많이 굽었습니다. 등받이에 기대 허리를 펴고 골반을 세우세요." });
        else if (lv === 1) feedback.push({ joint: "허리", level: "warn", msg: "허리가 약간 구부정합니다. 등을 펴세요." });
      }
      // 어깨(좌우 높이차/비대칭): 어깨 라인이 수평에서 벗어난 정도
      {
        const a = tiltFromHorizontal(shL, shR); angles.shoulder = +a.toFixed(1);
        const lv = a <= J.shoulder.good ? 0 : a <= J.shoulder.warn ? 1 : 2; pts += lv; n++;
        if (lv === 2) feedback.push({ joint: "어깨", level: "bad", msg: "어깨가 한쪽으로 많이 기울었습니다. 양 어깨 높이를 맞추세요." });
        else if (lv === 1) feedback.push({ joint: "어깨", level: "warn", msg: "어깨가 약간 비대칭입니다. 자세를 바로 하세요." });
      }

      // 종합: 관절별 위험점수 합(0~2씩) → 등급. 가산식(나쁜 관절이 점수를 올림).
      const avg = n ? pts / n : 0;
      const level = avg >= 1.34 ? "bad" : avg > 0.5 ? "warn" : "good";
      const score = Math.round((1 - avg / 2) * 100); // 100=완벽, 0=매우 나쁨
      if (!feedback.length) feedback.push({ joint: "전체", level: "good", msg: "좋은 자세입니다. 유지하세요!" });
      return { ok: true, angles, level, score, feedback, framework: this.config.framework };
    },
  };

  global.VIGENTErgo = Ergo;
})(window);
