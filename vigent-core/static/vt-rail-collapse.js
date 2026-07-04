/* vt-rail-collapse.js — /safety-local 우측 데이터 레일 아코디언(제목 클릭 토글)
   ─────────────────────────────────────────────────────────────────────
   ★ realtime_core.js·백엔드 무수정. 기존 DOM id 삭제/개명 없음(노드 이동만, id 유지).
   ★ 접기는 CSS class(.vt-collapsed/.vt-ppe-detail) = display 토글만 → 숨겨진 노드에도
     엔진이 값 계속 갱신(저하0). 요소를 제거하지 않는다.
   동작:
     · 우측 .right-panel 안 각 .card 제목 클릭 → 그 카드 접기/펼치기.
     · 기본 접힘 판별은 '카드가 특정 id 를 포함하는지'로(제목 문자열 의존 금지):
         접힘 = #statFall / #togPPE / #togBBox / #sceneLabel 를 포함한 .card.
     · PPE(.simple-result)는 .card 가 아니므로 별도: #ppeEvidence·#ppeModelBasis·#ppeGuide 를
         한 div(.vt-ppe-detail)로 감싸고 그 위에 '판단 근거·안내' 토글 추가(기본 접힘).
     · 상태를 localStorage 에 저장해 다음에도 유지. 탭 전환과 무관.
*/
(function(){
  "use strict";
  var LS = window.localStorage;
  function load(key, def){
    try{ var v = LS.getItem(key); return v===null ? def : (v==="1"); }catch(e){ return def; }
  }
  function save(key, on){ try{ LS.setItem(key, on?"1":"0"); }catch(e){} }

  function init(){
    var rail = document.querySelector(".right-panel");
    if(!rail) return;

    // 기본 '접힘' 카드를 판별하는 마커 id(이 id 를 포함한 .card 는 기본 접힘)
    var COLLAPSE_MARKERS = ["statFall", "togPPE", "togBBox", "sceneLabel"];

    // ── 1) 일반 .card 아코디언 ──
    var cards = rail.querySelectorAll(".card");
    Array.prototype.forEach.call(cards, function(card, i){
      var title = card.querySelector(".card-title");
      if(!title) return;
      var key = "vtRail.card." + i;

      var defCollapsed = COLLAPSE_MARKERS.some(function(id){
        var el = document.getElementById(id);
        return el && card.contains(el);
      });
      var collapsed = load(key, defCollapsed);
      card.classList.toggle("vt-collapsed", collapsed);

      title.addEventListener("click", function(){
        var on = card.classList.toggle("vt-collapsed");
        save(key, on);
      });
    });

    // ── 2) PPE(.simple-result) 상세 텍스트 접기 ──
    var ev = document.getElementById("ppeEvidence");
    if(ev && !document.querySelector(".vt-ppe-detail")){
      var parent = ev.parentNode;
      var wrap = document.createElement("div");
      wrap.className = "vt-ppe-detail";
      var btn = document.createElement("div");
      btn.className = "vt-ppe-toggle";
      btn.textContent = "판단 근거·안내";
      // 토글 버튼 → 상세 wrapper 순서로 #ppeEvidence 앞에 삽입
      parent.insertBefore(btn, ev);
      parent.insertBefore(wrap, ev);
      // 기존 상세 3개를 wrapper 로 이동(id 유지)
      ["ppeEvidence", "ppeModelBasis", "ppeGuide"].forEach(function(id){
        var n = document.getElementById(id);
        if(n) wrap.appendChild(n);
      });
      var pkey = "vtRail.ppeDetail";
      var popen = load(pkey, false);   // 기본 접힘
      wrap.classList.toggle("vt-open", popen);
      btn.classList.toggle("vt-open", popen);
      btn.addEventListener("click", function(){
        var on = wrap.classList.toggle("vt-open");
        btn.classList.toggle("vt-open", on);
        save(pkey, on);
      });
    }
  }

  if(document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", init);
  }else{
    init();
  }
})();
