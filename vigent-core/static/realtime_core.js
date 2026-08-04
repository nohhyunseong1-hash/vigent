// ═══════════════════════════════════════════════════
//  MODELS & STATE
// ═══════════════════════════════════════════════════
let holistic=null, cocoModel=null, mobileNetModel=null;
let camera=null, currentStream=null;
let cameraOn=false, paused=false, mirrored=false;
let lastTime=performance.now(), startTime=Date.now();
const stats={fall:0,posture:0,obj:0};
let activeServiceMode='fitness';
let latestServiceInsight=null;
let latestCoreFrameState=null;
let activeThemeProfile=null;
let lastSpokenFeedback='';
let lastSpokenAt=0;
const serviceEvents=[];
const lastCropSaveAt={left:0,right:0};
let cropSaveCount=0;
const squatState={
  phase:'ready',
  count:0,
  minKnee:180,
  maxTrunk:0,
  lastDepth:null,
  lastScore:null,
  bestScore:null,
  lastTempo:null,
  lastRom:null,
  lastSymmetry:null,
  reps:[],
  lastTransitionAt:0
};
const officeState={
  sittingSeconds:0,
  neckRiskSeconds:0,
  trunkRiskSeconds:0,
  shoulderRiskSeconds:0,
  lastUpdateAt:0,
  breakDue:false
};
const SERVICE_META={
  fitness:{
    title:'BODA Fitness',
    panel:'BODA Fitness 분석 중',
    sub:'운동 자세, 반복 패턴, 균형을 실시간으로 확인합니다.',
    modeSub:'운동 자세 코치',
    tile:'',
    badge:'운동 자세 코치',
    features:['스쿼트','런지','푸쉬업','플랭크','데드리프트','실시간 피드백'],
    pipeline:{pose:'high',objectDetection:true,multiPerson:true,handObjects:true,face:true,ppe:true,vlm:'on-demand'},
    metrics:['jointAngles','rom','repCount','tempo','symmetry','formScore','phase'],
    panels:['squatCounter','jointAngles','formFeedback','sessionReport'],
    overlay:'skeleton',
    thresholds:{squatDepthKnee:115,trunkWarnDeg:22,trunkDangerDeg:35,kneeDiffWarnDeg:18},
    alerts:['형태오류','가동범위부족','좌우불균형'],
    design:'fitness',
    terminology:{person:'사용자',count:'반복'}
  },
  safety:{
    title:'BODA Safety',
    panel:'BODA Safety 분석 중',
    sub:'보호구, 위험 행동, 위험 사물과 현장 이벤트를 확인합니다.',
    modeSub:'산업안전 알림',
    tile:'safety',
    badge:'현장 안전 알림',
    features:['작업자 수','안전모/조끼','위험구역','중량물 자세','증거 리포트'],
    pipeline:{pose:'medium',objectDetection:true,multiPerson:true,handObjects:true,face:true,ppe:true,vlm:'on-demand'},
    metrics:['personCount','zones','dwell','ppe','dangerAction','ergoLoad'],
    panels:['personCount','zoneStatus','ppeStatus','dangerAlerts','evidenceReport'],
    overlay:'bbox+zone',
    thresholds:{dwellWarnSec:30,fallConfirm:6,trunkWarnDeg:35,ppeFreshMs:5000},
    alerts:['낙상','위험구역침입','보호구미착용','중량물위험자세','장시간정지'],
    design:'safety',
    terminology:{person:'작업자',count:'인원'}
  },
  office:{
    title:'BODA Office Care',
    panel:'BODA Office Care 분석 중',
    sub:'거북목, 허리 굽힘, 어깨 불균형을 업무 자세 기준으로 확인합니다.',
    modeSub:'사무직 자세 관리',
    tile:'office',
    badge:'데스크 건강관리',
    features:['거북목','허리 굽힘','어깨 불균형','장시간 앉음','휴식 알림'],
    pipeline:{pose:'high',objectDetection:true,multiPerson:true,handObjects:true,face:true,ppe:true,vlm:'on-demand'},
    metrics:['neckForward','shoulderBalance','trunkBend','sittingTimer','breakReminder'],
    panels:['postureScore','neckShoulder','sittingTimer','breakAlert'],
    overlay:'skeleton-upper',
    thresholds:{neckForwardRatio:0.34,trunkWarnDeg:18,shoulderTiltWarnDeg:9,sittingWarnMin:50},
    alerts:['거북목','어깨말림','허리굽힘','장시간앉음→휴식'],
    design:'office',
    terminology:{person:'사용자',count:'세션'}
  }
};

const videoEl=document.getElementById('videoEl');
const canvas=document.getElementById('outputCanvas');
const ctx=canvas.getContext('2d');
const imageEl=document.getElementById('imageEl');
const CAMERA_DISPLAY_FLIP_X=true;

function applyCameraOrientation(isCamera=false){
  const videoTransform=isCamera&&CAMERA_DISPLAY_FLIP_X?'scaleX(-1)':'none';
  videoEl.style.setProperty('transform',videoTransform,'important');
  canvas.style.setProperty('transform','none','important');
  imageEl.style.setProperty('transform','none','important');
}

function shouldFlipDisplay(){return cameraOn&&CAMERA_DISPLAY_FLIP_X;}
function mediaRect(W,H){
  const sourceW=(videoEl.style.display!=='none'&&(videoEl.videoWidth||0))||(imageEl.naturalWidth||0)||W;
  const sourceH=(videoEl.style.display!=='none'&&(videoEl.videoHeight||0))||(imageEl.naturalHeight||0)||H;
  const scale=Math.min(W/sourceW,H/sourceH);
  const w=sourceW*scale, h=sourceH*scale;
  return {x:(W-w)/2,y:(H-h)/2,w,h,scale};
}
function viewX(p,W,H){const r=mediaRect(W,H);return r.x+(shouldFlipDisplay()?1-p.x:p.x)*r.w;}
function viewY(p,W,H){const r=mediaRect(W,H);return r.y+p.y*r.h;}
function displayBboxArray(b,W,H){
  if(!b) return b;
  const r=mediaRect(W,H);
  const x=r.x+(shouldFlipDisplay()?r.w-b[0]-b[2]:b[0]);
  return [x,r.y+b[1],b[2],b[3]];
}
function displayHandBox(b,W,H){
  if(!b) return b;
  const r=mediaRect(W,H);
  if(!shouldFlipDisplay()) return {...b,minX:r.x+b.minX,maxX:r.x+b.maxX,minY:r.y+b.minY,maxY:r.y+b.maxY};
  return {...b,minX:r.x+r.w-b.maxX,maxX:r.x+r.w-b.minX,minY:r.y+b.minY,maxY:r.y+b.maxY};
}

// 멀티스케일 감지 결과 (TF.js 독립 루프에서 업데이트)
let latestObjects=[];

// 손 사물 상태
let leftHeldObjects=[], rightHeldObjects=[];
let leftMobileNetResult=[], rightMobileNetResult=[];
let leftHeldHistory=[], rightHeldHistory=[];

// 객체 ID 추적
let objTracker={nextId:1, tracked:[]};

// 손 bbox 캐시 (영상 픽셀 기준)
let cachedLBBox=null, cachedRBBox=null;
// 스무딩된 포즈 전역 캐시 (updateSceneUI 등에서 참조)
let sm=null;
// TF.js 독립 루프 ID
let tfLoopTimer=null, mnLoopTimer=null;
let tfBusy=false, mnBusy=false;
let _cocoLastRun=0;   // 안전 모드 브라우저 COCO 저빈도 스로틀
const OBJECT_SCAN_INTERVAL=360;
const FINE_CLASSIFY_INTERVAL=900;
let latestPpeStatus={
  helmet:{state:'unknown',label:'확인 중',confidence:0,raw:''},
  vest:{state:'unknown',label:'확인 중',confidence:0,raw:''},
  updatedAt:0,
  source:'browser'
};
let ppeBackendBusy=false, lastPpeBackendAt=0;
const PPE_BACKEND_INTERVAL=2500;
// 백엔드 정밀 보정(yolov8s) — 브라우저 COCO-SSD가 놓친 객체(특히 휴대폰 등 소형)를 보강
let backendBoostBusy=false, lastBackendBoostAt=0, backendBoostAt=0;
let _boostDisp=[];   // ★ 박스 보간 표시 상태(2026-07-12): target=backendBoostDets 로 매 렌더 lerp 수렴 + 페이드아웃.
                     //   검출 자체(4~6fps)를 빠르게 하는 게 아니라 '표시'를 30fps로 부드럽게 하는 것(안전 판정은 검출 fps 기준).
const _COORD_DIAG=(typeof location!=='undefined')&&new URLSearchParams(location.search).get('diag')==='1';  // 진단 모드(?diag=1): 원시 vs 보간 박스 동시표시(개발 전용, 기본 off)
let backendBoostDets=[];
// 보호구(PPE) 클래스 — 안전 테마에서만 표시/사용 (오피스·피트니스에선 제외)
const PPE_CLASSES=new Set(['helmet','hardhat','hard hat','gloves','glove','vest','safety vest','reflective vest','boots','goggles','goggle','none','no helmet','no hardhat','no goggle','no gloves','no boots','no vest','no safety vest','mask','no mask']);
function isPpeClass(c){ return PPE_CLASSES.has(String(c).toLowerCase().replace(/[-_]/g,' ')); }
// 미착용(NO-*)·화재/연기·흉기 등 '위반/위험'은 빨강으로 표시. 착용/정상 보호구는 빨강 아님.
function isViolation(c){ const s=String(c||'').toLowerCase().replace(/[-_]/g,' ').trim();
  return s.startsWith('no ') || ['fire','smoke','cigarette','knife','scissors'].includes(s); }
let backendHazards=[];   // 백엔드 화재/연기/흡연 등 위험요소 (색상 휴리스틱)
const BACKEND_BOOST_INTERVAL=250;     // 고정밀 백엔드 호출 최소간격(≈4fps) — 포즈/탐지 반응성↑(통합호출 ~70ms라 여유)
// 검출 호출 최소간격(2026-07-12): 왕복 110ms·추론 83ms 대비 150ms가 과해 검출 fps 병목(~6.7fps)이었음 → 100ms(~9fps).
// 외부화: window.VIGENT_DETECT_MIN_MS 로 주입 가능. ⚠️ 엣지(RK3588 등 느린 추론)에서는 CPU 포화 방지 위해 상향(150~200) 필요.
const DETECT_MIN_INTERVAL_MS=(typeof window!=='undefined' && window.VIGENT_DETECT_MIN_MS) || 100;
const BACKEND_LOOP_INTERVAL=(typeof window!=='undefined' && window.VIGENT_BACKEND_LOOP_MS) || 150;   // 루프 타이머. 페이지 오버라이드 가능(미설정=150 → 전 테마 불변·저하0 · 2.1)
const BACKEND_BOOST_TTL=3000;
const BACKEND_PRIMARY_TTL=2800;       // 이 시간 내 백엔드 결과는 '주 탐지'로 우선 사용(CPU 지연 커버 → 깜빡임 방지)
let backendLoopTimer=null;

// ── 잔상(staleness) 지연 예산 ──────────────────────────────────────────────
// 렌더는 매 프레임 신선하지만 detection 박스는 저빈도(≈150~300ms) 캐시라, 갱신이 끊기면
// 옛 위치에 박스가 잔상처럼 남는다. 정상 갱신 주기보다 '뒤에서' 페이드를 시작하면
// 깜빡임 없이 긴 잔상만 사라진다(하드컷 대신 알파 페이드). 값은 config로 노출(4단계) —
// 잠정 기본값이며 실제 테스트 클립으로 튜닝해야 한다.
const _TUNE=(typeof window!=='undefined' && window.VIGENT_TUNING) || {};
let STALE_FADE_START_MS = _TUNE.staleFadeStartMs ?? 350;   // 이 시간까지는 완전 불투명(정상 갱신 주기 커버 → 깜빡임 방지)
let STALE_TTL_MS        = _TUNE.staleTtlMs        ?? 700;   // 이 시간 지나면 렌더에서 완전 제외(잔상 제거)
let SAME_PERSON_RADIUS_K= _TUNE.samePersonRadiusK ?? 1.8;  // 같은 사람으로 볼 가로 반경(박스폭 배수). 지연 중복 흡수, 실제 타인은 더 멂
// detection의 관측 시각(seenAt)으로 알파(0~1) 계산. seenAt 없으면 저하 방지 위해 1(그대로 표시).
function _staleAlpha(seenAt){
  if(!seenAt) return 1;
  const age=Date.now()-seenAt;
  if(age<=STALE_FADE_START_MS) return 1;
  if(age>=STALE_TTL_MS) return 0;
  return 1-(age-STALE_FADE_START_MS)/(STALE_TTL_MS-STALE_FADE_START_MS);
}
// 이동으로 생긴 '따라오는' 꼬리 잔상 제거: 오래된(페이드 중) 박스에 대해, 같은 클래스의
// 더 신선한 박스가 이미 있으면 = 객체가 새 위치로 옮겨간 것 → 옛 박스는 페이드하지 말고 즉시 드롭.
// 더 신선한 형제가 없으면(진짜로 사라진 객체) 그대로 두어 페이드로 부드럽게 정리(깜빡임 보호 유지).
function _dropTrailingStale(list){
  if(!Array.isArray(list) || list.length<2) return list;
  const now=Date.now();
  // 사람: 트래커가 빠른 이동 시 옛 위치 트랙을 gone>0으로 남겨 꼬리 잔상을 만든다.
  // '실제 감지 중(gone 0)'인 사람이 하나라도 있으면, gone>0 사람 박스는 꼬리이므로 즉시 제거.
  // 실제로 여러 사람은 각자 gone 0이라 안 지워지고, 전부 놓친 경우(살아있는 사람 없음)엔
  // 남겨서 seenAt 페이드로 처리 → 저사양 깜빡임 보호 유지.
  const livePerson = list.some(o=>o.class==='person' && !(o.gone>0));
  return list.filter(o=>{
    if(o.class==='person'){
      return !(livePerson && o.gone>0);            // 살아있는 사람 존재 → 이 gone 트랙은 꼬리 잔상 → 드롭
    }
    // 비-사람(지게차/PPE 등): 기존 로직 유지(같은 클래스의 더 신선한 박스가 있으면 오래된 것 드롭)
    if(!o.seenAt || now-o.seenAt < STALE_FADE_START_MS) return true;
    return !list.some(f=> f!==o && f.class===o.class && (f.seenAt||0) > o.seenAt + 60);
  });
}
// 같은 사람의 '살아있는' 중복 박스 제거: 한 사람에 대해 pose-follow 박스, 지연된 백엔드 detection 박스,
// 브라우저 COCO 박스가 서로 안 겹치며 동시에 남을 수 있다(꼬리). 가까운(=같은 사람) person 박스끼리는
// 권위 높은 하나만 유지(pose-follow > 최신 seenAt). 멀리 떨어진 박스는 다른 사람으로 보고 유지(멀티 대응).
function _dedupePersons(list){
  if(!Array.isArray(list)) return list;
  const idx=[];
  for(let k=0;k<list.length;k++) if(list[k] && list[k].class==='person') idx.push(k);
  if(idx.length<2) return list;
  const auth=o=>(o._poseFollow?1e15:0)+(o.seenAt||0);      // pose-follow 최우선, 그다음 최신 관측
  const drop=new Set();
  for(let a=0;a<idx.length;a++){
    for(let b=a+1;b<idx.length;b++){
      if(drop.has(idx[a]) || drop.has(idx[b])) continue;
      const oa=list[idx[a]], ob=list[idx[b]];
      const aw=oa.bbox[2]||1, ah=oa.bbox[3]||1, bw=ob.bbox[2]||1, bh=ob.bbox[3]||1;
      const dx=Math.abs((oa.bbox[0]+aw/2)-(ob.bbox[0]+bw/2));
      const dy=Math.abs((oa.bbox[1]+ah/2)-(ob.bbox[1]+bh/2));
      if(dx < Math.max(aw,bw)*SAME_PERSON_RADIUS_K && dy < Math.max(ah,bh)){  // 가까움 = 같은 사람
        drop.add( auth(oa)>=auth(ob) ? idx[b] : idx[a] );   // 권위 낮은 쪽 드롭
      }
    }
  }
  if(!drop.size) return list;
  return list.filter((o,k)=>!drop.has(k));
}
// 겹치는 같은-클래스 중복 박스 제거(비-사람). 백엔드가 한 대상(예: 머리)에 NO-Hardhat 박스를
// 크기 다르게 여러 개 반환할 때, IoU(겹침) 또는 containment(한 박스가 다른 걸 품음)로 중복 판정 → 최고 점수 하나만.
// 사람은 pose-follow/_dedupePersons가 별도 처리하므로 건드리지 않는다.
function _ios(a,b){                                            // intersection over smaller (포함 비율)
  const ix=Math.max(0, Math.min(a[0]+a[2],b[0]+b[2])-Math.max(a[0],b[0]));
  const iy=Math.max(0, Math.min(a[1]+a[3],b[1]+b[3])-Math.max(a[1],b[1]));
  const inter=ix*iy; if(inter<=0) return 0;
  return inter/Math.max(1, Math.min(a[2]*a[3], b[2]*b[3]));
}
function _dedupOverlapping(list){
  if(!Array.isArray(list) || list.length<2) return list;
  const sorted=[...list].sort((x,y)=>(y.score||0)-(x.score||0));   // 높은 점수 우선 유지
  const keep=[];
  for(const o of sorted){
    if(!o || o.class==='person'){ keep.push(o); continue; }        // 사람은 별도 처리
    const dup=keep.some(k=> k.class===o.class && (iou(k.bbox,o.bbox)>0.4 || _ios(k.bbox,o.bbox)>0.55));
    if(!dup) keep.push(o);
  }
  return keep;
}
// 백엔드 포즈(COCO-17, 소스좌표)의 bounding extent
function _poseKpExtent(p){
  const pts=p&&p.points, cf=(p&&p.conf)||[];
  if(!pts||!pts.length) return null;
  let minX=1e9,minY=1e9,maxX=-1e9,maxY=-1e9,n=0;
  for(let i=0;i<pts.length;i++){ if((cf[i]??1)<0.3||!pts[i])continue; const x=pts[i][0],y=pts[i][1];
    if(x<minX)minX=x; if(x>maxX)maxX=x; if(y<minY)minY=y; if(y>maxY)maxY=y; n++; }
  if(n<3) return null;
  return [minX,minY,maxX-minX,maxY-minY];
}
// 보호구(PPE) 위반 오탐 억제: 위반은 '사람' 위에서만 의미가 있다. 프레임에 사람 신호가 있는데
// PPE 박스가 어떤 사람과도 겹치지 않으면(빈 벽 오탐) 숨긴다. 사람 신호가 전혀 없으면 판단 불가 →
// 그대로 둔다(놓침 방지 fail-safe). 좌표는 모두 소스(VW×VH) 기준이라 직접 비교 가능.
function _filterOrphanPPE(list){
  if(!Array.isArray(list)) return list;
  const persons=[];
  for(const o of list) if(o && o.class==='person' && o.bbox) persons.push(o.bbox);
  if(posePersonExtentBox && Date.now()-posePersonExtentAt<=STALE_TTL_MS) persons.push(posePersonExtentBox);
  if(poseFresh()) for(const p of backendPoses){ const e=_poseKpExtent(p); if(e) persons.push(e); }
  if(!persons.length) return list;                       // 사람 신호 없음 → 판단 불가, 그대로(오탐 억제 안 함)
  const pad=b=>[b[0]-b[2]*0.2, b[1]-b[3]*0.35, b[2]*1.4, b[3]*1.45];   // 머리 위(안전모)·주변 여유
  return list.filter(o=>{
    if(!o || !(isPpeClass(o.class)||isViolation(o.class))) return true;      // PPE/위반만 대상
    return persons.some(pb=> iou(pad(pb),o.bbox)>0 || _ios(o.bbox,pad(pb))>0.25);   // 어떤 사람과도 안 겹치면 오탐 → 제거
  });
}

// ── 2단계: 사람 박스를 매 프레임 MediaPipe pose extent로 따라가게 ─────────────
// detection(YOLO/COCO)은 "이게 사람인가/클래스/ID"만 제공하고, 위치는 매 렌더 프레임
// 신선한 MediaPipe 랜드마크의 bounding extent로 다시 계산 → 추가 지연 0.
let posePersonExtentBox=null;   // 마지막 유효 pose extent [x,y,w,h] (소스 픽셀). 미검출 프레임엔 값 유지(hold)
let posePersonExtentAt=0;       // 그 extent 관측 시각(Date.now)
const _POSE_EXTENT_IDX=[0,11,12,13,14,15,16,23,24,25,26,27,28];  // 코+어깨+팔+엉덩이+무릎+발목
function posePersonExtent(lm,VW,VH){
  if(!lm || !lm.length) return null;
  let minX=1e9,minY=1e9,maxX=-1e9,maxY=-1e9,n=0;
  for(const i of _POSE_EXTENT_IDX){
    const p=lm[i]; if(!p || (p.visibility!=null && p.visibility<0.3)) continue;
    const x=p.x*VW, y=p.y*VH;
    if(x<minX)minX=x; if(x>maxX)maxX=x; if(y<minY)minY=y; if(y>maxY)maxY=y; n++;
  }
  if(n<4) return null;                                   // 랜드마크 부족 → 무효(폴백)
  const w=maxX-minX, h=maxY-minY;
  if(w<10 || h<10) return null;
  const padX=Math.max(12,w*0.12), padTop=Math.max(20,h*0.22), padBot=Math.max(8,h*0.06);  // 머리 위 여유 크게
  const x0=Math.max(0,minX-padX), y0=Math.max(0,minY-padTop);
  const x1=Math.min(VW,maxX+padX), y1=Math.min(VH,maxY+padBot);
  return [x0,y0,x1-x0,y1-y0];
}
// 소유권 부여 + 위치 교체: pose extent에 가장 가까운 person detection을 찾아, 그 박스의 위치만
// 신선한 pose extent로 바꾸고 seenAt을 갱신(→ 페이드/꼬리억제 대상에서 제외). 클래스/ID/score는 detection 유지.
function _applyPoseFollow(objs){
  if(!posePersonExtentBox || !posePersonExtentAt) return objs;
  if(Date.now()-posePersonExtentAt > STALE_TTL_MS) return objs;   // pose 끊긴 지 오래 → 폴백(detection 박스+페이드)
  const persons=objs.filter(o=>o.class==='person');
  if(!persons.length) return objs;                                // 매칭할 detection 없음 → 가짜 박스 만들지 않음(안전)
  const pcx=posePersonExtentBox[0]+posePersonExtentBox[2]/2;
  const pcy=posePersonExtentBox[1]+posePersonExtentBox[3]/2;
  let owner=null,bd=1e9;
  for(const o of persons){
    const cx=o.bbox[0]+o.bbox[2]/2, cy=o.bbox[1]+o.bbox[3]/2;
    const diag=Math.hypot(o.bbox[2]||0,o.bbox[3]||0);
    const d=Math.hypot(cx-pcx,cy-pcy);
    if(d<bd && d < Math.max(250, diag*1.5)){ bd=d; owner=o; }     // 빠른 이동으로 detection이 뒤처져도 매칭 유지
  }
  if(!owner) return objs;
  return objs.map(o=> o===owner
    ? {...o, bbox:posePersonExtentBox.slice(), seenAt:posePersonExtentAt, gone:0, _poseFollow:true}  // pose가 매 프레임 위치 확정 = 살아있음
    : o);
}

// 외곽선(인스턴스 세그멘테이션) 모드 — 박스 대신 객체 윤곽 폴리곤 표시
let segBusy=false, segAt=0, lastSegAt=0;
let segPolys=[];                      // [{class,score,points:[[x,y],...](소스 좌표)}]
let segLoopTimer=null;
const SEG_INTERVAL=350;               // 세그 추론 ~20ms로 가벼워 부드럽게(≈3fps) 갱신
const SEG_TTL=1600;
function segModeOn(){ return !!document.getElementById('togSegment')?.checked; }
function segFresh(){ return segPolys.length>0 && (Date.now()-segAt<=SEG_TTL); }

// 안전 사람=백엔드 포즈(스켈레톤). 세그보다 가벼움. 좌표는 소스(VW×VH).
let backendPoses=[], poseAt=0;
let prevBackendPoses=[], prevPoseAt=0;   // 직전 프레임 — 속도 기반 예측(지연 보정)용
function poseFresh(){ return backendPoses.length>0 && (Date.now()-poseAt<=SEG_TTL); }
// 몸통/팔다리만 연결(얼굴 연결선 제거 → 삼각형 방지). 머리는 '목 중점→코' 한 선 + 점으로 표시.
const COCO_SKELETON=[[5,7],[7,9],[6,8],[8,10],[5,6],[5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16]];
// 관절별 고유 색(COCO-17): 코·눈·귀(머리)→어깨·팔꿈치·손목(팔)→엉덩이·무릎·발목(다리) 순 색 변화
const KP_COLORS=['#f43f5e','#fb7185','#f97316','#f59e0b','#eab308','#84cc16','#22c55e','#10b981','#14b8a6','#06b6d4','#0ea5e9','#3b82f6','#8a6817','#8b5cf6','#a855f7','#d946ef','#ec4899'];
const COCO_KP_NAMES=['코','왼눈','오른눈','왼귀','오른귀','왼어깨','오른어깨','왼팔꿈치','오른팔꿈치','왼손목','오른손목','왼엉덩이','오른엉덩이','왼무릎','오른무릎','왼발목','오른발목'];

const IMPORTANT_SMALL_OBJECTS=new Set([
  'cell phone','remote','mouse','keyboard','cup','bottle','wine glass','fork','knife','spoon',
  'book','scissors','sports ball','tennis racket','baseball bat','cigarette','glasses','snack'
]);
const CLASS_MIN_SCORE={
  person:0.24,'cell phone':0.24,remote:0.24,mouse:0.24,keyboard:0.24,cup:0.23,bottle:0.23,
  'wine glass':0.23,book:0.24,knife:0.25,scissors:0.25,'sports ball':0.24,
  'tennis racket':0.24,'baseball bat':0.24,laptop:0.28,chair:0.30,
  cigarette:0.20,glasses:0.20,snack:0.20
};

// ── 표시 필터(config) — 산업현장 무관/오탐 COCO 박스를 '화면에서만' 숨김. 탐지 엔진·인원/PPE/통계 로직 불변(규칙6). ──
// 조정: hide 에 클래스 추가/삭제, safetyOnly=false 로 전체 표시, on=false 로 필터 끄기.
const DISPLAY_FILTER={
  on:true,
  safetyOnly:true,   // 안전 테마에서만 '의미있는 것'만 표시(office/sports는 사물 유지)
  // 안전 관련 추가 표시(현장 교통 위험 등) — _isSafetyCritical 밖이지만 의미있어 유지(차량 등)
  show:new Set(['car','truck','bus','motorcycle','bicycle','train','forklift','boat']),
  hide:new Set(['suitcase','handbag','backpack','tie','umbrella','frisbee','kite','teddy bear','vase','potted plant']),
};
function shouldDrawClass(c){
  if(!DISPLAY_FILTER.on) return true;
  c=String(c||'').toLowerCase();
  if(c==='person') return true;                               // 사람은 항상 표시
  if(DISPLAY_FILTER.hide.has(c)) return false;                // 명시 숨김(산업현장 무의미)
  if(DISPLAY_FILTER.show.has(c)) return true;                 // 차량 등 현장 위험은 유지(저하 방지)
  // safetyOnly 는 안전 테마에서만 적용 → office/sports 는 기존대로 사물 표시(저하 0)
  if(DISPLAY_FILTER.safetyOnly && (typeof activeServiceMode==='undefined' || activeServiceMode==='safety'))
    return _isSafetyCritical(c) || isViolation(c);
  return true;
}

// bbox 좌표 스케일 변환 (영상→캔버스)
function scaleBox(b, sx, sy){
  if(!b) return null;
  return{minX:b.minX*sx,maxX:b.maxX*sx,minY:b.minY*sy,maxY:b.maxY*sy};
}
function scaleBbox(arr, sx, sy){
  // [x,y,w,h] 변환
  return [arr[0]*sx, arr[1]*sy, arr[2]*sx, arr[3]*sy];
}
// conf 표기: 1% 미만은 반올림 '0%'가 오해를 부르므로(검출인데 미검출처럼 보임) 소수점으로 표기.
// 예: 0.002→'0.2%'. 1% 이상은 정수(%). (2026-07-11 개선: forklift 0.2% 오탐이 '0%'로 보이던 문제)
function fmtConf(s){ const p=(s||0)*100; return (p>0&&p<1?p.toFixed(1):Math.round(p))+'%'; }

// 포즈 스무딩
const SMOOTH_N=8, ACTION_N=7;
const poseHistory=[], actionHistory=[];
let prevHipY=null, hipVelocity=0, fallConfirm=0;
const FALL_CONFIRM=6;

document.getElementById('confThreshold').addEventListener('input',function(){
  document.getElementById('confVal').textContent=this.value+'%';
});

// ═══════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════
function loadStep(i,done){
  const el=document.getElementById('ls'+i);
  if(done){el.className='load-step done';el.textContent='✅ '+el.textContent.replace(/^[⏳✅] /,'');}
  else{el.className='load-step active';}
}

async function initModels(){
  try{
    setTimeout(()=>{document.getElementById('loadingOverlay').style.display='none';if(!cameraOn)setCameraUI(false);},1400);
    loadStep(0,false);
    // VIGENT_LOCAL=true 이면 로컬 번들(/static/vendor)에서 로드(CDN 없이·폐쇄망), 아니면 CDN.
    const _mpBase = window.VIGENT_LOCAL ? '/static/vendor/mediapipe/' : 'https://cdn.jsdelivr.net/npm/@mediapipe/holistic@0.5.1675471629/';
    holistic=new Holistic({locateFile:f=>_mpBase+f});
    // 현장 끊김 대응: 안전 테마는 얼굴메시가 불필요하므로 Holistic을 경량화(복잡도 0·얼굴정밀 off)
    // → 렌더 펌프(onHolisticResults)가 가벼워져 FPS↑, 카메라 부드러워짐. fitness/office는 기존(정밀) 유지.
    const _liteSafety=(typeof activeServiceMode!=='undefined'&&activeServiceMode==='safety')
      ||(typeof window!=='undefined'&&_normServiceMode(window.AX_LOCK_THEME)==='safety');
    holistic.setOptions({modelComplexity:_liteSafety?0:1,smoothLandmarks:true,enableSegmentation:false,
      refineFaceLandmarks:_liteSafety?false:true,minDetectionConfidence:0.5,minTrackingConfidence:0.5});
    holistic.onResults(onHolisticResults);
    loadStep(0,true);

    loadStep(1,false);
    cocoModel=await (window.VIGENT_LOCAL
      ? cocoSsd.load({modelUrl:'/static/vendor/tf/cocossd/model.json'})
      : cocoSsd.load({base:'mobilenet_v2'}));
    loadStep(1,true);

    loadStep(2,false);
    mobileNetModel=await (window.VIGENT_LOCAL
      ? mobilenet.load({version:2,alpha:1.0,modelUrl:'/static/vendor/tf/mobilenet/model.json'})
      : mobilenet.load({version:2,alpha:1.0}));
    loadStep(2,true);
    {const _mn=document.getElementById('mnStatus'); if(_mn)_mn.textContent='✅ 준비 완료';}

    loadStep(3,false);
    await startWebcam();
    loadStep(3,true);
    document.getElementById('loadingOverlay').style.display='none';
  }catch(err){
    document.getElementById('ls0').textContent='❌ 오류: '+err.message;
    setTimeout(()=>{document.getElementById('loadingOverlay').style.display='none';if(!cameraOn)setCameraUI(false);},900);
  }
}

// ═══════════════════════════════════════════════════
//  ① 멀티스케일 COCO-SSD + NMS
// ═══════════════════════════════════════════════════
function iou(a,b){
  const xi=Math.max(a[0],b[0]),yi=Math.max(a[1],b[1]);
  const xo=Math.min(a[0]+a[2],b[0]+b[2]),yo=Math.min(a[1]+a[3],b[1]+b[3]);
  const inter=Math.max(0,xo-xi)*Math.max(0,yo-yi);
  return inter/(a[2]*a[3]+b[2]*b[3]-inter||1);
}

function applyNMS(preds, iouThr=0.45){
  if(!preds.length) return [];
  const sorted=[...preds].sort((a,b)=>b.score-a.score);
  const keep=[], used=new Set();
  for(let i=0;i<sorted.length;i++){
    if(used.has(i)) continue;
    keep.push(sorted[i]);
    for(let j=i+1;j<sorted.length;j++){
      if(used.has(j)) continue;
      if(sorted[i].class===sorted[j].class && iou(sorted[i].bbox,sorted[j].bbox)>iouThr) used.add(j);
    }
  }
  return keep;
}

function personOverlapRatio(a,b){
  const ax1=a.bbox[0], ay1=a.bbox[1], ax2=ax1+a.bbox[2], ay2=ay1+a.bbox[3];
  const bx1=b.bbox[0], by1=b.bbox[1], bx2=bx1+b.bbox[2], by2=by1+b.bbox[3];
  const ix=Math.max(0,Math.min(ax2,bx2)-Math.max(ax1,bx1));
  const iy=Math.max(0,Math.min(ay2,by2)-Math.max(ay1,by1));
  const inter=ix*iy;
  const minArea=Math.max(1,Math.min(a.bbox[2]*a.bbox[3],b.bbox[2]*b.bbox[3]));
  return inter/minArea;
}

function uniquePersonDetections(preds){
  const people=preds.filter(p=>p.class==='person').sort((a,b)=>b.score-a.score);
  const keep=[];
  for(const p of people){
    const duplicate=keep.some(k=>iou(k.bbox,p.bbox)>0.22||personOverlapRatio(k,p)>0.55);
    if(!duplicate) keep.push(p);
  }
  return keep;
}

function clampBbox(p,W,H){
  const x=Math.max(0,Math.min(W,p.bbox[0]));
  const y=Math.max(0,Math.min(H,p.bbox[1]));
  const w=Math.max(1,Math.min(W-x,p.bbox[2]));
  const h=Math.max(1,Math.min(H-y,p.bbox[3]));
  return {...p,bbox:[x,y,w,h]};
}

function filterPredictions(preds,W,H,baseThr,opts={}){
  const frameArea=Math.max(1,W*H);
  return preds.map(p=>clampBbox(p,W,H)).filter(p=>{
    const area=(p.bbox[2]*p.bbox[3])/frameArea;
    const minScore=opts.handCrop
      ? Math.min(CLASS_MIN_SCORE[p.class]||baseThr, IMPORTANT_SMALL_OBJECTS.has(p.class)?0.18:0.22)
      : (CLASS_MIN_SCORE[p.class]||baseThr);
    if(p.score<minScore) return false;
    if(p.class==='person') return area>0.004;
    if(IMPORTANT_SMALL_OBJECTS.has(p.class)) return area>0.00018;
    return area>0.00045;
  });
}

async function multiScaleDetect(source){
  const thr=parseInt(document.getElementById('confThreshold').value)/100;
  const maxDet=20;

  // 스케일1: 원본
  const W=source.videoWidth||source.naturalWidth||canvas.width;
  const H=source.videoHeight||source.naturalHeight||canvas.height;
  const p1=filterPredictions(await cocoModel.detect(source,maxDet,Math.max(0.2,thr-0.04)),W,H,thr);

  // 안전: 백엔드(yolov8s)가 주 탐지 → 브라우저는 단일패스만(크롭 2회 생략, 메인스레드 부하↓, 정확도는 백엔드가 담당)
  // 백엔드가 탐지를 제공하면(전 테마) 브라우저는 단일패스만 → 메인스레드 부하↓(정확도는 백엔드가 담당)
  if(backendActive() || !document.getElementById('togMultiScale').checked) return applyNMS(p1);

  // 스케일2: 중앙 2배 확대 (작은 사물 감지용)
  const offCanvas=document.createElement('canvas');
  offCanvas.width=416; offCanvas.height=416;
  const offCtx=offCanvas.getContext('2d');
  // 중앙 50% 영역을 416x416으로 확대
  offCtx.drawImage(source, W*0.25, H*0.25, W*0.5, H*0.5, 0, 0, 416, 416);
  const p2raw=await cocoModel.detect(offCanvas,maxDet,Math.max(0.18,thr-0.08));
  // 좌표를 원본 좌표계로 변환
  const p2=filterPredictions(p2raw.map(p=>({...p,bbox:[W*0.25+p.bbox[0]*(W*0.5/416), H*0.25+p.bbox[1]*(H*0.5/416), p.bbox[2]*(W*0.5/416), p.bbox[3]*(H*0.5/416)]})),W,H,thr);

  // 스케일3: 상단 확대 (손에 든 사물 — 카메라 앞 작은 사물)
  const offCanvas3=document.createElement('canvas');
  offCanvas3.width=416; offCanvas3.height=416;
  const offCtx3=offCanvas3.getContext('2d');
  offCtx3.drawImage(source, W*0.1, H*0.05, W*0.8, H*0.6, 0, 0, 416, 416);
  const p3raw=await cocoModel.detect(offCanvas3,maxDet,Math.max(0.18,thr-0.08));
  const p3=filterPredictions(p3raw.map(p=>({...p,bbox:[W*0.1+p.bbox[0]*(W*0.8/416), H*0.05+p.bbox[1]*(H*0.6/416), p.bbox[2]*(W*0.8/416), p.bbox[3]*(H*0.6/416)]})),W,H,thr);

  // 크롭(p2·p3)은 작은 사물 감지용. 사람이 크롭을 채우면 원본 좌표로 환산 시 박스가
  // 과대(폭의 50~80%)해져, NMS에서 원본(p1)의 정확한 사람 박스를 이겨 '사람 박스가
  // 너무 크게' 보인다. → 크롭 사람 중 p1이 이미 잡은 사람과 겹치는 것은 버리고 p1의
  // 정확한 박스를 우선한다. (p1이 놓친 멀리/작은 사람만 보충 → 인식률은 유지)
  const p1Persons=p1.filter(o=>o.class==='person');
  const cropExtra=[...p2, ...p3].filter(o=>{
    if(o.class!=='person') return true;                          // 사물은 그대로 보충
    return !p1Persons.some(pp=> iou(pp.bbox,o.bbox)>0.3 || personOverlapRatio(pp,o)>0.5);
  });
  return applyNMS([...p1, ...cropExtra]);
}

// ═══════════════════════════════════════════════════
//  ② 객체 ID 추적 (Centroid Tracker)
// ═══════════════════════════════════════════════════
function centroid(bbox){return{x:bbox[0]+bbox[2]/2, y:bbox[1]+bbox[3]/2};}

