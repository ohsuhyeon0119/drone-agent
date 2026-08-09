# 동행이 iOS 앱 — 셋업

`wss://droneagent.cloud/ws/unified`에 붙어 실시간 음성 대화 + 초당 1장 카메라 송출을 한다.
서버 코드는 그대로 두고 브라우저 대신 네이티브 앱이 같은 WebSocket 프로토콜을 말한다.

의존성 없음. 파일 7개, 순수 SwiftUI + AVFoundation.

---

## 1. Xcode 프로젝트 생성 (5분)

1. Xcode → **File → New → Project… → iOS → App**
2. 이렇게 채운다:
   - Product Name: **`DroneAgent`** ← 반드시 이 이름 (파일명이 맞아떨어져야 함)
   - Organization Identifier: `com.본인아이디` (유일하기만 하면 됨)
   - Testing System: None, Storage: None
   - Team은 비워둬도 된다 — 3단계에서 설정한다
3. 저장 위치: **`drone-agent-app/ios/`** 폴더 선택,
   **`Create Git repository` 체크 해제** (상위가 이미 git repo다)

## 2. 소스 복사 (10초)

```bash
cd drone-agent-app/ios && ./install.sh
```

Xcode 16+는 폴더를 동기화하므로 바로 프로젝트에 나타난다.

## 3. 서명 (2분)

**타겟 DroneAgent → Signing & Capabilities**

- **Automatically manage signing** 체크
- **Team**: 본인 Apple ID (무료 계정 OK — `Add an Account…`로 로그인)
- Bundle Identifier가 `com.본인이름.DroneAgent`처럼 **전세계 유일**해야 한다.
  빨간 에러 나면 뒤에 아무 숫자나 붙일 것.

## 4. 권한 + 백그라운드 오디오 (2분)

**같은 화면에서 `+ Capability` → `Background Modes` → `Audio, AirPlay, and Picture in Picture` 체크**
(화면 잠겨도 대화가 안 끊긴다)

**타겟 → Info 탭 → 아래 3줄 추가** (`+` 눌러 Key 입력):

| Key | Value |
|---|---|
| `Privacy - Camera Usage Description` | 동행이가 주변 상황을 보기 위해 카메라를 사용합니다 |
| `Privacy - Microphone Usage Description` | 동행이와 음성으로 대화하기 위해 마이크를 사용합니다 |
| `Privacy - Local Network Usage Description` | 로컬 개발 서버에 연결하기 위해 사용합니다 |

> 로컬 서버(`ws://`)로 테스트할 계획이면 Info에 `App Transport Security Settings`
> → `Allow Local Networking` = `YES` 도 추가한다. `wss://droneagent.cloud`만 쓸 거면 불필요.

## 5. 아이폰 준비 (재부팅 포함 — 미리 해둘 것)

1. 아이폰 **설정 → 개인정보 보호 및 보안 → 개발자 모드 → 켬 → 재부팅**
2. 케이블로 맥에 연결, 폰에서 "이 컴퓨터를 신뢰" 탭
3. Xcode 상단 기기 선택에서 본인 아이폰 고르고 **⌘R**
4. 첫 실행은 실패한다 — 폰에서 **설정 → 일반 → VPN 및 기기 관리 → 개발자 앱 → 신뢰**
   누른 뒤 Xcode에서 다시 ⌘R

> 무료 계정으로 서명한 앱은 **7일 뒤 만료**된다. 만료되면 ⌘R 다시 하면 된다.

---

## 단계별 검증 순서

한 번에 다 켜지 말고 이 순서로 확인해야 어디서 깨졌는지 안다.

### ① 음성 재생 (서버 → 앱)

앱에서 **대화 시작** → 상태가 `연결됨`으로 바뀌는지 확인. 그 다음 맥에서:

```bash
curl -X POST https://droneagent.cloud/api/remind-medication
```

**폰 스피커에서 동행이 목소리가 나오면 절반은 끝난 것이다.** 자막도 같이 떠야 한다.

- 소리 안 남 → 폰 무음 스위치, 볼륨 확인. 그래도 안 되면 Xcode 콘솔 로그를 붙여줄 것.
- `연결됨`이 안 뜸 → 서버가 살아있는지 (`curl -I https://droneagent.cloud/`), 폰이 인터넷 되는지.

### ② 음성 대화 (앱 → 서버 → 앱)

"안녕하세요" 하고 말 걸어보기. 상태가 `연결됨`인 채로 답이 오면 성공.

- **동행이가 자기 말에 계속 대답한다** → 에코 캔슬이 안 걸린 것.
  `AudioIO.start()`의 `setVoiceProcessingEnabled(true)`가 throw하는지 확인.
  급하면 이어폰 꽂고 데모하면 우회된다.
- **말이 뚝뚝 끊긴다** → `Config.micSampleRate`가 16000인지, 서버 로그에 오디오가 들어오는지.

### ③ 카메라 감지

폰 카메라를 사람에게 향한 채로 두고 서버 로그를 본다. `[/unified:fall] detect` 류가
2초마다 찍히고, 앱 하단에 `🚨`/`💊` 칩이 뜨면 프레임이 잘 가고 있는 것.

> ⚠️ 서버 `.env`에 `PHONE_STREAM_URL`이 설정돼 있으면, phone-stream이 송출 중일 때
> 앱이 보내는 카메라/마이크가 **통째로 무시된다** (main.py `_phone_is_active`).
> 앱으로 데모할 거면 phone-stream 송출을 끄거나 `PHONE_STREAM_URL`을 비울 것.

---

## 알아둘 제약

- 서버의 `_active_unified_session`은 **전역 단일 세션**이다. 폰과 노트북을 동시에
  붙이면 나중에 붙은 쪽이 이긴다. 데모 중엔 브라우저 탭을 닫아둘 것.
- 자동 재연결 없음. 끊기면 **대화 시작**을 다시 누른다.
- 텍스트 입력 UI 없음 (`SessionClient.send(text:)`는 구현돼 있으니 필요하면 버튼만 붙이면 됨).

## 서버 주소 바꾸기

[Sources/Config.swift](Sources/Config.swift)의 `serverBase` 한 줄만 고치면 된다.
로컬 테스트용 `ws://<맥IP>:8003` 예시가 주석으로 들어 있다.
