#!/bin/bash
# ════════════════════════════════════════════════════════════
#  VIGENT 테마별 배포 패키지 빌더
#  한 소스(공유 코어)에서 "테마 전용" 깔끔한 패키지를 뽑는다.
#  ※ 소스 코드를 쪼개지 않음 — 유지보수는 한 곳, 배포만 테마별로 분리.
#
#  사용:  bash bin/build-package.sh <safety|office|sports> [출력경로]
#  예:    bash bin/build-package.sh safety
#         bash bin/build-package.sh office  ~/Desktop/VIGENT_office
# ════════════════════════════════════════════════════════════
set -e
THEME="${1:?사용: build-package.sh <safety|office|sports> [출력경로]}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${2:-$HOME/Desktop/VIGENT_$THEME}"

[ -f "$SRC/themes/$THEME/vision.yaml" ] || { echo "[오류] 테마 없음: $THEME"; exit 1; }
echo "════ VIGENT '$THEME' 패키지 빌드 → $OUT ════"

echo "[1/6] 복사(코어 + $THEME 테마만, 데이터·다른테마·비밀키 제외)..."
rm -rf "$OUT"; mkdir -p "$OUT/themes"
rsync -a \
  --exclude='.git' --exclude='data' --exclude='runs' --exclude='backup' \
  --exclude='destiny-matching' --exclude='실행' --exclude='colab' --exclude='docs' --exclude='tests' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
  --exclude='.env' --exclude='roboflow_key.txt' --exclude='config/site.yaml' --exclude='config/notify.yaml' \
  --exclude='themes' \
  "$SRC/" "$OUT/"
cp -R "$SRC/themes/$THEME" "$OUT/themes/$THEME"

echo "[2/6] 다른 테마 데이터로더 제거..."
for f in "$OUT"/vigent-core/*_data.py; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  [ "${base%_data.py}" = "$THEME" ] || { rm -f "$f"; echo "    제거 $base"; }
done

echo "[3/6] 이 테마가 쓰는 weights만 남기기..."
NEEDED="$(grep -ohE '[A-Za-z0-9_.-]+\.(pt|pth|task)' \
  "$SRC/themes/$THEME/vision.yaml" "$SRC/vigent-core/${THEME}_data.py" "$SRC/themes/$THEME/index.html" 2>/dev/null \
  | xargs -n1 basename 2>/dev/null | sort -u)"
for w in "$OUT"/vigent-core/weights/*; do
  [ -e "$w" ] || continue
  base="$(basename "$w")"
  printf '%s\n' "$NEEDED" | grep -qx "$base" || rm -f "$w"
done
echo "    유지: $(ls "$OUT/vigent-core/weights" 2>/dev/null | tr '\n' ' ')"

echo "[4/6] 런처 생성(이 테마로 고정)..."
cat > "$OUT/VIGENT_${THEME}_시작.command" <<EOF
#!/bin/bash
DIR="\$(cd "\$(dirname "\$0")" && pwd)"; PORT="\${VIGENT_PORT:-8010}"
PY=""; for c in python3 /opt/anaconda3/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  "\$c" -c "import uvicorn,fastapi,cv2,ultralytics" >/dev/null 2>&1 && { PY="\$c"; break; }; done
[ -z "\$PY" ] && { echo "먼저: pip install -r \"\$DIR/requirements.txt\""; read -r _; exit 1; }
lsof -ti tcp:\${PORT} 2>/dev/null | xargs kill -9 2>/dev/null
cd "\$DIR/vigent-core" || exit 1
VIGENT_THEME=$THEME "\$PY" -m uvicorn main:app --host 127.0.0.1 --port \${PORT} &
for i in \$(seq 1 40); do curl -fs -o /dev/null "http://127.0.0.1:\${PORT}/health" && break; sleep 1; done
open "http://127.0.0.1:\${PORT}/$THEME" 2>/dev/null || xdg-open "http://127.0.0.1:\${PORT}/$THEME" 2>/dev/null
wait
EOF
chmod +x "$OUT/VIGENT_${THEME}_시작.command"

echo "[5/6] requirements·데이터폴더·설명..."
cat > "$OUT/requirements.txt" <<'EOF'
fastapi
uvicorn
opencv-python
ultralytics
numpy
pyyaml
python-dotenv
EOF
mkdir -p "$OUT"/data/{recognition,evidence,risk_assessments,tbm,audit}
cat > "$OUT/실행안내.txt" <<EOF
VIGENT '$THEME' 전용 설치본
  1) pip install -r requirements.txt   (현장 PC 1회)
  2) VIGENT_${THEME}_시작.command  더블클릭 → 브라우저에서 /$THEME 관제 화면
  · 무인 헤드리스: config/site.example.yaml → site.yaml 수정 후 bin/vigent-edge.command
  · 비밀키(.env)는 포함돼 있지 않음 — 필요 시 .env.example 복사해 입력
EOF

echo "[6/6] 정리..."
find "$OUT" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
echo "✅ 완료: $OUT  (용량 $(du -sh "$OUT" | cut -f1))"