function updateTracker(predictions){
  const MAX_DIST=80, MAX_GONE=10;
  const now=Date.now();   // 관측 시각 — 매칭된 트랙은 갱신, 미매칭(gone)은 옛 값 유지 → 잔상 페이드
  // 현재 감지 결과의 centroid
  const currCentroids=predictions.map(p=>centroid(p.bbox));

  if(objTracker.tracked.length===0){
    objTracker.tracked=predictions.map((p,i)=>({...p,id:objTracker.nextId++,gone:0,hits:1,avgScore:p.score,seenAt:now}));
    return stableTrackedObjects(objTracker.tracked);
  }

  const matched=new Set(), usedTrk=new Set();
  const result=[];

  // 기존 트랙과 매칭
  for(let i=0;i<objTracker.tracked.length;i++){
    const t=objTracker.tracked[i];
    const tc=centroid(t.bbox);
    let bestDist=Infinity, bestJ=-1;
    for(let j=0;j<currCentroids.length;j++){
      if(matched.has(j)) continue;
      const d=Math.hypot(tc.x-currCentroids[j].x, tc.y-currCentroids[j].y);
      if(d<bestDist && d<MAX_DIST && predictions[j].class===t.class){bestDist=d;bestJ=j;}
    }
    if(bestJ>=0){
      matched.add(bestJ); usedTrk.add(i);
      const p=predictions[bestJ];
      const alpha=document.getElementById('togPrecision').checked?0.62:1;
      const smoothBox=t.bbox&&p.bbox?t.bbox.map((v,idx)=>v*(1-alpha)+p.bbox[idx]*alpha):p.bbox;
      result.push({
        ...p,
        bbox:smoothBox,
        id:t.id,
        gone:0,
        hits:(t.hits||1)+1,
        avgScore:((t.avgScore||p.score)*0.7+p.score*0.3),
        seenAt:now                                  // 매칭됨 = 방금 관측 → 갱신
      });
    } else {
      if(t.gone<MAX_GONE) result.push({...t,gone:t.gone+1});   // 미매칭 = 옛 seenAt 유지 → 페이드
    }
  }
  // 새로운 객체
  for(let j=0;j<predictions.length;j++){
    if(!matched.has(j)) result.push({...predictions[j],id:objTracker.nextId++,gone:0,hits:1,avgScore:predictions[j].score,seenAt:now});
  }
  objTracker.tracked=result;
  return stableTrackedObjects(result);
}

// 안전 특화 안정화: 안전 위험(사람·보호구·위험물)은 관대하게(놓치지 않음),
// 일반 사물은 엄격하게(N프레임 확정 + 높은 임계 → 깜빡임/불안정 제거).
// 임계값을 일괄로 올리면 진짜 위험을 놓치므로, '표시 임계'와 '안전 임계'를 분리한다.
function _isSafetyCritical(c){
  c = String(c||'').toLowerCase();
  return c==='person' || isPpeClass(c) || DANGER_OBJ.includes(c)
      || c==='fire' || c==='smoke' || c==='cigarette' || c==='forklift';
}
function stableTrackedObjects(tracked){
  if(!document.getElementById('togPrecision')?.checked) return tracked;
  const safety = (typeof activeServiceMode!=='undefined' && activeServiceMode==='safety');
  return tracked.filter(o=>{
    const crit = safety && _isSafetyCritical(o.class);
    if(o.gone>0){                                  // 사라진 직후 잔상(히스테리시스)
      return crit ? (o.hits>=2 && o.gone<=4)       // 안전: 조금 더 오래 유지
                  : (o.hits>=3 && o.gone<=2);       // 일반: 빨리 정리(깜빡임↓)
    }
    if(crit) return (o.hits||1)>=2 || (o.avgScore||o.score||0)>=0.45;  // 안전 위험: 2프레임 확정 or 평균신뢰(단발 헛것 제거, 미탐은 2프레임이면 즉시 통과)
    return (o.hits||1)>=3 || (o.avgScore||o.score||0)>=0.62;           // 일반 사물: 엄격(3프레임/고신뢰)
  });
}

// ═══════════════════════════════════════════════════
//  ③ 손에 든 사물 감지 (근접도 교차 검사)
// ═══════════════════════════════════════════════════
function getHandBBox(handLM, W, H, margin=90){
  if(!handLM||handLM.length===0) return null;
  const xs=handLM.map(p=>p.x*W), ys=handLM.map(p=>p.y*H);
  // 손목→중지 끝 방향으로 grip 영역 확장
  const wrist=handLM[0], tip=handLM[12];
  const dirX=(tip.x-wrist.x)*W, dirY=(tip.y-wrist.y)*H;
  const extX=dirX*0.7, extY=dirY*0.7;
  return{
    minX:Math.max(0,Math.min(...xs,wrist.x*W+extX)-margin),
    maxX:Math.min(W,Math.max(...xs,wrist.x*W+extX)+margin),
    minY:Math.max(0,Math.min(...ys,wrist.y*H+extY)-margin),
    maxY:Math.min(H,Math.max(...ys,wrist.y*H+extY)+margin),
  };
}

// 손 크롭 영역에 저임계값 COCO-SSD 재검색
async function detectNearHand(source, handBBox){
  if(!cocoModel||!handBBox) return [];
  const bw=handBBox.maxX-handBBox.minX, bh=handBBox.maxY-handBBox.minY;
  if(bw<30||bh<30) return [];
  const offC=document.createElement('canvas');
  offC.width=320; offC.height=320;
  offC.getContext('2d').drawImage(source,handBBox.minX,handBBox.minY,bw,bh,0,0,320,320);
  try{
    const raw=await cocoModel.detect(offC,10,0.18);
    return raw.filter(p=>p.class!=='person').map(p=>({
      ...p,
      score:p.score,
      bbox:[handBBox.minX+p.bbox[0]*(bw/320),handBBox.minY+p.bbox[1]*(bh/320),p.bbox[2]*(bw/320),p.bbox[3]*(bh/320)]
    }));
  }catch(e){return [];}
}

// 전용 사람 수 감지 (낮은 임계값)
let detectedPersonCount=0;
const personCountHistory=[];
function updateStablePersonCount(rawCount, poseDetected=false){
  let count=Math.max(rawCount||0,poseDetected?1:0);
  if(activeServiceMode!=='safety'&&poseDetected&&count>1) count=1;
  personCountHistory.push(count);
  if(personCountHistory.length>8) personCountHistory.shift();
  const freq={};
  personCountHistory.forEach(v=>{freq[v]=(freq[v]||0)+1;});
  let best=count, bestN=-1;
  Object.entries(freq).forEach(([k,v])=>{
    const n=parseInt(k,10);
    if(v>bestN||(v===bestN&&n>best)){best=n;bestN=v;}
  });
  detectedPersonCount=best;
  return best;
}
async function runPersonCount(source){
  if(!cocoModel) return;
  try{
    const preds=await cocoModel.detect(source,20,0.25);
    updateStablePersonCount(preds.filter(p=>p.class==='person').length,!!sm);
  }catch(e){}
}

function findHeldObjects(handBBox, predictions, W, H){
  if(!handBBox) return [];
  const hx=(handBBox.minX+handBBox.maxX)/2, hy=(handBBox.minY+handBBox.maxY)/2;
  const hw=handBBox.maxX-handBBox.minX, hh=handBBox.maxY-handBBox.minY;
  return predictions.filter(p=>{
    if(p.class==='person') return false;
    const cx=p.bbox[0]+p.bbox[2]/2, cy=p.bbox[1]+p.bbox[3]/2;
    // 중심점이 손 영역 안에 있거나, bbox가 손 영역과 겹치는 경우
    const centerIn=cx>=handBBox.minX&&cx<=handBBox.maxX&&cy>=handBBox.minY&&cy<=handBBox.maxY;
    const overlapX=Math.min(p.bbox[0]+p.bbox[2],handBBox.maxX)-Math.max(p.bbox[0],handBBox.minX);
    const overlapY=Math.min(p.bbox[1]+p.bbox[3],handBBox.maxY)-Math.max(p.bbox[1],handBBox.minY);
    const overlap=overlapX>0&&overlapY>0?(overlapX*overlapY)/(p.bbox[2]*p.bbox[3]):0;
    return centerIn||(overlap>0.25);
  }).map(p=>{
    const cx=p.bbox[0]+p.bbox[2]/2, cy=p.bbox[1]+p.bbox[3]/2;
    const distNorm=Math.hypot((cx-hx)/(hw||1),(cy-hy)/(hh||1));
    const overlapX=Math.min(p.bbox[0]+p.bbox[2],handBBox.maxX)-Math.max(p.bbox[0],handBBox.minX);
    const overlapY=Math.min(p.bbox[1]+p.bbox[3],handBBox.maxY)-Math.max(p.bbox[1],handBBox.minY);
    const overlap=overlapX>0&&overlapY>0?(overlapX*overlapY)/(p.bbox[2]*p.bbox[3]):0;
    const attachScore=(p.score||0)*0.55+Math.min(1,overlap)*0.3+Math.max(0,1-distNorm)*0.15;
    return {...p,attachScore,score:Math.max(p.score||0,attachScore*0.75)};
  }).sort((a,b)=>(b.attachScore||0)-(a.attachScore||0)).slice(0,3);
}

function stabilizeHeldObjects(current, side){
  const history=side==='left'?leftHeldHistory:rightHeldHistory;
  history.push(current);
  if(history.length>4) history.shift();
  if(!document.getElementById('togPrecision')?.checked) return current;
  const flat=history.flat();
  return current.filter(o=>{
    const seen=flat.filter(h=>h.class===o.class&&iou(h.bbox,o.bbox)>0.25).length;
    return seen>=2||o.score>=0.44||(o.attachScore||0)>=0.42;
  });
}

// ④ MobileNet 손 영역 크롭 분류
const MN_KO={
  // 📱 전자기기
  'cellular telephone':'📱 휴대폰','cell phone':'📱 휴대폰','mobile phone':'📱 휴대폰',
  'smartphone':'📱 스마트폰','iphone':'📱 아이폰','android phone':'📱 스마트폰',
  'remote control':'📡 리모컨','remote':'📡 리모컨',
  'mouse':'🖱 마우스','computer mouse':'🖱 마우스',
  'keyboard':'⌨️ 키보드','space bar':'⌨️ 키보드',
  'laptop':'💻 노트북','notebook computer':'💻 노트북','laptop computer':'💻 노트북',
  'tablet':'📱 태블릿','ipad':'📱 아이패드',
  'headphone':'🎧 헤드폰','earphone':'🎧 이어폰','airpod':'🎧 에어팟',
  'camera':'📷 카메라','digital camera':'📷 카메라','nikon':'📷 카메라','canon':'📷 카메라',
  'calculator':'🔢 계산기',
  // 🚬 흡연/작은 소지품
  'cigarette':'🚬 담배','cigar':'🚬 담배','cigar, stogie, cheroot':'🚬 담배',
  'tobacco':'🚬 담배','matchstick':'🚬 성냥','lighter':'🔥 라이터',
  // ☕ 음료/컵
  'cup':'☕ 컵','coffee mug':'☕ 머그컵','mug':'☕ 머그컵','teapot':'🍵 찻주전자',
  'water bottle':'🍶 물병','bottle':'🍶 병','beer bottle':'🍺 맥주병','wine bottle':'🍷 와인병',
  'beer glass':'🍺 맥주잔','wine glass':'🍷 와인잔','cocktail':'🍸 칵테일',
  'espresso':'☕ 에스프레소','coffee':'☕ 커피','tea':'🍵 차',
  'can':'🥫 캔','pop bottle':'🥤 음료수병','soda':'🥤 탄산음료',
  // 🍎 과일
  'banana':'🍌 바나나','apple':'🍎 사과','orange':'🍊 오렌지',
  'watermelon':'🍉 수박','strawberry':'🍓 딸기','grape':'🍇 포도',
  'pineapple':'🍍 파인애플','mango':'🥭 망고','peach':'🍑 복숭아',
  'pear':'🍐 배','lemon':'🍋 레몬','lime':'🍋 라임','kiwi':'🥝 키위',
  'coconut':'🥥 코코넛','cherry':'🍒 체리','melon':'🍈 멜론',
  'fig':'🍈 무화과','pomegranate':'🍎 석류','avocado':'🥑 아보카도',
  'blueberry':'🫐 블루베리',
  // 🥦 채소
  'broccoli':'🥦 브로콜리','carrot':'🥕 당근','corn':'🌽 옥수수',
  'cucumber':'🥒 오이','pepper':'🌶 파프리카','bell pepper':'🫑 피망',
  'potato':'🥔 감자','sweet potato':'🍠 고구마','tomato':'🍅 토마토',
  'eggplant':'🍆 가지','zucchini':'🥒 주키니','onion':'🧅 양파',
  'garlic':'🧄 마늘','mushroom':'🍄 버섯','lettuce':'🥬 상추',
  'cabbage':'🥬 양배추','spinach':'🥬 시금치',
  // 🍕 음식
  'pizza':'🍕 피자','sandwich':'🥪 샌드위치','hamburger':'🍔 햄버거','burger':'🍔 버거',
  'hot dog':'🌭 핫도그','taco':'🌮 타코','burrito':'🌯 부리토',
  'sushi':'🍣 스시','dumpling':'🥟 만두','noodle':'🍜 국수','ramen':'🍜 라면',
  'bread':'🍞 빵','bagel':'🥯 베이글','croissant':'🥐 크루아상',
  'cake':'🎂 케이크','cookie':'🍪 쿠키','chocolate':'🍫 초콜릿','ice cream':'🍦 아이스크림',
  'waffle':'🧇 와플','pancake':'🥞 팬케이크','egg':'🥚 달걀','fried egg':'🍳 달걀',
  'cheese':'🧀 치즈','bacon':'🥓 베이컨','steak':'🥩 스테이크',
  'snack':'🍪 과자','cracker':'🍘 크래커','pretzel':'🥨 프레첼','potato chip':'🍟 감자칩',
  'corn chip':'🌽 과자','packet':'🍪 포장 과자','plastic bag':'🍪 과자 봉지',
  // 📖 문구/책
  'book':'📖 책','notebook':'📓 노트','binder':'📁 바인더','magazine':'📰 잡지',
  'newspaper':'📰 신문','envelope':'✉️ 편지',
  'pen':'🖊 펜','pencil':'✏️ 연필','ballpoint':'🖊 볼펜','marker':'🖊 마커',
  'ruler':'📏 자','scissors':'✂️ 가위','stapler':'🗂 스테이플러',
  // 🔧 도구
  'knife':'🔪 칼','hammer':'🔨 망치','screwdriver':'🪛 드라이버','wrench':'🔧 렌치',
  'flashlight':'🔦 손전등','torch':'🔦 손전등','candle':'🕯 양초',
  'umbrella':'☂️ 우산','key':'🗝 열쇠','lock':'🔒 자물쇠',
  // 👜 패션/소품
  'wallet':'👛 지갑','purse':'👜 핸드백','backpack':'🎒 배낭','handbag':'👜 가방',
  'sunglass':'🕶 선글라스','sunglasses':'🕶 선글라스','glasses':'👓 안경','eyeglasses':'👓 안경','spectacles':'👓 안경','watch':'⌚ 시계',
  'hat':'🎩 모자','cap':'🧢 모자','helmet':'⛑ 헬멧',
  'shoe':'👟 신발','sneaker':'👟 운동화','boot':'👢 부츠',
  // 🏀 스포츠
  'tennis ball':'🎾 테니스공','golf ball':'⛳ 골프공','basketball':'🏀 농구공',
  'football':'🏈 풋볼','soccer ball':'⚽ 축구공','baseball':'⚾ 야구공',
  'tennis racket':'🎾 테니스라켓','baseball bat':'🏏 야구방망이',
  'dumbbell':'🏋 아령','barbell':'🏋 바벨',
  // 🌿 기타
  'flower':'🌸 꽃','rose':'🌹 장미','tulip':'🌷 튤립','sunflower':'🌻 해바라기',
  'plant':'🪴 식물','cactus':'🌵 선인장','leaf':'🍃 잎사귀',
  'toy':'🧸 장난감','teddy bear':'🧸 테디베어','doll':'🪆 인형',
};

// 전체 화면 MobileNet 분류 결과
let fullFrameResults=[];

function translateMN(className){
  const lower=className.toLowerCase();
  // 정확 매칭 우선
  for(const[k,v]of Object.entries(MN_KO)){
    if(lower===k) return v;
  }
  // 부분 매칭
  for(const[k,v]of Object.entries(MN_KO)){
    if(lower.includes(k)) return v;
  }
  // 번역 안 된 경우 영어 그대로 반환 (첫글자 대문자)
  return className.split(',')[0].trim();
}

function normalizeFineObject(className){
  const lower=(className||'').toLowerCase();
  if(lower.match(/cigarette|cigar|stogie|cheroot|tobacco|matchstick|lighter/)){
    return {class:'cigarette', label:'🚬 담배/흡연물'};
  }
  if(lower.match(/sunglass|sunglasses|eyeglass|glasses|spectacle|goggles|lens/)){
    return {class:'glasses', label:'👓 안경/선글라스'};
  }
  if(lower.match(/cookie|cracker|pretzel|chocolate|wafer|potato chip|corn chip|snack|packet|plastic bag|popcorn|candy|bar/)){
    return {class:'snack', label:'🍪 과자/간식'};
  }
  return null;
}

function ppeKeywordScore(preds, type){
  const positive=type==='helmet'
    ? /helmet|hard hat|hardhat|crash helmet|construction helmet|protective helmet|safety helmet/
    : /safety vest|high visibility|hi-vis|reflective vest|orange safety|yellow safety|visibility vest/;
  const negative=type==='helmet'
    ? /cap|baseball cap|hat|cowboy|sombrero|bonnet|hair|wig/
    : /shirt|t-shirt|sweatshirt|jacket|coat|suit|apron|cardigan|cloak/;
  let best=null;
  for(const p of preds||[]){
    const name=(p.className||'').toLowerCase();
    const prob=p.probability||0;
    if(positive.test(name) && (!best||prob>best.confidence)){
      best={state:'worn',label:type==='helmet'?'착용 추정':'착용 추정',confidence:prob,raw:p.className};
    }
    if(!best&&negative.test(name)&&prob>0.35){
      best={state:'missing',label:'미착용 의심',confidence:prob,raw:p.className};
    }
  }
  if((preds||[]).length){
    const top=preds[0]||{};
    return {state:'missing',label:'미착용 의심',confidence:Math.max(0.45,top.probability||0),raw:top.className||'보호구 단서 없음'};
  }
  return {state:'unknown',label:'확인 중',confidence:0,raw:''};
}

function poseCropBox(lm, part, W, H){
  if(!lm) return null;
  const nose=lm[0], lEar=lm[7], rEar=lm[8], lS=lm[11], rS=lm[12], lH=lm[23], rH=lm[24];
  if(part==='head'){
    const pts=[nose,lEar,rEar,lS,rS].filter(Boolean);
    if(pts.length<3) return null;
    const xs=pts.map(p=>p.x*W), ys=pts.map(p=>p.y*H);
    const minX=Math.min(...xs), maxX=Math.max(...xs), minY=Math.min(...ys), maxY=Math.max(...ys);
    const pad=Math.max(28,(maxX-minX)*0.65);
    return clampRect(minX-pad,minY-pad*1.25,(maxX-minX)+pad*2,(maxY-minY)+pad*1.9,W,H);
  }
  const pts=[lS,rS,lH,rH].filter(Boolean);
  if(pts.length<3) return null;
  const xs=pts.map(p=>p.x*W), ys=pts.map(p=>p.y*H);
  const minX=Math.min(...xs), maxX=Math.max(...xs), minY=Math.min(...ys), maxY=Math.max(...ys);
  const padX=Math.max(32,(maxX-minX)*0.35), padY=Math.max(28,(maxY-minY)*0.18);
  return clampRect(minX-padX,minY-padY,(maxX-minX)+padX*2,(maxY-minY)+padY*2,W,H);
}

function clampRect(x,y,w,h,W,H){
  const nx=Math.max(0,Math.min(W-1,x));
  const ny=Math.max(0,Math.min(H-1,y));
  const nw=Math.max(1,Math.min(W-nx,w));
  const nh=Math.max(1,Math.min(H-ny,h));
  return {x:nx,y:ny,w:nw,h:nh};
}

async function classifyPPERegions(source,W,H){
  if(!mobileNetModel||!sm) return;
  const headBox=poseCropBox(sm,'head',W,H);
  const torsoBox=poseCropBox(sm,'torso',W,H);
  async function classifyBox(box){
    if(!box||box.w<20||box.h<20) return [];
    const oc=document.createElement('canvas');
    oc.width=224; oc.height=224;
    oc.getContext('2d').drawImage(source,box.x,box.y,box.w,box.h,0,0,224,224);
    return await mobileNetModel.classify(oc,8);
  }
  try{
    const headPreds=await classifyBox(headBox);
    const torsoPreds=await classifyBox(torsoBox);
    latestPpeStatus={
      helmet:ppeKeywordScore(headPreds,'helmet'),
      vest:ppeKeywordScore(torsoPreds,'vest'),
      updatedAt:Date.now(),
      source:'browser_mobilenet'
    };
  }catch(e){}
}

async function analyzePPEWithBackend(source,W,H){
  if(ppeBackendBusy) return;
  if(activeServiceMode!=='safety') return;
  const now=Date.now();
  if(now-lastPpeBackendAt<PPE_BACKEND_INTERVAL) return;
  lastPpeBackendAt=now;
  ppeBackendBusy=true;
  try{
    const maxW=640;
    const scale=Math.min(1,maxW/(W||640));
    const cw=Math.max(1,Math.round((W||640)*scale));
    const ch=Math.max(1,Math.round((H||480)*scale));
    const oc=document.createElement('canvas');
    oc.width=cw; oc.height=ch;
    oc.getContext('2d').drawImage(source,0,0,W||cw,H||ch,0,0,cw,ch);
    const image_base64=oc.toDataURL('image/jpeg',0.72).split(',')[1];
    const resp=await fetch(`${API_BASE}/ppe/analyze-frame`,{
      method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({image_base64})
    });
    if(!resp.ok) return;
    const data=await resp.json();
    if(!data.success) return;
    const prev=latestPpeStatus||{};
    const backendHelmet=data.helmet||prev.helmet||{state:'unknown',label:'확인 중',confidence:0,raw:''};
    const backendVest=data.vest||{};
    latestPpeStatus={
      helmet:backendHelmet,
      vest:backendVest.state&&backendVest.state!=='unknown'?backendVest:(prev.vest||{state:'unknown',label:'확인 중',confidence:0,raw:''}),
      updatedAt:Date.now(),
      source:'ppe_yolo',
      people_count:data.people_count||0,
      model_path:data.model_path||''
    };
  }catch(e){
    // 백엔드 PPE 분석은 보조 기능이다. 실패 시 브라우저 경량 판정을 유지한다.
  }finally{
    ppeBackendBusy=false;
  }
}

// 백엔드 yolov8s로 현재 프레임을 분석해, 브라우저가 놓친 객체를 보강한다.
// 완전 보조 기능: 실패하면 조용히 무시되어 기존 브라우저 탐지가 그대로 유지된다.
async function analyzeObjectsWithBackend(source,W,H){
  if(backendBoostBusy) return;
  // 좌표 안전: 실제 소스 해상도를 인자보다 우선(미준비/해상도 경계 시 1프레임 박스 붕괴 방지)
  W=(source&&source.videoWidth)||W; H=(source&&source.videoHeight)||H;
  if(!W||!H) return;
  const now=Date.now();
  // 스켈레톤 실시간성 위해 모든 테마 6.6fps(150ms)
  if(now-lastBackendBoostAt < DETECT_MIN_INTERVAL_MS) return;
  lastBackendBoostAt=now;
  backendBoostBusy=true;
  try{
    const maxW=640;
    const scale=Math.min(1,maxW/(W||640));
    const cw=Math.max(1,Math.round((W||640)*scale));
    const ch=Math.max(1,Math.round((H||480)*scale));
    const oc=document.createElement('canvas');
    oc.width=cw; oc.height=ch;
    oc.getContext('2d').drawImage(source,0,0,W||cw,H||ch,0,0,cw,ch);
    const image_base64=oc.toDataURL('image/jpeg',0.72).split(',')[1];
    // 외곽선 모드 토글 시 세그, 안전 모드는 사람 포즈(스켈레톤)를 같은 호출에서 함께 요청(추가 인코딩 없음)
    const wantSeg=segModeOn();
    const wantPose=!segModeOn();   // 안전·피트니스·오피스 모두 백엔드 포즈 스켈레톤 사용
    const resp=await fetch(`${API_BASE}/detect/frame`,{
      method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({image_base64, ppe: activeServiceMode==='safety' && (document.getElementById('togFieldMode')?.checked ?? true), safety_only: activeServiceMode==='safety', seg: wantSeg, pose: wantPose})
    });
    if(!resp.ok) return;
    const data=await resp.json();
    if(!data.success) return;
    backendHazards=Array.isArray(data.hazards)?data.hazards:[];   // 화재/연기/흡연
    try{ window.backendSignals=data.signals||{}; window.backendHazardsLive=backendHazards; window.proximityHazards=Array.isArray(data.proximity)?data.proximity:[]; }catch(_){}  // 라이브 이벤트 기록용 전역
    if(!Array.isArray(data.detections)) return;
    // 백엔드 박스(전송한 cw×ch 좌표) → 원본 소스(W×H) 좌표로 환원
    const invX=(W||cw)/cw, invY=(H||ch)/ch;
    const _seenAt=Date.now();                     // 이 배치 detection의 관측 시각(잔상 페이드 기준)
    backendBoostDets=data.detections
      .filter(d=> activeServiceMode==='safety' || !isPpeClass(d.class))   // 보호구는 안전 테마에서만
      .map(d=>{
        const[x,y,w,h]=d.bbox;
        return {class:d.class, score:d.score, bbox:[x*invX,y*invY,w*invX,h*invY], source:'backend', seenAt:_seenAt, id:(d.id ?? -1)};   // id 가산(1.8b · 클라 id 매칭용, 미부여=-1)
      });
    backendBoostAt=_seenAt;
    // 세그멘테이션 폴리곤(통합 응답) — 좌표 환원 후 저장. detect와 같은 프레임이라 추가 인코딩 없음.
    if(wantSeg && Array.isArray(data.segments) && data.segments.length){
      segPolys=data.segments
        .filter(s=> activeServiceMode==='safety' || !isPpeClass(s.class))
        .map(s=>({class:s.class, score:s.confidence, points:(s.polygon||[]).map(p=>[p[0]*invX, p[1]*invY])}))
        .filter(s=>s.points.length>=3);
      segAt=Date.now();
    }
    // 사람 포즈 키포인트(통합 응답) — 좌표 환원 후 저장(안전: 스켈레톤 표시)
    if(wantPose && Array.isArray(data.poses) && data.poses.length){
      prevBackendPoses=backendPoses; prevPoseAt=poseAt;   // 직전 프레임 보관(예측용)
      backendPoses=data.poses
        .map(p=>({points:(p.keypoints||[]).map(k=>[k[0]*invX, k[1]*invY]), conf:p.keypoint_confidence||[]}))
        .filter(p=>p.points.length>=5);
      poseAt=Date.now();
    }
  }catch(e){
    // 보조 기능이므로 실패 시 무시 (기존 브라우저 탐지 유지)
  }finally{
    backendBoostBusy=false;
  }
}

// 외곽선 모드: 프레임을 백엔드 세그멘테이션(/segment/frame)에 보내 폴리곤을 받아온다.
// 좌표는 전송 크기 → 원본 소스(VW×VH)로 환원해 둔다. 실패/미가용 시 segPolys 유지(폴백=박스).
async function analyzeSegments(source,W,H){
  if(segBusy) return;
  const now=Date.now();
  if(now-lastSegAt<SEG_INTERVAL) return;
  lastSegAt=now;
  segBusy=true;
  try{
    const maxW=640;
    const scale=Math.min(1,maxW/(W||640));
    const cw=Math.max(1,Math.round((W||640)*scale));
    const ch=Math.max(1,Math.round((H||480)*scale));
    const oc=document.createElement('canvas'); oc.width=cw; oc.height=ch;
    oc.getContext('2d').drawImage(source,0,0,W||cw,H||ch,0,0,cw,ch);
    const image_base64=oc.toDataURL('image/jpeg',0.72).split(',')[1];
    const resp=await fetch(`${API_BASE}/segment/frame`,{
      method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({image_base64, ppe: activeServiceMode==='safety' && (document.getElementById('togFieldMode')?.checked ?? true), safety_only: activeServiceMode==='safety'})
    });
    if(!resp.ok) return;
    const data=await resp.json();
    if(!data.success || !Array.isArray(data.segments)) return;
    const invX=(W||cw)/cw, invY=(H||ch)/ch;
    segPolys=data.segments
      .filter(s=> activeServiceMode==='safety' || !isPpeClass(s.class))
      .map(s=>({
        class:s.class, score:s.confidence,
        points:(s.polygon||[]).map(p=>[p[0]*invX, p[1]*invY])   // 소스(VW×VH) 좌표
      }))
      .filter(s=>s.points.length>=3);
    segAt=Date.now();
  }catch(e){
    // 폴백: 실패 시 기존 박스 유지
  }finally{ segBusy=false; }
}

function mobileNetToHeldObjects(preds, handBBox){
  if(!handBBox||!preds||!preds.length) return [];
  const bw=handBBox.maxX-handBBox.minX, bh=handBBox.maxY-handBBox.minY;
  if(bw<20||bh<20) return [];
  return preds
    .map(p=>({raw:p, fine:normalizeFineObject(p.className)}))
    .filter(item=>item.fine&&item.raw.probability>=0.16)
    .slice(0,2)
    .map(item=>({
      class:item.fine.class,
      confidence:item.raw.probability,
      score:item.raw.probability,
      bbox:[handBBox.minX,handBBox.minY,bw,bh],
      source:'mobilenet-hand',
      raw_class:item.raw.className,
      label:item.fine.label
    }));
}

async function classifyHandRegion(source, handBBox, W, H){
  if(!mobileNetModel||!handBBox||!(document.getElementById('togMobileNet')?.checked??true)) return [];
  try{
    const offC=document.createElement('canvas');
    offC.width=224; offC.height=224;
    const offCtx=offC.getContext('2d');
    const bw=handBBox.maxX-handBBox.minX, bh=handBBox.maxY-handBBox.minY;
    if(bw<10||bh<10) return [];
    offCtx.drawImage(source, handBBox.minX, handBBox.minY, bw, bh, 0, 0, 224, 224);
    const preds=await mobileNetModel.classify(offC,5);
    return preds;
  }catch(e){return [];}
}

function cropToBase64(source, box, W, H){
  if(!box) return null;
  const pad=Math.max(28,(box.maxX-box.minX)*0.45);
  const x=Math.max(0,box.minX-pad);
  const y=Math.max(0,box.minY-pad);
  const bw=Math.min(W-x,(box.maxX-box.minX)+pad*2);
  const bh=Math.min(H-y,(box.maxY-box.minY)+pad*2);
  if(bw<24||bh<24) return null;
  const oc=document.createElement('canvas');
  oc.width=320; oc.height=320;
  oc.getContext('2d').drawImage(source,x,y,bw,bh,0,0,320,320);
  return {image:oc.toDataURL('image/jpeg',0.82), bbox:{x,y,w:bw,h:bh}};
}

async function saveHandCropForTraining(hand, box, preds){
  const toggle=document.getElementById('togSaveHandCrops');
  if(!toggle||!toggle.checked||!cameraOn||!box) return;
  const now=Date.now();
  if(now-(lastCropSaveAt[hand]||0)<2500) return;
  const VW=videoEl.videoWidth||1280, VH=videoEl.videoHeight||720;
  const crop=cropToBase64(videoEl,box,VW,VH);
  if(!crop) return;
  const top=preds&&preds[0]?preds[0]:null;
  const label=top?translateMN(top.className).replace(/[^\w가-힣]+/g,'_'):'unknown';
  lastCropSaveAt[hand]=now;
  try{
    const resp=await fetch(API_BASE+'/dataset/small-object/crop',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        image_base64:crop.image,
        hand,
        predicted_label:label,
        confidence:top?top.probability:null,
        source:'realtime_vision_hand_crop',
        bbox:crop.bbox,
        metadata:{raw_class:top?top.className:'',active_service:activeServiceMode}
      })
    });
    if(resp.ok){
      cropSaveCount++;
      const el=document.getElementById('handCropStatus');
      if(el) el.textContent=`학습용 손 크롭 저장: ${cropSaveCount}장 저장됨`;
    }
  }catch(e){
    const el=document.getElementById('handCropStatus');
    if(el) el.textContent='학습용 손 크롭 저장: 서버 연결 필요';
  }
}

// ═══════════════════════════════════════════════════
//  포즈 스무딩 & 행동 인식
// ═══════════════════════════════════════════════════
function smoothPose(lm){
  if(!lm) return null;
  poseHistory.push(lm.map(p=>p?{x:p.x,y:p.y,z:p.z||0,visibility:p.visibility||0}:null));
  if(poseHistory.length>SMOOTH_N) poseHistory.shift();
  if(poseHistory.length<2) return lm;
  return lm.map((pt,i)=>{
    if(!pt) return null;
    let wx=0,wy=0,wz=0,wSum=0;
    poseHistory.forEach((h,fi)=>{
      if(!h||!h[i]) return;
      const w=fi+1; wx+=h[i].x*w; wy+=h[i].y*w; wz+=h[i].z*w; wSum+=w;
    });
    return wSum?{x:wx/wSum,y:wy/wSum,z:wz/wSum,visibility:pt.visibility}:pt;
  });
}
function smoothAction(r){
  actionHistory.push(r);
  if(actionHistory.length>ACTION_N) actionHistory.shift();
  if(r.danger||r.warn) return {...r,confidence:1};
  const c={};
  for(const a of actionHistory) c[a.action]=(c[a.action]||0)+1;
  let best=r,bc=0;
  for(const a of actionHistory){if(c[a.action]>bc){bc=c[a.action];best=a;}}
  return {...best,confidence:bc/Math.max(1,actionHistory.length)};
}
function updateVel(lm){
  if(!lm||!lm[23]||!lm[24]) return;
  const hy=(lm[23].y+lm[24].y)/2;
  if(prevHipY!==null) hipVelocity=hipVelocity*.75+Math.abs(hy-prevHipY)*.25;
  prevHipY=hy;
}

function calcAngle(a,b,c){
  if(!a||!b||!c) return null;
  const ab={x:a.x-b.x,y:a.y-b.y},cb={x:c.x-b.x,y:c.y-b.y};
  const dot=ab.x*cb.x+ab.y*cb.y, mag=Math.sqrt(ab.x**2+ab.y**2)*Math.sqrt(cb.x**2+cb.y**2);
  return mag?Math.round(Math.acos(Math.min(1,Math.max(-1,dot/mag)))*180/Math.PI):null;
}
function dist(a,b){return(!a||!b)?0:Math.sqrt((a.x-b.x)**2+(a.y-b.y)**2);}
function avgVal(a,b){return(a!==null&&b!==null)?(a+b)/2:(a!==null?a:b);}
function getTrunkTilt(lm){
  const lS=lm[11],rS=lm[12],lH=lm[23],rH=lm[24];
  if(!lS||!rS||!lH||!rH) return 0;
  return Math.abs(Math.atan2((lS.x+rS.x)/2-(lH.x+rH.x)/2,(lS.y+rS.y)/2-(lH.y+rH.y)/2)*180/Math.PI);
}

function recognizeAction(lm){
  if(!lm) return{action:'인식 대기 중',icon:'⏳'};
  const lS=lm[11],rS=lm[12],lH=lm[23],rH=lm[24],lK=lm[25],rK=lm[26],lA=lm[27],rA=lm[28],lW=lm[15],rW=lm[16];
  if(!lS||!rS||!lH||!rH) return{action:'인식 중...',icon:'🔄'};
  const trunk=getTrunkTilt(lm), hipY=(lH.y+rH.y)/2;
  const lKA=calcAngle(lH,lK,lA), rKA=calcAngle(rH,rK,rA), avgKnee=avgVal(lKA,rKA);
  const lHA=calcAngle(lS,lH,lK), rHA=calcAngle(rS,rH,rK), avgHip=avgVal(lHA,rHA);
  const sitting=avgKnee!==null&&avgKnee<135&&avgHip!==null&&avgHip<145;
  const squatting=avgKnee!==null&&avgKnee<95&&trunk<40;
  if(squatting){fallConfirm=0;return{action:'스쿼트/쪼그리기',icon:'🦵'};}
  if(sitting){fallConfirm=0;return{action:'앉아 있음',icon:'🪑'};}
  const fastFall=trunk>55&&hipY>0.62&&hipVelocity>0.012;
  const slowFall=trunk>48&&hipVelocity>0.008;
  fastFall||slowFall?fallConfirm++:fallConfirm=Math.max(0,fallConfirm-2);
  if(fallConfirm>=FALL_CONFIRM&&document.getElementById('togFall').checked) return{action:'낙상 감지!',icon:'🚨',danger:true};
  if(fallConfirm>=3) return{action:'넘어질 위험',icon:'⚠️',warn:true};
  const armsUp=(lW&&lS&&lW.y<lS.y-.06)||(rW&&rS&&rW.y<rS.y-.06);
  const ankleSpread=lA&&rA?Math.abs(lA.x-rA.x):0;
  if(hipVelocity>0.018&&avgKnee!==null&&avgKnee<155) return{action:'달리기',icon:'🏃'};
  if((hipVelocity>0.008||ankleSpread>0.1)&&avgKnee!==null&&avgKnee<165&&trunk<25) return{action:'걷기',icon:'🚶'};
  if(armsUp) return{action:'팔 들기',icon:'🙋'};
  if(trunk>30&&trunk<48) return{action:'앞으로 숙임',icon:'🙇'};
  return{action:'서 있음',icon:'🧍'};
}

