#!/bin/bash
# iOS getUserMedia는 HTTPS(secure context) 필수라서 자체 서명 인증서를 만든다.
# 현재 Mac의 LAN IP를 SAN에 포함시켜, 폰이 https://<LAN IP>:8443 으로 접속 가능하게 함.
set -euo pipefail
cd "$(dirname "$0")"

LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
if [ -z "$LAN_IP" ]; then
  echo "LAN IP를 찾지 못했습니다. Wi-Fi 연결을 확인하세요." >&2
  exit 1
fi

mkdir -p certs
openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=drone-agent-phone-stream" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:${LAN_IP}"

echo ""
echo "✅ 인증서 생성 완료 (SAN: localhost, 127.0.0.1, ${LAN_IP})"
echo "서버 기동:  python server.py"
echo "아이폰에서: https://${LAN_IP}:8443  (최초 접속 시 인증서 경고 → '고급' → 계속 진행)"
echo "노트북에서: https://${LAN_IP}:8443/viewer"
