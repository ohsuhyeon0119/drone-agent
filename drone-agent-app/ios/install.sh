#!/bin/bash
# Xcode에서 DroneAgent 프로젝트를 만든 뒤 이 스크립트를 돌리면
# Sources/*.swift를 앱 타겟 폴더에 복사한다 (기본 생성된 파일은 덮어쓴다).
#
#   cd drone-agent-app/ios && ./install.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

# Xcode가 만드는 레이아웃이 버전/저장위치에 따라 한 겹 다르다:
#   ios/DroneAgent/DroneAgent/DroneAgentApp.swift   (컨테이너 폴더까지 만든 경우)
#   ios/DroneAgent/DroneAgentApp.swift              (바로 만든 경우)
# 그래서 경로를 가정하지 않고 생성된 진입점 파일을 찾아서 그 폴더에 넣는다.
ENTRY="$(find "$HERE" -name 'DroneAgentApp.swift' -not -path "$HERE/Sources/*" -print -quit 2>/dev/null || true)"

if [ -z "$ENTRY" ]; then
  echo "✗ Xcode가 생성한 DroneAgentApp.swift를 $HERE 아래에서 못 찾았습니다."
  echo "  프로젝트를 'DroneAgent' 이름으로 이 폴더에 먼저 만드세요."
  echo "  (이미 만들었다면 실제 경로를 알려주세요)"
  exit 1
fi

TARGET="$(dirname "$ENTRY")"
echo "→ 타겟 폴더: $TARGET"
echo

cp -v "$HERE"/Sources/*.swift "$TARGET"/
cp -v "$HERE"/Sources/Info.plist "$(dirname "$TARGET")"/

echo
echo "✓ 복사 완료. Xcode로 돌아가 ⌘R."
echo "  파일이 프로젝트 네비게이터에 안 보이면 Xcode를 껐다 켜거나,"
echo "  Finder에서 파일들을 끌어다 놓고 'Copy items if needed'를 해제하세요."