// ═══════════════════════════════════════════════════
//  번역 & 아이콘
// ═══════════════════════════════════════════════════
const KO={'person':'사람','car':'자동차','bicycle':'자전거','motorcycle':'오토바이','bus':'버스','truck':'트럭','chair':'의자','couch':'소파','laptop':'노트북','tv':'TV','book':'책','bottle':'병','cup':'컵','knife':'칼','fork':'포크','spoon':'숟가락','bowl':'그릇','cell phone':'휴대폰','keyboard':'키보드','mouse':'마우스','dog':'강아지','cat':'고양이','bird':'새','umbrella':'우산','backpack':'배낭','sports ball':'공','scissors':'가위','clock':'시계','handbag':'핸드백','traffic light':'신호등','bench':'벤치','potted plant':'화분','vase':'꽃병','remote':'리모컨','suitcase':'가방','skateboard':'스케이트보드','tennis racket':'테니스 라켓','baseball bat':'야구 방망이','wine glass':'와인잔','dining table':'식탁','refrigerator':'냉장고','oven':'오븐','sink':'싱크대','microwave':'전자레인지','toaster':'토스터','pizza':'피자','banana':'바나나','apple':'사과','orange':'오렌지','sandwich':'샌드위치','hot dog':'핫도그','cake':'케이크','broccoli':'브로콜리','carrot':'당근','cigarette':'담배/흡연물','glasses':'안경/선글라스','snack':'과자/간식'};
const ICONS={'person':'🧑','car':'🚗','bicycle':'🚲','motorcycle':'🏍','bus':'🚌','truck':'🚚','chair':'🪑','couch':'🛋','laptop':'💻','tv':'📺','book':'📖','bottle':'🍶','cup':'☕','knife':'🔪','fork':'🍴','spoon':'🥄','bowl':'🍜','cell phone':'📱','keyboard':'⌨','mouse':'🖱','dog':'🐶','cat':'🐱','bird':'🐦','umbrella':'☂','backpack':'🎒','sports ball':'⚽','scissors':'✂','clock':'🕐','handbag':'👜','traffic light':'🚦','bench':'🪵','potted plant':'🪴','vase':'🏺','remote':'📡','suitcase':'🧳','wine glass':'🍷','dining table':'🍽','refrigerator':'🧊','pizza':'🍕','banana':'🍌','apple':'🍎','orange':'🍊','sandwich':'🥪','cake':'🎂','cigarette':'🚬','glasses':'👓','snack':'🍪'};
const DANGER_OBJ=['knife','scissors'];
const CAUTION_OBJ=['car','truck','bus','motorcycle','cigarette'];
// 안전 모드에서 '그릴' 객체 화이트리스트 — 사람·위험물·차량/중장비·화재. 일상 잡동사니(의자·컵·노트북 등)는 숨겨 화면을 깔끔하게.
const SAFETY_SHOW=new Set(['person','knife','scissors','car','truck','bus','motorcycle','bicycle','forklift','train','boat','fire','smoke','cigarette']);
function _safetyVisible(objs){
  // 안전 테마 판정 — activeServiceMode 설정 타이밍에 의존하지 않게 AX_LOCK_THEME 도 함께 본다(누수 방지)
  const isSafety=(typeof activeServiceMode!=='undefined'&&activeServiceMode==='safety')||(typeof window!=='undefined'&&window.AX_LOCK_THEME==='safety');
  if(!isSafety) return objs;  // 다른 테마는 그대로
  return (objs||[]).filter(o=>{
    const c=String(o.class||'').toLowerCase();
    return SAFETY_SHOW.has(c) || isPpeClass(o.class) || o.danger || o.hazard;  // 안전 관련 + 보호구 + 위험/화재 표시만
  });
}
const SCENE_MAP={'사무실':['laptop','keyboard','mouse','chair','book','cell phone'],'도로/교통':['car','truck','bus','motorcycle','bicycle','traffic light'],'주방/식당':['cup','bowl','knife','spoon','fork','bottle','oven','refrigerator'],'스포츠':['sports ball','tennis racket','baseball bat','skateboard'],'거실':['couch','tv','remote','potted plant'],'야외/공원':['bench','bird','dog','cat','umbrella','backpack']};
function translateClass(c){return KO[c]||c;}
function classIcon(c){return ICONS[c]||'📦';}
function safetyTag(c){return DANGER_OBJ.includes(c)?{label:'위험',cls:'danger'}:CAUTION_OBJ.includes(c)?{label:'주의',cls:'caution'}:{label:'안전',cls:'safe'};}
function inferScene(objs){
  if(!objs.length) return{scene:'분석 중...',tags:[]};
  const lbls=objs.map(o=>o.class);
  const sc={};
  for(const[s,kw]of Object.entries(SCENE_MAP)){const n=kw.filter(k=>lbls.includes(k)).length;if(n) sc[s]=n;}
  if(!Object.keys(sc).length) return{scene:lbls.includes('person')?'실내/실외':'알 수 없음',tags:[]};
  const sorted=Object.entries(sc).sort((a,b)=>b[1]-a[1]);
  return{scene:sorted[0][0],tags:sorted.slice(0,3).map(([s])=>s)};
}

// ═══════════════════════════════════════════════════
//  그리기
// ═══════════════════════════════════════════════════
function drawSkeleton(pose,W,H){
  if(!pose||!(document.getElementById('togSkeleton')?.checked??true)) return;
  const conn=[[11,12],[11,13],[13,15],[12,14],[14,16],[11,23],[12,24],[23,24],[23,25],[24,26],[25,27],[26,28],[27,29],[28,30],[29,31],[30,32]];
  ctx.strokeStyle='rgba(255,255,255,.8)'; ctx.lineWidth=2.5;
  for(const[a,b]of conn){if(!pose[a]||!pose[b]||pose[a].visibility<.4||pose[b].visibility<.4)continue;ctx.beginPath();ctx.moveTo(viewX(pose[a],W,H),viewY(pose[a],W,H));ctx.lineTo(viewX(pose[b],W,H),viewY(pose[b],W,H));ctx.stroke();}
  if(!(document.getElementById('togJoints')?.checked??true)) return;
  for(let i=0;i<pose.length;i++){const p=pose[i];if(!p||p.visibility<.4)continue;const c=i<=10?'#00d4ff':i<=22?'#a78bfa':i<=28?'#10b981':'#ef4444';ctx.beginPath();ctx.arc(viewX(p,W,H),viewY(p,W,H),5,0,2*Math.PI);ctx.fillStyle=c;ctx.fill();ctx.strokeStyle='rgba(0,0,0,.5)';ctx.lineWidth=1;ctx.stroke();}
}

function drawJointLabel(x,y,text,color){
  ctx.save();
  ctx.font='900 13px Segoe UI, Apple SD Gothic Neo, sans-serif';
  ctx.textBaseline='middle';
  const padX=5, h=20, w=ctx.measureText(text).width+padX*2;
  ctx.fillStyle='rgba(5,10,18,.72)';
  ctx.fillRect(x+7,y-h/2,w,h);
  ctx.strokeStyle=color;
  ctx.lineWidth=1.2;
  ctx.strokeRect(x+7,y-h/2,w,h);
  ctx.fillStyle=color;
  ctx.fillText(text,x+7+padX,y);
  ctx.restore();
}

function drawAngleBadge(pose,W,H,centerIdx,label,value,color){
  const p=pose&&pose[centerIdx];
  if(!p||p.visibility<.4||value===null) return;
  const x=viewX(p,W,H), y=viewY(p,W,H)+22;
  const text=`${label} ${value}°`;
  ctx.save();
  ctx.font='900 12px Segoe UI, Apple SD Gothic Neo, sans-serif';
  const w=ctx.measureText(text).width+12, h=20;
  ctx.fillStyle='rgba(0,0,0,.68)';
  ctx.fillRect(x-w/2,y,w,h);
  ctx.strokeStyle=color;
  ctx.lineWidth=1;
  ctx.strokeRect(x-w/2,y,w,h);
  ctx.fillStyle=color;
  ctx.fillText(text,x-w/2+6,y+14);
  ctx.restore();
}

function drawDetailedPoseOverlay(pose,W,H){
  if(!pose) return;
  const showLabels=document.getElementById('togJointLabels')?.checked;
  const showAngles=document.getElementById('togAngleOverlay')?.checked;
  const labels=[
    [0,'NOSE','#7dd3fc'],[11,'LSHO','#fbbf24'],[12,'RSHO','#fb923c'],
    [13,'LELB','#d9f99d'],[14,'RELB','#fde047'],[15,'LWRI','#93c5fd'],[16,'RWRI','#60a5fa'],
    [23,'LHIP','#22d3ee'],[24,'RHIP','#06b6d4'],[25,'LKNE','#a3e635'],[26,'RKNE','#84cc16'],
    [27,'LANK','#ef4444'],[28,'RANK','#dc2626']
  ];
  if(showLabels){
    for(const [idx,name,color] of labels){
      const p=pose[idx];
      if(!p||p.visibility<.42) continue;
      drawJointLabel(viewX(p,W,H),viewY(p,W,H),name,color);
    }
  }
  if(showAngles){
    drawAngleBadge(pose,W,H,13,'LELB',calcAngle(pose[11],pose[13],pose[15]),'#d9f99d');
    drawAngleBadge(pose,W,H,14,'RELB',calcAngle(pose[12],pose[14],pose[16]),'#fde047');
    drawAngleBadge(pose,W,H,23,'LHIP',calcAngle(pose[11],pose[23],pose[25]),'#22d3ee');
    drawAngleBadge(pose,W,H,24,'RHIP',calcAngle(pose[12],pose[24],pose[26]),'#06b6d4');
    drawAngleBadge(pose,W,H,25,'LKNE',calcAngle(pose[23],pose[25],pose[27]),'#a3e635');
    drawAngleBadge(pose,W,H,26,'RKNE',calcAngle(pose[24],pose[26],pose[28]),'#84cc16');
  }
}

function drawFace(f,W,H){
  if(!f||!(document.getElementById('togFaceLM')?.checked??true)) return;
  const kp=[10,152,234,454,33,263,1,61,291,13,14,70,63,105,66,107,336,296,334,159,145,386,374,172,397];
  for(const i of kp){if(!f[i])continue;ctx.beginPath();ctx.arc(viewX(f[i],W,H),viewY(f[i],W,H),2.5,0,2*Math.PI);ctx.fillStyle='#00d4ff';ctx.fill();}
  if((document.getElementById('togFaceMesh')?.checked??true)){
    const ol=[10,338,297,332,284,251,389,356,454,323,361,288,397,365,379,378,400,377,152,148,176,149,150,136,172,58,132,93,234,127,162,21,54,103,67,109,10];
    ctx.beginPath();ol.forEach((i,j)=>{if(!f[i])return;j===0?ctx.moveTo(viewX(f[i],W,H),viewY(f[i],W,H)):ctx.lineTo(viewX(f[i],W,H),viewY(f[i],W,H));});ctx.strokeStyle='rgba(0,212,255,.35)';ctx.lineWidth=1;ctx.stroke();
  }
}

function drawHand(lm,W,H,color){
  if(!lm||!(document.getElementById('togHands')?.checked??true)) return;
  const c=[[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[0,9],[9,10],[10,11],[11,12],[0,13],[13,14],[14,15],[15,16],[0,17],[17,18],[18,19],[19,20]];
  ctx.strokeStyle=color+'bb'; ctx.lineWidth=2;
  for(const[a,b]of c){ctx.beginPath();ctx.moveTo(viewX(lm[a],W,H),viewY(lm[a],W,H));ctx.lineTo(viewX(lm[b],W,H),viewY(lm[b],W,H));ctx.stroke();}
  for(const p of lm){ctx.beginPath();ctx.arc(viewX(p,W,H),viewY(p,W,H),3.5,0,2*Math.PI);ctx.fillStyle=color;ctx.fill();}
}

// 손→사물 연결선 그리기
function drawHandToObj(handLM,heldObjs,W,H,scX,scY,color){
  if(!handLM||!heldObjs.length||!(document.getElementById('togHandLines')?.checked??true)) return;
  const wrist=handLM[0];
  const palmCX=viewX(wrist,W,H), palmCY=viewY(wrist,W,H);
  for(const obj of heldObjs){
    const sb=displayBboxArray(scaleBbox(obj.bbox,scX,scY),W,H);
    const objCX=sb[0]+sb[2]/2, objCY=sb[1]+sb[3]/2;
    ctx.setLineDash([6,4]);
    ctx.strokeStyle=color+'cc'; ctx.lineWidth=2;
    ctx.beginPath(); ctx.moveTo(palmCX,palmCY); ctx.lineTo(objCX,objCY); ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath(); ctx.arc(objCX,objCY,8,0,2*Math.PI);
    ctx.fillStyle=color+'33'; ctx.fill();
    ctx.strokeStyle=color; ctx.lineWidth=2; ctx.stroke();
  }
}

// 손 영역 박스 그리기
function drawHandBBox(bbox,W,H,color,label){
  if(!bbox||!(document.getElementById('togHands')?.checked??true)) return;
  bbox=displayHandBox(bbox,W,H);
  ctx.strokeStyle=color+'88'; ctx.lineWidth=1.5; ctx.setLineDash([4,3]);
  ctx.strokeRect(bbox.minX,bbox.minY,bbox.maxX-bbox.minX,bbox.maxY-bbox.minY);
  ctx.setLineDash([]);
  ctx.font='bold 10px Segoe UI'; ctx.fillStyle=color;
  ctx.fillText(label,bbox.minX+4,bbox.minY-4);
}

function drawObjects(objs,W,H,lHeld,rHeld,scX,scY,hidePerson){
  if(!document.getElementById('togBBox').checked) return;
  // 사람 박스 생략은 '대체 표시(스켈레톤/포즈)가 실제로 있을 때만'. 없으면 박스로 표시해
  // 사람이 항상 보이게 한다(MediaPipe 미로딩 등으로 사람이 통째로 사라지는 회귀 방지).
  // 인원수·PPE·위험구역 판정은 탐지 데이터로 동작하므로 박스 생략과 무관하게 유지된다.
  const cmap={safe:'#10b981',caution:'#f59e0b',danger:'#ef4444'};
  for(const o of objs){
    if(hidePerson && o.class==='person' && !o._poseFollow) continue;   // pose 따라가는 사람 박스는 표시(2단계), 나머지 사람은 기존대로 스켈레톤에 양보
    if(!shouldDrawClass(o.class)) continue;   // 표시 필터: 무관/오탐 COCO 숨김(탐지 데이터엔 그대로 남음 — 통계·판정 불변)
    const _fa=_staleAlpha(o.seenAt);            // 잔상 페이드: 오래된 박스는 알파↓ 후 제외
    if(_fa<=0) continue;                          // STALE_TTL 초과 → 렌더 제외(옛 자리 고정 잔상 제거)
    ctx.save(); ctx.globalAlpha=_fa;
    const[x,y,w,h]=displayBboxArray(scaleBbox(o.bbox,scX,scY),W,H);
    const tag=safetyTag(o.class);
    const isLH=lHeld.some(l=>iou(l.bbox,o.bbox)>.3);
    const isRH=rHeld.some(r=>iou(r.bbox,o.bbox)>.3);
    let col=cmap[tag.cls];
    if(isLH) col='#10b981';
    if(isRH) col='#f97316';
    if(isViolation(o.class)) col='#ef4444';   // 미착용·화재 등 위반은 항상 빨강(우선)
    ctx.fillStyle=col+'18'; ctx.fillRect(x,y,w,h);
    ctx.strokeStyle=col; ctx.lineWidth=isLH||isRH?3:2; ctx.strokeRect(x,y,w,h);
    const cs=14; ctx.lineWidth=3;
    [[x,y,1,1],[x+w,y,-1,1],[x,y+h,1,-1],[x+w,y+h,-1,-1]].forEach(([cx,cy,xd,yd])=>{ctx.beginPath();ctx.moveTo(cx,cy+yd*cs);ctx.lineTo(cx,cy);ctx.lineTo(cx+xd*cs,cy);ctx.stroke();});
    if(document.getElementById('togLabel').checked){
      ctx.font='bold 12px Segoe UI';
      const handTag=isLH?' 🟢L':isRH?' 🟠R':'';
      const label=`${translateClass(o.class)}${handTag} ${fmtConf(o.score)}`;
      const tw=ctx.measureText(label).width+14; const ly=y>24?y-5:y+h+17;
      ctx.fillStyle=col; ctx.fillRect(x,ly-17,tw,20); ctx.fillStyle='#000'; ctx.fillText(label,x+5,ly-1);
    }
    if(o.id){ctx.font='bold 9px Segoe UI';ctx.fillStyle='rgba(255,255,255,.5)';ctx.fillText('#'+o.id,x+3,y+11);}
    ctx.restore();                                // globalAlpha 복원(잔상 페이드)
  }
}

// 백엔드 정밀 결과 중 '브라우저가 놓친' 객체만 별도 스타일(점선 시안)로 덧그린다.
// 브라우저가 이미 잡은 객체와 겹치면(IoU>0.45) 중복 표시하지 않는다.
function drawBackendBoost(browserObjs,W,H,scX,scY){
  if(!backendActive()) return;
  if(!document.getElementById('togBBox')?.checked) return;
  const now=Date.now();
  const showLabel=document.getElementById('togLabel')?.checked;
  const _sliderThr=(parseInt(document.getElementById('confThreshold')?.value||'0'))/100;   // ★ 슬라이더 backend 연동(2026-07-11)
  // ── target: 최신 backend 검출(신선도 TTL·슬라이더·착용정상·브라우저중복 필터) ──
  const fresh = (now-backendBoostAt<=BACKEND_BOOST_TTL) ? backendBoostDets.filter(o=>
      o.score>=_sliderThr
      && (o.class||'').toLowerCase()!=='person'                                            // ★ person 은 pose 재배치(즉시성) 경로 우선 → lerp 제외(경합 방지, 2026-07-12)
      && !(isPpeClass(o.class) && !isViolation(o.class))                                   // 착용 정상 보호구는 표시 생략(기존 동작 유지)
      && !browserObjs.some(b=>b.class===o.class && iou(b.bbox,o.bbox)>0.45)                 // 브라우저가 이미 잡은 것 중복 제외
    ) : [];
  // ── 보간(2026-07-12): 표시 박스를 target 으로 lerp 수렴 + 페이드아웃(300ms). 큰 이동은 스냅(수렴 지연 방지). ──
  const LERP=0.5, FADE=300, SNAP_IOU=0.5;   // lerp 0.5 → 90% 수렴 ~110ms(30fps). 큰이동(IoU<0.5)은 즉시 스냅(jitter 거슬리면 SNAP_IOU 조정).
  _boostDisp.forEach(d=>d._m=false);
  for(const t of fresh){
    let d=_boostDisp.find(x=>!x._m && x.class===t.class && iou(x.bbox,t.bbox)>0.30);       // 클래스+IoU 매칭
    if(d){
      d._m=true; d.score=t.score; d.seen=now;
      const snap=iou(d.bbox,t.bbox)<SNAP_IOU;                                              // 큰 이동이면 스냅(수렴 대기 없이 즉시)
      for(let i=0;i<4;i++) d.bbox[i]= snap ? t.bbox[i] : d.bbox[i]+(t.bbox[i]-d.bbox[i])*LERP;
    }
    else { _boostDisp.push({class:t.class,bbox:t.bbox.slice(),score:t.score,alpha:0,seen:now,_m:true}); }  // 신규는 스냅 없이 페이드인
  }
  _boostDisp=_boostDisp.filter(d=>{
    if(d._m){ d.alpha=Math.min(1,d.alpha+0.25); return true; }
    d.alpha=Math.max(0,1-(now-d.seen)/FADE); return d.alpha>0.02;                          // target 사라지면 300ms 페이드아웃(유령 방지)
  });
  // ── 그리기 ──
  for(const d of _boostDisp){
    const[x,y,w,h]=displayBboxArray(scaleBbox(d.bbox,scX,scY),W,H);
    const viol=isViolation(d.class); const bcol=viol?'#ef4444':'#22d3ee';
    ctx.save(); ctx.globalAlpha=d.alpha;
    ctx.setLineDash([6,4]); ctx.strokeStyle=bcol; ctx.lineWidth=viol?3:2; ctx.strokeRect(x,y,w,h); ctx.setLineDash([]);
    if(showLabel){
      ctx.font='bold 12px Segoe UI';
      const label=`${translateClass(d.class)} ${viol?'⚠':'✓정밀'} ${fmtConf(d.score)}`;
      const tw=ctx.measureText(label).width+14; const ly=y>24?y-5:y+h+17;
      ctx.fillStyle=bcol; ctx.fillRect(x,ly-17,tw,20);
      ctx.fillStyle=viol?'#fff':'#003'; ctx.fillText(label,x+5,ly-1);
    }
    ctx.restore();
  }
  // ── 진단 모드(?diag=1, 개발 전용): 원시 박스(보간 없이 마지막 응답, 반투명 파랑) + '검출 후 경과ms' 동시 표시 ──
  //   판별: 파랑(원시)·빨강(보간)이 함께 사람 뒤를 따르면 순수 지연(1번, F-10). 빨강만 이상=보간버그(4번). 둘다 사람과 무관=좌표(3번).
  if(_COORD_DIAG){
    const age=now-backendBoostAt;
    for(const o of fresh){
      const[x,y,w,h]=displayBboxArray(scaleBbox(o.bbox,scX,scY),W,H);
      ctx.save(); ctx.globalAlpha=0.55; ctx.strokeStyle='#3b82f6'; ctx.lineWidth=2; ctx.strokeRect(x,y,w,h);
      ctx.fillStyle='#3b82f6'; ctx.font='10px monospace'; ctx.fillText(`raw +${age}ms`,x+3,y+12); ctx.restore();
    }
  }
}

// 외곽선(세그멘테이션) 그리기 — 박스 대신 객체 윤곽 폴리곤. 좌표는 소스(VW×VH) → 캔버스 환산.
// 박스와 동일한 레터박스/미러 변환을 적용해 영상과 정확히 정렬한다.
function drawSegments(W,H,scX,scY,onlyClass){
  if(!segPolys.length) return;
  const r=mediaRect(W,H);
  const flip=shouldFlipDisplay();
  const showLabel=document.getElementById('togLabel')?.checked;
  const cmap={safe:'#10b981',caution:'#f59e0b',danger:'#ef4444'};
  for(const s of segPolys){
    if(onlyClass && s.class!==onlyClass) continue;   // 특정 클래스만(예: 안전의 사람 외곽선)
    const col=cmap[safetyTag(s.class).cls]||'#22d3ee';
    ctx.beginPath();
    for(let i=0;i<s.points.length;i++){
      const sx=s.points[i][0]*scX, sy=s.points[i][1]*scY;
      const dx=r.x+(flip? r.w-sx : sx), dy=r.y+sy;
      if(i===0) ctx.moveTo(dx,dy); else ctx.lineTo(dx,dy);
    }
    ctx.closePath();
    ctx.fillStyle=col+'22'; ctx.fill();
    ctx.strokeStyle=col; ctx.lineWidth=2.5; ctx.lineJoin='round'; ctx.stroke();
    if(showLabel){
      const sx=s.points[0][0]*scX, sy=s.points[0][1]*scY;
      const lx=r.x+(flip? r.w-sx : sx), ly=r.y+sy;
      ctx.font='bold 12px Segoe UI';
      const label=`${translateClass(s.class)} ${fmtConf(s.score)}`;
      const tw=ctx.measureText(label).width+12;
      ctx.fillStyle=col; ctx.fillRect(lx,ly-18,tw,18);
      ctx.fillStyle='#001018'; ctx.fillText(label,lx+4,ly-5);
    }
  }
}

// 백엔드 포즈(COCO-17) 스켈레톤 그리기 — 안전에서 사람을 박스/외곽선 대신 키포인트로 표시.
// 좌표는 소스(VW×VH) → 캔버스 환산(박스와 동일한 레터박스/미러 변환).
// 포즈 중심점(신뢰 키포인트 평균) — 프레임 간 사람 매칭용
function _poseCentroid(pts,cf){let sx=0,sy=0,n=0;for(let i=0;i<pts.length;i++){if((cf?.[i]??1)<0.3)continue;sx+=pts[i][0];sy+=pts[i][1];n++;}return n?[sx/n,sy/n]:null;}
// 속도 기반 예측: 직전 프레임과 매칭해 '지금 위치'를 추정(백엔드 지연/저빈도 보정). 표시 전용이라 정확도·판정 영향 없음.
const POSE_PREDICT_CAP_MS=200;   // 예측 시간 상한(↑일수록 지연↓·튐 위험↑)
const POSE_PREDICT_MAX_PX=45;    // 키포인트당 최대 보정 거리
function _predictPosePoints(cur){
  if(!prevBackendPoses.length || !prevPoseAt) return cur.points;
  const dt=poseAt-prevPoseAt; if(dt<=0) return cur.points;
  const cc=_poseCentroid(cur.points,cur.conf); if(!cc) return cur.points;
  let best=null,bd=1e9;
  for(const pp of prevBackendPoses){const pc=_poseCentroid(pp.points,pp.conf);if(!pc)continue;const d=Math.hypot(cc[0]-pc[0],cc[1]-pc[1]);if(d<bd){bd=d;best=pp;}}
  if(!best || bd>220) return cur.points;   // 매칭 실패/너무 멀면 예측 안 함(튐 방지)
  const elapsed=Math.min(Math.max(0, Date.now()-poseAt), POSE_PREDICT_CAP_MS);
  return cur.points.map((pt,i)=>{
    const pp=best.points[i];
    if(!pp || (cur.conf[i]??1)<0.3 || (best.conf[i]??1)<0.3) return pt;
    let dx=((pt[0]-pp[0])/dt)*elapsed, dy=((pt[1]-pp[1])/dt)*elapsed;
    dx=Math.max(-POSE_PREDICT_MAX_PX,Math.min(POSE_PREDICT_MAX_PX,dx));
    dy=Math.max(-POSE_PREDICT_MAX_PX,Math.min(POSE_PREDICT_MAX_PX,dy));
    return [pt[0]+dx, pt[1]+dy];
  });
}
function drawBackendPoses(W,H,scX,scY){
  if(!backendPoses.length) return;
  const r=mediaRect(W,H); const flip=shouldFlipDisplay(); const KP=0.3;
  const px=x=>{const sx=x*scX; return r.x+(flip? r.w-sx : sx);};
  const py=y=>r.y+y*scY;
  ctx.save();
  ctx.lineWidth=3; ctx.lineCap='round';
  for(const p of backendPoses){
    const kp=_predictPosePoints(p), cf=p.conf||[];
    // 뼈대: 양 끝 관절 색으로 그라데이션
    for(const [a,b] of COCO_SKELETON){
      if(!kp[a]||!kp[b]) continue;
      if((cf[a]??1)<KP || (cf[b]??1)<KP) continue;
      const x1=px(kp[a][0]),y1=py(kp[a][1]),x2=px(kp[b][0]),y2=py(kp[b][1]);
      const g=ctx.createLinearGradient(x1,y1,x2,y2);
      g.addColorStop(0,KP_COLORS[a]||'#22c55e'); g.addColorStop(1,KP_COLORS[b]||'#22c55e');
      ctx.strokeStyle=g;
      ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
    }
    // 목 중점(양 어깨 중간) → 코 : 머리-몸통을 삼각형 없이 한 선으로 연결
    if(kp[5]&&kp[6]&&kp[0] && (cf[5]??1)>=KP && (cf[6]??1)>=KP && (cf[0]??1)>=KP){
      const nx=(kp[5][0]+kp[6][0])/2, ny=(kp[5][1]+kp[6][1])/2;
      const x1=px(nx),y1=py(ny),x2=px(kp[0][0]),y2=py(kp[0][1]);
      const g=ctx.createLinearGradient(x1,y1,x2,y2);
      g.addColorStop(0,KP_COLORS[5]); g.addColorStop(1,KP_COLORS[0]);
      ctx.strokeStyle=g; ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
    }
    // 관절: 각자 고유 색 (얼굴=코·눈·귀는 점으로만 표시 → 선 없이 깔끔)
    for(let i=0;i<kp.length;i++){
      if((cf[i]??1)<KP) continue;
      ctx.fillStyle=KP_COLORS[i]||'#22c55e';
      ctx.beginPath(); ctx.arc(px(kp[i][0]),py(kp[i][1]),4,0,Math.PI*2); ctx.fill();
      ctx.lineWidth=1.5; ctx.strokeStyle='rgba(0,0,0,.55)'; ctx.stroke(); ctx.lineWidth=3;
    }
  }
  ctx.restore();
}

// AX 딥러닝 자세/낙상 분류기 (브라우저, posture-model.js) ─ MediaPipe33→COCO17 매핑 후 추론
let axPostureModel=null, axFallModel=null, axAILoaded=false;
let axPostureResult=null, axFallResult=null;   // 인식 요약 패널용 최신 결과
async function loadAXModels(){
  try{ axPostureModel=await AXPosture.load('/static/models/posture/posture_weights.json'); }catch(e){}
  try{ axFallModel=await AXPosture.load('/static/models/fall/fall_weights.json'); }catch(e){}
  axAILoaded=!!(axPostureModel||axFallModel);
}
if(window.AXPosture) loadAXModels();

const MP2COCO=[0,2,5,7,8,11,12,13,14,15,16,23,24,25,26,27,28];
function mpToCoco(rawPose,W,H){
  if(!rawPose||rawPose.length<29) return null;
  const out=[];
  for(const idx of MP2COCO){
    const p=rawPose[idx];
    if(!p) return null;
    out.push([p.x*W, p.y*H]);
  }
  return out;
}
let _axInferAt=0;
// 자세/낙상 '추론'만 수행(3Hz). 결과는 좌하단 인식 패널에 표시 → 화면 겹침/혼란 방지.
function drawAXPostureBadge(rawPose,W,H){
  if(!axAILoaded || !rawPose) return;
  const nowMs=performance.now();
  if(nowMs-_axInferAt<=330) return;
  const coco=mpToCoco(rawPose,W,H);
  if(!coco) return;
  _axInferAt=nowMs;
  if(axPostureModel){ const r=axPostureModel.predictFromKeypoints(coco); axPostureResult={...r, at:Date.now()}; }
  if(axFallModel){ const f=axFallModel.predictFromKeypoints(coco); axFallResult={...f, at:Date.now()}; }
}
// (구 자세 뱃지 그리기는 제거됨 — 자세/낙상 정보는 좌하단 인식 패널에 표시)

// 백엔드 위험요소(화재/연기/흡연) 뱃지 — 우상단. /detect/frame 응답의 hazards 표시.
function drawHazardBadge(W,H){
  if(!backendHazards.length) return;
  if(Date.now()-backendBoostAt>BACKEND_BOOST_TTL) return;
  const icon={fire:'🔥',smoke:'💨',smoking:'🚬',fall_from_height:'🪂'};
  const lines=backendHazards.slice(0,4).map(h=>(icon[h.type]||'⚠️')+' '+(h.label||h.type)+' '+(((h.confidence||0)*100)|0)+'%');
  const hasHigh=backendHazards.some(h=>h.severity==='high');
  const col=hasHigh?'#ef4444':'#f59e0b';
  ctx.save();
  ctx.font='bold 14px Segoe UI';
  const w=Math.max(...lines.map(l=>ctx.measureText(l).width))+20;
  const x=Math.max(12,W-w-12), y=12, bh=lines.length*22+10;
  ctx.fillStyle='rgba(7,11,18,.8)'; ctx.fillRect(x,y,w,bh);
  ctx.strokeStyle=col; ctx.lineWidth=2; ctx.strokeRect(x,y,w,bh);
  ctx.fillStyle=col;
  lines.forEach((l,i)=>ctx.fillText(l,x+10,y+22+i*22));
  ctx.restore();
}

// 📋 "지금 인식 중" 요약 패널 — 화면 위 박스가 복잡해도 한눈에 읽히게 평이한 한국어로 정리
let _recogPanelAt=0;
function updateRecognitionPanel(frame){
  const el=document.getElementById('recogPanel'); if(!el) return;
  const nowMs=performance.now();
  if(nowMs-_recogPanelAt<300) return;   // ~3Hz로 제한(매 프레임 DOM 리플로우 방지)
  _recogPanelAt=nowMs;
  const objs=(frame&&frame.latestObjects)||[];
  const people=objs.filter(o=>o.class==='person').length;
  const counts={};
  objs.forEach(o=>{ if(o.class!=='person') counts[o.class]=(counts[o.class]||0)+1; });
  const topObjs=Object.keys(counts).sort((a,b)=>counts[b]-counts[a]).slice(0,4).map(c=>translateClass(c));
  // PPE: 학습된 모델 결과(backendBoostDets)의 Hardhat/NO-Hardhat 기반
  const norm=s=>String(s).toLowerCase().replace(/-/g,' ');
  const ppeFresh=backendBoostDets.length && (Date.now()-backendBoostAt<BACKEND_BOOST_TTL+2000);
  const cls=ppeFresh?backendBoostDets.map(d=>norm(d.class)):[];
  function ppe(onSet,offSet){
    if(!ppeFresh) return ['확인 중 (정밀보정 켜기)','dim'];
    if(offSet.some(x=>cls.includes(x))) return ['미착용 ❌','bad'];
    if(onSet.some(x=>cls.includes(x))) return ['착용 ✅','ok'];
    return ['미감지','dim'];
  }
  const [helmetTxt,helmetCls]=ppe(['hardhat','helmet'],['no hardhat','no helmet']);
  const [vestTxt,vestCls]=ppe(['safety vest','vest'],['no safety vest','no vest']);
  // 자세/낙상 (브라우저 AI, 최근 2.5초 이내)
  const pm={safe:'정상',caution:'주의',danger:'위험'}, pcl={safe:'ok',caution:'warn',danger:'bad'};
  let postTxt='확인 중', postCls='dim';
  if(axPostureResult && Date.now()-axPostureResult.at<2500){ postTxt=pm[axPostureResult.class_name]||axPostureResult.class_name; postCls=pcl[axPostureResult.class_name]||'dim'; }
  let showFall=false;
  if(axFallResult && Date.now()-axFallResult.at<2500 && axFallResult.class_name==='fall') showFall=true;
  // 화재/연기(백엔드 위험요소)
  const hzFresh=backendHazards.length && (Date.now()-backendBoostAt<BACKEND_BOOST_TTL+2000);
  const hzTxt=hzFresh?backendHazards.slice(0,2).map(h=>h.label||h.type).join(', '):'없음';
  const hzCls=hzFresh?(backendHazards.some(h=>h.severity==='high')?'bad':'warn'):'ok';

  let html='<h4>지금 인식 중</h4>';
  // 테마별로 "그 테마에 필요한 인식 항목"만 보여준다 (직관적·심플)
  const _M=activeServiceMode;
  if(_M==='safety'){
    html+=`<div class="row"><span>작업자</span><b>${people}명</b></div>`;
    html+=`<div class="row"><span>안전모</span><b class="${helmetCls}">${helmetTxt}</b></div>`;
    html+=`<div class="row"><span>안전조끼</span><b class="${vestCls}">${vestTxt}</b></div>`;
    html+=`<div class="row"><span>자세</span><b class="${postCls}">${postTxt}</b></div>`;
    if(showFall) html+=`<div class="row"><span>낙상</span><b class="bad">감지됨</b></div>`;
    html+=`<div class="row"><span>화재/연기</span><b class="${hzCls}">${hzTxt}</b></div>`;
    html+=`<div class="row"><span>위험물</span><b>${topObjs.length?topObjs.join(', '):'—'}</b></div>`;
    const _z=axState.zoneSummary, _nh=axState.nearHazard;
    if(dangerZones.length) html+=`<div class="row"><span>구역 체류</span><b class="${_z.inside>0?'bad':'ok'}">${_z.inside}명${_z.maxDwell>0?' · '+_z.maxDwell.toFixed(0)+'s':''}</b></div>`;
    if(_nh){ const _m=_nh.meters; const _show=_m!=null?_m<5:_nh.d<0.25;
      if(_show) html+=`<div class="row"><span>위험물 거리</span><b class="${(_m!=null?_m<1.5:_nh.d<0.12)?'bad':'warn'}">${_m!=null?_m.toFixed(1)+'m':'근접'}</b></div>`; }
    let _spd=0,_kmh=0; for(const id in axState.tracks){ const t=axState.tracks[id]; if(t.speed>_spd)_spd=t.speed; if(t.kmh>_kmh)_kmh=t.kmh; }
    if(axCal.H){ if(_kmh>0.3) html+=`<div class="row"><span>이동 속도</span><b class="${_kmh>5?'warn':'ok'}">${_kmh.toFixed(1)} km/h</b></div>`; }
    else if(_spd>0.02) html+=`<div class="row"><span>이동 속도</span><b class="${_spd>0.6?'warn':'ok'}">${_spd>0.6?'빠름':'정상'}</b></div>`;
    if(axCal.H) html+=`<div class="row"><span>거리 보정</span><b class="ok">${axCal.info||'적용됨'}</b></div>`;
  }else if(_M==='fitness'){
    html+=`<div class="row"><span>사람</span><b>${people}명</b></div>`;
    html+=`<div class="row"><span>운동 자세</span><b class="${postCls}">${postTxt}</b></div>`;
    const _g=axState.gym;
    html+=`<div class="row"><span>${_g.exName||'운동'}</span><b>${_g.count||0}회</b></div>`;
    if(_g.angle!=null) html+=`<div class="row"><span>각도</span><b class="${_g.phase==='down'?'warn':'ok'}">${_g.angle}° · ${_g.cue||''}</b></div>`;
    const fresh = rppg.lastBpm && (performance.now()/1000 - rppg.lastBpmAt < 5);
    let hr, hrCls;
    if(fresh){ const z=hrZone(rppg.lastBpm); hr=`${rppg.lastBpm} bpm · ${z.label}` + (rppg.quality<3?' (약함)':''); hrCls=z.cls; }
    else if(rppg.buf.length>10){ hr='측정 중…(얼굴 정지)'; hrCls='dim'; }
    else { hr='얼굴이 보이게'; hrCls='dim'; }
    html+=`<div class="row"><span>심박수</span><b class="${hrCls}">${hr}</b></div>`;
  }else{ // office — 데스크 자세 케어
    html+=`<div class="row"><span>사람</span><b>${people}명</b></div>`;
    html+=`<div class="row"><span>데스크 자세</span><b class="${postCls}">${postTxt}</b></div>`;
    const _fb={ok:'좋은 자세 유지 중',warn:'거북목·어깨 확인',bad:'자세 교정 필요',dim:'상체가 보이게 앉기'}[postCls]||'';
    html+=`<div class="row"><span>피드백</span><b class="${postCls}">${_fb}</b></div>`;
    const _o=axState.office;
    if(_o){
      if(_o.shoulderTilt!=null) html+=`<div class="row"><span>어깨 기울기</span><b class="${_o.shoulderTilt>9?'warn':'ok'}">${_o.shoulderTilt}°</b></div>`;
      if(_o.neck!=null) html+=`<div class="row"><span>거북목</span><b class="${_o.neck>34?'bad':(_o.neck>24?'warn':'ok')}">${_o.neck}%</b></div>`;
      html+=`<div class="row"><span>자세 점수</span><b class="${_o.score>=80?'ok':(_o.score>=60?'warn':'bad')}">${_o.score}</b></div>`;
    }
    if(axState.postHist&&axState.postHist.length>3){
      const _sp='▁▂▃▄▅▆▇█', _h=axState.postHist.slice(-24);
      const _s=_h.map(v=>_sp[Math.min(7,Math.max(0,Math.floor(v/100*7)))]).join('');
      html+=`<div class="row"><span>점수 추세</span><b style="font-family:monospace;letter-spacing:-1px">${_s}</b></div>`;
    }
  }
  el.innerHTML=html;
}

// rPPG 심박수 (스포츠/피트니스 테마 전용) — 이마 피부 초록채널 미세변화로 비접촉 측정
const rppg = { buf: [], lastBpm: null, lastBpmAt: 0, lastEstAt: 0, quality: 0, bpmHist: [], lastLogAt: 0, source: '', lastBackendOk: 0, lastBackendTry: 0 };
function applyBpm(bpm, snr, source){
  rppg.bpmHist.push(bpm); if(rppg.bpmHist.length>5) rppg.bpmHist.shift();
  const s=[...rppg.bpmHist].sort((a,b)=>a-b);
  rppg.lastBpm=s[Math.floor(s.length/2)];          // 중앙값 안정화
  const now=performance.now()/1000; rppg.lastBpmAt=now; rppg.quality=snr; rppg.source=source;
  if(now-rppg.lastLogAt>10){                        // 10초마다 인식 기록
    rppg.lastLogAt=now; const z=hrZone(rppg.lastBpm);
    fetch(API_BASE+'/recognition/note',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({text:`❤️ 심박수 ${rppg.lastBpm} bpm · ${z.label} (${source})`})}).catch(()=>{});
  }
}
async function refineBpmBackend(){           // 서비스 내장: 백엔드 scipy로 정밀 계산
  const b=rppg.buf; if(b.length<64) return;
  const dur=b[b.length-1].t-b[0].t; if(dur<3) return;
  const fs=b.length/dur;
  try{
    const r=await fetch(API_BASE+'/vitals/rppg',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({samples:b.map(p=>p.g), fs})});
    const j=await r.json();
    if(j&&j.success){ rppg.lastBackendOk=performance.now()/1000; applyBpm(j.bpm, j.quality, '정밀'); }
  }catch(e){}
}
function hrZone(bpm){
  if(bpm<100) return {label:'저강도', cls:'ok'};
  if(bpm<140) return {label:'중강도', cls:'ok'};
  if(bpm<170) return {label:'고강도', cls:'warn'};
  return {label:'최대', cls:'bad'};
}
const _rppgCv = document.createElement('canvas'); _rppgCv.width = 40; _rppgCv.height = 25;
const _rppgCtx = _rppgCv.getContext('2d', { willReadFrequently: true });

