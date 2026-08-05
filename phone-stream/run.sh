#!/bin/bash
# 로컬 원커맨드 실행: venv/의존성/인증서를 알아서 준비하고 서버를 띄운다.
# 아이폰은 터미널에 출력되는 QR 코드를 카메라로 찍으면 바로 접속된다.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "venv 생성 중..."
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
if [ -z "$LAN_IP" ]; then
  echo "LAN IP를 찾지 못했습니다. Wi-Fi 연결을 확인하세요." >&2
  exit 1
fi

# 인증서가 없거나 현재 IP가 SAN에 없으면 (IP가 바뀐 경우) 재생성
if [ ! -f certs/cert.pem ] || \
   ! openssl x509 -in certs/cert.pem -noout -ext subjectAltName 2>/dev/null | grep -q "IP Address:${LAN_IP}"; then
  ./make_cert.sh
fi

# 녹화 모드 선택 (env로 미리 지정하면 프롬프트 생략: RECORD_MODE=off|jpeg|mp4)
if [ -z "${RECORD_MODE:-}" ]; then
  echo ""
  echo "녹화 모드를 선택하세요:"
  echo "  0) 저장 안 함 — 실시간 전달만 [기본]"
  echo "  1) JPEG 프레임 저장  (recordings/<세션>/frames/*.jpg)"
  echo "  2) mp4 영상 저장     (폰 연결 종료 시 조립, recordings/<세션>/video.mp4)"
  read -r -p "선택 [0/1/2]: " sel || sel=""
  case "$sel" in
    1) RECORD_MODE=jpeg ;;
    2) RECORD_MODE=mp4 ;;
    *) RECORD_MODE=off ;;
  esac
fi
export RECORD_MODE
echo "녹화 모드: ${RECORD_MODE}"

PORT="${PORT:-8443}"
URL="https://${LAN_IP}:${PORT}"

echo ""
echo "──────────────────────────────────────────────"
echo "📱 아이폰 (같은 Wi-Fi): ${URL}"
echo "   최초 접속 시 인증서 경고 → 고급/자세히 → 계속 진행"
echo "🖥  수신 확인 뷰어:      ${URL}/viewer"
echo "──────────────────────────────────────────────"
.venv/bin/python -c "
import qrcode
qr = qrcode.QRCode(border=1)
qr.add_data('${URL}')
qr.print_ascii(invert=True)
" 2>/dev/null || true
echo ""

exec .venv/bin/python server.py
