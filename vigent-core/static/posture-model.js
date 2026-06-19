/* AX 자세-위험 분류기 (브라우저 추론)
 * backend/ml/posture_model.forward_json 및 pose_features.extract_features 와
 * 동일한 연산을 JS로 구현한다. posture_weights.json 을 받아 작은 MLP를 forward 한다.
 * TensorFlow.js 불필요 (순수 JS). 실패 시 호출 측에서 무시하면 기존 동작 유지.
 *
 * 사용:
 *   const m = await AXPosture.load('/static/models/posture/posture_weights.json');
 *   const r = m.predictFromKeypoints(coco17);  // {class_name, class_id, confidence, probs}
 */
(function (global) {
  // COCO-17 인덱스
  const NOSE=0, LSH=5, RSH=6, LEL=7, REL=8, LWR=9, RWR=10,
        LHIP=11, RHIP=12, LKNEE=13, RKNEE=14, LANK=15, RANK=16;

  function angle(a, b, c) {
    if (!a || !b || !c) return 180.0;
    const bax = a[0]-b[0], bay = a[1]-b[1];
    const bcx = c[0]-b[0], bcy = c[1]-b[1];
    const na = Math.hypot(bax, bay), nc = Math.hypot(bcx, bcy);
    if (na < 1e-6 || nc < 1e-6) return 180.0;
    let cos = (bax*bcx + bay*bcy) / (na*nc);
    cos = Math.max(-1, Math.min(1, cos));
    return Math.acos(cos) * 180 / Math.PI;
  }
  function inclineFromVertical(low, high) {
    const vx = high[0]-low[0], vy = high[1]-low[1];
    const n = Math.hypot(vx, vy);
    if (n < 1e-6) return 0.0;
    let cos = (vx*0 + (vy/n)*(-1)); // vertical up = (0,-1)
    cos = Math.max(-1, Math.min(1, cos));
    return Math.acos(cos) * 180 / Math.PI;
  }
  const mid = (a, b) => [(a[0]+b[0])/2, (a[1]+b[1])/2];
  const clamp01 = v => Math.max(0, Math.min(1, v));

  // pose_features.extract_features 와 동일 (관절각 8 + 몸통/목 기울기 2)
  function extractFeatures(kp) {
    if (!kp || kp.length < 17) { kp = (kp||[]).concat(Array(17).fill([0,0])).slice(0,17); }
    const shoulderMid = mid(kp[LSH], kp[RSH]);
    const hipMid = mid(kp[LHIP], kp[RHIP]);
    const ang = [
      angle(kp[LSH], kp[LEL], kp[LWR]),
      angle(kp[RSH], kp[REL], kp[RWR]),
      angle(kp[LHIP], kp[LKNEE], kp[LANK]),
      angle(kp[RHIP], kp[RKNEE], kp[RANK]),
      angle(kp[LSH], kp[LHIP], kp[LKNEE]),
      angle(kp[RSH], kp[RHIP], kp[RKNEE]),
      angle(kp[LEL], kp[LSH], kp[LHIP]),
      angle(kp[REL], kp[RSH], kp[RHIP]),
    ];
    const torso = inclineFromVertical(hipMid, shoulderMid);
    const neck = inclineFromVertical(shoulderMid, kp[NOSE]);
    const f = [];
    for (let i = 0; i < 8; i++) f.push(clamp01(ang[i] / 180));
    f.push(clamp01(torso / 90));
    f.push(clamp01(neck / 90));
    return f;
  }

  function forward(layers, x) {
    let a = x.slice();
    for (const layer of layers) {
      const W = layer.W, b = layer.b, units = b.length, inDim = a.length;
      const z = new Array(units).fill(0);
      for (let j = 0; j < units; j++) {
        let s = b[j];
        for (let i = 0; i < inDim; i++) s += a[i] * W[i][j];
        z[j] = s;
      }
      if (layer.activation === 'relu') {
        a = z.map(v => Math.max(0, v));
      } else if (layer.activation === 'softmax') {
        const mx = Math.max(...z);
        const e = z.map(v => Math.exp(v - mx));
        const sum = e.reduce((p, q) => p + q, 0);
        a = e.map(v => v / sum);
      } else { a = z; }
    }
    return a;
  }

  async function load(url) {
    const resp = await fetch(url);
    const data = await resp.json();
    const layers = data.layers;
    const classNames = data.class_names || ['safe', 'caution', 'danger'];
    return {
      classNames,
      featureNames: data.feature_names,
      predict(features) {
        const probs = forward(layers, features);
        let cls = 0;
        for (let i = 1; i < probs.length; i++) if (probs[i] > probs[cls]) cls = i;
        return { class_id: cls, class_name: classNames[cls], confidence: probs[cls], probs };
      },
      predictFromKeypoints(coco17) {
        return this.predict(extractFeatures(coco17));
      },
    };
  }

  global.AXPosture = { load, extractFeatures, forward };
})(window);