function sampleHeartRate(face){
  if(activeServiceMode!=='fitness') return;        // 스포츠 테마에서만 동작
  if(!face || face.length < 400) return;
  const VW=videoEl.videoWidth||0, VH=videoEl.videoHeight||0;
  if(!VW||!VH) return;
  const top=face[10], bot=face[9], lft=face[67], rgt=face[297];   // 이마 영역
  if(!top||!bot||!lft||!rgt) return;
  const x1=Math.min(lft.x,rgt.x)*VW, x2=Math.max(lft.x,rgt.x)*VW;
  const y1=top.y*VH, y2=bot.y*VH;
  const w=x2-x1, h=y2-y1;
  if(w<8||h<6) return;
  try{
    _rppgCtx.drawImage(videoEl, x1,y1,w,h, 0,0,40,25);
    const d=_rppgCtx.getImageData(0,0,40,25).data;
    let g=0; for(let i=0;i<d.length;i+=4) g+=d[i+1];
    g/=(d.length/4);
    const t=performance.now()/1000;
    rppg.buf.push({t,g});
    const cutoff=t-12; while(rppg.buf.length && rppg.buf[0].t<cutoff) rppg.buf.shift();
    if(t-rppg.lastEstAt>1.0 && rppg.buf.length>=64){
      rppg.lastEstAt=t; estimateBPM();
      if(t-rppg.lastBackendTry>1.5){ rppg.lastBackendTry=t; refineBpmBackend(); }  // 서비스 내장 정밀계산
    }
  }catch(e){}
}

function estimateBPM(){
  const b=rppg.buf, n=b.length;
  const t0=b[0].t, dur=b[n-1].t-t0;
  if(dur<6) return;                                // 최소 6초 신호 필요
  const mean=b.reduce((a,c)=>a+c.g,0)/n;
  const sig=b.map(p=>p.g-mean);                    // detrend
  let bestF=0,bestP=0,sumP=0,cnt=0;
  for(let f=0.7; f<=4.0; f+=0.05){                 // 42~240 bpm 탐색
    let re=0,im=0;
    for(let i=0;i<n;i++){ const ph=2*Math.PI*f*(b[i].t-t0); re+=sig[i]*Math.cos(ph); im-=sig[i]*Math.sin(ph); }
    const p=re*re+im*im; sumP+=p; cnt++;
    if(p>bestP){bestP=p;bestF=f;}
  }
  const bpm=Math.round(bestF*60), snr=bestP/((sumP/cnt)||1);
  if(bpm>=42 && bpm<=200 && snr>=2){              // 품질 게이트
    if(performance.now()/1000 - rppg.lastBackendOk < 4) return;  // 백엔드 정밀값이 최신이면 양보
    applyBpm(bpm, snr, '간이');                   // 백엔드 미가용 시 JS 폴백
  }
}

// 기능3: 위험구역 — 점(꼭짓점)을 찍어 다각형으로 설정 → /zone/danger 저장
let dangerZones=[], zoneDrawMode=false, zonePoints=[], zoneCursor=null;   // 다중 위험구역
const ZONES_LS_KEY='ax_danger_zones';
function saveZonesLocal(){ try{ localStorage.setItem(ZONES_LS_KEY, JSON.stringify(dangerZones)); }catch(e){} }
function dangerZonePolys(){ return dangerZones.map(z=>zonePolygon(z)).filter(p=>p&&p.length>=3); }   // 모든 구역 폴리곤
async function loadDangerZone(){
  try{ const s=localStorage.getItem(ZONES_LS_KEY); if(s){ const a=JSON.parse(s); if(Array.isArray(a)){ dangerZones=a; return; } } }catch(e){}
  // 마이그레이션: 로컬에 없으면 백엔드 단일 구역을 1개로 가져옴
  try{ const r=await fetch(API_BASE+'/zone/danger'); const j=await r.json(); if(j.success && j.zone && zonePolygon(j.zone)) dangerZones=[j.zone]; }catch(e){}
}
// 저장된 구역 → 다각형 점 배열(정규화). 구버전 사각형도 자동 지원.
function zonePolygon(z){
  if(!z) return null;
  if(Array.isArray(z.points) && z.points.length>=3) return z.points;
  if(typeof z.x1==='number') return [{x:z.x1,y:z.y1},{x:z.x2,y:z.y1},{x:z.x2,y:z.y2},{x:z.x1,y:z.y2}];
  return null;
}
// 점(px,py)이 다각형 pts 안에 있는지 (ray casting)
function pointInPoly(px,py,pts){
  let inside=false;
  for(let i=0,j=pts.length-1;i<pts.length;j=i++){
    const xi=pts[i].x,yi=pts[i].y,xj=pts[j].x,yj=pts[j].y;
    if(((yi>py)!==(yj>py)) && (px < (xj-xi)*(py-yi)/((yj-yi)||1e-9)+xi)) inside=!inside;
  }
  return inside;
}
function drawDangerZone(W,H){
  // 저장된 모든 구역
  for(const pts of dangerZonePolys()) _drawZonePoly(pts,W,H,false);
  // 그리는 중인 구역(미리보기)
  if(zoneDrawMode && zonePoints.length>0) _drawZonePoly(zonePoints,W,H,true);
}
function _drawZonePoly(pts,W,H,drawing){
  if(!pts || pts.length===0) return;
  const col = dzActive ? '#ff3030' : '#ef4444';
  const P = pts.map(p=>[p.x*W, p.y*H]);
  ctx.save();
  // 면 채움(3점 이상)
  if(P.length>=3){
    ctx.beginPath(); ctx.moveTo(P[0][0],P[0][1]); for(let i=1;i<P.length;i++)ctx.lineTo(P[i][0],P[i][1]); ctx.closePath();
    ctx.fillStyle='rgba(239,68,68,'+(dzActive?0.24:0.14)+')'; ctx.fill();
  }
  // 외곽선(점들을 순서대로 연결)
  ctx.strokeStyle=col; ctx.lineWidth=2; ctx.lineJoin='round';
  ctx.beginPath(); ctx.moveTo(P[0][0],P[0][1]); for(let i=1;i<P.length;i++)ctx.lineTo(P[i][0],P[i][1]);
  if(!drawing && P.length>=3) ctx.closePath();
  ctx.stroke();
  // 그리는 중: 마지막 점 → 커서까지 점선 미리보기
  if(drawing && zoneCursor){
    ctx.setLineDash([6,5]); ctx.beginPath();
    ctx.moveTo(P[P.length-1][0],P[P.length-1][1]); ctx.lineTo(zoneCursor.x*W,zoneCursor.y*H); ctx.stroke();
    ctx.setLineDash([]);
  }
  // 꼭짓점 핸들(시작점은 더 크게 — 여기 다시 클릭하면 완료)
  for(let i=0;i<P.length;i++){
    const first=(i===0&&drawing);
    ctx.beginPath(); ctx.arc(P[i][0],P[i][1], first?7:5, 0, Math.PI*2);
    ctx.fillStyle=first?'#fff':col; ctx.fill();
    ctx.lineWidth=2; ctx.strokeStyle=col; ctx.stroke();
  }
  ctx.font='bold 13px Segoe UI'; ctx.fillStyle=col;
  ctx.fillText(drawing?('⚠ 위험구역 그리는 중 ('+P.length+'점)'):'⚠ 위험구역', P[0][0]+8, P[0][1]-9);
  ctx.restore();
}

// 위험구역 침입 감지 → 화면 경고 배너 + 알람음
let dzMuted=false, dzConsec=0, dzActive=false, dzAlarmTimer=null, dzAudio=null;
let dzDangerConsec=0, dzWarnConsec=0;   // 신체부위별 차등(몸통=위험, 손/팔=경고)
function dzBeep(){
  if(dzMuted) return;
  try{
    if(!dzAudio) dzAudio=new (window.AudioContext||window.webkitAudioContext)();
    if(dzAudio.state==='suspended') dzAudio.resume();
    const o=dzAudio.createOscillator(), g=dzAudio.createGain();
    o.type='square'; o.frequency.value=900;
    g.gain.setValueAtTime(0.0001,dzAudio.currentTime);
    g.gain.exponentialRampToValueAtTime(0.18,dzAudio.currentTime+0.02);
    g.gain.exponentialRampToValueAtTime(0.0001,dzAudio.currentTime+0.28);
    o.connect(g); g.connect(dzAudio.destination); o.start(); o.stop(dzAudio.currentTime+0.3);
  }catch(e){}
}
function checkDangerZone(objects,W,H,scX,scY){
  const polys=dangerZonePolys();
  if(!polys.length) return false;
  const persons=(objects||[]).filter(o=>o.class==='person');
  for(const o of persons){
    const a=displayBboxArray(scaleBbox(o.bbox,scX,scY),W,H);   // 화면(캔버스) 좌표
    const cx=(a[0]+a[2]/2)/W, cy=(a[1]+a[3]/2)/H;              // 정규화 중심
    for(const pts of polys){ if(pointInPoly(cx,cy,pts)) return true; }   // 어느 구역이든 진입 시
  }
  return false;
}
// 위험구역 침입 증거 캡처: 영상+오버레이 합성 프레임 + 사유 → 백엔드 저장(위험성평가 반영)
let dzCaptureAt=0;
function captureIntrusionEvidence(frame){
  const now=Date.now(); if(now-dzCaptureAt<8000) return;     // 8초 쿨다운(중복 방지)
  const polys=dangerZonePolys(); if(!polys.length) return;
  const W=frame.W,H=frame.H;
  // 구역 내 작업자 수(어느 구역이든)
  let inZone=0;
  for(const o of (frame.latestObjects||[])){
    if(o.class!=='person') continue;
    const a=displayBboxArray(scaleBbox(o.bbox,frame.scX,frame.scY),W,H);
    const cx=(a[0]+a[2]/2)/W, cy=(a[1]+a[3]/2)/H;
    if(polys.some(pts=>pointInPoly(cx,cy,pts))) inZone++;
  }
  // 사유: 위험구역 접근 + (정밀보정 신선 시) 보호구 미착용
  const reasons=['위험구역 접근'];
  const fresh=backendBoostDets.length && (Date.now()-backendBoostAt<BACKEND_BOOST_TTL+2000);
  if(fresh){ const cls=backendBoostDets.map(d=>String(d.class).toLowerCase().replace(/-/g,' '));
    if(cls.includes('no hardhat')||cls.includes('no helmet')) reasons.push('안전모 미착용');
    if(cls.includes('no safety vest')||cls.includes('no vest')) reasons.push('안전조끼 미착용'); }
  // 합성 스냅샷(검은 배경 + 영상 + 오버레이 박스/구역) → 증거 사진
  const oc=document.createElement('canvas'); oc.width=W; oc.height=H; const octx=oc.getContext('2d');
  octx.fillStyle='#000'; octx.fillRect(0,0,W,H);
  try{ const r=mediaRect(W,H);
    if(shouldFlipDisplay()){ octx.save(); octx.translate(r.x+r.w,r.y); octx.scale(-1,1); octx.drawImage(videoEl,0,0,r.w,r.h); octx.restore(); }
    else octx.drawImage(videoEl,r.x,r.y,r.w,r.h);
  }catch(e){}
  try{ octx.drawImage(canvas,0,0); }catch(e){}
  let img; try{ img=oc.toDataURL('image/jpeg',0.7); }catch(e){ return; }
  dzCaptureAt=now;
  const vlmOn = !!document.getElementById('togVlmConfirm')?.checked;   // safety 화면에만 존재(없으면 false)
  fetch(API_BASE+'/zone/intrusion',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({image_base64:img, people:inZone, reasons, zone:'위험구역A', vlm_confirm:vlmOn})})
    .then(r=>r.json()).then(j=>{ if(j&&j.suppressed) console.info('[VIGENT] 🧠 VLM 오탐 필터 — 침입 알림 억제(증거는 저장)'); }).catch(()=>{});
}
// 위험구역 점유 상태를 서버에 푸시(아두이노 E-stop 폴링용)
function pushZoneState(active){
  try{ fetch(API_BASE+'/zone/state',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({zone:'위험구역A',active:!!active})}); }catch(e){}
}
// 키포인트(소스 좌표) → 정규화 캔버스 좌표(레터박스/미러 반영) — pointInPoly와 동일 좌표계
function kpToNorm(kx,ky,W,H,scX,scY){
  const r=mediaRect(W,H); const flip=shouldFlipDisplay();
  const sx=kx*scX, sy=ky*scY;
  return [(r.x+(flip? r.w-sx : sx))/W, (r.y+sy)/H];
}
// 손바닥/손끝 추정 — COCO-17엔 손 키포인트가 없어 팔꿈치→손목 방향으로 연장해 추정(보조 경고용).
// 손이 구역에 들어가기 전에 미리 잡히도록 손끝까지 포함(안전측).
function _estHandPoints(kp,cf){
  const out=[];
  for(const [el,wr] of [[7,9],[8,10]]){   // (왼팔꿈치,왼손목),(오른팔꿈치,오른손목)
    if(!kp[el]||!kp[wr]||(cf[el]??1)<0.3||(cf[wr]??1)<0.3) continue;
    const dx=kp[wr][0]-kp[el][0], dy=kp[wr][1]-kp[el][1];   // 팔뚝 방향
    out.push([kp[wr][0]+dx*0.35, kp[wr][1]+dy*0.35]);       // 손바닥 추정
    out.push([kp[wr][0]+dx*0.75, kp[wr][1]+dy*0.75]);       // 손끝 추정
  }
  return out;
}
// 위험구역 침입 심각도: 'danger'(몸통/머리/다리 등) | 'warning'(손/팔/손바닥) | 'none'
// 포즈 키포인트가 있으면 부위별로 판정, 없으면 박스 기준(기존 동작 = danger) 폴백.
const FOREARM_KP=new Set([7,8,9,10]);   // COCO-17: 팔꿈치(7,8)·손목(9,10) = 손끝~팔꿈치 구간
function zoneIntrusionSeverity(frame){
  const polys=dangerZonePolys();
  if(!polys.length) return 'none';
  const W=frame.W,H=frame.H,scX=frame.scX,scY=frame.scY;
  const inAny=(nx,ny)=>polys.some(pts=>pointInPoly(nx,ny,pts));   // 어느 구역이든
  if(poseFresh() && backendPoses.length){
    let core=false, forearm=false;
    for(const p of backendPoses){
      const kp=p.points, cf=p.conf||[];
      for(let i=0;i<kp.length && i<17;i++){
        if((cf[i]??1)<0.3 || !kp[i]) continue;
        const n=kpToNorm(kp[i][0],kp[i][1],W,H,scX,scY);
        if(!inAny(n[0],n[1])) continue;
        if(FOREARM_KP.has(i)) forearm=true; else core=true;   // 손/팔 vs 그 외 신체
      }
      // 손바닥/손끝(추정)도 경고 대상 — 손목이 구역 밖이어도 손이 들어가면 잡힘
      for(const h of _estHandPoints(kp,cf)){
        const n=kpToNorm(h[0],h[1],W,H,scX,scY);
        if(inAny(n[0],n[1])) forearm=true;
      }
    }
    if(core) return 'danger';      // 몸통·머리·다리 등 → 본격 경보
    if(forearm) return 'warning';  // 손/팔만 → 경고
    return 'none';
  }
  // 폴백(포즈 없음/비안전): 박스 중심 기준 → danger (기존 동작 유지, 저하 없음)
  return checkDangerZone(frame.latestObjects,W,H,scX,scY) ? 'danger' : 'none';
}
let _zoneHbAt=0;
function handleDangerZone(frame){
  const el=document.getElementById('dzAlert'), mute=document.getElementById('dzMute'), vc=document.getElementById('videoContainer');
  const _now=Date.now();                              // 1.5초 하트비트: 현재 상태를 주기적으로 갱신(신선도)
  if(_now-_zoneHbAt>1500){ _zoneHbAt=_now; pushZoneState(dzActive); }
  const sev = dangerZones.length ? zoneIntrusionSeverity(frame) : 'none';
  if(sev==='danger'){ dzDangerConsec++; dzWarnConsec=0; }
  else if(sev==='warning'){ dzWarnConsec++; dzDangerConsec=0; }
  else { dzDangerConsec=0; dzWarnConsec=0; }

  // ── 위험(몸통/머리/다리 등): 본격 경보 — 알람 + 증거/텔레그램 + E-stop ──
  if(dzDangerConsec>=3 && !dzActive){              // 3프레임 연속(오탐 방지)
    dzActive=true;
    if(el){ el.textContent='위험구역 침입 감지! 즉시 확인하세요'; el.classList.remove('warn'); el.classList.add('show'); }
    mute&&mute.classList.add('show'); vc&&vc.classList.remove('dz-warn'); vc&&vc.classList.add('dz-on');
    dzBeep(); dzAlarmTimer=setInterval(dzBeep,650);
    try{ captureIntrusionEvidence(frame); }catch(e){}   // 증거 사진 + /zone/intrusion(저장·텔레그램)
    pushZoneState(true);                                // E-stop 보조정지 신호
  } else if(dzDangerConsec===0 && dzActive){       // 위험 이탈 → 경보 해제
    dzActive=false;
    el&&el.classList.remove('show'); mute&&mute.classList.remove('show'); vc&&vc.classList.remove('dz-on');
    if(dzAlarmTimer){ clearInterval(dzAlarmTimer); dzAlarmTimer=null; }
    pushZoneState(false);
  }

  // ── 경고(손/팔만): 시각 경고만 — 알람·텔레그램·E-stop 없음. 위험 경보 중에는 표시 안 함 ──
  if(!dzActive){
    if(dzWarnConsec>=3){
      if(el && !el.classList.contains('warn')){ el.textContent='주의: 손/팔이 위험구역에 진입했습니다'; el.classList.add('warn'); el.classList.add('show'); }
      vc&&vc.classList.add('dz-warn');
    } else if(dzWarnConsec===0){
      if(el && el.classList.contains('warn')){ el.classList.remove('warn'); el.classList.remove('show'); }
      vc&&vc.classList.remove('dz-warn');
    }
  }
}
function initZoneUI(){
  const cv=document.getElementById('outputCanvas');
  const btn=document.getElementById('zoneBtn'), hint=document.getElementById('zoneHint');
  if(!cv||!btn) return;
  const norm=e=>{ const r=cv.getBoundingClientRect(); return {x:Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)), y:Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))}; };
  const setHint=t=>{ if(hint){ hint.textContent=t; hint.style.display=zoneDrawMode?'block':'none'; } };
  function enter(){ zoneDrawMode=true; zonePoints=[]; zoneCursor=null; btn.classList.add('active'); cv.style.cursor='crosshair';
    setHint('점을 클릭해 꼭짓점을 찍으세요 · 시작점 다시 클릭/더블클릭 = 완료 · 우클릭 = 한 점 취소'); }
  function cancel(){ zoneDrawMode=false; zonePoints=[]; zoneCursor=null; btn.classList.remove('active'); cv.style.cursor=''; if(hint)hint.style.display='none'; }
  async function finish(){
    if(zonePoints.length<3){ setHint('꼭짓점을 3개 이상 찍어주세요 (현재 '+zonePoints.length+'개)'); return; }
    const z={points:zonePoints.map(p=>({x:+p.x.toFixed(4),y:+p.y.toFixed(4)}))};
    dangerZones.push(z); saveZonesLocal();                 // 구역 추가(여러 개 설정 가능)
    try{ fetch(API_BASE+'/zone/danger',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(z)}); }catch(err){}  // 백엔드 최신 구역(서버측/E-stop 호환)
    cancel();
  }
  btn.addEventListener('click',()=>{ if(zoneDrawMode) cancel(); else enter(); });
  // 위험구역 삭제(전체) — 그리는 중이면 취소까지
  const clearBtn=document.getElementById('zoneClearBtn');
  if(clearBtn) clearBtn.addEventListener('click',()=>{ if(zoneDrawMode) cancel(); dangerZones=[]; saveZonesLocal(); });
  cv.addEventListener('click',e=>{
    if(!zoneDrawMode) return;
    const p=norm(e);
    if(zonePoints.length>=3){                          // 시작점 근처 다시 클릭 → 닫고 완료
      const f=zonePoints[0];
      if(Math.hypot(p.x-f.x,p.y-f.y)<0.025){ finish(); return; }
    }
    const last=zonePoints[zonePoints.length-1];         // 더블클릭으로 생기는 중복 점 방지
    if(last && Math.hypot(p.x-last.x,p.y-last.y)<0.012) return;
    zonePoints.push(p);
    setHint('꼭짓점 '+zonePoints.length+'개 · 시작점 다시 클릭/더블클릭 = 완료 · 우클릭 = 취소');
  });
  cv.addEventListener('mousemove',e=>{ if(zoneDrawMode) zoneCursor=norm(e); });
  cv.addEventListener('dblclick',e=>{ if(zoneDrawMode){ e.preventDefault(); finish(); } });
  cv.addEventListener('contextmenu',e=>{ if(zoneDrawMode){ e.preventDefault(); if(zonePoints.length>0){ zonePoints.pop(); setHint('꼭짓점 '+zonePoints.length+'개 · 우클릭으로 더 취소 가능'); } else cancel(); } });
  window.addEventListener('keydown',e=>{ if(zoneDrawMode && e.key==='Escape') cancel(); });
}
loadDangerZone();
if(document.readyState!=='loading'){ initZoneUI(); initCalUI(); initThermUI(); } else window.addEventListener('DOMContentLoaded', ()=>{ initZoneUI(); initCalUI(); initThermUI(); });

// ═══════════════════════════════════════════════════
//  UI 업데이트
// ═══════════════════════════════════════════════════
function updateHandUI(lHeld,rHeld,lMN,rMN,lLM,rLM){
  if(!document.getElementById('lhandStatus')) return;   // 손/물체 패널 없는 테마 페이지
  // 왼손 상태
  const ls=document.getElementById('lhandStatus');
  ls.textContent=lLM?'✅ 감지됨':'❌ 미감지'; ls.className='value '+(lLM?'green':'');
  const rs=document.getElementById('rhandStatus');
  rs.textContent=rLM?'✅ 감지됨':'❌ 미감지'; rs.className='value '+(rLM?'green':'');
  updateSimpleHandResult(lHeld,rHeld,!!lLM,!!rLM);

  // 왼손 사물
  document.getElementById('leftHandItems').innerHTML=lHeld.length===0
    ?'<div class="no-data"><span class="icon">🤚</span>'+(lLM?'들고 있는 사물 없음':'왼손 미감지')+'</div>'
    :lHeld.map(o=>`<div class="held-item left-hand"><span class="held-hand-tag L">L</span><div class="held-info"><div class="held-name">${classIcon(o.class)} ${translateClass(o.class)}</div><div class="held-sub">${o.class}</div></div><div class="held-conf" style="color:var(--lhand)">${(o.score*100).toFixed(0)}%</div></div>`).join('');

  // 오른손 사물
  document.getElementById('rightHandItems').innerHTML=rHeld.length===0
    ?'<div class="no-data"><span class="icon">🤚</span>'+(rLM?'들고 있는 사물 없음':'오른손 미감지')+'</div>'
    :rHeld.map(o=>`<div class="held-item right-hand"><span class="held-hand-tag R">R</span><div class="held-info"><div class="held-name">${classIcon(o.class)} ${translateClass(o.class)}</div><div class="held-sub">${o.class}</div></div><div class="held-conf" style="color:var(--rhand)">${(o.score*100).toFixed(0)}%</div></div>`).join('');

  // MobileNet 결과
  const fmtMN=preds=>preds.slice(0,3).map(p=>`${translateMN(p.className)} (${(p.probability*100).toFixed(0)}%)`).join('<br>');
  document.getElementById('leftMobileNet').innerHTML=lMN.length?fmtMN(lMN):'—';
  document.getElementById('rightMobileNet').innerHTML=rMN.length?fmtMN(rMN):'—';

  // 비디오 위 오버레이 업데이트
  const overlay=document.getElementById('handHeldOverlay');
  let html='';
  const lBest=lMN[0]?translateMN(lMN[0].className):lHeld[0]?translateClass(lHeld[0].class):null;
  const rBest=rMN[0]?translateMN(rMN[0].className):rHeld[0]?translateClass(rHeld[0].class):null;
  if(lBest) html+=`<div class="hand-pill left"><div class="hand-dot left"></div>왼손: ${lBest}</div>`;
  if(rBest) html+=`<div class="hand-pill right"><div class="hand-dot right"></div>오른손: ${rBest}</div>`;
  overlay.innerHTML=html;

  setDot('dotHand',(lLM||rLM)?'active':'');
}

function updateSimpleHandResult(lHeld,rHeld,lHas,rHas){
  const card=document.getElementById('handSimpleCard');
  if(!card) return;
  const title=document.getElementById('handResultTitle');
  const desc=document.getElementById('handResultDesc');
  const guide=document.getElementById('handSimpleGuide');
  const left=document.getElementById('leftSimpleStatus');
  const right=document.getElementById('rightSimpleStatus');
  const leftNames=lHeld.map(o=>o.label||translateClass(o.class)).slice(0,2);
  const rightNames=rHeld.map(o=>o.label||translateClass(o.class)).slice(0,2);
  left.textContent=leftNames.length?leftNames.join(', '):(lHas?'손만 감지':'미감지');
  right.textContent=rightNames.length?rightNames.join(', '):(rHas?'손만 감지':'미감지');

  const all=[
    ...lHeld.map(o=>({...o,hand:'왼손'})),
    ...rHeld.map(o=>({...o,hand:'오른손'}))
  ];
  const danger=all.filter(o=>DANGER_OBJ.includes(o.class)||o.class==='cigarette');

  if(danger.length){
    card.className='simple-result danger';
    guide.className='simple-guide danger';
    title.textContent=`주의 물체 감지: ${danger.map(o=>o.label||translateClass(o.class)).join(', ')}`;
    desc.textContent=`${danger[0].hand}에서 주의가 필요한 물체를 확인했습니다. 실제 상황이 맞는지 화면을 보고 확인하세요.`;
    guide.textContent='산업안전 모드라면 보호구, 작업 구역, 도구 사용 상태를 함께 확인하세요.';
  }else if(all.length){
    card.className='simple-result good';
    guide.className='simple-guide';
    title.textContent=`손에 든 물체: ${all.map(o=>o.label||translateClass(o.class)).slice(0,3).join(', ')}`;
    desc.textContent='손과 물체가 함께 감지됐습니다. 더 정확히 보려면 물체를 카메라 중앙에 1초 정도 유지하세요.';
    guide.textContent='정확도가 낮게 느껴지면 조명을 밝게 하고 손과 배경이 겹치지 않게 해주세요.';
  }else if(lHas||rHas){
    card.className='simple-result warn';
    guide.className='simple-guide warn';
    title.textContent='손은 보이지만 물체는 아직 뚜렷하지 않습니다';
    desc.textContent='손 주변의 물체가 작거나 가려져 있으면 사물명이 표시되지 않을 수 있습니다.';
    guide.textContent='물체를 손바닥 앞쪽에 두고 카메라 중앙에 더 크게 보여주세요.';
  }else{
    card.className='simple-result warn';
    guide.className='simple-guide warn';
    title.textContent='손에 든 물체를 확인 중입니다';
    desc.textContent='손과 물체가 카메라 중앙에 보이면 무엇을 들고 있는지 한 문장으로 표시합니다.';
    guide.textContent='손이 화면 가장자리나 어두운 곳에 있으면 감지가 어려울 수 있습니다.';
  }
}

function updateObjectUI(tracked){
  const visible=tracked.filter(o=>o.gone===0);
  const sc=inferScene(visible);
  document.getElementById('sceneLabel').textContent=sc.scene;
  document.getElementById('sceneTags').innerHTML=sc.tags.map(t=>`<span class="scene-tag">${t}</span>`).join('');
  document.getElementById('objCount').textContent=visible.length;
  document.getElementById('statTotal').textContent=visible.length;
  document.getElementById('statUniq').textContent=new Set(visible.map(o=>o.class)).size;
  document.getElementById('statHeld').textContent=leftHeldObjects.length+rightHeldObjects.length;
  document.getElementById('statDanger').textContent=visible.filter(o=>DANGER_OBJ.includes(o.class)).length;
  const cmap={safe:'#10b981',caution:'#f59e0b',danger:'#ef4444'};
  document.getElementById('objList').innerHTML=visible.length===0
    ?'<div class="no-data"><span class="icon">🔍</span>감지된 사물 없음</div>'
    :visible.map(o=>{const tag=safetyTag(o.class);const isLH=leftHeldObjects.some(l=>iou(l.bbox,o.bbox)>.4);const isRH=rightHeldObjects.some(r=>iou(r.bbox,o.bbox)>.4);const glowCls=isLH?'held-glow-L':isRH?'held-glow-R':'';return`<div class="obj-item ${glowCls}"><span class="obj-id">#${o.id||'—'}</span><div class="obj-icon">${classIcon(o.class)}</div><div class="obj-info"><div class="obj-name">${translateClass(o.class)}${isLH?' 🟢':isRH?' 🟠':''}</div><div class="obj-conf">${o.class} · ${(o.score*100).toFixed(0)}%</div><div class="conf-bar"><div class="conf-fill" style="width:${o.score*100}%;background:${cmap[tag.cls]}"></div></div></div><div class="obj-badge ${tag.cls}">${tag.label}</div></div>`;}).join('');
  setDot('dotObj','active');
}

function updateVisionTaskLive(ar){
  const visible=latestObjects.filter(o=>o.gone===0);
  const classes=[...new Set(visible.map(o=>translateClass(o.class)))];
  const tracked=visible.filter(o=>o.id);
  const set=(id,text)=>{const el=document.getElementById(id);if(el) el.textContent=text;};
  set('taskClassificationLive',classes.length?`${classes.slice(0,4).join(', ')} 등 ${classes.length}종`:'분류 대기 중');
  set('taskDetectionLive',visible.length?`${visible.length}개 객체 위치 표시 중`:'탐지 대기 중');
  set('taskSegmentationLive',visible.length?`${visible.length}개 객체 bbox 기반 분할 후보`:'분할 후보 대기 중');
  const scene=inferScene(visible);
  const people=Math.max(detectedPersonCount,sm?1:0);
  set('taskCaptioningLive',visible.length||people?`${scene.scene} · 사람 ${people}명 · ${ar?actionText(ar):'행동 분석 중'}`:'캡션 대기 중');
  set('taskTrackingLive',tracked.length?`ID ${tracked.map(o=>'#'+o.id).slice(0,5).join(', ')} 추적 중`:'추적 대기 중');
  set('taskActionLive',ar?`${ar.icon||''} ${ar.action} ${ar.confidence?Math.round(ar.confidence*100)+'%':''}`:'행동 대기 중');
}

function actionText(ar){
  return ar&&ar.action?ar.action:'분석 중';
}

async function loadVisionCapabilities(){
  const box=document.getElementById('visionTaskResult');
  if(!box) return;
  box.textContent='기능 상태 확인 중...';
  try{
    const res=await fetch(API_BASE+'/vision/capabilities');
    const data=await res.json();
    if(!res.ok) throw new Error(data.detail||'기능 상태 조회 실패');
    box.textContent=(data.capabilities||[]).map(c=>`${c.name} [${c.status}]\n- ${c.description}\n- 구현: ${c.current_implementation}`).join('\n\n');
  }catch(e){
    box.textContent='기능 상태 조회 실패: '+(e.message||e);
  }
}

async function analyzeCurrentVisionFrame(){
  const box=document.getElementById('visionTaskResult');
  if(!box) return;
  box.textContent='현재 카메라 프레임을 서버에서 분석 중...';
  try{
    const res=await fetch(API_BASE+'/vision/analyze-current');
    const data=await res.json();
    if(!res.ok) throw new Error(data.detail||'현재 프레임 분석 실패');
    const tasks=data.tasks||{};
    const lines=[
      `사람 수: ${data.people_count}`,
      `활동: ${data.activity}`,
      `장면: ${(data.scene&&data.scene.label)||'unknown'} (${Math.round(((data.scene&&data.scene.confidence)||0)*100)}%)`,
      '',
      `객체 분류: ${(tasks.object_classification?.classes||[]).map(x=>x.class+' '+x.count).join(', ')||'없음'}`,
      `객체 탐지/위치: ${tasks.object_detection_localization?.count||0}개`,
      `객체 분할: ${tasks.object_segmentation?.count||0}개 (${tasks.object_segmentation?.mode||'proxy'})`,
      `이미지 캡셔닝: ${tasks.image_captioning?.caption||'-'}`,
      `객체 추적: ${tasks.object_tracking?.count||0}개`,
      `행동 분류: ${(tasks.action_classification?.actions||[]).map(a=>'#'+(a.track_id||'-')+' '+a.action).join(', ')||'없음'}`,
      '',
      JSON.stringify(tasks,null,2)
    ];
    box.textContent=lines.join('\n');
  }catch(e){
    box.textContent='현재 프레임 분석 실패: '+(e.message||e)+'\n카메라가 켜져 있는지 확인하세요.';
  }
}

function updateFaceUI(f){
  if(!document.getElementById('faceDetected')) return;   // 얼굴 패널 없는 테마 페이지
  const ok=f&&f.length>0;
  const fd=document.getElementById('faceDetected');
  fd.textContent=ok?'✅ 감지됨':'❌ 미감지'; fd.className='value '+(ok?'green':'');
  if(!ok){['faceLandmarks','faceGender','faceAge','faceDirection','eyeBlink','mouthState','focusScore'].forEach(id=>{const e=document.getElementById(id);if(e)e.textContent='—';});document.getElementById('emotionBars').innerHTML='<div class="no-data"><span class="icon">😶</span>얼굴을 카메라에 비춰주세요</div>';return;}
  document.getElementById('faceLandmarks').textContent=`${f.length}개`;
  const dir=getFaceDir(f); document.getElementById('faceDirection').textContent=dir;
  const g=estimateGender(f); if(g) document.getElementById('faceGender').textContent=`${g.icon} ${g.gender} (~${g.conf}%)`;
  document.getElementById('faceAge').textContent=(estimateAge(f)||'—')+' (추정)';
  const earL=dist(f[159],f[145])/(dist(f[33],f[133])||1), earR=dist(f[386],f[374])/(dist(f[362],f[263])||1), ear=(earL+earR)/2;
  document.getElementById('eyeBlink').textContent=ear<.15?'😴 감김':ear<.22?'😑 반감김':'👁 열림';
  if(f[13]&&f[14]&&f[61]&&f[291]) document.getElementById('mouthState').textContent=dist(f[13],f[14])/(dist(f[61],f[291])||1)>.22?'👄 열림':'😶 닫힘';
  document.getElementById('focusScore').textContent=dir==='정면'?(ear<.15?'😴 졸음 주의':'✅ 집중'):`⚠️ ${dir} 시선`;
  const em=detectEmotion(f); const ec={'기쁨':'#10b981','중립':'#94a3b8','놀람':'#f59e0b','졸음':'#7c3aed'};
  if(em) document.getElementById('emotionBars').innerHTML=Object.entries(em).map(([n,v])=>`<div class="emotion-bar"><div class="emotion-label">${n}</div><div class="emotion-track"><div class="emotion-fill" style="width:${v}%;background:${ec[n]||'#fff'}"></div></div><div class="emotion-val" style="color:${ec[n]}">${v}%</div></div>`).join('');
  setDot('dotFace','active');
}

function updatePoseUI(lm,sm){
  if(!lm) return;
  if(!document.getElementById('angTrunk')) return;   // 자세 패널 없는 테마 페이지
  const st=(id,v)=>document.getElementById(id).textContent=v!==null?v+'°':'—';
  st('angLElbow',calcAngle(lm[11],lm[13],lm[15])); st('angRElbow',calcAngle(lm[12],lm[14],lm[16]));
  st('angLKnee',calcAngle(lm[23],lm[25],lm[27])); st('angRKnee',calcAngle(lm[24],lm[26],lm[28]));
  st('angLHip',calcAngle(lm[11],lm[23],lm[25])); st('angRHip',calcAngle(lm[12],lm[24],lm[26]));
  const trunk=getTrunkTilt(lm); document.getElementById('angTrunk').textContent=trunk?trunk.toFixed(0)+'°':'—';
  const lS=lm[11],rS=lm[12]; if(lS&&rS) document.getElementById('angShoulder').textContent=Math.abs(Math.atan2(rS.y-lS.y,rS.x-lS.x)*180/Math.PI).toFixed(0)+'°';
  const ar=smoothAction(recognizeAction(sm||lm));
  document.getElementById('poseAction').textContent=`${ar.icon} ${ar.action}`;
  const stab=trunk<10?'안정':trunk<25?'보통':'불안정';
  const se=document.getElementById('poseStability'); se.textContent=stab; se.className='value '+(stab==='안정'?'green':stab==='보통'?'yellow':'red');
  if(lS&&rS){const lH=lm[23],rH=lm[24];const d=(lS.x+rS.x)/2-(lH&&rH?(lH.x+rH.x)/2:(lS.x+rS.x)/2);document.getElementById('poseDirection').textContent=Math.abs(d)<.05?'정면':d<0?'왼쪽 향함':'오른쪽 향함';}
  const lA=lm[27],rA=lm[28],lH=lm[23],rH=lm[24];
  if(lA&&rA&&lH&&rH){const bd=Math.abs((lH.x+rH.x)/2-(lA.x+rA.x)/2);document.getElementById('poseBalance').textContent=bd<.05?'✅ 균형':bd<.1?'⚠ 약간 불균형':'❌ 불균형';}
  const velP=Math.min(100,hipVelocity*3000);
  const vf=document.getElementById('velFill'); vf.style.width=velP+'%'; vf.style.background=velP>60?'#ef4444':velP>30?'#f59e0b':'#10b981';
  document.getElementById('velVal').textContent=(hipVelocity*1000).toFixed(1);
  document.getElementById('velLabel').textContent=velP>60?'🏃 빠름':velP>30?'🚶 중간':'🧍 정지';
  document.getElementById('fallProgress').textContent=`${fallConfirm}/${FALL_CONFIRM}`;
  document.getElementById('fallProgFill').style.width=`${(fallConfirm/FALL_CONFIRM)*100}%`;
  setDot('dotPose','active');
  return smoothAction(recognizeAction(sm||lm));
}

function updateSafetyUI(ar,lm,objs){
  const issues=[]; let grade='safe';
  if(ar.danger){issues.push({type:'danger',icon:'🚨',title:'낙상 감지!',desc:'6프레임 연속 확인 · 즉각 확인 필요'});grade='danger';if(document.getElementById('togFall').checked)stats.fall++;}
  if(ar.warn){issues.push({type:'warn',icon:'⚠️',title:'낙상 위험',desc:'불안정한 자세 감지'});if(grade!=='danger')grade='warn';}
  if(lm&&document.getElementById('togPosture').checked){const t=getTrunkTilt(lm);if(t>35&&!ar.danger&&!ar.warn){issues.push({type:'warn',icon:'🙇',title:'불안정한 자세',desc:`몸통 기울기 ${t.toFixed(0)}°`});if(grade!=='danger')grade='warn';stats.posture++;}}
  if(document.getElementById('togObjSafe').checked){for(const o of objs){if(DANGER_OBJ.includes(o.class)){issues.push({type:'warn',icon:'🔪',title:`위험 사물: ${translateClass(o.class)}`,desc:`신뢰도 ${(o.score*100).toFixed(0)}%`});if(grade!=='danger')grade='warn';stats.obj++;}}}
  const ppeIssues=getPpeIssues();
  if(document.getElementById('togPPE')?.checked&&ppeIssues.length){
    ppeIssues.forEach(i=>issues.push(i));
    if(grade!=='danger') grade='warn';
  }
  const gm={safe:{text:'✅ 안전',cls:'green'},warn:{text:'⚠️ 주의',cls:'yellow'},danger:{text:'🚨 위험',cls:'red'}};
  const ge=document.getElementById('safetyGrade'); ge.textContent=gm[grade].text; ge.className='value '+gm[grade].cls;
  const fe=document.getElementById('fallRisk'); fe.textContent=ar.danger?'🔴 낙상!':ar.warn?'🟡 위험 징후':'🟢 정상'; fe.className='value '+(ar.danger?'red':ar.warn?'yellow':'green');
  const trunk=lm?getTrunkTilt(lm):0;
  const pe=document.getElementById('postureRisk'); pe.textContent=trunk>40?'🔴 위험':trunk>25?'🟡 주의':'🟢 정상'; pe.className='value '+(trunk>40?'red':trunk>25?'yellow':'green');
  const hd=objs.some(o=>DANGER_OBJ.includes(o.class));
  const oe=document.getElementById('objRisk'); oe.textContent=hd?'🔴 위험 사물!':'🟢 이상 없음'; oe.className='value '+(hd?'red':'green');
  document.getElementById('activityState').textContent=`${ar.icon} ${ar.action}`;
  document.getElementById('alertList').innerHTML=issues.length===0?'<div class="no-data"><span class="icon">✅</span>이상 없음</div>':issues.map(i=>`<div class="alert-box ${i.type}"><div class="alert-icon">${i.icon}</div><div class="alert-body"><div class="alert-title">${i.title}</div><div class="alert-desc">${i.desc}</div></div></div>`).join('');
  document.getElementById('statFall').textContent=stats.fall+'회';
  document.getElementById('statPosture').textContent=stats.posture+'회';
  document.getElementById('statObj').textContent=stats.obj+'회';
  document.getElementById('statTime').textContent=Math.round((Date.now()-startTime)/1000)+'s';
  setDot('dotSafe',grade==='safe'?'active':grade==='warn'?'warn':'danger');
  const ab=document.getElementById('actionBadge'),wb=document.getElementById('warnBadge'),db=document.getElementById('dangerBadge');
  if((document.getElementById('togActionLabel')?.checked??true)){ab.style.display='flex';document.getElementById('actionText').textContent=ar.action;}else ab.style.display='none';
  if(ar.danger){db.style.display='flex';wb.style.display='none';document.getElementById('dangerText').textContent='낙상 감지!';if(document.getElementById('togSound').checked)playAlert();}
  else if(ar.warn||ppeIssues.length){wb.style.display='flex';db.style.display='none';document.getElementById('warnText').textContent=ppeIssues.length?'보호구 확인':'주의';}
  else{wb.style.display='none';db.style.display='none';}
  updatePpeUI();
}

function getPpeIssues(){
  const issues=[];
  const h=latestPpeStatus.helmet, v=latestPpeStatus.vest;
  const fresh=Date.now()-(latestPpeStatus.updatedAt||0)<5000;
  if(!fresh) return issues;
  if(h.state==='missing') issues.push({type:'warn',icon:'⛑',title:'안전모 미착용 의심',desc:`머리 영역 분류: ${h.raw||'보호모 단서 없음'}`});
  if(v.state==='missing') issues.push({type:'warn',icon:'🦺',title:'안전조끼 미착용 의심',desc:`상체 영역 분류: ${v.raw||'조끼 단서 없음'}`});
  return issues;
}

function updatePpeUI(){
  const card=document.getElementById('ppeSimpleCard');
  if(!card) return;
  const h=latestPpeStatus.helmet, v=latestPpeStatus.vest;
  const fresh=Date.now()-(latestPpeStatus.updatedAt||0)<5000;
  const workerCount=Math.max(detectedPersonCount,sm?1:0);
  const statusText=(item)=>{
    if(!fresh||item.state==='unknown') return '확인 중';
    if(item.state==='worn') return `착용 추정 ${Math.round(item.confidence*100)}%`;
    return `미착용 의심 ${Math.round(item.confidence*100)}%`;
  };
  const workerEl=document.getElementById('ppeWorkerCount');
  if(workerEl) workerEl.textContent=workerCount>0?`${workerCount}명`:'미감지';
  document.getElementById('helmetStatus').textContent=statusText(h);
  document.getElementById('vestStatus').textContent=statusText(v);
  const title=document.getElementById('ppeResultTitle');
  const desc=document.getElementById('ppeResultDesc');
  const guide=document.getElementById('ppeGuide');
  const evidence=document.getElementById('ppeEvidence');
  const basis=document.getElementById('ppeModelBasis');
  const missing=[h.state==='missing'?'안전모':null,v.state==='missing'?'안전조끼':null].filter(Boolean);
  const worn=[h.state==='worn'?'안전모':null,v.state==='worn'?'안전조끼':null].filter(Boolean);
  if(evidence){
    const headRaw=fresh&&h.raw?`머리: ${h.raw} (${Math.round((h.confidence||0)*100)}%)`:'머리: 확인 중';
    const torsoRaw=fresh&&v.raw?`상체: ${v.raw} (${Math.round((v.confidence||0)*100)}%)`:'상체: 확인 중';
    const source=latestPpeStatus.source==='ppe_yolo'?'전용 PPE YOLO':'브라우저 경량 모델';
    evidence.textContent=`판단 근거(${source}): ${headRaw} · ${torsoRaw}`;
  }
  if(basis){
    basis.textContent=latestPpeStatus.source==='ppe_yolo'
      ? '안전모는 전용 YOLO 후보 모델 결과를 우선 사용합니다. 안전조끼는 Open Images에 직접 클래스가 부족해 별도 PPE 데이터가 필요합니다.'
      : '현재는 브라우저 경량 모델 보조 판정입니다. 백엔드 PPE 모델이 연결되면 안전모 인식 결과가 우선 표시됩니다.';
  }
  if(!fresh){
    card.className='simple-result warn'; guide.className='simple-guide warn';
    title.textContent='안전모와 안전조끼를 확인 중입니다';
    desc.textContent='작업자의 머리와 상체가 화면에 보이면 보호구 착용 여부를 표시합니다.';
    guide.textContent='카메라에 머리, 어깨, 상체가 함께 보이도록 맞춰주세요.';
  }else if(missing.length){
    card.className='simple-result danger'; guide.className='simple-guide danger';
    title.textContent=`작업자 ${workerCount||'?'}명 · ${missing.join(', ')} 미착용 의심`;
    desc.textContent='보호구 미착용 후보가 있어 관리자 확인이 필요합니다. 현재 판단은 경량 모델 기반 후보입니다.';
    guide.textContent='미착용이 맞다면 현재 장면 기록을 눌러 캡처 이미지와 함께 리포트에 남기세요.';
  }else if(worn.length){
    card.className='simple-result good'; guide.className='simple-guide';
    title.textContent=`작업자 ${workerCount||'?'}명 · ${worn.join(', ')} 착용 추정`;
    desc.textContent='보호구 착용 단서가 감지됐습니다. 조명과 각도를 유지하면 더 안정적으로 인식됩니다.';
    guide.textContent='전용 PPE 데이터로 학습하면 안전모/조끼 정확도를 더 높일 수 있습니다.';
  }else{
    card.className='simple-result warn'; guide.className='simple-guide warn';
    title.textContent='보호구 단서가 뚜렷하지 않습니다';
    desc.textContent='일반 카메라 조건에서 보호구가 작거나 가려지면 확실히 판단하기 어렵습니다.';
    guide.textContent='작업자의 상체가 더 크게 보이도록 카메라 각도를 조정하세요.';
  }
}

// 얼굴 분석 헬퍼
function estimateGender(f){if(!f||f.length<400)return null;const fW=dist(f[234],f[454]),fH=dist(f[10],f[152]),jW=dist(f[172],f[397]);if(!fH||!fW)return null;let s=0;if(fW/fH>.72)s++;if(jW/fW>.75)s++;if(dist(f[70],f[63])/fW>.08)s++;return s>=2?{gender:'남성 추정',icon:'👨',conf:Math.round(50+Math.abs(s-1.5)/1.5*35)}:{gender:'여성 추정',icon:'👩',conf:Math.round(50+Math.abs(s-1.5)/1.5*35)};}
function estimateAge(f){
  if(!f||f.length<400||!f[10]||!f[152]) return null;
  const faceH=dist(f[10],f[152]);
  if(!faceH||faceH<0.01) return null;
  const faceW=dist(f[234],f[454])||faceH;

  // 1. 눈 높이 비율 — 어린이일수록 눈이 얼굴 대비 크다
  const eyeH=((dist(f[159],f[145])||0)+(dist(f[386],f[374])||0))/2;
  const eyeHRatio=eyeH/faceH;

  // 2. 이마 비율 — 어린이일수록 이마가 크다 (눈썹~머리 꼭대기)
  const browY=((f[105]?.y||0)+(f[334]?.y||0))/2;
  const foreheadRatio=Math.abs(browY-(f[10]?.y||0))/faceH;

  // 3. 코~턱 비율 — 어른일수록 하안면이 길다
  const noseChinRatio=f[1]&&f[152]?dist(f[1],f[152])/faceH:0.33;

  // 4. 얼굴 폭/높이 비율 — 어린이일수록 얼굴이 동그랗다
  const aspectRatio=faceW/faceH;

  // 5. 눈 간격 — 어린이일수록 눈 사이가 상대적으로 넓다
  const eyeSpanRatio=f[33]&&f[263]?dist(f[33],f[263])/faceW:0.4;

  // 점수화 (높을수록 어린아이)
  let score=0;
  if(eyeHRatio>0.070) score+=3;
  else if(eyeHRatio>0.055) score+=2;
  else if(eyeHRatio>0.042) score+=1;

  if(foreheadRatio>0.34) score+=3;
  else if(foreheadRatio>0.28) score+=2;
  else if(foreheadRatio>0.22) score+=1;

  if(noseChinRatio<0.28) score+=3;
  else if(noseChinRatio<0.33) score+=2;
  else if(noseChinRatio<0.38) score+=1;

  if(aspectRatio>0.88) score+=2;
  else if(aspectRatio>0.80) score+=1;

  if(eyeSpanRatio>0.50) score+=2;
  else if(eyeSpanRatio>0.44) score+=1;

  // 분류 (최대 13점)
  if(score>=9)  return '어린이 👶 (10세 미만)';
  if(score>=6)  return '청소년 🧒 (10~19세)';
  if(score>=3)  return '청장년 🧑 (20~40대)';
  return '중장년 🧓 (50대 이상)';
}
function detectEmotion(f){if(!f||f.length<400||!f[13]||!f[14])return null;const mO=dist(f[13],f[14])/(dist(f[61],f[291])||1),earL=dist(f[159],f[145])/(dist(f[33],f[133])||1),earR=dist(f[386],f[374])/(dist(f[362],f[263])||1),ear=(earL+earR)/2,smS=((f[0]?.y||0)-((f[61]?.y||0)+(f[291]?.y||0))/2);let e={'기쁨':0,'중립':0,'놀람':0,'졸음':0};if(smS>.01)e['기쁨']=Math.min(100,Math.round(smS*2500));if(mO>.35)e['놀람']=Math.min(100,Math.round(mO*200));if(ear<.18)e['졸음']=Math.min(100,Math.round((.25-ear)*600));if(Object.values(e).reduce((a,b)=>a+b,0)<25)e['중립']=75;const t=Object.values(e).reduce((a,b)=>a+b,1);for(const k in e)e[k]=Math.round(e[k]/t*100);return e;}
function getFaceDir(f){if(!f||f.length<400||!f[1]||!f[33]||!f[263])return'—';const dx=f[1].x-(f[33].x+f[263].x)/2,dy=f[1].y-(f[33].y+f[263].y)/2;if(Math.abs(dx)<.03&&Math.abs(dy)<.03)return'정면';if(dx<-.05)return'왼쪽';if(dx>.05)return'오른쪽';return dy<0?'위쪽':'아래쪽';}

// ═══════════════════════════════════════════════════
//  HOLISTIC 콜백 (메인 루프)
// ═══════════════════════════════════════════════════
function buildCoreFrameState(results,W,H,VW,VH,rect,scX,scY,rawPose,smoothedPose,face,lHandLM,rHandLM){
  const action=smoothAction(recognizeAction(smoothedPose));
  const genderInfo=face&&face.length>0?estimateGender(face):null;
  const ageInfo=face&&face.length>0?estimateAge(face):null;
  const visibleObjects=latestObjects.filter(o=>o.gone===0);
  const specialActions=detectSpecialActions(lHandLM,rHandLM,smoothedPose,face,leftHeldObjects,rightHeldObjects);
  return {
    results,W,H,VW,VH,rect,scX,scY,
    rawPose,
    pose:smoothedPose,
    face,
    leftHandLM:lHandLM,
    rightHandLM:rHandLM,
    leftHandBBox:cachedLBBox,
    rightHandBBox:cachedRBBox,
    leftHeldObjects,
    rightHeldObjects,
    latestObjects,
    visibleObjects,
    leftMobileNetResult,
    rightMobileNetResult,
    action,
    genderInfo,
    ageInfo,
    specialActions,
    serviceMode:activeServiceMode,
    timestamp:Date.now()
  };
}

// ★ 좌표 스케일 race 계측(2026-07-12): 캡처 시점 frame 기준값 vs 렌더 시점 실제값이 어긋나는 순간만 로그(조용한 race 포획).
let _coordMismLast=0;
function _coordMismatchTelemetry(frame,nowVW,nowVH,nowW,nowH){
  const mism=(frame.VW&&nowVW&&frame.VW!==nowVW)||(frame.VH&&nowVH&&frame.VH!==nowVH)||(frame.W!==nowW)||(frame.H!==nowH);
  if(!mism) return;
  const t=Date.now(); if(t-_coordMismLast<800) return; _coordMismLast=t;   // throttle(스팸 방지)
  const msg=`[coord-mismatch] captured VW×VH=${frame.VW}×${frame.VH} W×H=${frame.W}×${frame.H} → now VW×VH=${nowVW}×${nowVH} W×H=${nowW}×${nowH}`;
  console.warn(msg);
  try{ fetch('/recognition/log',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rule:'coord_mismatch',level:'debug',note:msg})}); }catch(_){}
}
// 카메라 기동/전환·리사이즈 등 기준값이 바뀌는 이벤트를 타임스탬프와 함께 기록(race 창 특정용).
function _coordEvent(tag){
  const m=`[coord-event] ${tag} VW×VH=${videoEl.videoWidth}×${videoEl.videoHeight} canvas=${canvas.width}×${canvas.height} @${Date.now()}`;
  console.info(m);
  try{ fetch('/recognition/log',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rule:'coord_event',level:'debug',note:m})}); }catch(_){}
}
function renderCoreFrameOverlays(frame){
  // ★ race guard: 캐시된 frame.scX 사용 금지 — 렌더 시점 실제 videoWidth/canvas 로 스케일 재계산
  //   (캡처~렌더 사이 창 리사이즈·카메라 전환으로 기준값이 바뀌면 캐시 scX가 어긋남 → 매 렌더 최신값으로 동기화).
  try{
    const nowVW=videoEl.videoWidth||0, nowVH=videoEl.videoHeight||0, nowW=canvas.width, nowH=canvas.height;
    _coordMismatchTelemetry(frame,nowVW,nowVH,nowW,nowH);
    if(nowVW>0&&nowVH>0&&(nowW!==frame.W||nowH!==frame.H||nowVW!==frame.VW||nowVH!==frame.VH)){
      const rect=mediaRect(nowW,nowH);
      frame.W=nowW; frame.H=nowH; frame.VW=nowVW; frame.VH=nowVH; frame.rect=rect;
      frame.scX=rect.w/nowVW; frame.scY=rect.h/nowVH;
    }
  }catch(e){}
  if(thermOn){ try{ drawThermal(frame.W,frame.H); }catch(e){} return; }   // 열화상 온도 모드: 다른 오버레이 생략
  drawSkeleton(frame.pose,frame.W,frame.H);
  drawDetailedPoseOverlay(frame.pose,frame.W,frame.H);
  drawFace(frame.face,frame.W,frame.H);
  drawHand(frame.leftHandLM,frame.W,frame.H,'#10b981');
  drawHand(frame.rightHandLM,frame.W,frame.H,'#f97316');
  const lBBoxDisplay=scaleBox(frame.leftHandBBox,frame.scX,frame.scY);
  const rBBoxDisplay=scaleBox(frame.rightHandBBox,frame.scX,frame.scY);
  drawHandBBox(lBBoxDisplay,frame.W,frame.H,'#10b981','왼손');
  drawHandBBox(rBBoxDisplay,frame.W,frame.H,'#f97316','오른손');
  drawHandToObj(frame.leftHandLM,frame.leftHeldObjects,frame.W,frame.H,frame.scX,frame.scY,'#10b981');
  drawHandToObj(frame.rightHandLM,frame.rightHeldObjects,frame.W,frame.H,frame.scX,frame.scY,'#f97316');
  // 외곽선 모드: 세그 결과가 신선하면 폴리곤 윤곽으로, 아니면 박스로 폴백(저하 없음)
  if(segModeOn() && segFresh()){
    drawSegments(frame.W,frame.H,frame.scX,frame.scY);
  } else {
    // 사람 대체 표시(MediaPipe 스켈레톤 or 안전 백엔드 포즈)가 실제로 있을 때만 박스 숨김
    const personHasViz = !!frame.pose || poseFresh();
    // 고정밀 백엔드를 주 탐지로 승격(가산): 백엔드 결과가 있으면 우선, 없으면 브라우저 그대로
    drawObjects(_mergedObjects(frame.latestObjects),frame.W,frame.H,frame.leftHeldObjects,frame.rightHeldObjects,frame.scX,frame.scY, personHasViz);
    // 안전: 작업자(사람)는 박스 대신 포즈 스켈레톤으로 표시(다른 객체는 박스 유지)
    // 안전=항상 백엔드 포즈, 피트니스/오피스=MediaPipe 없을 때 폴백(이중 그리기 방지)
    if(poseFresh() && (activeServiceMode==='safety' || !frame.pose)){ try{ drawBackendPoses(frame.W,frame.H,frame.scX,frame.scY); }catch(e){} }
  }
  try{ drawAXPostureBadge(frame.rawPose,frame.W,frame.H); }catch(e){}  // 추론만(표시는 패널)
  try{ drawDangerZone(frame.W,frame.H); }catch(e){}
  try{ handleDangerZone(frame); }catch(e){}
  try{ sampleHeartRate(frame.face); }catch(e){}
  try{ axRunUpgrades(frame); }catch(e){}        // 추적기반 업그레이드(구역체류·안전거리·히트맵·AIGym·자세각도·얼굴가림)
  try{ axDrawCal(frame.W,frame.H); }catch(e){}   // 거리보정 점/사각형 표시(보정 중)
  try{ updateRecognitionPanel(frame); }catch(e){}
}

function consumeCoreFrameForActiveTheme(frame){
  // Phase 1: 기존 UI 소비 순서를 그대로 보존한다. 테마별 게이팅은 Phase 2 이후 적용.
  updateFaceUI(frame.face);
  updatePoseUI(frame.rawPose,frame.pose);
  updateObjectUI(frame.latestObjects);
  updateVisionTaskLive(frame.action);
  updateHandUI(frame.leftHeldObjects,frame.rightHeldObjects,frame.leftMobileNetResult,frame.rightMobileNetResult,frame.leftHandLM,frame.rightHandLM);
  updateSafetyUI(frame.action,frame.pose,frame.visibleObjects);
  updateSceneUI(frame.genderInfo,frame.ageInfo,frame.action,frame.specialActions,frame.leftHeldObjects,frame.rightHeldObjects);
}

async function onHolisticResults(results){
  const now=performance.now();
  lastHolisticAt=now;   // 워치독: 프레임 펌프가 살아있음을 표시
  const fps=Math.round(1000/Math.max(1,now-lastTime)); lastTime=now;
  document.getElementById('fpsCounter').textContent=`FPS: ${fps}`;
  document.getElementById('fpsDisplay').textContent=`FPS: ${fps}`;

  const cont=document.getElementById('videoContainer');
  canvas.width=cont.clientWidth; canvas.height=cont.clientHeight;
  const W=canvas.width, H=canvas.height;
  ctx.clearRect(0,0,W,H);

  const rawPose=results.poseLandmarks, face=results.faceLandmarks;
  const rawLHandLM=results.leftHandLandmarks, rawRHandLM=results.rightHandLandmarks;
  // Keep MediaPipe's anatomical left/right labels. Display orientation is handled
  // separately by viewX/displayBboxArray, so hand identities should not be swapped.
  const lHandLM=rawLHandLM;
  const rHandLM=rawRHandLM;
  sm=smoothPose(rawPose); // 전역 변수 업데이트 (updateSceneUI 등에서 참조)
  updateVel(sm);

  // ── 손 영역 바운딩박스 계산 (영상 픽셀 기준) ──
  const VW=videoEl.videoWidth||1280, VH=videoEl.videoHeight||720;
  cachedLBBox=getHandBBox(lHandLM,VW,VH);
  cachedRBBox=getHandBBox(rHandLM,VW,VH);

  // 2단계: 사람 박스 위치를 매 프레임 신선한 pose extent로 갱신. 못 잡은 프레임은 마지막값 hold(아래 _applyPoseFollow가 STALE_TTL까지 유지 후 페이드).
  const _pe=posePersonExtent(sm,VW,VH);
  if(_pe){ posePersonExtentBox=_pe; posePersonExtentAt=Date.now(); }

  // ── 그리기 (TF.js 추론은 별도 루프 - 캐시된 데이터 사용) ──
  // 영상→캔버스 스케일
  const rect=mediaRect(W,H);
  const scX=rect.w/VW, scY=rect.h/VH;
  const frame=buildCoreFrameState(results,W,H,VW,VH,rect,scX,scY,rawPose,sm,face,lHandLM,rHandLM);
  latestCoreFrameState=frame;

  // ── 그리기 (TF.js 추론은 별도 루프 - 캐시된 데이터 사용) ──
  renderCoreFrameOverlays(frame);

  // ── UI 업데이트 ──
  consumeCoreFrameForActiveTheme(frame);
}

// ═══════════════════════════════════════════════════
//  독립 TF.js 감지 루프 (MediaPipe와 분리)
// ═══════════════════════════════════════════════════
// 진단: 조용히 삼켜지던 "객체 인식 안 됨" 원인을 화면+콘솔에 1회만 노출.
let _detectDiagShown=null;
function _detectDiag(msg){
  if(_detectDiagShown===msg) return;          // 같은 메시지 반복 방지
  _detectDiagShown=msg;
  try{ console.error('[탐지진단]', msg); }catch(_){}
  const rp=document.getElementById('recogPanel');
  if(rp) rp.innerHTML='<h4>객체 인식 진단</h4><div class="dim" style="font-size:12.5px;line-height:1.5">'+msg+'</div>';
}

// ── 백엔드 주 탐지 승격 ────────────────────────────────
// 고정밀 백엔드(yolov8s+융합)를 '주 탐지'로 쓰고, 브라우저 COCO-SSD는 백엔드가
// 놓친 객체만 보충(가산)한다. 백엔드 결과가 없으면 기존(브라우저) 그대로 → 절대 저하 없음.
// 안전 모드는 토글과 무관하게 백엔드(주 탐지·포즈) 항상 사용. 그 외 모드는 '백엔드 정밀 보정' 토글을 따름.
function backendActive(){ return activeServiceMode==='safety' || !!document.getElementById('togBackendBoost')?.checked; }
function _mergedObjects(browserObjs){
  browserObjs = browserObjs || latestObjects || [];
  let out;
  if(!backendActive()){
    out = browserObjs;                                        // 백엔드 미사용 시 기존 브라우저 그대로(저하 없음)
  }else{
    const fresh = (Date.now()-backendBoostAt <= BACKEND_PRIMARY_TTL) ? backendBoostDets : [];
    if(!fresh.length){
      out = browserObjs;                                      // 백엔드 결과 없으면 저하 없이 브라우저 유지
    }else{
      out = fresh.map(d=>({...d}));                           // 백엔드(고정밀) 우선 = 라벨/정밀도 보정
      for(const b of browserObjs){                            // 백엔드가 못 잡은 영역만 브라우저로 보충
        if(!fresh.some(f=> iou(f.bbox,b.bbox)>0.45)) out.push(b);
      }
    }
  }
  out = _dedupOverlapping(out);                               // 겹침+포함 중복 제거(백엔드가 NO-Hardhat 등 한 대상에 여러 박스 반환하는 것 방지)
  out = _applyPoseFollow(out);                                // 사람 박스 위치를 신선한 pose extent로 교체(지연 0)
  out = _dropTrailingStale(out);                              // 트래커 gone 꼬리 제거
  out = _dedupePersons(out);                                  // 같은 사람의 '살아있는' 중복 박스(지연 백엔드+브라우저+pose)를 하나로
  out = _filterOrphanPPE(out);                                // 사람과 동떨어진 보호구 위반(빈 벽 오탐) 제거
  return _safetyVisible(out);                                 // 안전 모드: 안전 관련 객체만 그림(잡동사니 숨김)
}

// ── 폴백 렌더 ──────────────────────────────────────────
// 모든 캔버스 그리기가 onHolisticResults(=MediaPipe Holistic 펌프)에만 묶여 있어,
// Holistic 로딩/구동이 실패하면 객체 탐지가 정상이어도 박스가 화면에 안 그려진다.
// → Holistic 결과가 일정시간 끊기면(또는 한 번도 안 오면) 객체 박스만이라도 직접 그린다. (절대 저하 없음)
let _fallbackRafId=null, _mpStaleSince=0;
const HOLISTIC_STALE_MS=700;
function _startFallbackRender(){
  cancelAnimationFrame(_fallbackRafId);
  const loop=()=>{
    _fallbackRafId=requestAnimationFrame(loop);
    if(!cameraOn||paused) return;
    // Holistic가 최근에 그렸으면(=살아있으면) 폴백은 손대지 않는다(이중 그리기 방지)
    if(lastHolisticAt && (performance.now()-lastHolisticAt) < HOLISTIC_STALE_MS){ _mpStaleSince=0; return; }
    if(!_mpStaleSince) _mpStaleSince=Date.now();   // MediaPipe 미가동 시작 시각
    if(thermOn) return;                          // 열화상 모드는 자체 렌더
    if(!videoEl||videoEl.readyState<2) return;
    try{
      const cont=document.getElementById('videoContainer');
      canvas.width=cont.clientWidth; canvas.height=cont.clientHeight;
      const W=canvas.width, H=canvas.height;
      ctx.clearRect(0,0,W,H);
      const VW=videoEl.videoWidth||1280, VH=videoEl.videoHeight||720;
      const rect=mediaRect(W,H); const scX=rect.w/VW, scY=rect.h/VH;
      if(segModeOn() && segFresh()){ try{ drawSegments(W,H,scX,scY); }catch(e){} }
      else { const personHasViz=poseFresh();   // 폴백 경로(MediaPipe 없음): 백엔드 포즈 있으면 박스 숨기고 스켈레톤
             try{ drawObjects(_mergedObjects(latestObjects),W,H,leftHeldObjects,rightHeldObjects,scX,scY, personHasViz); }catch(e){}
             if(poseFresh()){ try{ drawBackendPoses(W,H,scX,scY); }catch(e){} } }
      try{ drawDangerZone(W,H); }catch(e){}
      // 위험구역 침입 판정/경보 — 폴백 경로에서도 반드시 실행. (기존엔 메인 렌더에만 있어 MediaPipe 로딩 실패 시
      // 구역은 그려지지만 침입 판정이 아예 안 돌아 경고가 안 떴다. 백엔드 포즈/탐지는 MediaPipe와 무관하게 독립 동작.)
      try{ handleDangerZone({W,H,scX,scY,VW,VH,rect,latestObjects,timestamp:Date.now()}); }catch(e){}
      // MediaPipe 진단은 '한 번도 안 떴고 + 12초 유예' 후에만(로딩 지연을 실패로 오인하지 않게)
      if(!lastHolisticAt && _mpStaleSince && (Date.now()-_mpStaleSince > 12000))
        _detectDiag('카메라·객체 인식은 정상 동작 중입니다.<br>단 MediaPipe(자세/손/낙상)가 12초 넘게 로딩되지 않았습니다(네트워크·CDN 지연).<br>· 새로고침(⌘⇧R) 권장<br>· 폐쇄망이면 로컬 번들이 필요합니다.');
    }catch(e){}
  };
  _fallbackRafId=requestAnimationFrame(loop);
}
function _stopFallbackRender(){ cancelAnimationFrame(_fallbackRafId); _fallbackRafId=null; }

function startTFLoops(){
  stopTFLoops();

  // COCO-SSD: 200ms마다 (≈5fps)
  tfLoopTimer=setInterval(async()=>{
    // cocoModel 미로딩 시 영원히 조용히 return 하던 것을 진단 노출로 변경
    if(cameraOn && !paused && !cocoModel){
      _detectDiag('객체 인식 모델(COCO-SSD)이 로딩되지 않았습니다.<br>· 새로고침(⌘⇧R)<br>· 인터넷/광고차단 확장 확인<br>· 콘솔(F12)에서 빨간 에러 확인');
    }
    if(!cameraOn||paused||!cocoModel||videoEl.readyState<2) return;
    // 안전 모드: 백엔드가 주 탐지(4fps) → 브라우저 COCO는 추적/보조용으로 저빈도(≈1.4fps)만 → 메인스레드 확보
    if(backendActive()){ if(Date.now()-_cocoLastRun < 700) return; _cocoLastRun=Date.now(); }  // 백엔드 활성 시 브라우저 COCO 저빈도
    if(tfBusy) return;
    tfBusy=true;
    const VW=videoEl.videoWidth||1280, VH=videoEl.videoHeight||720;
    const thr=parseInt(document.getElementById('confThreshold').value)/100;
    try{
      const merged=await multiScaleDetect(videoEl);

      // 사람 중복 박스 제거(멀티스케일에서 같은 사람이 큰/작은 박스로 겹쳐 잡히는 것 방지)
      // → 추적기에도 deduped 결과를 넘겨 한 사람이 여러 ID(#8,#10)로 잡히지 않게 함
      const dedupPersons=uniquePersonDetections(merged);
      const cleanMerged=[...dedupPersons, ...merged.filter(o=>o.class!=='person')];

      // 사람 수 (낮은 임계값)
      updateStablePersonCount(dedupPersons.length,!!sm);
      latestObjects=updateTracker(cleanMerged);

      // 손에 든 사물 (손 bbox는 영상 픽셀 기준)
      if(cachedLBBox){
        const lFound=findHeldObjects(cachedLBBox,merged,VW,VH);
        // 손 크롭 저임계값 추가 검색
        const bw=cachedLBBox.maxX-cachedLBBox.minX, bh=cachedLBBox.maxY-cachedLBBox.minY;
        if(bw>30&&bh>30){
          const oc2=document.createElement('canvas'); oc2.width=224; oc2.height=224;
          oc2.getContext('2d').drawImage(videoEl,cachedLBBox.minX,cachedLBBox.minY,bw,bh,0,0,224,224);
          const lExtra=await cocoModel.detect(oc2,5,0.18);
          const lMapped=filterPredictions(lExtra.filter(p=>p.class!=='person').map(p=>({...p,bbox:[cachedLBBox.minX+p.bbox[0]*(bw/224),cachedLBBox.minY+p.bbox[1]*(bh/224),p.bbox[2]*(bw/224),p.bbox[3]*(bh/224)]})),VW,VH,thr,{handCrop:true});
          leftHeldObjects=stabilizeHeldObjects(applyNMS([...lFound,...lMapped],0.4).filter(o=>o.class!=='person'),'left');
        }else{ leftHeldObjects=stabilizeHeldObjects(lFound,'left'); }
      }else{ leftHeldObjects=[]; leftHeldHistory=[]; }

      if(cachedRBBox){
        const rFound=findHeldObjects(cachedRBBox,merged,VW,VH);
        const bw=cachedRBBox.maxX-cachedRBBox.minX, bh=cachedRBBox.maxY-cachedRBBox.minY;
        if(bw>30&&bh>30){
          const oc3=document.createElement('canvas'); oc3.width=224; oc3.height=224;
          oc3.getContext('2d').drawImage(videoEl,cachedRBBox.minX,cachedRBBox.minY,bw,bh,0,0,224,224);
          const rExtra=await cocoModel.detect(oc3,5,0.18);
          const rMapped=filterPredictions(rExtra.filter(p=>p.class!=='person').map(p=>({...p,bbox:[cachedRBBox.minX+p.bbox[0]*(bw/224),cachedRBBox.minY+p.bbox[1]*(bh/224),p.bbox[2]*(bw/224),p.bbox[3]*(bh/224)]})),VW,VH,thr,{handCrop:true});
          rightHeldObjects=stabilizeHeldObjects(applyNMS([...rFound,...rMapped],0.4).filter(o=>o.class!=='person'),'right');
        }else{ rightHeldObjects=stabilizeHeldObjects(rFound,'right'); }
      }else{ rightHeldObjects=[]; rightHeldHistory=[]; }
    }catch(e){ _detectDiag('객체 인식 루프 오류: '+(e&&e.message?e.message:e)+'<br>(콘솔 F12에서 상세 확인)'); } finally { tfBusy=false; }
  },OBJECT_SCAN_INTERVAL);

  // MobileNet: 세밀한 손 사물 분류. 객체 감지 루프와 분리해 카메라 프레임 끊김을 줄인다.
  mnLoopTimer=setInterval(async()=>{
    if(!cameraOn||paused||!mobileNetModel||videoEl.readyState<2) return;
    if(!(document.getElementById('togMobileNet')?.checked??true)) return;
    if(mnBusy) return;
    mnBusy=true;
    const VW=videoEl.videoWidth||1280, VH=videoEl.videoHeight||720;
    try{
      // 손 영역 분류 (패딩 2배로 확대해 물체 더 잘 잡기)
      if(cachedLBBox){
        const b=cachedLBBox;
        const pad=(b.maxX-b.minX)*0.6;
        const x=Math.max(0,b.minX-pad), y=Math.max(0,b.minY-pad);
        const bw=Math.min(VW-x,(b.maxX-b.minX)+pad*2), bh=Math.min(VH-y,(b.maxY-b.minY)+pad*2);
        if(bw>20&&bh>20){
          const oc=document.createElement('canvas'); oc.width=224; oc.height=224;
          oc.getContext('2d').drawImage(videoEl,x,y,bw,bh,0,0,224,224);
          const r=await mobileNetModel.classify(oc,7);
          if(r.length){
            leftMobileNetResult=r;
            const fineHeld=mobileNetToHeldObjects(r,cachedLBBox);
            if(fineHeld.length) leftHeldObjects=stabilizeHeldObjects(applyNMS([...leftHeldObjects,...fineHeld],0.35).filter(o=>o.class!=='person'),'left');
            await saveHandCropForTraining('left',cachedLBBox,r);
          }
        }
      }else{ leftMobileNetResult=[]; }
      if(cachedRBBox){
        const b=cachedRBBox;
        const pad=(b.maxX-b.minX)*0.6;
        const x=Math.max(0,b.minX-pad), y=Math.max(0,b.minY-pad);
        const bw=Math.min(VW-x,(b.maxX-b.minX)+pad*2), bh=Math.min(VH-y,(b.maxY-b.minY)+pad*2);
        if(bw>20&&bh>20){
          const oc=document.createElement('canvas'); oc.width=224; oc.height=224;
          oc.getContext('2d').drawImage(videoEl,x,y,bw,bh,0,0,224,224);
          const r=await mobileNetModel.classify(oc,7);
          if(r.length){
            rightMobileNetResult=r;
            const fineHeld=mobileNetToHeldObjects(r,cachedRBBox);
            if(fineHeld.length) rightHeldObjects=stabilizeHeldObjects(applyNMS([...rightHeldObjects,...fineHeld],0.35).filter(o=>o.class!=='person'),'right');
            await saveHandCropForTraining('right',cachedRBBox,r);
          }
        }
      }else{ rightMobileNetResult=[]; }
      // 전체 화면 분류 (1초마다, 손 결과가 없을 때 보조)
      if(!cachedLBBox&&!cachedRBBox){
        const oc=document.createElement('canvas'); oc.width=224; oc.height=224;
        oc.getContext('2d').drawImage(videoEl,0,0,VW,VH,0,0,224,224);
        const r=await mobileNetModel.classify(oc,10);
        if(r.length) fullFrameResults=r;
      } else {
        fullFrameResults=[];
      }
      if(document.getElementById('togPPE')?.checked){
        await classifyPPERegions(videoEl,VW,VH);
        await analyzePPEWithBackend(videoEl,VW,VH);
      }
      if(backendActive()){
        await analyzeObjectsWithBackend(videoEl,VW,VH);
      }
    }catch(e){} finally { mnBusy=false; }
  },FINE_CLASSIFY_INTERVAL);

  // 백엔드 고정밀(yolov8s+융합) 탐지 독립 루프 — mobilenet/MediaPipe 상태와 무관하게 항상 공급.
  // 결과는 _mergedObjects가 '주 탐지'로 우선 사용 → 정확도 향상(가산식, 저하 없음).
  if(backendLoopTimer) clearInterval(backendLoopTimer);
  backendLoopTimer=setInterval(()=>{
    if(!cameraOn||paused||!videoEl||videoEl.readyState<2) return;
    if(!backendActive()) return;   // 안전은 항상 ON(주 탐지·포즈), 그 외는 토글
    const VW=videoEl.videoWidth||1280, VH=videoEl.videoHeight||720;
    analyzeObjectsWithBackend(videoEl,VW,VH);   // 내부 throttle/busy 가드로 중복 호출 방지
  },BACKEND_LOOP_INTERVAL);

  // (세그멘테이션은 별도 루프 없이 detect 호출에 통합됨 — analyzeObjectsWithBackend가 seg도 함께 수신.
  //  중복 프레임 인코딩/요청을 없애 버퍼링을 줄인다.)
}

function stopTFLoops(){
  if(tfLoopTimer){clearInterval(tfLoopTimer);tfLoopTimer=null;}
  if(mnLoopTimer){clearInterval(mnLoopTimer);mnLoopTimer=null;}
  if(backendLoopTimer){clearInterval(backendLoopTimer);backendLoopTimer=null;}
  if(segLoopTimer){clearInterval(segLoopTimer);segLoopTimer=null;}
  tfBusy=false; mnBusy=false;
}

// ═══════════════════════════════════════════════════
//  카메라 제어
// ═══════════════════════════════════════════════════
async function toggleCamera(){cameraOn?await stopCamera():await startWebcam();}

// 프레임 펌프: MediaPipe Camera 유틸을 우선 쓰되, 미로딩/무동작 시 requestAnimationFrame 폴백.
// (Camera 유틸이 실패하면 영상만 켜지고 인식이 전부 멈추는 문제 방지)
let lastHolisticAt=0;
let _framePumpStop=false;
function _startRafPump(){
  _framePumpStop=false;
  camera={stop(){_framePumpStop=true;}};
  const pump=async()=>{
    if(_framePumpStop) return;
    try{
      if(!paused && cameraOn && holistic && videoEl.readyState>=2){
        applyCameraOrientation(true);
        await holistic.send({image:videoEl});
      }
    }catch(e){}
    if(!_framePumpStop) requestAnimationFrame(pump);
  };
  requestAnimationFrame(pump);
}
function _startFramePump(actualW,actualH){
  _framePumpStop=false;
  if(typeof Camera!=='undefined' && Camera){
    try{
      camera=new Camera(videoEl,{onFrame:async()=>{if(paused||!cameraOn)return;applyCameraOrientation(true);await holistic.send({image:videoEl});},width:actualW,height:actualH});
      camera.start();
      // 워치독: 3.5초 안에 holistic 결과가 한 번도 안 오면 rAF 폴백으로 전환
      const startedAt=performance.now();
      setTimeout(()=>{
        if(_framePumpStop) return;
        if(!lastHolisticAt || lastHolisticAt < startedAt){
          try{ camera && camera.stop && camera.stop(); }catch(e){}
          _startRafPump();
        }
      },3500);
      return;
    }catch(e){ try{console.warn('Camera 유틸 실패 → rAF 폴백',e);}catch(_){} }
  }
  _startRafPump();
}

async function startWebcam(){
  imageEl.style.display='none'; videoEl.style.display='block';
  mirrored=CAMERA_DISPLAY_FLIP_X;
  applyCameraOrientation(true);
  if(camera){try{camera.stop();}catch(e){}}
  if(currentStream){currentStream.getTracks().forEach(t=>t.stop());}
  const cameraConstraints={
    video:{
      facingMode:'user',
      width:{ideal:1280,min:640},
      height:{ideal:720,min:480},
      frameRate:{ideal:30,max:30}
    },
    audio:false
  };
  try{
    currentStream=await navigator.mediaDevices.getUserMedia(cameraConstraints);
  }catch(e){
    currentStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:{ideal:1280},height:{ideal:720},frameRate:{ideal:30,max:30}},audio:false});
  }
  videoEl.srcObject=currentStream; await videoEl.play();
  try{ videoEl.onloadedmetadata=()=>{try{_coordEvent('camera-meta');}catch(_){}}; _coordEvent('camera-start'); }catch(_){}
  applyCameraOrientation(true);
  const actualW=videoEl.videoWidth||1280, actualH=videoEl.videoHeight||720;
  cameraOn=true; setCameraUI(true);
  _startFramePump(actualW,actualH);   // Camera 유틸 + rAF 폴백/워치독
  // 진단: 7초 내에도 인식 결과가 전혀 없으면 조용한 검은 화면 대신 안내
  const _camStartAt=performance.now();
  setTimeout(()=>{
    if(cameraOn && (!lastHolisticAt || lastHolisticAt < _camStartAt)){
      const rp=document.getElementById('recogPanel');
      if(rp) rp.innerHTML='<h4>지금 인식 중</h4><div class="dim" style="font-size:12.5px;line-height:1.5">AI 인식 모델이 응답하지 않습니다.<br>· 새로고침(⌘⇧R)<br>· 인터넷 연결 확인<br>후 다시 시도해 주세요.</div>';
    }
  },7000);
  lastTime=performance.now(); // FPS 타이머 리셋 (모델 로딩 시간 제외)
  poseHistory.length=0; actionHistory.length=0; prevHipY=null; hipVelocity=0; fallConfirm=0; objTracker={nextId:1,tracked:[]};
  startTFLoops(); // TF.js 독립 루프 시작
  _startFallbackRender(); // MediaPipe 펌프가 죽어도 객체 박스는 그린다 (폴백)
}

async function stopCamera(){
  stopTFLoops();
  _stopFallbackRender();
  if(camera){try{camera.stop();}catch(e){} camera=null;}
  if(currentStream){currentStream.getTracks().forEach(t=>t.stop()); currentStream=null;}
  videoEl.srcObject=null; ctx.clearRect(0,0,canvas.width,canvas.height);
  applyCameraOrientation(false);
  cameraOn=false; setCameraUI(false);
  poseHistory.length=0; actionHistory.length=0; prevHipY=null; hipVelocity=0; fallConfirm=0;
  leftHeldObjects=[]; rightHeldObjects=[]; leftHeldHistory=[]; rightHeldHistory=[]; leftMobileNetResult=[]; rightMobileNetResult=[]; fullFrameResults=[]; detectedPersonCount=0;
  {const _hh=document.getElementById('handHeldOverlay'); if(_hh)_hh.innerHTML='';}
}

function setCameraUI(on){
  document.getElementById('cameraOffScreen').style.display=on?'none':'flex';
  document.getElementById('camStatusBadge').className='cam-status-badge '+(on?'on':'off');
  document.getElementById('camLed').className='cam-led '+(on?'on':'off');
  document.getElementById('camStatusText').textContent=on?'카메라 ON':'카메라 OFF';
  document.getElementById('camBtnText').textContent=on?'카메라 끄기':'카메라 켜기';
  document.getElementById('btnCamToggle').className=on?'btn cam-off':'btn active';
  document.getElementById('btnPause').disabled=!on;
  if(!on&&paused){paused=false;document.getElementById('btnPause').textContent='⏸ 정지';}
  if(!on){['dotPose','dotFace','dotObj','dotHand','dotSafe'].forEach(id=>setDot(id,''));}
}

async function handleFile(event){
  const file=event.target.files[0]; if(!file) return;
  if(cameraOn) await stopCamera();
  objTracker={nextId:1,tracked:[]};
  if(file.type.startsWith('image/')){
    videoEl.style.display='none'; imageEl.style.display='block';
    applyCameraOrientation(false);
    document.getElementById('cameraOffScreen').style.display='none';
    imageEl.src=URL.createObjectURL(file);
    imageEl.onload=async()=>{
      await holistic.send({image:imageEl});
      if(document.getElementById('pane-ai')) switchTab('ai');
      setLLMStatus('done','업로드 사진 분석 준비 완료');
      {const _lr=document.getElementById('llmResult'); if(_lr)_lr.textContent='업로드한 사진이 준비됐습니다. API 키를 입력하고 “현재 화면/사진 분석하기”를 누르면 LLM이 사진 내용을 자세히 설명합니다.';}
    };
    document.getElementById('camBtnText').textContent='카메라 켜기';
    document.getElementById('btnCamToggle').className='btn active';
    document.getElementById('camStatusText').textContent='이미지 모드';
  }else{
    imageEl.style.display='none'; videoEl.style.display='block';
    applyCameraOrientation(false);
    document.getElementById('cameraOffScreen').style.display='none';
    videoEl.srcObject=null; videoEl.src=URL.createObjectURL(file); videoEl.play(); videoEl.loop=true;
    camera=new Camera(videoEl,{onFrame:async()=>{if(paused)return;await holistic.send({image:videoEl});},width:1280,height:720});
    camera.start();
    document.getElementById('btnPause').disabled=false;
    document.getElementById('camBtnText').textContent='카메라 켜기';
    document.getElementById('btnCamToggle').className='btn active';
    document.getElementById('camStatusText').textContent='영상 모드';
  }
  document.getElementById('camStatusBadge').className='cam-status-badge off';
  document.getElementById('camLed').className='cam-led off';
}

function toggleMirror(){
  mirrored=CAMERA_DISPLAY_FLIP_X;
  applyCameraOrientation(cameraOn);
}

// ═══════════════════════════════════════════════════
//  Vision LLM 분석
// ═══════════════════════════════════════════════════
let llmAnalysisCount=0, llmAutoTimer=null, llmAutoRunning=false;
const API_BASE=(location.protocol==='file:'||!location.host)?'http://127.0.0.1:8005':'';

const ERGO_DOMAIN_PROMPTS={
  general:{
    label:'일반 인체공학',
    domain:'일반 인체공학',
    specific:`공통 분석:
- 목, 척추, 어깨, 팔꿈치, 손목, 골반, 무릎의 정렬을 종합 평가한다.
- 가장 큰 위험 자세 1개를 먼저 지목하고, 판단 불가한 항목은 추측하지 말고 "판단 불가"로 표시한다.
- 의료 진단처럼 단정하지 말고 자세 개선 관점으로 표현한다.`
  },
  fitness:{
    label:'헬스/웨이트',
    domain:'스포츠 - 헬스/웨이트트레이닝',
    specific:`운동 종류 자동 감지:
- 스쿼트, 데드리프트, 벤치프레스, 오버헤드프레스, 바벨로우, 풀업, 런지, 힙힌지 후보를 구분한다.
스쿼트 핵심:
- 무릎-발끝 정렬, 무릎 내반, 척추 중립, 힙 depth, 발뒤꿈치 들림 여부를 평가한다.
데드리프트 핵심:
- 등 굽음(cat-back), 과신전, 힙힌지 패턴, 어깨 위치를 평가한다.
오버헤드프레스 핵심:
- 전완 수직, 코어 긴장, 허리 과신전, 어깨 충돌 위험 각도를 본다.
출력 추가:
- exercise_type, rep_phase, rep_count_estimate, fatigue_risk, injury_warning.`
  },
  golf:{
    label:'골프',
    domain:'스포츠 - 골프 스윙 분석',
    specific:`스윙 단계 인식:
- Address, Takeaway, Backswing, Top, Downswing, Impact, Follow-through, Finish 중 현재 프레임 단계를 판단한다.
단계별 체크:
- Address: 무릎 굴곡 25-30도, 척추 전굴 30-45도, 어깨-힙 정렬, 체중 50:50.
- Backswing: 어깨 회전 90도, 힙 회전 45도 이하, 왼팔 직선, reverse pivot 여부.
- Impact: 앞발 체중 70-80%, 힙 선행, 손목 편평 유지.
- Follow-through: 척추 역C자, 균형 완료 여부.
출력 추가:
- swing_phase, x_factor_angle, spine_angle_consistency, golf_injury_risk.`
  },
  yoga:{
    label:'요가/필라테스',
    domain:'스포츠 - 요가 & 필라테스 자세 분석',
    specific:`아사나 후보:
- Tadasana, Warrior 1/2/3, Triangle, Downward Dog, Plank, Bridge, Pigeon, Tree, Boat, Fish 중 가까운 자세를 추정한다.
분석 항목:
- 이상적 자세 대비 정렬 정확도 0-100점.
- 주요 이탈 관절 3개.
- 전굴 각도, 힙 개방도, 어깨 가동범위.
- 좌우 대칭성과 무게중심 안정성.
출력 추가:
- asana_name, alignment_score, flexibility_assessment, symmetry_score.`
  },
  boxing:{
    label:'복싱/격투기',
    domain:'스포츠 - 복싱 & 격투 스포츠 분석',
    specific:`기본 자세:
- Orthodox, Southpaw, Switch 중 자세를 추정한다.
분석 항목:
- 가드: 턱 보호, 팔꿈치 45-90도, 체중 분배 앞발 40 / 뒷발 60.
- 펀치: Jab, Cross, Hook 후보, 힙 회전 선행, 가드 복귀 여부.
- 피로도: 가드 하강, 자세 붕괴, 목 노출 패턴.
출력 추가:
- stance, punch_type, guard_quality, fatigue_indicator, wrist_alignment_risk.`
  },
  industrial:{
    label:'산업안전',
    domain:'산업안전 / 작업 인체공학',
    specific:`국제 표준 기반 간이 평가:
- REBA: 전신 위험도.
- RULA: 상지 집중 위험도.
- NIOSH Lifting Equation 관점: 들기 작업이면 허리 굽힘, 물체 거리, 비틀림을 확인.
- OWAS 관점: 작업 자세를 분류한다.
REBA 간이 기준:
- 몸통 0도=1, 20도=2, 60도=3, 60도 이상=4.
- 목 0-20도=1, 20도 이상=2.
- 다리 양발지지=1, 불안정/외발=2.
- 상완 20도 이하=1, 20-45도=2, 45-90도=3, 90도 이상=4.
- 전완 60-100도=1, 나머지=2.
- 손목 0-15도=1, 15도 이상=2.
출력 추가:
- reba_score, rula_score, lifting_risk, cumulative_exposure_minutes, legal_limit_warning.`
  },
  msd:{
    label:'근골격계질환 예방',
    domain:'직업성 근골격계질환 예방',
    specific:`질환 리스크 매핑:
- 경추: 전굴 15도 이상 지속 시 거북목/경추 부담. 머리 무게 환산 정상 5kg, 15도 12kg, 30도 18kg, 45도 22kg, 60도 27kg.
- 요추: 굴곡 + 비틀림 복합 동작, 앉은 자세 후만, 디스크 내압 위험.
- 어깨: 팔 거상 60-120도 반복, 회전근개 충돌 위험.
- 손목: 굴곡/신전 15도 이상 지속, 반복 손목 동작.
- 무릎: 과굴곡 130도 이상, 쪼그리기 누적.
출력 추가:
- cervical_risk, lumbar_risk, shoulder_risk, wrist_risk, knee_risk, daily_exposure_minutes, urgent_intervention.`
  }
};

function buildErgoVisionPrompt(presetKey){
  const preset=ERGO_DOMAIN_PROMPTS[presetKey]||ERGO_DOMAIN_PROMPTS.general;
  return `당신은 인체공학(Ergonomics) 및 스포츠 의학 전문 AI 분석가입니다.

아래 카메라 프레임 이미지를 분석하여 정밀한 인체공학 보고서를 한국어로 출력하세요.

분석 입력 데이터:
- 카메라 프레임 이미지
- 브라우저 포즈/객체 분석 결과가 화면에 보일 수 있으나, 불확실하면 추측하지 말고 "판단 불가"라고 표시
- 누적 시간: 현재 세션 기준
- 분석 도메인: ${preset.domain}

반드시 포함할 분석 항목:

A. 주요 관절 상태
- 목(경추): 전굴/후굴 각도 추정, 측굴 여부. 거북목 기준은 전굴 15도 이상 지속.
- 어깨: 좌우 높이 차, 전인/내회전 의심 여부.
- 척추: 요추 전만/후만, 흉추 후만, 구부정함 여부.
- 팔꿈치/손목: 굴곡 각도와 반복성 여부.
- 무릎: 굴곡 각도, 내반/외반 정렬.
- 골반: 전방경사/후방경사, 좌우 수평.

B. 자세 위험도 평가(REBA 기반 간이 점수)
- 목 위험 점수 1-3.
- 몸통 위험 점수 1-5.
- 상지 위험 점수 1-3.
- 하지 위험 점수 1-2.
- 종합 REBA 점수 및 조치 권고.

C. 시간 기반 추적
- 현재 위험 자세가 얼마나 유지된 것으로 보이는지 설명.
- 거북목 전굴 15도 이상은 2분 경고, 5분 즉시 교정 알림 기준.
- 구부정한 자세는 3분 이상 경고 기준.
- 반복 동작은 10회 이상이면 피로 누적 경고 기준.

D. 도메인별 특화 분석
${preset.specific}

E. 즉각적 권고사항
- 지금 당장 교정해야 할 것 1가지만 먼저 제시.
- 단기 권고 1개.
- 장기 권고 1개.

출력 형식:
먼저 초보자가 바로 이해할 수 있는 한 문장 요약을 쓰고, 이어서 아래 JSON을 출력하세요.

{
  "risk_score": 0-10,
  "primary_issue": "가장 심각한 문제",
  "joint_status": {
    "neck": {"angle": 숫자 또는 null, "risk": "low|medium|high", "note": "설명"},
    "spine": {"angle": 숫자 또는 null, "risk": "low|medium|high", "note": "설명"},
    "shoulder": {"balance": "설명", "risk": "low|medium|high"},
    "knee": {"angle_L": 숫자 또는 null, "angle_R": 숫자 또는 null, "alignment": "설명"}
  },
  "reba_score": 숫자 또는 null,
  "posture_duration_warning": "경고 메시지 또는 null",
  "domain_analysis": "도메인 특화 분석 결과",
  "immediate_action": "지금 즉시 해야 할 교정",
  "recommendations": ["권고1", "권고2", "권고3"]
}`;
}

function applyErgoPromptPreset(presetKey){
  const promptEl=document.getElementById('llmPrompt');
  const presetEl=document.getElementById('ergoPromptPreset');
  if(presetEl&&presetEl.value!==presetKey) presetEl.value=presetKey;
  if(promptEl) promptEl.value=buildErgoVisionPrompt(presetKey);
}

// LLM 프로바이더 힌트 (2026-07-14: ollama 로컬 옵션 제거 — OpenAI 단일화. anthropic 은 유지)
document.getElementById('llmModel')?.addEventListener('change',function(){
  const hints={claude:'— Anthropic', gpt4o:'— OpenAI', gemini:'— Google'};
  document.getElementById('apiKeyHint').textContent=hints[this.value]||'';
});

function captureFrame(){
  return captureFrameDataUrl().split(',')[1];
}

function captureFrameDataUrl(){
  const oc=document.createElement('canvas');
  const imageMode=imageEl.style.display==='block'&&imageEl.complete&&imageEl.naturalWidth>0;
  if(imageMode){
    oc.width=imageEl.naturalWidth||640;
    oc.height=imageEl.naturalHeight||480;
    oc.getContext('2d').drawImage(imageEl,0,0,oc.width,oc.height);
  }else{
    oc.width=videoEl.videoWidth||640;
    oc.height=videoEl.videoHeight||480;
    const c=oc.getContext('2d');
    if(shouldFlipDisplay()){
      c.translate(oc.width,0);
      c.scale(-1,1);
    }
    c.drawImage(videoEl,0,0,oc.width,oc.height);
  }
  return oc.toDataURL('image/jpeg',0.85);
}

function hasAnalyzableFrame(){
  const imageMode=imageEl.style.display==='block'&&imageEl.complete&&imageEl.naturalWidth>0;
  const videoMode=(cameraOn||videoEl.src)&&videoEl.readyState>=2;
  return imageMode||videoMode;
}

async function analyzeWithClaude(base64, apiKey, prompt){
  const resp=await fetch('https://api.anthropic.com/v1/messages',{
    method:'POST',
    headers:{
      'x-api-key':apiKey,
      'anthropic-version':'2023-06-01',
      'anthropic-dangerous-direct-browser-access':'true',
      'content-type':'application/json'
    },
    body:JSON.stringify({
      model:'claude-3-5-sonnet-20241022',
      max_tokens:1024,
      messages:[{role:'user',content:[
        {type:'image',source:{type:'base64',media_type:'image/jpeg',data:base64}},
        {type:'text',text:prompt}
      ]}]
    })
  });
  if(!resp.ok) throw new Error(`Claude API 오류: ${resp.status} ${await resp.text()}`);
  const d=await resp.json();
  return d.content[0].text;
}

async function analyzeWithOpenAI(base64, apiKey, prompt){
  const resp=await fetch('https://api.openai.com/v1/chat/completions',{
    method:'POST',
    headers:{'Authorization':'Bearer '+apiKey,'Content-Type':'application/json'},
    body:JSON.stringify({
      model:'gpt-4o',
      max_tokens:1024,
      messages:[{role:'user',content:[
        {type:'image_url',image_url:{url:'data:image/jpeg;base64,'+base64}},
        {type:'text',text:prompt}
      ]}]
    })
  });
  if(!resp.ok) throw new Error(`OpenAI API 오류: ${resp.status} ${await resp.text()}`);
  const d=await resp.json();
  return d.choices[0].message.content;
}

async function analyzeWithGemini(base64, apiKey, prompt){
  const model='gemini-2.0-flash-lite';
  const resp=await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({contents:[{parts:[
      {inline_data:{mime_type:'image/jpeg',data:base64}},
      {text:prompt}
    ]}]})
  });
  if(!resp.ok) throw new Error(`Gemini API 오류: ${resp.status} ${await resp.text()}`);
  const d=await resp.json();
  return d.candidates[0].content.parts[0].text;
}

async function analyzeWithServerVision(base64, apiKey, prompt, provider){
  const resp=await fetch(API_BASE+'/llm/vision',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      provider,
      api_key:apiKey,
      image_base64:base64,
      prompt,
      model:''
    })
  });
  const data=await resp.json().catch(()=>({}));
  if(!resp.ok) throw new Error(data.detail||`서버 LLM 오류: ${resp.status}`);
  return data.text||'분석 결과가 비어 있습니다.';
}

function applyLLMPrecisionResult(text, elapsed){
  const card=document.getElementById('llmPrecisionCard');
  const title=document.getElementById('llmPrecisionTitle');
  const desc=document.getElementById('llmPrecisionDesc');
  if(!card||!title||!desc) return;
  const clean=String(text||'').replace(/\s+/g,' ').trim();
  const lower=clean.toLowerCase();
  let level='good';
  if(/위험|미착용|주의|오류|불량|의심|risk|danger|unsafe/.test(lower)) level='danger';
  else if(/판단 불가|불확실|추정|uncertain|unknown/.test(lower)) level='warn';
  card.className='simple-result '+level;
  title.textContent='LLM 정밀 분석 완료';
  desc.textContent=(clean.length>280?clean.slice(0,280)+'...':clean)+` (${elapsed}초)`;

  const easyMain=document.getElementById('easyMainText');
  const easySub=document.getElementById('easySubText');
  if(easyMain) easyMain.textContent='LLM이 현재 장면을 정밀 분석했습니다.';
  if(easySub) easySub.textContent=clean.length>180?clean.slice(0,180)+'...':clean;
}

async function checkLLMStatus(){
  const state=document.getElementById('llmConnectState');
  const selected=document.getElementById('llmModel').value;
  const typedKey=(document.getElementById('llmApiKey').value||'').trim();
  state.textContent='확인 중...';
  state.className='value yellow';
  setLLMStatus('analyzing','연결 상태 확인 중...');
  try{
    const resp=await fetch(API_BASE+'/llm/status');
    const data=await resp.json();
    if(!resp.ok||!data.success) throw new Error(data.detail||'상태 확인 실패');
    const provider=selected==='gpt4o'?'openai':selected;
    const info=data.providers[provider]||{};
    if(typedKey||info.configured){
      state.textContent=typedKey?'API 키 입력됨':'서버 키 설정됨';
      state.className='value green';
      setLLMStatus('done','LLM 연결 준비 완료');
      document.getElementById('llmResult').textContent=`${provider} 멀티모달 분석을 사용할 준비가 됐습니다. 사진을 업로드하거나 카메라 화면을 켠 뒤 분석 버튼을 누르세요.`;
    }else{
      state.textContent='API 키 없음';
      state.className='value red';
      setLLMStatus('error','API 키 필요');
      document.getElementById('llmResult').textContent=`${provider} API 키가 없습니다. 화면의 API 키 입력칸에 키를 넣거나 서버 환경변수(${info.env||'API_KEY'})를 설정해야 실제 멀티모달 분석이 됩니다. Claude/Codex 채팅 사용 권한은 이 서비스 API 키와 별개입니다.`;
    }
  }catch(e){
    state.textContent='서버 연결 실패';
    state.className='value red';
    setLLMStatus('error','상태 확인 실패');
    document.getElementById('llmResult').textContent='❌ LLM 상태 확인 실패: '+e.message;
  }
}

function setLLMStatus(state, text){
  const dot=document.getElementById('llmDot');
  const stEl=document.getElementById('llmStatusText');
  if(dot) dot.className='llm-dot'+(state?' '+state:'');
  if(stEl) stEl.textContent=text;
}

async function runLLMAnalysis(){
  const apiKey=(document.getElementById('llmApiKey').value||'').trim();
  const model=document.getElementById('llmModel').value;
  const prompt=(document.getElementById('llmPrompt').value||'').trim();
  if(!hasAnalyzableFrame()){alert('카메라를 켜거나 사진을 업로드해주세요.');return;}
  const typedKey=apiKey.length>0;

  document.getElementById('btnLLM').disabled=true;
  setLLMStatus('analyzing','분석 중...');
  document.getElementById('llmResult').textContent='⏳ AI가 화면을 분석하고 있습니다...';

  const t0=Date.now();
  try{
    const base64=captureFrame();
    const result=await analyzeWithServerVision(base64,apiKey,prompt,model);

    llmAnalysisCount++;
    const elapsed=((Date.now()-t0)/1000).toFixed(1);
    const now=new Date().toLocaleTimeString('ko-KR');

    document.getElementById('llmResult').textContent=result;
    applyLLMPrecisionResult(result, elapsed);
    document.getElementById('llmConnectState').textContent=typedKey?'API 키로 연결됨':'서버 키로 연결됨';
    document.getElementById('llmConnectState').className='value green';
    document.getElementById('llmCount').textContent=llmAnalysisCount+'회';
    document.getElementById('llmLastTime').textContent=now;
    document.getElementById('llmRespTime').textContent=elapsed+'초';
    setLLMStatus('','완료 ('+now+')');
  }catch(e){
    const msg=String(e.message||e);
    let help='';
    if(msg.includes('API 키')) help='\n\n해결: API 키 입력칸에 선택한 모델의 API 키를 넣거나, 서버 환경변수 OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY 중 하나를 설정해야 합니다.';
    else if(msg.includes('Network')||msg.includes('LLM 호출 실패')) help='\n\n해결: 인터넷 연결, API 키 권한, 결제/사용량 제한, 회사 방화벽을 확인하세요.';
    document.getElementById('llmResult').textContent='❌ LLM 분석 오류: '+msg+help;
    document.getElementById('llmConnectState').textContent='연결 실패';
    document.getElementById('llmConnectState').className='value red';
    setLLMStatus('','오류 발생');
  }finally{
    document.getElementById('btnLLM').disabled=false;
  }
}

function triggerLLMAnalysis(){runLLMAnalysis();}

function toggleLLMAuto(){
  const btn=document.getElementById('btnLLMToggle');
  const sec=parseInt(document.getElementById('llmInterval').value)||0;
  if(llmAutoRunning){
    clearInterval(llmAutoTimer); llmAutoTimer=null; llmAutoRunning=false;
    btn.textContent='▶ 자동 분석 시작';
    btn.style.background='rgba(16,185,129,.15)';
    setLLMStatus('','자동 분석 중지됨');
  } else {
    if(sec===0){alert('자동 분석 간격을 5초 이상으로 설정해주세요.');return;}
    llmAutoRunning=true;
    btn.textContent='⏹ 자동 분석 중지';
    btn.style.background='rgba(239,68,68,.15)';
    runLLMAnalysis();
    llmAutoTimer=setInterval(runLLMAnalysis, sec*1000);
  }
}
function togglePause(){paused=!paused;document.getElementById('btnPause').textContent=paused?'▶ 재개':'⏸ 정지';if(paused){poseHistory.length=0;actionHistory.length=0;prevHipY=null;hipVelocity=0;}}
function switchTab(tab){
  // 순서 비의존: 각 .tab의 data-pane으로 매칭(테마별 페이지가 탭을 일부만 가질 수 있음)
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',(t.dataset.pane||'')===tab));
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
  const pane=document.getElementById('pane-'+tab);
  if(pane) pane.classList.add('active');
  if(tab==='commerce' && typeof updateCommercialReadiness==='function') updateCommercialReadiness();
}
function switchDomain(domain){
  document.querySelectorAll('.domain-btn').forEach(btn=>btn.classList.toggle('active',btn.dataset.domain===domain));
  document.querySelectorAll('.domain-pane').forEach(p=>p.classList.remove('active'));
  const pane=document.getElementById('domain-'+domain);
  if(pane) pane.classList.add('active');
  const presetMap={sports:'fitness',industrial:'industrial',office:'msd'};
  if(presetMap[domain]) applyErgoPromptPreset(presetMap[domain]);
}

function getActiveThemeProfile(){
  return SERVICE_META[activeServiceMode]||SERVICE_META.fitness;
}

function applyThemeProfile(meta){
  activeThemeProfile=meta||getActiveThemeProfile();
  document.body.dataset.themeDesign=activeThemeProfile.design||activeServiceMode;
  document.body.dataset.overlayMode=activeThemeProfile.overlay||'default';
  document.body.dataset.pipelinePose=activeThemeProfile.pipeline?.pose||'default';
  // Phase 2 guardrail: 프로파일은 선언/상태만 적용한다. 실제 기능 on/off는 Phase 3 이후.
  const modeTile=document.getElementById('analysisModeTile');
  if(modeTile) modeTile.dataset.overlayMode=activeThemeProfile.overlay||'default';
  const panel=document.querySelector('.right-panel');
  if(panel) panel.dataset.panelSet=(activeThemeProfile.panels||[]).join(',');
}

function setServiceMode(mode){
  activeServiceMode=mode;
  const meta=SERVICE_META[mode]||SERVICE_META.fitness;
  document.body.classList.remove('theme-fitness','theme-safety','theme-office');
  document.body.classList.add('theme-'+mode);
  document.querySelectorAll('.product-btn').forEach(btn=>btn.classList.toggle('active',btn.dataset.service===mode));
  document.querySelectorAll('[data-service-control]').forEach(btn=>btn.classList.toggle('active',btn.dataset.serviceControl===mode));
  document.querySelectorAll('[data-service-card]').forEach(card=>card.classList.toggle('active',card.dataset.serviceCard===mode));
  // 모드별 컨트롤 정리: data-ax="safety,fitness" 가 현재 모드를 포함하지 않으면 숨김(타 모드 도구 노출 방지)
  document.querySelectorAll('[data-ax]').forEach(el=>{
    const ax=(el.dataset.ax||'').split(',').map(s=>s.trim()).filter(Boolean);
    el.style.display = (ax.length===0 || ax.includes(mode)) ? '' : 'none';
  });
  // 안전 모드: 백엔드 정밀 보정은 항상 켜짐(주 탐지·포즈) → 토글 숨김(끄면 동작하는 혼란 방지)
  const _bbRow=document.getElementById('togBackendBoost')?.closest('.toggle-row');
  if(_bbRow) _bbRow.style.display = (mode==='safety') ? 'none' : '';
  const badge=document.getElementById('themeBadge');
  if(badge) badge.textContent=meta.badge||meta.title;
  if(mode==='fitness') switchDomain('sports');
  else if(mode==='safety') switchDomain('industrial');
  else switchDomain('office');
  applyThemeProfile(meta);
  updateServiceLiveCards(latestServiceInsight);
}

function setDot(id,state){document.getElementById(id).className='status-dot'+(state?' '+state:'');}
let lastAlert=0;
function playAlert(){const now=Date.now();if(now-lastAlert<3000)return;lastAlert=now;try{const ac=new AudioContext();const o=ac.createOscillator();const g=ac.createGain();o.connect(g);g.connect(ac.destination);o.frequency.value=880;g.gain.setValueAtTime(.3,ac.currentTime);g.gain.exponentialRampToValueAtTime(.001,ac.currentTime+.4);o.start();o.stop(ac.currentTime+.4);}catch(e){}}

function scoreClass(score){
  if(score>=82) return 'good';
  if(score>=62) return 'warn';
  return 'danger';
}

function poseMetricSnapshot(lm){
  if(!lm) return {hasPose:false,trunk:0,leftKnee:null,rightKnee:null,leftHip:null,rightHip:null,shoulderTilt:null,neckOffset:null};
  const leftKnee=calcAngle(lm[23],lm[25],lm[27]);
  const rightKnee=calcAngle(lm[24],lm[26],lm[28]);
  const leftHip=calcAngle(lm[11],lm[23],lm[25]);
  const rightHip=calcAngle(lm[12],lm[24],lm[26]);
  const trunk=getTrunkTilt(lm)||0;
  const lS=lm[11], rS=lm[12], nose=lm[0];
  const shoulderTilt=(lS&&rS)?Math.abs(Math.atan2(rS.y-lS.y,rS.x-lS.x)*180/Math.PI):null;
  const neckOffset=(lS&&rS&&nose)?Math.abs(nose.x-((lS.x+rS.x)/2))/(Math.abs(lS.x-rS.x)||0.3):null;
  return {hasPose:true,trunk,leftKnee,rightKnee,leftHip,rightHip,shoulderTilt,neckOffset};
}

function updateSquatCounter(metrics){
  const elCount=document.getElementById('squatRepCount');
  if(!metrics||!metrics.hasPose){
    if(elCount) updateSquatUI('전신 인식 필요');
    return {count:squatState.count, phase:squatState.phase, lastDepth:squatState.lastDepth, bestScore:squatState.bestScore, cue:'전신 인식 필요'};
  }
  const knees=[metrics.leftKnee,metrics.rightKnee].filter(v=>v!==null&&!Number.isNaN(v));
  if(knees.length===0){
    updateSquatUI('무릎 각도 측정 중');
    return {count:squatState.count, phase:squatState.phase, lastDepth:squatState.lastDepth, bestScore:squatState.bestScore, cue:'무릎 각도 측정 중'};
  }
  const avgKnee=knees.reduce((a,b)=>a+b,0)/knees.length;
  const kneeDiff=knees.length===2?Math.abs(knees[0]-knees[1]):0;
  const now=performance.now();
  let cue='준비 자세';

  if(squatState.phase==='ready'&&avgKnee<125&&metrics.trunk<60&&now-squatState.lastTransitionAt>450){
    squatState.phase='down';
    squatState.minKnee=avgKnee;
    squatState.maxTrunk=metrics.trunk||0;
    squatState.lastTransitionAt=now;
    cue='하강 중';
  }else if(squatState.phase==='down'){
    squatState.minKnee=Math.min(squatState.minKnee,avgKnee);
    squatState.maxTrunk=Math.max(squatState.maxTrunk,metrics.trunk||0);
    cue='최저점 확인 중';
    if(avgKnee>155&&now-squatState.lastTransitionAt>650){
      const depth=squatState.minKnee;
      const tempoSec=(now-squatState.lastTransitionAt)/1000;
      const rom=Math.max(0,Math.round(180-depth));
      const symmetry=Math.max(0,Math.min(100,Math.round(100-kneeDiff*2.2)));
      let score=92;
      if(depth>115) score-=18;
      else if(depth>100) score-=8;
      if(squatState.maxTrunk>42) score-=16;
      else if(squatState.maxTrunk>30) score-=7;
      if(kneeDiff>18) score-=10;
      if(tempoSec<0.9||tempoSec>5.0) score-=6;
      score=Math.max(45,Math.min(100,Math.round(score)));
      squatState.count++;
      squatState.lastDepth=Math.round(depth);
      squatState.lastScore=score;
      squatState.lastTempo=Number(tempoSec.toFixed(1));
      squatState.lastRom=rom;
      squatState.lastSymmetry=symmetry;
      squatState.bestScore=squatState.bestScore===null?score:Math.max(squatState.bestScore,score);
      squatState.reps.push({rep:squatState.count,depth:Math.round(depth),score,maxTrunk:Math.round(squatState.maxTrunk),tempoSec:squatState.lastTempo,rom,symmetry,time:new Date().toISOString()});
      if(squatState.reps.length>20) squatState.reps.shift();
      squatState.phase='ready';
      squatState.lastTransitionAt=now;
      cue=`${squatState.count}회 완료`;
    }
  }else if(avgKnee>150){
    cue='준비 자세';
  }

  updateSquatUI(cue);
  return {count:squatState.count, phase:squatState.phase, lastDepth:squatState.lastDepth, lastScore:squatState.lastScore, bestScore:squatState.bestScore, lastTempo:squatState.lastTempo, lastRom:squatState.lastRom, lastSymmetry:squatState.lastSymmetry, cue};
}

function updateSquatUI(cue){
  const set=(id,text)=>{const el=document.getElementById(id);if(el) el.textContent=text;};
  set('squatRepCount',squatState.count);
  set('squatPhase',squatState.phase==='down'?'하강':'준비');
  set('squatLastDepth',squatState.lastDepth===null?'—':`${squatState.lastDepth}°`);
  set('squatBestScore',squatState.bestScore===null?'—':`${squatState.bestScore}`);
  const guide=document.getElementById('squatGuide');
  if(guide){
    guide.className='simple-guide '+(squatState.lastScore!==null&&squatState.lastScore<70?'warn':'');
    guide.textContent=squatState.lastScore===null
      ? cue
      : `${cue} · 최근 점수 ${squatState.lastScore}점 · ROM ${squatState.lastRom??'—'}° · 템포 ${squatState.lastTempo??'—'}초`;
  }
}

function analyzeFitnessExercises(ar,m,lm){
  const knees=[m.leftKnee,m.rightKnee].filter(v=>v!==null&&!Number.isNaN(v));
  const hips=[m.leftHip,m.rightHip].filter(v=>v!==null&&!Number.isNaN(v));
  const avgKnee=knees.length?knees.reduce((a,b)=>a+b,0)/knees.length:null;
  const avgHip=hips.length?hips.reduce((a,b)=>a+b,0)/hips.length:null;
  const kneeDiff=knees.length===2?Math.abs(knees[0]-knees[1]):0;
  const elbowL=lm?calcAngle(lm[11],lm[13],lm[15]):null;
  const elbowR=lm?calcAngle(lm[12],lm[14],lm[16]):null;
  const elbows=[elbowL,elbowR].filter(v=>v!==null&&!Number.isNaN(v));
  const avgElbow=elbows.length?elbows.reduce((a,b)=>a+b,0)/elbows.length:null;
  const shoulderY=lm&&lm[11]&&lm[12]?(lm[11].y+lm[12].y)/2:null;
  const hipY=lm&&lm[23]&&lm[24]?(lm[23].y+lm[24].y)/2:null;
  const ankleY=lm&&lm[27]&&lm[28]?(lm[27].y+lm[28].y)/2:null;
  const horizontalBody=shoulderY!==null&&hipY!==null&&Math.abs(shoulderY-hipY)<0.16;
  const lowerBodyLong=hipY!==null&&ankleY!==null&&Math.abs(ankleY-hipY)>0.16;
  const candidates=[];

  const add=(type,label,score,metrics,problems,feedback)=>{
    candidates.push({
      type,label,
      score:Math.max(40,Math.min(100,Math.round(score))),
      metrics,problems:problems.filter(Boolean),feedback
    });
  };

  let squatScore=92;
  const squatProblems=[];
  if(m.trunk>35){squatScore-=20;squatProblems.push('상체 숙임 큼');}
  if(kneeDiff>18){squatScore-=14;squatProblems.push('좌우 무릎 차이 큼');}
  if(avgKnee!==null&&avgKnee>125){squatScore-=8;squatProblems.push('깊이 얕음');}
  add('squat','스쿼트',squatScore,[avgKnee?`무릎 ${avgKnee.toFixed(0)}도`:'무릎 측정 중',`몸통 ${m.trunk.toFixed(0)}도`,`좌우 ${kneeDiff.toFixed(0)}도`],squatProblems,'무릎과 발끝 방향을 맞추고 상체를 안정적으로 유지하세요.');

  if(knees.length===2){
    const frontKnee=Math.min(m.leftKnee??180,m.rightKnee??180);
    const backKnee=Math.max(m.leftKnee??0,m.rightKnee??0);
    let lungeScore=90;
    const p=[];
    if(frontKnee>125){lungeScore-=16;p.push('앞무릎 굴곡 부족');}
    if(backKnee<95){lungeScore-=10;p.push('뒷다리 접힘 과다');}
    if(kneeDiff<18){lungeScore-=8;p.push('런지 깊이 구분 약함');}
    if(m.trunk>28){lungeScore-=12;p.push('몸통 기울기 큼');}
    add('lunge','런지',lungeScore,[`앞무릎 ${frontKnee.toFixed(0)}도`,`뒷무릎 ${backKnee.toFixed(0)}도`,`몸통 ${m.trunk.toFixed(0)}도`],p,'앞발 전체로 지면을 누르고 골반이 한쪽으로 빠지지 않게 맞추세요.');
  }

  if(horizontalBody&&avgElbow!==null){
    let pushupScore=92;
    const p=[];
    if(avgElbow>155){pushupScore-=8;p.push('팔꿈치가 거의 펴진 상단 자세');}
    if(avgElbow<55){pushupScore-=10;p.push('팔꿈치 굴곡이 과도함');}
    if(m.trunk>18){pushupScore-=18;p.push('몸통 라인 무너짐');}
    add('pushup','푸쉬업',pushupScore,[`팔꿈치 ${avgElbow.toFixed(0)}도`,`몸통 ${m.trunk.toFixed(0)}도`],p,'머리부터 골반까지 일직선을 유지하고 팔꿈치를 과하게 벌리지 마세요.');
  }

  if(horizontalBody&&lowerBodyLong){
    let plankScore=94;
    const p=[];
    if(m.trunk>14){plankScore-=18;p.push('허리/골반 라인 불안정');}
    if(shoulderY!==null&&hipY!==null&&hipY-shoulderY>0.13){plankScore-=10;p.push('엉덩이 처짐 후보');}
    add('plank','플랭크',plankScore,[`몸통 ${m.trunk.toFixed(0)}도`,shoulderY!==null&&hipY!==null?`어깨-골반 ${(Math.abs(shoulderY-hipY)*100).toFixed(0)}%`:'정렬 측정 중'],p,'복부에 힘을 주고 어깨, 골반, 발목을 한 선에 가깝게 유지하세요.');
  }

  if(avgHip!==null&&avgKnee!==null){
    let deadliftScore=91;
    const p=[];
    if(m.trunk<15){deadliftScore-=6;p.push('힙힌지 감지 약함');}
    if(m.trunk>50){deadliftScore-=22;p.push('허리 굽힘 부담 큼');}
    if(avgKnee<75){deadliftScore-=8;p.push('무릎 사용 과다');}
    if(avgHip>150){deadliftScore-=8;p.push('고관절 접힘 부족');}
    add('deadlift','데드리프트/힙힌지',deadliftScore,[`고관절 ${avgHip.toFixed(0)}도`,`무릎 ${avgKnee.toFixed(0)}도`,`몸통 ${m.trunk.toFixed(0)}도`],p,'엉덩이를 뒤로 빼며 힙힌지를 만들고 허리가 말리지 않게 유지하세요.');
  }

  const action=(ar?.action||'');
  const priority=action.includes('스쿼트')?'squat':horizontalBody?'plank':null;
  candidates.sort((a,b)=>{
    if(priority&&a.type===priority) return -1;
    if(priority&&b.type===priority) return 1;
    return b.score-a.score;
  });
  return candidates[0]||candidates.find(c=>c.type==='squat');
}

function buildFitnessInsight(ar, lm){
  const m=poseMetricSnapshot(lm);
  if(!m.hasPose) return {name:'BODA Fitness 실시간 코치',sub:'스쿼트, 런지, 플랭크 자세를 쉽게 확인합니다.',score:null,summary:'사람의 전신이 보이면 운동 자세를 분석합니다.',problem:'아직 포즈가 충분히 감지되지 않았습니다.',feedback:'카메라에 머리부터 발까지 보이게 서 주세요.',metrics:['전신 인식 필요'],level:'warn'};
  const squat=updateSquatCounter(m);
  const knees=[m.leftKnee,m.rightKnee].filter(v=>v!==null);
  const avgKnee=knees.length?knees.reduce((a,b)=>a+b,0)/knees.length:null;
  const kneeDiff=knees.length===2?Math.abs(knees[0]-knees[1]):0;
  const exercise=analyzeFitnessExercises(ar,m,lm);
  let score=92;
  const problems=[];
  const feedback=[];
  if(m.trunk>35){score-=22;problems.push('상체가 많이 숙여졌습니다');feedback.push('가슴을 세우고 복부에 힘을 준 상태로 내려가세요.');}
  else if(m.trunk>22){score-=10;problems.push('상체 기울기가 조금 큽니다');feedback.push('허리가 말리지 않게 시선과 가슴을 정면에 두세요.');}
  if(kneeDiff>18){score-=14;problems.push('좌우 무릎 각도 차이가 큽니다');feedback.push('양발에 체중을 비슷하게 싣고 같은 속도로 움직이세요.');}
  if(avgKnee!==null&&ar.action.includes('스쿼트')&&avgKnee>125){score-=8;problems.push('스쿼트 깊이가 얕을 수 있습니다');feedback.push('통증이 없다면 고관절을 더 접어 천천히 내려가세요.');}
  if(squat.lastTempo!==null&&(squat.lastTempo<0.9||squat.lastTempo>5.0)){problems.push('반복 템포가 일정하지 않습니다');feedback.push('내려가고 올라오는 속도를 일정하게 유지하세요.');}
  if(exercise&&exercise.type!=='squat'){
    score=Math.round((score+exercise.score)/2);
    if(exercise.problems.length) problems.unshift(...exercise.problems.slice(0,2));
    feedback.unshift(exercise.feedback);
  }
  const exerciseLabel=exercise?.label||'운동 자세';
  const summary=ar.action.includes('스쿼트')||squat.count>0
    ? `스쿼트 ${squat.count}회 · 점수 ${Math.max(40,Math.round(score))}점 · ROM ${squat.lastRom??'측정 중'}${squat.lastRom!==null?'°':''}입니다.`
    : `${exerciseLabel} 후보 · 점수 ${Math.max(40,Math.round(score))}점으로 분석 중입니다.`;
  const exerciseMetrics=exercise?[`운동 ${exercise.label}`,...exercise.metrics]:['운동 후보 분석 중'];
  return {
    name:'BODA Fitness 실시간 코치',
    sub:'운동 자세 오류, 균형, 반복 안정성을 즉시 확인합니다.',
    score:Math.max(40,Math.min(100,Math.round(score))),
    summary,
    problem:problems.length?problems.join(' · '):'큰 자세 오류는 보이지 않습니다.',
    feedback:feedback[0]||'현재 리듬을 유지하되 무릎과 발끝 방향을 계속 맞추세요.',
    metrics:[...exerciseMetrics.slice(0,3),`스쿼트 ${squat.count}회`,squat.lastRom!==null?`ROM ${squat.lastRom}도`:'ROM 측정 중',squat.lastTempo!==null?`템포 ${squat.lastTempo}초`:'템포 대기',squat.lastSymmetry!==null?`대칭 ${squat.lastSymmetry}점`:`좌우 차이 ${kneeDiff.toFixed(0)}도`],
    level:scoreClass(score)
  };
}

function buildSafetyInsight(ar, lm, objects){
  const m=poseMetricSnapshot(lm);
  const visible=objects.filter(o=>o.gone===0);
  const danger=visible.filter(o=>DANGER_OBJ.includes(o.class));
  const ppeIssues=getPpeIssues();
  const personCount=Math.max(detectedPersonCount,m.hasPose?1:0);
  let score=94;
  const problems=[];
  const feedback=[];
  if(ar.danger){score-=38;problems.push('낙상 후보가 감지됐습니다');feedback.push('관리자가 즉시 현장을 확인해야 합니다.');}
  else if(ar.warn){score-=16;problems.push('불안정한 자세가 감지됐습니다');feedback.push('작업자 상태와 주변 장애물을 확인하세요.');}
  if(m.hasPose&&m.trunk>35){score-=15;problems.push('허리 굽힘 부담이 큽니다');feedback.push('중량물은 몸 가까이 붙이고 무릎을 함께 사용하세요.');}
  if(danger.length){score-=12;problems.push(`위험 사물 ${danger.map(o=>translateClass(o.class)).join(', ')} 감지`);feedback.push('위험 도구 사용 구역과 보호구 착용 상태를 확인하세요.');}
  if(ppeIssues.length){score-=18;problems.push(ppeIssues.map(i=>i.title).join(' · '));feedback.push('안전모와 안전조끼 착용 여부를 현장에서 다시 확인하세요.');}
  if(personCount===0){score-=10;problems.push('작업자 감지가 불안정합니다');feedback.push('카메라 각도, 조명, 작업자 가림을 조정하세요.');}
  const h=latestPpeStatus.helmet.state==='worn'?'안전모 착용':latestPpeStatus.helmet.state==='missing'?'안전모 미착용 의심':'안전모 확인 중';
  const v=latestPpeStatus.vest.state==='worn'?'조끼 착용':latestPpeStatus.vest.state==='missing'?'조끼 미착용 의심':'조끼 확인 중';
  return {
    name:'BODA Safety 현장 알림',
    sub:'보호구, 위험구역, 위험 행동 후보를 관리자 관점으로 요약합니다.',
    score:Math.max(35,Math.min(100,Math.round(score))),
    summary:personCount>0?`작업자 ${personCount}명 기준으로 보호구와 위험 자세를 확인 중입니다.`:'작업자가 명확히 보이지 않습니다.',
    problem:problems.length?problems.join(' · '):'현재 큰 위험 신호는 없습니다.',
    feedback:feedback[0]||'현장 리포트용으로 위험 이벤트가 발생하면 현재 장면 기록을 눌러 증거를 남기세요.',
    metrics:[`작업자 ${personCount}명`,h,v,`위험 사물 ${danger.length}개`],
    level:scoreClass(score)
  };
}

function buildOfficeInsight(ar, lm){
  const m=poseMetricSnapshot(lm);
  if(!m.hasPose) return {name:'BODA Office Care',sub:'거북목, 허리 굽힘, 어깨 불균형을 쉽게 확인합니다.',score:null,summary:'상체가 보이면 데스크 자세를 분석합니다.',problem:'아직 상체 포즈가 충분히 감지되지 않았습니다.',feedback:'얼굴, 어깨, 허리가 카메라에 함께 보이도록 앉아 주세요.',metrics:['상체 인식 필요'],level:'warn'};
  let score=93;
  const problems=[];
  const feedback=[];
  const now=performance.now();
  const delta=officeState.lastUpdateAt?Math.min(3,(now-officeState.lastUpdateAt)/1000):0;
  officeState.lastUpdateAt=now;
  const sitting=ar.action==='앉아 있음';
  const neckRisk=m.neckOffset!==null&&m.neckOffset>0.34;
  const trunkRisk=m.trunk>18;
  const shoulderRisk=m.shoulderTilt!==null&&m.shoulderTilt>9;
  if(sitting) officeState.sittingSeconds+=delta;
  if(neckRisk) officeState.neckRiskSeconds+=delta;
  else officeState.neckRiskSeconds=Math.max(0,officeState.neckRiskSeconds-delta*0.5);
  if(trunkRisk) officeState.trunkRiskSeconds+=delta;
  else officeState.trunkRiskSeconds=Math.max(0,officeState.trunkRiskSeconds-delta*0.5);
  if(shoulderRisk) officeState.shoulderRiskSeconds+=delta;
  else officeState.shoulderRiskSeconds=Math.max(0,officeState.shoulderRiskSeconds-delta*0.5);
  officeState.breakDue=officeState.sittingSeconds>=50*60;
  if(neckRisk){score-=18;problems.push('목이 앞으로 빠진 거북목 자세입니다');feedback.push('턱을 가볍게 당기고 귀가 어깨 위에 오도록 맞추세요.');}
  if(trunkRisk){score-=16;problems.push('상체가 앞으로 숙여졌습니다');feedback.push('허리를 등받이에 붙이고 모니터를 눈높이에 맞추세요.');}
  if(shoulderRisk){score-=10;problems.push('어깨 좌우 높이 차이가 있습니다');feedback.push('키보드와 마우스를 몸 중앙에 두고 양어깨 힘을 빼세요.');}
  if(officeState.neckRiskSeconds>=120){score-=8;problems.push('거북목 자세가 2분 이상 지속됐습니다');feedback.push('지금 10초 동안 턱을 당기고 목 뒤를 길게 세우세요.');}
  if(officeState.trunkRiskSeconds>=180){score-=8;problems.push('구부정한 자세가 3분 이상 이어졌습니다');feedback.push('등받이에 허리를 붙이고 의자 깊숙이 앉으세요.');}
  if(officeState.breakDue){score-=10;problems.push('장시간 앉음 휴식 시간이 필요합니다');feedback.push('자리에서 일어나 2분간 걷거나 가볍게 스트레칭하세요.');}
  if(ar.action!=='앉아 있음'&&ar.action!=='서 있음'){score-=5;}
  const min=Math.floor(officeState.sittingSeconds/60);
  const sec=Math.floor(officeState.sittingSeconds%60).toString().padStart(2,'0');
  const riskMin=Math.floor(Math.max(officeState.neckRiskSeconds,officeState.trunkRiskSeconds,officeState.shoulderRiskSeconds)/60);
  const riskSec=Math.floor(Math.max(officeState.neckRiskSeconds,officeState.trunkRiskSeconds,officeState.shoulderRiskSeconds)%60).toString().padStart(2,'0');
  return {
    name:'BODA Office Care',
    sub:'업무 중 목, 허리, 어깨 자세를 실시간으로 교정합니다.',
    score:Math.max(40,Math.min(100,Math.round(score))),
    summary:`현재 ${ar.action} · 착석 ${min}:${sec} · 데스크 자세 점수 ${Math.max(40,Math.round(score))}점입니다.`,
    problem:problems.length?problems.join(' · '):'목, 허리, 어깨 정렬이 비교적 안정적입니다.',
    feedback:feedback[0]||'현재 자세를 유지하되 30분마다 짧게 일어나 움직이세요.',
    metrics:[`착석 ${min}:${sec}`,`위험 지속 ${riskMin}:${riskSec}`,`목 전방 ${m.neckOffset!==null?(m.neckOffset*100).toFixed(0)+'%':'측정 중'}`,`몸통 ${m.trunk.toFixed(0)}도`,m.shoulderTilt!==null?`어깨 ${m.shoulderTilt.toFixed(0)}도`:'어깨 측정 중',officeState.breakDue?'휴식 필요':'휴식 대기'],
    level:scoreClass(score)
  };
}

function buildServiceInsight(ar, lm, objects){
  const insight={
    fitness:buildFitnessInsight(ar,lm),
    safety:buildSafetyInsight(ar,lm,objects||[]),
    office:buildOfficeInsight(ar,lm)
  };
  latestServiceInsight=insight;
  return insight;
}

function speakServiceFeedback(text){
  const tog=document.getElementById('togVoiceFeedback');
  if(!tog||!tog.checked||!window.speechSynthesis||!text) return;
  const now=Date.now();
  if(text===lastSpokenFeedback&&now-lastSpokenAt<12000) return;
  if(now-lastSpokenAt<5000) return;
  lastSpokenFeedback=text;
  lastSpokenAt=now;
  window.speechSynthesis.cancel();
  const u=new SpeechSynthesisUtterance(text);
  u.lang='ko-KR'; u.rate=1.02; u.pitch=1;
  window.speechSynthesis.speak(u);
}

function updateServiceLiveCards(insight){
  const meta=SERVICE_META[activeServiceMode]||SERVICE_META.fitness;
  const item=(insight&&insight[activeServiceMode])||{
    name:meta.panel.replace(' 분석 중',''),
    sub:meta.sub,
    score:null,
    summary:`${meta.title} 모드가 선택됐습니다. 카메라를 켜면 현재 분석 대상이 여기에 표시됩니다.`,
    problem:'아직 실시간 분석 결과가 없습니다.',
    feedback:'카메라를 켜고 분석 대상이 화면 중앙에 오도록 맞추세요.',
    metrics:['분석 대기'],
    level:'warn'
  };
  if(!document.getElementById('activeServiceName')) return;
  document.getElementById('activeServiceName').textContent=item.name;
  document.getElementById('activeServiceSub').textContent=item.sub;
  const scoreEl=document.getElementById('serviceScore');
  scoreEl.textContent=item.score===null?'--':String(item.score);
  scoreEl.className='live-score '+(item.level||'warn');
  document.getElementById('serviceSummary').textContent=item.summary;
  document.getElementById('serviceProblem').textContent=item.problem;
  document.getElementById('serviceFeedback').textContent=item.feedback;
  document.getElementById('serviceMetrics').innerHTML=(item.metrics||[]).map(m=>`<div class="metric-pill">${escapeHtml(m)}</div>`).join('');
  const featureBox=document.getElementById('themeFeaturePills');
  if(featureBox){
    featureBox.innerHTML=(meta.features||[]).map(f=>`<div class="theme-pill">${escapeHtml(f)}</div>`).join('');
  }
  const modeTile=document.getElementById('analysisModeTile');
  if(modeTile) modeTile.className='analysis-tile mode '+(meta.tile||'');
  const scoreBox=document.getElementById('overlayScoreBox');
  if(scoreBox) scoreBox.className='analysis-tile analysis-score '+(item.level||'warn');
  const setText=(id,text)=>{const el=document.getElementById(id);if(el) el.textContent=text;};
  setText('overlayModeTitle',meta.title);
  setText('overlayModeSub',meta.modeSub);
  setText('overlayFocus',item.summary);
  setText('overlayFeedback',item.problem==='큰 자세 오류는 보이지 않습니다.'||item.problem==='현재 큰 위험 신호는 없습니다.'||item.problem==='목, 허리, 어깨 정렬이 비교적 안정적입니다.'?item.feedback:`문제: ${item.problem} · 개선: ${item.feedback}`);
  setText('overlayScore',item.score===null?'--':String(item.score));
  setText('panelModeTitle',meta.panel);
  setText('panelModeSub',meta.sub);
  const chipBox=document.getElementById('overlayChips');
  if(chipBox){
    const chips=(item.metrics||[]).slice(0,4).map(m=>`<div class="analysis-chip ${item.level||'warn'}">${escapeHtml(m)}</div>`);
    chipBox.innerHTML=chips.length?chips.join(''):'<div class="analysis-chip warn">분석 대기</div>';
  }
  if(item.level==='danger'||item.level==='warn') speakServiceFeedback(item.feedback);
  updateCommercialReadiness();
}

function commercialAuditPayload(){
  const scored=serviceEvents.filter(e=>typeof e.score==='number');
  const avgScore=scored.length?Math.round(scored.reduce((a,e)=>a+e.score,0)/scored.length):null;
  const hasPpeFresh=Date.now()-(latestPpeStatus.updatedAt||0)<5000;
  const eventWithImage=serviceEvents.filter(e=>e.image).length;
  const objectSamples=latestObjects.filter(o=>o.gone===0).length;
  const checks=[
    {key:'realtime',name:'실시간 카메라 분석',done:cameraOn||serviceEvents.length>0,desc:'카메라 입력, 포즈/객체/손 분석 루프'},
    {key:'report',name:'증거 이미지 리포트',done:eventWithImage>0,desc:`캡처 포함 이벤트 ${eventWithImage}개`},
    {key:'fitness',name:'스쿼트 반복/자세 기록',done:squatState.count>0,desc:`스쿼트 ${squatState.count}회, 최고 ${squatState.bestScore??'—'}점`},
    {key:'safety',name:'PPE 판단 근거 표시',done:hasPpeFresh,desc:`안전모 ${latestPpeStatus.helmet.label}, 조끼 ${latestPpeStatus.vest.label}`},
    {key:'objects',name:'객체/작은 물건 데이터',done:objectSamples>0||cropSaveCount>0,desc:`현재 객체 ${objectSamples}개, 손 crop ${cropSaveCount}장`},
    {key:'review',name:'검수/정확도 루프',done:serviceEvents.length>=3,desc:'상용 전 맞음/틀림 검수 데이터 필요'},
    {key:'custom_model',name:'전용 모델 학습',done:false,desc:'PPE YOLO와 작은 물건 classifier 학습 필요'}
  ];
  const doneCount=checks.filter(c=>c.done).length;
  const score=Math.round((doneCount/checks.length)*10);
  return {
    created_at:new Date().toISOString(),
    active_service:activeServiceMode,
    readiness_score_10:score,
    avg_session_score:avgScore,
    events:serviceEvents.length,
    events_with_image:eventWithImage,
    squat:{count:squatState.count,bestScore:squatState.bestScore,lastDepth:squatState.lastDepth,lastTempo:squatState.lastTempo,lastRom:squatState.lastRom,lastSymmetry:squatState.lastSymmetry,reps:squatState.reps},
    ppe:latestPpeStatus,
    object_samples:objectSamples,
    crop_save_count:cropSaveCount,
    office:{...officeState},
    checks,
    next_actions:[
      'PPE YOLO 전용 모델 학습 데이터 3,000장 이상 확보',
      '스쿼트 정면/측면 모드 분리 및 300개 이상 영상 검수',
      '사무직 자세 유지 시간 누적 지표 추가',
      '검수 화면에서 맞음/틀림/판단불가 라벨 수집',
      '기능별 F1/mAP/카운트 정확도 리포트 생성'
    ]
  };
}

function updateCommercialReadiness(){
  const pane=document.getElementById('pane-commerce');
  if(!pane) return;
  const audit=commercialAuditPayload();
  const scoreEl=document.getElementById('commerceScore');
  if(scoreEl) scoreEl.textContent=`${audit.readiness_score_10}/10`;
  const desc=document.getElementById('commerceScoreDesc');
  if(desc) desc.textContent=audit.readiness_score_10>=7?'파일럿 제안 가능 단계입니다.':'데이터 검수와 전용 모델 준비가 더 필요합니다.';
  const eventEl=document.getElementById('commerceEventCount');
  if(eventEl) eventEl.textContent=`${audit.events_with_image}/${audit.events}`;
  const squatEl=document.getElementById('commerceSquatCount');
  if(squatEl) squatEl.textContent=`${audit.squat.count}회`;
  const reviewEl=document.getElementById('commerceReviewNeed');
  if(reviewEl) reviewEl.textContent=audit.events>=10?'중간':audit.events>=3?'높음':'매우 높음';
  const list=document.getElementById('commerceChecklist');
  if(list){
    list.innerHTML=audit.checks.map(c=>`
      <div class="readiness-item ${c.done?'done':c.key==='custom_model'?'blocked':''}">
        <div class="mark">${c.done?'✓':c.key==='custom_model'?'!':'·'}</div>
        <div><div class="name">${escapeHtml(c.name)}</div><div class="desc">${escapeHtml(c.desc)}</div></div>
        <div class="status">${c.done?'완료':'필요'}</div>
      </div>
    `).join('');
  }
}

function downloadCommercialAudit(){
  const payload=commercialAuditPayload();
  const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json;charset=utf-8'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url;
  a.download=`ax_commercial_audit_${Date.now()}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function saveServiceSnapshot(){
  const item=latestServiceInsight&&latestServiceInsight[activeServiceMode];
  if(!item){alert('아직 기록할 분석 결과가 없습니다.');return;}
  let imageDataUrl='';
  try{imageDataUrl=captureFrameDataUrl();}catch(e){}
  serviceEvents.push({
    time:new Date().toISOString(),
    service:activeServiceMode,
    score:item.score,
    summary:item.summary,
    problem:item.problem,
    feedback:item.feedback,
    metrics:item.metrics,
    image:imageDataUrl,
    ppe:JSON.parse(JSON.stringify(latestPpeStatus)),
    fitnessExercise:item.name&&activeServiceMode==='fitness'?{summary:item.summary,problem:item.problem,feedback:item.feedback,metrics:item.metrics}:null,
    squat:{count:squatState.count,lastDepth:squatState.lastDepth,lastScore:squatState.lastScore,bestScore:squatState.bestScore,lastTempo:squatState.lastTempo,lastRom:squatState.lastRom,lastSymmetry:squatState.lastSymmetry,reps:[...squatState.reps]},
    office:{...officeState},
    objects:latestObjects.filter(o=>o.gone===0).slice(0,10).map(o=>({class:o.class,score:o.score,bbox:o.bbox,id:o.id}))
  });
  {const _rs=document.getElementById('reportStatus'); if(_rs)_rs.textContent=`기록된 이벤트 ${serviceEvents.length}개 · 마지막 기록 ${new Date().toLocaleTimeString('ko-KR')}`;}
  updateCommercialReadiness();
}

function downloadSessionReport(){
  if(serviceEvents.length===0) saveServiceSnapshot();
  const scored=serviceEvents.filter(e=>typeof e.score==='number');
  const avgScore=scored.length?Math.round(scored.reduce((a,e)=>a+e.score,0)/scored.length):null;
  const serviceName={fitness:'BODA Fitness',safety:'BODA Safety',office:'BODA Office Care'}[activeServiceMode]||activeServiceMode;
  const rows=serviceEvents.map((e,idx)=>`
    <section class="event">
      <div class="event-head">
        <div>
          <h2>#${idx+1} ${escapeHtml(({fitness:'BODA Fitness',safety:'BODA Safety',office:'BODA Office Care'}[e.service]||e.service))}</h2>
          <p>${escapeHtml(new Date(e.time).toLocaleString('ko-KR'))}</p>
        </div>
        <div class="score">${e.score===null||e.score===undefined?'--':escapeHtml(e.score)}</div>
      </div>
      ${e.image?`<img class="shot" src="${e.image}" alt="event capture ${idx+1}">`:''}
      <dl>
        <dt>한눈 요약</dt><dd>${escapeHtml(e.summary)}</dd>
        <dt>문제점</dt><dd>${escapeHtml(e.problem)}</dd>
        <dt>개선 피드백</dt><dd>${escapeHtml(e.feedback)}</dd>
        <dt>지표</dt><dd>${(e.metrics||[]).map(m=>`<span class="pill">${escapeHtml(m)}</span>`).join('')}</dd>
        <dt>보호구</dt><dd>안전모 ${escapeHtml(e.ppe?.helmet?.label||e.ppe?.helmet?.state||'확인 중')} · 조끼 ${escapeHtml(e.ppe?.vest?.label||e.ppe?.vest?.state||'확인 중')}</dd>
        <dt>스쿼트</dt><dd>${escapeHtml(e.squat?.count??0)}회 · 최근 최저각 ${escapeHtml(e.squat?.lastDepth??'—')} · ROM ${escapeHtml(e.squat?.lastRom??'—')} · 템포 ${escapeHtml(e.squat?.lastTempo??'—')}초 · 대칭 ${escapeHtml(e.squat?.lastSymmetry??'—')}점 · 최고점수 ${escapeHtml(e.squat?.bestScore??'—')}</dd>
        <dt>운동 분석</dt><dd>${(e.fitnessExercise?.metrics||[]).map(m=>`<span class="pill">${escapeHtml(m)}</span>`).join('')||'—'}</dd>
        <dt>데스크 자세</dt><dd>착석 ${escapeHtml(Math.floor((e.office?.sittingSeconds||0)/60))}분 · 거북목 ${escapeHtml(Math.floor((e.office?.neckRiskSeconds||0)/60))}분 · 허리굽힘 ${escapeHtml(Math.floor((e.office?.trunkRiskSeconds||0)/60))}분 · 휴식 ${e.office?.breakDue?'필요':'대기'}</dd>
      </dl>
    </section>
  `).join('');
  const html=`<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>BODA TECH 분석 리포트</title>
  <style>
    body{font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Segoe UI',sans-serif;margin:0;background:#f7fafc;color:#111827;}
    header{background:#0f172a;color:white;padding:28px 34px;} h1{margin:0 0 8px;font-size:26px;} header p{margin:0;color:#cbd5e1;}
    main{max-width:980px;margin:0 auto;padding:24px;} .summary{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px;}
    .box,.event{background:white;border:1px solid #e5e7eb;border-radius:12px;padding:16px;box-shadow:0 8px 24px rgba(15,23,42,.06);}
    .box b{display:block;font-size:24px;margin-top:6px;color:#0f172a;} .event{margin-bottom:16px;}
    .event-head{display:flex;justify-content:space-between;gap:12px;align-items:center;border-bottom:1px solid #e5e7eb;padding-bottom:10px;margin-bottom:12px;}
    h2{margin:0;font-size:18px;} .event-head p{margin:4px 0 0;color:#64748b;font-size:13px;}
    .score{font-size:34px;font-weight:900;color:#f59e0b;} .shot{width:100%;max-height:520px;object-fit:contain;background:#020617;border-radius:10px;margin-bottom:12px;}
    dl{display:grid;grid-template-columns:110px 1fr;gap:8px 12px;margin:0;} dt{font-weight:800;color:#475569;} dd{margin:0;line-height:1.55;}
    .pill{display:inline-block;background:#e0f2fe;color:#075985;border-radius:999px;padding:4px 9px;margin:2px;font-size:12px;font-weight:700;}
  </style></head><body>
  <header><h1>BODA TECH 서비스 실시간 분석 리포트</h1><p>${escapeHtml(new Date().toLocaleString('ko-KR'))} · 현재 모드 ${escapeHtml(serviceName)}</p></header>
  <main>
    <div class="summary">
      <div class="box">기록 이벤트<b>${serviceEvents.length}개</b></div>
      <div class="box">평균 점수<b>${avgScore===null?'--':avgScore}</b></div>
      <div class="box">스쿼트 누적<b>${squatState.count}회</b></div>
    </div>
    ${rows}
  </main></body></html>`;
  const blob=new Blob([html],{type:'text/html;charset=utf-8'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url;
  a.download=`ax_service_report_${Date.now()}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ═══════════════════════════════════════════════════
//  특수 행동 감지 — 포즈 랜드마크 기반 (카메라 거리 무관)
// ═══════════════════════════════════════════════════
function detectSpecialActions(lHandLM, rHandLM, poseLM, faceLM, lHeld, rHeld){
  const acts=[];
  if(!poseLM) return acts;

  // 포즈 기준점 (정규화 좌표 0~1)
  const nose=poseLM[0], lEar=poseLM[7], rEar=poseLM[8];
  const lS=poseLM[11], rS=poseLM[12]; // 어깨
  const lW=poseLM[15], rW=poseLM[16]; // 손목(포즈)
  if(!lS||!rS) return acts;

  const shoulderY=(lS.y+rS.y)/2;
  const shoulderSpan=Math.abs(lS.x-rS.x)||0.3; // 어깨 너비 = 스케일 기준
  const faceY=nose?nose.y:shoulderY-0.15;
  const faceX=nose?nose.x:(lS.x+rS.x)/2;

  // 손목이 특정 기준점 근처인지 (어깨 너비 기준 상대거리)
  function near(handLM, refX, refY, factorX, factorY){
    if(!handLM) return false;
    const w=handLM[0];
    return Math.abs(w.x-refX)<shoulderSpan*factorX && Math.abs(w.y-refY)<shoulderSpan*factorY;
  }
  function aboveShoulder(handLM, offset=0.04){
    return handLM && handLM[0].y < shoulderY-offset;
  }

  // 포즈 손목 위치로도 보완 (MediaPipe 손 랜드마크가 없을 때)
  const lWristY=lHandLM?lHandLM[0].y:(lW?lW.y:1);
  const lWristX=lHandLM?lHandLM[0].x:(lW?lW.x:0);
  const rWristY=rHandLM?rHandLM[0].y:(rW?rW.y:1);
  const rWristX=rHandLM?rHandLM[0].x:(rW?rW.x:1);

  const lAbove=lWristY<shoulderY-0.04;
  const rAbove=rWristY<shoulderY-0.04;

  // 귀 근처 (전화)
  const lEarX=lEar?lEar.x:lS.x, lEarY=lEar?lEar.y:shoulderY-0.18;
  const rEarX=rEar?rEar.x:rS.x, rEarY=rEar?rEar.y:shoulderY-0.18;
  const lNearLEar=near(lHandLM,lEarX,lEarY,0.5,0.4);
  const rNearREar=near(rHandLM,rEarX,rEarY,0.5,0.4);

  // 입·코 근처
  const lNearMouth=near(lHandLM,faceX,faceY+shoulderSpan*0.15,0.4,0.35);
  const rNearMouth=near(rHandLM,faceX,faceY+shoulderSpan*0.15,0.4,0.35);

  // 머리 위 근처 (얼굴보다 위)
  const lNearHead=lAbove && Math.abs(lWristX-faceX)<shoulderSpan*0.55;
  const rNearHead=rAbove && Math.abs(rWristX-faceX)<shoulderSpan*0.55;

  // 얼굴 영역 (코 근처)
  const lNearFace=near(lHandLM,faceX,faceY,0.45,0.35);
  const rNearFace=near(rHandLM,faceX,faceY,0.45,0.35);

  const lHasPhone=lHeld.some(o=>o.class==='cell phone');
  const rHasPhone=rHeld.some(o=>o.class==='cell phone');
  const hasCup=lHeld.some(o=>['cup','bottle','wine glass'].includes(o.class))||rHeld.some(o=>['cup','bottle','wine glass'].includes(o.class));
  const hasBook=lHeld.some(o=>o.class==='book')||rHeld.some(o=>o.class==='book');
  const hasKnife=lHeld.some(o=>['knife','scissors'].includes(o.class))||rHeld.some(o=>['knife','scissors'].includes(o.class));
  const hasBat=lHeld.some(o=>['baseball bat','tennis racket'].includes(o.class))||rHeld.some(o=>['baseball bat','tennis racket'].includes(o.class));

  // MobileNet 결과에서도 전화/컵/책 여부 확인
  const mnL=leftMobileNetResult, mnR=rightMobileNetResult;
  const mnHasPhone=[...mnL,...mnR].some(p=>p.className.toLowerCase().match(/phone|mobile|cellular/));
  const mnHasCup=[...mnL,...mnR].some(p=>p.className.toLowerCase().match(/cup|mug|bottle|glass|teapot/));
  const mnHasBook=[...mnL,...mnR].some(p=>p.className.toLowerCase().match(/book|notebook|binder|magazine/));

  // 전화 통화
  if((lHasPhone||rHasPhone||mnHasPhone)&&(lNearLEar||rNearREar||(lAbove&&lNearFace)||(rAbove&&rNearFace)))
    acts.push({icon:'📞',text:'전화 통화 중',detail:'휴대폰이 귀/얼굴 근처에 있음'});
  else if(lHasPhone||rHasPhone||mnHasPhone)
    acts.push({icon:'📱',text:'휴대폰 사용 중',detail:'스크롤·타이핑 등 화면 조작 추정'});

  // 음료 마시기
  if((hasCup||mnHasCup)&&(lNearMouth||rNearMouth))
    acts.push({icon:'🥤',text:'음료 마시는 중',detail:'컵이 입 근처에 있음'});
  else if(hasCup||mnHasCup)
    acts.push({icon:'☕',text:'음료 들고 있음',detail:'컵·병·잔 감지됨'});

  // 책 읽기
  if(hasBook||mnHasBook)
    acts.push({icon:'📖',text:'책·문서 보는 중',detail:'책이 손에 감지됨'});

  // 위험 도구
  if(hasKnife)
    acts.push({icon:'⚠️',text:'날카로운 도구 소지',detail:'칼·가위 감지됨',danger:true});

  if(hasBat)
    acts.push({icon:'🏏',text:'운동 도구 사용',detail:'배트·라켓 감지됨'});

  // 음식 먹기 (사물 없이 손이 입 근처)
  if(!hasCup&&!mnHasCup&&(lNearMouth||rNearMouth)&&!lHasPhone&&!rHasPhone&&!mnHasPhone)
    acts.push({icon:'🍽',text:'음식 먹는 중',detail:'손이 입 근처에 있음'});

  // 머리·얼굴 만지기
  const anyAbove=lNearHead||rNearHead;
  const anyFaceTch=(lNearFace&&!lNearMouth)||(rNearFace&&!rNearMouth);
  if(anyAbove&&!anyFaceTch&&!hasCup&&!lHasPhone&&!rHasPhone&&!mnHasPhone&&!mnHasCup)
    acts.push({icon:'💆',text:'머리 만지는 중',detail:'손이 머리 높이에 있음'});
  else if(anyFaceTch&&!lNearMouth&&!rNearMouth&&!lHasPhone&&!rHasPhone&&!mnHasPhone)
    acts.push({icon:'🤔',text:'얼굴 만지는 중',detail:'손이 얼굴 근처에 있음'});

  // 손가락으로 가리키기
  function isPointing(hLM){
    if(!hLM) return false;
    const t8=hLM[8],t12=hLM[12],w=hLM[0];
    return t8&&t12&&w&&dist(t8,w)>0.12&&dist(t12,w)<dist(t8,w)*0.85;
  }
  if((isPointing(lHandLM)||isPointing(rHandLM))&&!anyAbove&&!lNearMouth&&!rNearMouth)
    acts.push({icon:'👆',text:'손가락으로 가리키는 중',detail:'검지를 뻗고 있음'});

  return acts;
}

// ═══════════════════════════════════════════════════
//  자연어 장면 설명 생성
// ═══════════════════════════════════════════════════
function generateNarrative(genderInfo, ageInfo, actionResult, specialActs, lHeld, rHeld){
  // 사람 수 (전용 감지값 우선, 최소 1명)
  const personCount=Math.max(detectedPersonCount,sm?1:0);
  if(personCount===0){
    return{sentence:'사람을 찾는 중입니다', sub:'사람이 화면 중앙에 보이면 인원, 자세, 행동을 함께 분석합니다.'};
  }
  const countKo=['','한','두','세','네','다섯','여섯'];
  const cStr=personCount<=6?countKo[personCount]:personCount+'';

  // 성별
  let who='사람';
  if(genderInfo){ who=genderInfo.gender.includes('남')?'남성':'여성'; }
  const subject=personCount===1?`${who} ${cStr}명이`:`사람 ${cStr}명이`;

  // 행동 — 특수행동 우선, 없으면 포즈 기반
  const spMap={
    '전화 통화 중':'전화 통화를 하고 있습니다',
    '휴대폰 사용 중':'휴대폰을 사용하고 있습니다',
    '음료 마시는 중':'음료를 마시고 있습니다',
    '음식 먹는 중':'음식을 먹고 있습니다',
    '책·문서 보는 중':'책을 보고 있습니다',
    '머리 만지는 중':'머리를 만지고 있습니다',
    '얼굴 만지는 중':'얼굴을 만지고 있습니다',
    '손가락으로 가리키는 중':'손가락으로 무언가를 가리키고 있습니다',
    '날카로운 도구 소지':'날카로운 도구를 들고 있습니다',
    '음료 들고 있음':'음료를 들고 있습니다',
    '운동 도구 사용':'운동 도구를 사용하고 있습니다',
  };
  const poseMap={
    '서 있음':'서 있습니다','걷기':'걷고 있습니다','달리기':'달리고 있습니다',
    '앉아 있음':'앉아 있습니다','스쿼트/쪼그리기':'쪼그려 앉아 있습니다',
    '팔 들기':'팔을 들고 있습니다','앞으로 숙임':'몸을 앞으로 숙이고 있습니다',
    '낙상 감지!':'넘어졌습니다','넘어질 위험':'비틀거리고 있습니다',
  };
  let actionStr=(specialActs.length>0&&spMap[specialActs[0].text])
    ? spMap[specialActs[0].text]
    : (poseMap[actionResult.action]||actionResult.action+'합니다');

  // 사물 목록 — MobileNet 우선(임계값 낮춤), 없으면 COCO-SSD, 없으면 전체화면
  const mnNames=[];
  // 왼손: 상위 결과 중 번역 가능한 첫 번째
  for(const p of leftMobileNetResult){
    if(p.probability<0.12) break;
    const t=translateMN(p.className);
    if(t&&!mnNames.includes(t)){mnNames.push(t);break;}
  }
  // 오른손: 상위 결과 중 번역 가능한 첫 번째 (왼손과 다른 것)
  for(const p of rightMobileNetResult){
    if(p.probability<0.12) break;
    const t=translateMN(p.className);
    if(t&&!mnNames.includes(t)){mnNames.push(t);break;}
  }
  // 전체화면 보조 (손 결과 없을 때)
  if(mnNames.length===0&&fullFrameResults.length>0){
    for(const p of fullFrameResults){
      if(p.probability<0.15) break;
      const t=translateMN(p.className);
      if(t&&!mnNames.includes(t)){mnNames.push(t);if(mnNames.length>=2)break;}
    }
  }
  const cocoNames=[...new Set([...lHeld.map(o=>translateClass(o.class)),...rHeld.map(o=>translateClass(o.class))])];
  const heldNames=mnNames.length>0?mnNames:cocoNames;

  let objStr='';
  if(heldNames.length===1) objStr=`${heldNames[0]}을(를) 손에 들고 `;
  else if(heldNames.length>1) objStr=`${heldNames.join('·')}을(를) 들고 `;

  const sentence=`${subject} ${objStr}${actionStr}`;
  const subParts=[];
  if(ageInfo) subParts.push(`연령대: ${ageInfo}`);
  if(specialActs.length>1) subParts.push(specialActs.slice(1).map(s=>s.icon+' '+s.text).join(' · '));
  return{sentence, sub:subParts.join(' | ')};
}

function escapeHtml(value){
  return String(value??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function easyObjectSummary(lHeld, rHeld){
  const rows=[];
  const seen=new Set();
  function add(obj, source){
    if(!obj||obj.class==='person') return;
    const key=`${obj.class}-${source}`;
    if(seen.has(key)) return;
    seen.add(key);
    rows.push({
      className:obj.class,
      name:translateClass(obj.class),
      icon:ICONS[obj.class]||'📦',
      score:obj.score??obj.confidence??0,
      source,
      safety:safetyTag(obj.class)
    });
  }
  lHeld.forEach(o=>add(o,'왼손'));
  rHeld.forEach(o=>add(o,'오른손'));
  [...latestObjects]
    .filter(o=>o.class!=='person')
    .sort((a,b)=>(b.score??0)-(a.score??0))
    .slice(0,6)
    .forEach(o=>add(o,'화면'));
  return rows.slice(0,5);
}

function setEasyCardState(el, state){
  if(!el) return;
  el.classList.remove('good','warn','danger');
  if(state) el.classList.add(state);
}

function updateEasyScene(narr, genderInfo, ageInfo, ar, specialActs, lHeld, rHeld){
  const main=document.getElementById('easyMainText');
  if(!main) return;

  const pc=Math.max(detectedPersonCount,sm?1:0);
  const objects=easyObjectSummary(lHeld,rHeld);
  updateServiceLiveCards(buildServiceInsight(ar, sm, latestObjects));
  const hasDangerObject=objects.some(o=>o.safety.cls==='danger');
  const hasCautionObject=objects.some(o=>o.safety.cls==='caution');
  const hasDangerAction=specialActs.some(s=>s.danger)||ar.danger;
  const isWarn=ar.warn||hasCautionObject||specialActs.length>0;
  const safetyState=hasDangerAction||hasDangerObject?'danger':isWarn?'warn':'good';

  main.textContent=narr.sentence;
  document.getElementById('easySubText').textContent=narr.sub||'감지 결과를 쉬운 말로 요약했습니다. 아래에서 객체와 행동을 바로 확인하세요.';

  document.getElementById('easyPeople').textContent=pc>0?`${pc}명`:'없음';
  setEasyCardState(document.getElementById('easyPeopleCard'),pc>0?'good':'warn');

  const safetyText=safetyState==='danger'?'위험':safetyState==='warn'?'주의':'안전';
  document.getElementById('easySafety').textContent=safetyText;
  setEasyCardState(document.getElementById('easySafetyCard'),safetyState);

  document.getElementById('easyObjects').innerHTML=objects.length?objects.map(o=>`
    <div class="easy-object">
      <div class="ico">${o.icon}</div>
      <div>
        <div class="name">${escapeHtml(o.name)}</div>
        <div class="meta">${escapeHtml(o.source)}에서 감지 · ${escapeHtml(o.safety.label)}</div>
      </div>
      <div class="conf">${Math.round((o.score||0)*100)}%</div>
    </div>
  `).join(''):'<div class="easy-empty">현재 뚜렷하게 인식한 객체가 없습니다.<br>물체를 카메라 중앙에 더 가깝게 보여주세요.</div>';

  const actionItems=[];
  const actionConfidence=ar.confidence?Math.round(ar.confidence*100):null;
  actionItems.push(`<div class="easy-next-item">${escapeHtml(ar.icon||'🧍')} 현재 행동: <strong>${escapeHtml(ar.action)}</strong>${actionConfidence?` · 안정도 ${actionConfidence}%`:''}</div>`);
  if(genderInfo||ageInfo){
    actionItems.push(`<div class="easy-next-item">인물 추정: ${escapeHtml(genderInfo?genderInfo.gender:'성별 미확인')}${genderInfo?` (${genderInfo.conf}%)`:''}${ageInfo?` · ${escapeHtml(ageInfo)}`:''}</div>`);
  }
  if(specialActs.length){
    actionItems.push(...specialActs.slice(0,3).map(s=>`<div class="easy-next-item ${s.danger?'danger':'warn'}">${escapeHtml(s.icon)} ${escapeHtml(s.text)}</div>`));
  }
  document.getElementById('easyActions').innerHTML=actionItems.join('');

  const next=[];
  if(pc===0) next.push(['warn','사람이 잘 보이도록 카메라 각도와 거리를 조정하세요.']);
  if(objects.length===0) next.push(['warn','인식할 물체는 화면 중앙에 두고 손이나 배경에 너무 가리지 않게 하세요.']);
  if(hasDangerAction||hasDangerObject) next.push(['danger','위험 후보가 있습니다. 실제 상황이 맞는지 즉시 확인하고 검수 화면에 라벨을 남기세요.']);
  if(safetyState==='good'&&pc>0) next.push(['good','큰 위험 신호는 없습니다. 정확도 개선을 위해 맞음/틀림 검수 데이터를 계속 쌓으세요.']);
  if(objects.some(o=>(o.score||0)<0.45)) next.push(['warn','일부 객체 신뢰도가 낮습니다. 조명, 초점, 거리 조정 후 다시 확인하세요.']);
  document.getElementById('easyNextSteps').innerHTML=next.map(([cls,text])=>`<div class="easy-next-item ${cls==='danger'?'danger':cls==='warn'?'warn':''}">${escapeHtml(text)}</div>`).join('');
}

// ─── 장면 UI 업데이트 ───
function updateSceneUI(genderInfo, ageInfo, ar, specialActs, lHeld, rHeld){
  if(!document.getElementById('narrativeText')) return;   // 장면 오버레이 없는 테마 페이지
  const narr=generateNarrative(genderInfo,ageInfo,ar,specialActs,lHeld,rHeld);
  document.getElementById('narrativeText').textContent=narr.sentence;
  document.getElementById('narrativeSub').textContent=narr.sub;

  const overlay=document.getElementById('narrativeOverlay');
  overlay.style.display=(document.getElementById('togNarrative')?.checked??true)?'block':'none';

  updateEasyScene(narr,genderInfo,ageInfo,ar,specialActs,lHeld,rHeld);

  // 패널 메인 카드
  document.getElementById('sceneNarrativeMain').innerHTML=`
    <div class="narr-sentence">
      <div class="ns-text">${narr.sentence}</div>
      ${narr.sub?`<div class="ns-sub">${narr.sub}</div>`:''}
    </div>`;

  // 인물 정보 행
  const pc=Math.max(detectedPersonCount,sm?1:0);
  document.getElementById('personCount').textContent=pc>0?`${pc}명 감지`:'감지 중...';
  if(genderInfo){document.getElementById('narrativeGender').textContent=genderInfo.gender+` (추정 ${genderInfo.conf}%)`;}
  if(ageInfo){document.getElementById('narrativeAge').textContent=ageInfo;}
  document.getElementById('narrativeAction').textContent=`${ar.icon||''} ${ar.action}`;

  // 특수 행동
  if(specialActs.length===0){
    document.getElementById('specialActionsDisplay').innerHTML='<div class="no-data"><span class="icon">🎯</span>일반 행동 중</div>';
  }else{
    document.getElementById('specialActionsDisplay').innerHTML=specialActs.map(s=>`<span class="special-action-tag${s.danger?' style="background:rgba(239,68,68,.2);border-color:rgba(239,68,68,.4);color:#fca5a5;"':''}">${s.icon} ${s.text}</span>`).join('');
  }
}

/* ════════════════════════════════════════════════════════════════
   AX 업그레이드 모듈 — 라이선스 안전(자체구현), 추적 id 기반 분석.
   공통: 추적 위치/속도 이력 · 얼굴 비식별화
   Safety: 구역 체류시간/인원 · 안전거리 · 동선 히트맵
   Fitness: AI Gym 다종목 반복 카운터
   Office: 자세 각도(어깨/거북목/허리) + 점수 추세
   모두 try/catch로 격리되어 실패해도 기존 탐지/루프에 영향 없음.
   ════════════════════════════════════════════════════════════════ */
const axState = {
  tracks:{},                       // id → {cx,cy,lastT,speed,zoneInT,dwell}
  heat:null, heatCols:64, heatRows:36, heatMax:1,
  gym:{ex:null, exName:'스쿼트', count:0, phase:'up', minA:999, angle:null, cue:''},
  office:null, zoneSummary:{inside:0,maxDwell:0}, nearHazard:null,
};
// 사람 목록 → {id, box[x,y,w,h]px, cx,cy(정규화 중심)}  (좌표변환 내장: 위험구역과 동일)
function axPersons(frame){
  const W=frame.W,H=frame.H;
  return (frame.latestObjects||[]).filter(o=>o.class==='person').map(o=>{
    const b=displayBboxArray(scaleBbox(o.bbox,frame.scX,frame.scY),W,H);
    return {id:(o.id!=null?o.id:-1), box:b, cx:(b[0]+b[2]/2)/W, cy:(b[1]+b[3]/2)/H,
            feet:[b[0]+b[2]/2, b[1]+b[3]]};   // 발(하단중앙) px = 지면 접점
  });
}
// 속도 추적 대상: 사람 + 이동 수단
const AX_SPEED_CLASSES=new Set(['person','car','truck','bus','motorcycle','bicycle','train']);
const AX_CLASS_KO={person:'사람',car:'차량',truck:'트럭',bus:'버스',motorcycle:'오토바이',bicycle:'자전거',train:'기차'};
function axTargets(frame){
  const W=frame.W,H=frame.H;
  return (frame.latestObjects||[]).filter(o=>AX_SPEED_CLASSES.has(o.class)).map(o=>{
    const b=displayBboxArray(scaleBbox(o.bbox,frame.scX,frame.scY),W,H);
    return {id:(o.id!=null?o.id:-1), cls:o.class, box:b, cx:(b[0]+b[2]/2)/W, cy:(b[1]+b[3]/2)/H,
            feet:[b[0]+b[2]/2, b[1]+b[3]]};
  });
}
function axUpdateTracks(persons,tnow){
  const seen=new Set();
  for(const p of persons){
    if(p.id<0) continue; seen.add(p.id);
    let t=axState.tracks[p.id];
    if(!t){ t={cx:p.cx,cy:p.cy,lastT:tnow,speed:0,zoneInT:0,dwell:0,wx:null,wy:null,kmh:0}; axState.tracks[p.id]=t; }
    t.cls=p.cls||t.cls||'person'; t.box=p.box;
    const dt=Math.max(0.001,(tnow-t.lastT)/1000);
    t.speed=t.speed*0.6+Math.hypot((p.cx-t.cx)/dt,(p.cy-t.cy)/dt)*0.4;   // 상대 속도(정규화/초)
    if(axCal.H && p.feet){                                              // 보정됨 → 실제 m/s→km/h
      const w=applyH(axCal.H,p.feet[0],p.feet[1]);
      if(t.wx!=null){ const kmh=(Math.hypot(w[0]-t.wx,w[1]-t.wy)/dt)*3.6; if(kmh<150) t.kmh=t.kmh*0.6+kmh*0.4; }
      t.wx=w[0]; t.wy=w[1];
    }
    t.cx=p.cx; t.cy=p.cy; t.lastT=tnow;
  }
  for(const id in axState.tracks){ if(!seen.has(+id)&&tnow-axState.tracks[id].lastT>3000) delete axState.tracks[id]; }
}
// Safety: 구역 체류시간/인원 (추적 id별 누적)
function axZoneDwell(persons,tnow){
  const polys=dangerZonePolys(); let inside=0,maxDwell=0;
  if(polys.length) for(const p of persons){
    const t=axState.tracks[p.id]; if(!t) continue;
    if(polys.some(pts=>pointInPoly(p.cx,p.cy,pts))){ if(!t.zoneInT)t.zoneInT=tnow; t.dwell=(tnow-t.zoneInT)/1000; inside++; if(t.dwell>maxDwell)maxDwell=t.dwell; }
    else { t.zoneInT=0; t.dwell=0; }
  }
  axState.zoneSummary={inside,maxDwell};
}
// Safety: 안전거리 (사람 중심 ↔ 위험물 중심 최단, 정규화) + 근접 시 선 표시
const AX_HAZARD=new Set(['knife','scissors','car','truck','motorcycle','bus','train','forklift']);
function axSafeDistance(persons,frame){
  const W=frame.W,H=frame.H; let best=null;
  for(const o of (frame.latestObjects||[])){
    if(!AX_HAZARD.has(o.class)) continue;
    const b=displayBboxArray(scaleBbox(o.bbox,frame.scX,frame.scY),W,H);
    const hcx=(b[0]+b[2]/2)/W, hcy=(b[1]+b[3]/2)/H, hfeet=[b[0]+b[2]/2, b[1]+b[3]];
    for(const p of persons){ const dn=Math.hypot(p.cx-hcx,p.cy-hcy);
      if(best===null||dn<best.d) best={d:dn,cls:o.class,pfeet:p.feet,hfeet}; }
  }
  if(best && axCal.H){ const a=applyH(axCal.H,best.pfeet[0],best.pfeet[1]),c=applyH(axCal.H,best.hfeet[0],best.hfeet[1]); best.meters=Math.hypot(a[0]-c[0],a[1]-c[1]); }
  axState.nearHazard=best;
  const near = best && (best.meters!=null ? best.meters<3 : best.d<0.18);
  if(near){
    const danger = best.meters!=null ? best.meters<1.5 : best.d<0.12;
    ctx.save(); ctx.strokeStyle=danger?'#ef4444':'#f59e0b'; ctx.lineWidth=2; ctx.setLineDash([5,4]);
    ctx.beginPath(); ctx.moveTo(best.pfeet[0],best.pfeet[1]); ctx.lineTo(best.hfeet[0],best.hfeet[1]); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle=ctx.strokeStyle; ctx.font='bold 12px Segoe UI';
    ctx.fillText('⚠ '+(best.meters!=null?best.meters.toFixed(1)+'m':'근접'), (best.pfeet[0]+best.hfeet[0])/2,(best.pfeet[1]+best.hfeet[1])/2-4); ctx.restore();
  }
}
// Safety: 동선 히트맵 누적 + 그리기(토글)
function axHeatAccum(persons){
  if(!axState.heat) axState.heat=new Float32Array(axState.heatCols*axState.heatRows);
  for(const p of persons){ const c=Math.min(axState.heatCols-1,Math.max(0,Math.floor(p.cx*axState.heatCols)));
    const r=Math.min(axState.heatRows-1,Math.max(0,Math.floor(p.cy*axState.heatRows)));
    const i=r*axState.heatCols+c; axState.heat[i]+=1; if(axState.heat[i]>axState.heatMax)axState.heatMax=axState.heat[i]; }
}
function axHeatDraw(W,H){
  const tog=document.getElementById('togHeatmap'); if(!tog||!tog.checked||!axState.heat) return;
  const cw=W/axState.heatCols, ch=H/axState.heatRows; ctx.save();
  for(let r=0;r<axState.heatRows;r++)for(let c=0;c<axState.heatCols;c++){
    const v=axState.heat[r*axState.heatCols+c]/axState.heatMax; if(v<0.05) continue;
    ctx.fillStyle=`hsla(${(1-v)*220},90%,50%,${Math.min(0.5,v*0.6)})`; ctx.fillRect(c*cw,r*ch,cw+1,ch+1);
  }
  ctx.restore();
}
// 공통: 얼굴 비식별화(모자이크) — 토글. 캔버스가 영상 위에 있으므로 불투명 덮기로 가림.
function axBlurFaces(frame){
  const tog=document.getElementById('togBlur'); if(!tog||!tog.checked) return;
  const f=frame.face; if(!f||!f.length) return;
  const W=frame.W,H=frame.H; let minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9;
  for(const p of f){ const X=viewX(p,W,H),Y=viewY(p,W,H); if(X<minx)minx=X; if(Y<miny)miny=Y; if(X>maxx)maxx=X; if(Y>maxy)maxy=Y; }
  let x=minx,y=miny,w=maxx-minx,h=maxy-miny; x-=w*0.12; y-=h*0.18; w*=1.24; h*=1.34;
  if(w<6||h<6) return;
  ctx.save(); const cols=8,rows=8,cw=w/cols,ch=h/rows;
  for(let r=0;r<rows;r++)for(let c=0;c<cols;c++){ const g=90+((c*37+r*53)%70); ctx.fillStyle=`rgb(${g},${g},${g+6})`; ctx.fillRect(x+c*cw,y+r*ch,cw+0.6,ch+0.6); }
  ctx.strokeStyle='rgba(0,0,0,.4)'; ctx.lineWidth=1; ctx.strokeRect(x,y,w,h);
  ctx.fillStyle='#fff'; ctx.font='bold 11px Segoe UI'; ctx.fillText('🙈 비식별', x+3, y-4); ctx.restore();
}
// Fitness: AI Gym 다종목 반복 카운터 (관절각 → 상태기계)
const AX_EX={
  squat:{name:'스쿼트', a:lm=>avgVal(calcAngle(lm[23],lm[25],lm[27]),calcAngle(lm[24],lm[26],lm[28])), down:100,up:160},
  pushup:{name:'푸쉬업', a:lm=>avgVal(calcAngle(lm[11],lm[13],lm[15]),calcAngle(lm[12],lm[14],lm[16])), down:95,up:158},
  situp:{name:'싯업',   a:lm=>avgVal(calcAngle(lm[11],lm[23],lm[25]),calcAngle(lm[12],lm[24],lm[26])), down:70,up:120},
  curl:{name:'암컬',    a:lm=>avgVal(calcAngle(lm[11],lm[13],lm[15]),calcAngle(lm[12],lm[14],lm[16])), down:55,up:150},
};
function axGym(frame){
  const sel=document.getElementById('axExercise'); const ex=(sel&&sel.value)||'squat';
  const g=axState.gym, def=AX_EX[ex];
  if(g.ex!==ex){ g.ex=ex; g.exName=def.name; g.count=0; g.phase='up'; g.minA=999; }
  const lm=frame.rawPose; if(!lm){ g.angle=null; g.cue='전신이 보이게'; return; }
  const a=def.a(lm); if(a==null){ g.angle=null; g.cue='관절 인식 중'; return; }
  if(g.phase==='up' && a<=def.down){ g.phase='down'; g.minA=a; }
  else if(g.phase==='down'){ if(a<g.minA)g.minA=a; if(a>=def.up){ g.phase='up'; g.count++; } }
  g.angle=Math.round(a); g.cue=g.phase==='down'?'올라오세요':'내려가세요';
}
// Office: 자세 각도(어깨 기울기·거북목·허리) + 점수 추세
function axOffice(frame){
  const lm=frame.rawPose; if(!lm) return null;
  const nose=lm[0],lS=lm[11],rS=lm[12];
  const shoulderTilt=(lS&&rS)?Math.round(Math.abs(Math.atan2(rS.y-lS.y,rS.x-lS.x)*180/Math.PI)):null;
  const neck=(nose&&lS&&rS)?Math.round(Math.abs(nose.x-((lS.x+rS.x)/2))/((Math.abs(lS.x-rS.x))||0.3)*100):null;
  const lean=Math.round(Math.abs(180-getTrunkTilt(lm)));   // 직립≈180° → 실제 전방 굽힘각으로 변환
  let score=100; if(shoulderTilt!=null&&shoulderTilt>9)score-=20; if(neck!=null&&neck>34)score-=25; if(lean>18)score-=20;
  axState.postHist=(axState.postHist||[]); axState.postHist.push(score); if(axState.postHist.length>80)axState.postHist.shift();
  return {shoulderTilt,neck,lean,score:Math.max(0,score)};
}
// ── 거리 보정(호모그래피): 바닥 직사각형 4점 + 실측(가로·세로 m) → 이미지↔지면 변환 ──
const axCal = { H:null, dims:null, info:'', pts:[], mode:false };
try{ const s=localStorage.getItem('axCalH'); if(s){ const j=JSON.parse(s); if(j&&j.H){ axCal.H=j.H; axCal.dims=j.dims; axCal.info=j.info||'보정됨'; } } }catch(e){}
function applyH(H,x,y){ const d=(H[6]*x+H[7]*y+H[8])||1e-9; return [(H[0]*x+H[1]*y+H[2])/d,(H[3]*x+H[4]*y+H[5])/d]; }
function gaussSolve(A,b,n){            // Ax=b (n원 연립), 부분피벗 가우스 소거
  for(let i=0;i<n;i++){
    let mx=i; for(let r=i+1;r<n;r++) if(Math.abs(A[r][i])>Math.abs(A[mx][i])) mx=r;
    if(Math.abs(A[mx][i])<1e-12) return null;
    [A[i],A[mx]]=[A[mx],A[i]]; [b[i],b[mx]]=[b[mx],b[i]];
    for(let r=0;r<n;r++){ if(r===i) continue; const f=A[r][i]/A[i][i];
      for(let c=i;c<n;c++) A[r][c]-=f*A[i][c]; b[r]-=f*b[i]; }
  }
  const x=new Array(n); for(let i=0;i<n;i++) x[i]=b[i]/A[i][i]; return x;
}
function solveHomography(src,dst){     // src(이미지 px)[4] → dst(지면 m)[4] → 3x3(9원소)
  const A=[],b=[];
  for(let i=0;i<4;i++){ const [x,y]=src[i],[X,Y]=dst[i];
    A.push([x,y,1,0,0,0,-x*X,-y*X]); b.push(X);
    A.push([0,0,0,x,y,1,-x*Y,-y*Y]); b.push(Y); }
  const h=gaussSolve(A,b,8); if(!h) return null;
  return [h[0],h[1],h[2],h[3],h[4],h[5],h[6],h[7],1];
}
function axStartCalibration(){
  axCal.mode=!axCal.mode; axCal.pts=[];
  const hint=document.getElementById('calHint'), btn=document.getElementById('calBtn');
  if(btn) btn.classList.toggle('active',axCal.mode);
  if(hint){ hint.style.display=axCal.mode?'block':'none'; hint.textContent='바닥 직사각형 4모서리를 좌상→우상→우하→좌하 순서로 클릭'; }
}
function initCalUI(){
  const cv=document.getElementById('outputCanvas'), hint=document.getElementById('calHint'), btn=document.getElementById('calBtn');
  if(!cv) return;
  cv.addEventListener('click',e=>{
    if(!axCal.mode) return;
    const r=cv.getBoundingClientRect();
    const x=(e.clientX-r.left)/r.width*cv.width, y=(e.clientY-r.top)/r.height*cv.height;   // 캔버스 px(=bbox px 공간)
    axCal.pts.push([x,y]); if(hint) hint.textContent='모서리 '+axCal.pts.length+'/4';
    if(axCal.pts.length===4){
      const wm=parseFloat(prompt('가로(폭) 실제 길이를 미터(m)로 입력','3'));
      const dm=parseFloat(prompt('세로(깊이) 실제 길이를 미터(m)로 입력','3'));
      if(wm>0&&dm>0){
        const H=solveHomography(axCal.pts,[[0,0],[wm,0],[wm,dm],[0,dm]]);
        if(H){ axCal.H=H; axCal.dims={wm,dm}; axCal.info=wm+'m×'+dm+'m';
          try{ localStorage.setItem('axCalH',JSON.stringify({H,dims:axCal.dims,info:axCal.info})); }catch(e){}
          if(hint) hint.textContent='✅ 보정 완료: '+axCal.info;
        } else if(hint) hint.textContent='❌ 보정 실패(점이 일직선?) 다시 시도';
      }
      axCal.mode=false; axCal.pts=[]; if(btn)btn.classList.remove('active');
      if(hint) setTimeout(()=>{hint.style.display='none';},2600);
    }
  });
}
function axDrawCal(W,H){
  if(!(axCal.mode && axCal.pts.length)) return;
  ctx.save(); ctx.strokeStyle='#a78bfa'; ctx.lineWidth=2;
  ctx.beginPath(); axCal.pts.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1])); if(axCal.pts.length===4)ctx.closePath(); ctx.stroke();
  axCal.pts.forEach((p,i)=>{ ctx.fillStyle='#a78bfa'; ctx.beginPath(); ctx.arc(p[0],p[1],5,0,7); ctx.fill();
    ctx.fillStyle='#fff'; ctx.font='bold 11px Segoe UI'; ctx.fillText(i+1,p[0]+7,p[1]-5); });
  ctx.restore();
}

// ── 열화상 온도 감지 (업로드한 열화상 이미지/영상) ──
// 픽셀 밝기(luma) → 온도(Tmin~Tmax 선형). 핫스팟·클릭지점 온도 + 임계초과 경보(텔레그램).
let thermOn=false, thermClick=null, _thermLastAlert=0;
const _thermCv=document.createElement('canvas');
function _thermSrc(){
  // 업로드 이미지 우선. 라이브 웹캠(videoEl.srcObject=RGB)은 온도 측정 불가라 제외, 업로드 영상만 허용.
  if(imageEl.style.display==='block'&&imageEl.complete&&imageEl.naturalWidth>0) return {el:imageEl,w:imageEl.naturalWidth,h:imageEl.naturalHeight,img:true};
  if(videoEl.style.display!=='none'&&!videoEl.srcObject&&(videoEl.videoWidth||0)>0) return {el:videoEl,w:videoEl.videoWidth,h:videoEl.videoHeight,img:false};
  return null;
}
function toggleTherm(){
  thermOn=!thermOn; thermClick=null;
  const b=document.getElementById('thermBtn'), p=document.getElementById('thermPanel');
  if(b)b.classList.toggle('active',thermOn);
  if(p)p.classList.toggle('show',thermOn);
  thermRefresh();
}
function thermRefresh(){ const s=_thermSrc(); if(thermOn&&s&&s.img&&typeof holistic!=='undefined'&&holistic){ try{ holistic.send({image:imageEl}); }catch(e){} } }
function drawThermal(W,H){
  const s=_thermSrc();
  const tmin=parseFloat(document.getElementById('thermMin').value), tmax=parseFloat(document.getElementById('thermMax').value);
  ctx.save();
  if(!s || isNaN(tmin)||isNaN(tmax)||tmax<=tmin){
    ctx.fillStyle='rgba(7,11,18,.86)'; ctx.fillRect(12,12,372,54);
    ctx.fillStyle='#fda4af'; ctx.font='bold 13px Segoe UI';
    ctx.fillText('일반 카메라(RGB)로는 온도 측정 불가', 20, 31);
    ctx.fillStyle='#cbd5e1'; ctx.font='12px Segoe UI';
    ctx.fillText('열화상 이미지/영상을 업로드하거나 열화상 카메라를 연결하세요', 20, 50);
    ctx.restore(); return;
  }
  const sw=480, sh=Math.max(1,Math.round(480*s.h/s.w));
  _thermCv.width=sw; _thermCv.height=sh;
  const c=_thermCv.getContext('2d',{willReadFrequently:true});
  let data; try{ c.drawImage(s.el,0,0,sw,sh); data=c.getImageData(0,0,sw,sh).data; }catch(e){ ctx.restore(); return; }
  const toT=l=>tmin+(l/255)*(tmax-tmin);
  let maxL=-1,mx=0,my=0,sum=0;
  for(let y=0;y<sh;y++)for(let x=0;x<sw;x++){ const i=(y*sw+x)*4; const l=0.299*data[i]+0.587*data[i+1]+0.114*data[i+2]; sum+=l; if(l>maxL){maxL=l;mx=x;my=y;} }
  const maxT=toT(maxL), avgT=toT(sum/(sw*sh));
  const r=mediaRect(W,H); const place=(nx,ny)=>[r.x+nx*r.w, r.y+ny*r.h];
  const [hx,hy]=place((mx+0.5)/sw,(my+0.5)/sh);
  ctx.strokeStyle='#ef4444'; ctx.lineWidth=2;
  ctx.beginPath(); ctx.arc(hx,hy,9,0,7); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(hx-14,hy); ctx.lineTo(hx+14,hy); ctx.moveTo(hx,hy-14); ctx.lineTo(hx,hy+14); ctx.stroke();
  ctx.fillStyle='#ef4444'; ctx.font='bold 13px Segoe UI'; ctx.fillText('최고 '+maxT.toFixed(1)+'°C', hx+12, hy-10);
  if(thermClick){
    const px=Math.min(sw-1,Math.max(0,Math.round(thermClick.x*sw))), py=Math.min(sh-1,Math.max(0,Math.round(thermClick.y*sh)));
    const i=(py*sw+px)*4; const t=toT(0.299*data[i]+0.587*data[i+1]+0.114*data[i+2]);
    const [cx,cy]=place(thermClick.x,thermClick.y);
    ctx.strokeStyle='#22d3ee'; ctx.lineWidth=2; ctx.beginPath(); ctx.arc(cx,cy,7,0,7); ctx.stroke();
    ctx.fillStyle='#22d3ee'; ctx.fillText(t.toFixed(1)+'°C', cx+10, cy-8);
  }
  ctx.fillStyle='rgba(7,11,18,.82)'; ctx.fillRect(12,12,150,46);
  ctx.fillStyle='#e8eef5'; ctx.font='bold 13px Segoe UI';
  ctx.fillText('평균 '+avgT.toFixed(1)+'°C', 22, 31); ctx.fillText('최고 '+maxT.toFixed(1)+'°C', 22, 50);
  ctx.restore();
  const alertT=parseFloat(document.getElementById('thermAlert').value);
  if(!isNaN(alertT) && maxT>=alertT){
    ctx.save(); ctx.fillStyle='rgba(220,38,38,.92)'; ctx.fillRect(W/2-150,12,300,30);
    ctx.fillStyle='#fff'; ctx.font='bold 14px Segoe UI'; ctx.textAlign='center'; ctx.fillText('과열 경보 '+maxT.toFixed(1)+'°C', W/2, 33); ctx.restore();
    const now=Date.now();
    if(now-_thermLastAlert>30000){ _thermLastAlert=now;
      fetch(API_BASE+'/sensor/temperature',{method:'POST',headers:{'content-type':'application/json'},
        body:JSON.stringify({sensor:'thermal', celsius:+maxT.toFixed(1), site:'온도경보', threshold_c:alertT})}).catch(()=>{});
    }
  }
}
function initThermUI(){
  const cv=document.getElementById('outputCanvas'); if(!cv) return;
  cv.addEventListener('click',e=>{
    if(!thermOn) return;
    const W=cv.width,H=cv.height, r=mediaRect(W,H), rect=cv.getBoundingClientRect();
    const x=(e.clientX-rect.left)/rect.width*W, y=(e.clientY-rect.top)/rect.height*H;
    const nx=(x-r.x)/r.w, ny=(y-r.y)/r.h;
    if(nx>=0&&nx<=1&&ny>=0&&ny<=1){ thermClick={x:nx,y:ny}; thermRefresh(); }
  });
  ['thermMin','thermMax','thermAlert'].forEach(id=>{ const el=document.getElementById(id); if(el) el.addEventListener('change',thermRefresh); });
}

// 디스패처: 매 프레임 호출(renderCoreFrameOverlays에서 try/catch로)
// 과속 경보: 합성 스냅샷 + 속도 → 백엔드(텔레그램). 15초 쿨다운.
let _ovrLastAlert=0;
function captureOverspeed(frame, label, kmh){
  const now=Date.now(); if(now-_ovrLastAlert<15000) return; _ovrLastAlert=now;
  const W=frame.W,H=frame.H; const oc=document.createElement('canvas'); oc.width=W; oc.height=H; const octx=oc.getContext('2d');
  octx.fillStyle='#000'; octx.fillRect(0,0,W,H);
  try{ const r=mediaRect(W,H);
    if(shouldFlipDisplay()){ octx.save(); octx.translate(r.x+r.w,r.y); octx.scale(-1,1); octx.drawImage(videoEl,0,0,r.w,r.h); octx.restore(); }
    else octx.drawImage(videoEl,r.x,r.y,r.w,r.h);
  }catch(e){}
  try{ octx.drawImage(canvas,0,0); }catch(e){}
  let img=''; try{ img=oc.toDataURL('image/jpeg',0.7); }catch(e){}
  fetch(API_BASE+'/alert/overspeed',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({image_base64:img, kmh:Math.round(kmh), label:label, site:'과속경보'})}).catch(()=>{});
}
// 이동 객체(사람·차량) 실시간 속도 라벨. 거리 보정 시 km/h, 미보정 시 '이동중'.
function axDrawSpeed(frame){
  const tog=document.getElementById('togSpeed'); if(!tog||!tog.checked) return;
  const W=frame.W,H=frame.H, now=performance.now(), cal=!!axCal.H;
  const thr=parseFloat((document.getElementById('speedAlert')||{}).value); let over=null;
  ctx.save(); ctx.font='bold 13px Segoe UI';
  for(const id in axState.tracks){
    const t=axState.tracks[id];
    if(!t.box || now-t.lastT>250) continue;                 // 이번 프레임에 보인 것만
    const moving = cal ? t.kmh>1.5 : t.speed>0.05;
    if(!moving) continue;
    const overThr = cal && !isNaN(thr) && t.kmh>=thr;       // 과속 임계 초과
    if(overThr && (!over || t.kmh>over.kmh)) over={kmh:t.kmh, cls:t.cls};
    const fast = overThr || (cal ? t.kmh>=20 : t.speed>0.6);
    const txt=(AX_CLASS_KO[t.cls]||'')+' '+(cal ? t.kmh.toFixed(0)+' km/h' : '이동중')+(overThr?' ⚠':'');
    const x=t.box[0], y=Math.max(20,t.box[1]);
    const tw=ctx.measureText(txt).width+12;
    ctx.fillStyle='rgba(7,11,18,.82)'; ctx.fillRect(x, y-20, tw, 18);
    ctx.fillStyle=fast?'#f87171':'#34d399'; ctx.fillText(txt, x+6, y-6);
  }
  if(!cal){ ctx.fillStyle='rgba(7,11,18,.78)'; ctx.fillRect(12,H-28,322,20);
    ctx.fillStyle='#cbd5e1'; ctx.font='12px Segoe UI'; ctx.fillText('실제 km/h·과속 경보는 [거리 보정] 후 동작합니다', 20, H-14); }
  ctx.restore();
  if(over){ try{ captureOverspeed(frame, AX_CLASS_KO[over.cls]||'객체', over.kmh); }catch(e){} }
}
function axRunUpgrades(frame){
  const tnow=performance.now();
  const persons=axPersons(frame);
  axUpdateTracks(axTargets(frame),tnow);   // 사람+차량 추적/속도
  if(activeServiceMode==='safety'){
    axZoneDwell(persons,tnow); axSafeDistance(persons,frame);
    axHeatAccum(persons); axHeatDraw(frame.W,frame.H);
  } else if(activeServiceMode==='fitness'){ axGym(frame); }
  else { axState.office=axOffice(frame); }
  axDrawSpeed(frame);   // 이동 객체 속도 라벨(토글)
  axBlurFaces(frame);   // 공통(프라이버시) — 항상 마지막에 덮어 가림
}

// 테마 정규화: 해시/파라미터 값 → 내부 모드명
function _normServiceMode(v){
  v=(v||'').toLowerCase();
  if(['fitness','sports'].includes(v)) return 'fitness';
  if(['safety','industrial'].includes(v)) return 'safety';
  if(['office','desk'].includes(v)) return 'office';
  return null;
}
window.addEventListener('load',()=>{
  // 런처 ?lock=테마 → 해당 테마로 고정 + 제품 전환 UI 숨김(단일 테마 전용 화면)
  const lock=_normServiceMode(window.AX_LOCK_THEME || new URLSearchParams(location.search).get('lock'));
  if(lock){
    document.body.classList.add('theme-locked');
    setServiceMode(lock);
  } else {
    const mode=_normServiceMode((location.hash||'').replace('#',''));
    if(mode) setServiceMode(mode);
    else {applyErgoPromptPreset('fitness');applyThemeProfile(getActiveThemeProfile());}
  }
  initModels();
});
window.addEventListener('resize',()=>{const c=document.getElementById('videoContainer');canvas.width=c.clientWidth;canvas.height=c.clientHeight;try{_coordEvent('resize');}catch(_){}});
