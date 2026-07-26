# 폰 → 서버 실시간 영상 스트리밍 .plan

## 목표

아이폰으로 촬영 중인 영상이 **실시간으로 서버에 도착**하게 만든다.
서버에 도착한 영상을 AI(Groq detect / Gemini Live)에 먹이는 부분은 이미 구현되어 있으므로
(SCENARIO_A_IMPLEMENTATION.md 참고), 우리는 그 파이프라인이 소비할 수 있는 형태로
**폰 → 서버 인입 구간**만 책임진다.

## 소비자(AI 파이프라인)가 원하는 입력 형태 — 설계의 출발점

기존 구조를 보면:

```
[카메라] --~1fps JPEG--> [WebSocket] --> [frame_buffer(최신 1장)] --2초 주기--> Groq VLM
                                     └--> Gemini Live send_realtime_input(video)
```

즉 AI 쪽 실소비량은 **초당 1~2장의 JPEG**다. 30fps 인코딩된 비디오 스트림(H.264 등)을
보내봐야 서버에서 다시 프레임으로 디코딩해야 하므로, "진짜 비디오 코덱 스트리밍"이
반드시 필요한 게 아니다. 핵심 요구는:

1. 폰 카메라 프레임이 **낮은 지연(수백 ms 이내)** 으로 서버에 계속 도착할 것
2. 서버가 **최신 프레임을 언제든 꺼낼 수 있는 버퍼** 형태로 들고 있을 것 (기존 `frame_buffer`와 동일 인터페이스)
3. 폰에서 앱 설치 없이 (또는 최소 설치로) 바로 시연 가능할 것

## 후보 방식 비교

### 방법 1 — 모바일 브라우저 + WebSocket JPEG 프레임 스트리밍 ✅ 채택

아이폰 Safari에서 웹페이지 접속 → `getUserMedia`로 카메라 캡처 → canvas로 JPEG 인코딩
→ WebSocket 바이너리로 서버 전송 (5~10fps 조절 가능).

- 장점:
  - 기존 파이프라인과 **입력 포맷이 동일**(JPEG 프레임 + WS). `frame_buffer`에 그대로 꽂힘.
  - 앱 설치 불필요. 폰에서 URL 하나 열면 끝.
  - 서버 코드가 기존 스택(FastAPI + WebSocket) 그대로 — 새 인프라 0개.
  - 이후 마이크 PCM 오디오 전송도 같은 WS에 얹기 쉬움 (Gemini Live용, 기존 프론트가 이미 하던 방식).
- 단점:
  - 코덱 기반 스트리밍이 아니라 fps를 크게 올리면(>15fps) 대역폭 비효율.
    → AI 소비량이 1~2fps라 문제 없음.
  - **iOS에서 `getUserMedia`는 HTTPS(secure context) 필수** → 자체 서명 인증서 or ngrok/tailscale 필요.
- 지연: LAN 기준 프레임당 수십~수백 ms. 충분.

### 방법 2 — WebRTC (브라우저 → aiortc 서버)

폰 브라우저가 WebRTC PeerConnection으로 서버(Python `aiortc`)에 영상 트랙을 보내고,
서버가 트랙에서 프레임을 뽑아 `frame_buffer`에 넣는 방식.

- 장점: 진짜 저지연(<200ms) 연속 비디오. 네트워크 상황에 따라 화질 자동 적응. 오디오 트랙도 표준으로 함께.
- 단점: 시그널링 + ICE/STUN + aiortc 의존성 등 구조 복잡도가 확 올라감.
  aiortc는 버전 민감하고 디버깅이 까다로움. HTTPS 요구는 여기도 동일.
  AI 소비가 1~2fps인 상황에선 오버엔지니어링.
- 판단: **fps를 진짜로 높게 써야 하는 요구가 생기면 그때 승격**할 2순위 안.

### 방법 3 — 방송 앱(RTMP/SRT) + MediaMTX 수신 서버

Larix Broadcaster 같은 앱으로 RTMP/SRT 송출 → 서버의 MediaMTX(or nginx-rtmp)가 수신 →
ffmpeg/OpenCV로 프레임 추출 → `frame_buffer`.

- 장점: 폰 쪽 코드 0줄, 송출 안정성(재연결, 비트레이트 적응)은 제일 좋음.
- 단점: RTMP 자체 지연 1~3초(SRT면 <1초지만 앱/서버 세팅 복잡). 별도 미디어 서버 프로세스 +
  ffmpeg 디코딩 파이프 관리 필요. 오디오를 Gemini Live로 보내는 경로가 따로 놀게 됨.
- 판단: 데모 PoC엔 인프라가 과함.

### (탈락) HLS/DASH — 지연 5~30초라 "실시간 감지" 요구에 부적합.

## 채택: 방법 1 (모바일 브라우저 + WebSocket JPEG)

이유 요약: AI 소비 형태(초당 1~2장 JPEG)와 정확히 일치하고, 기존 스택 그대로에,
폰에는 아무것도 설치할 필요가 없다. 데모 리스크가 가장 낮다.

## 구현 설계 (`phone-stream/`)

```
[아이폰 Safari]  phone.html
   getUserMedia(후면 카메라)
   canvas → JPEG(quality 0.7) → WS binary 전송 (기본 5fps, UI로 조절)
   [8B float64: 보정된 캡처시각][JPEG bytes]
        │  wss:// (자체서명 인증서, LAN)
        ▼
[FastAPI server.py]
   /ws/phone   ← 프레임 수신 → frame_buffer(최신 1장) 갱신 + 뷰어 브로드캐스트
   /ws/viewer  ← 모니터링 페이지들에 fan-out (느린 뷰어는 오래된 프레임 drop)
   /frame.jpg  ← ★ AI 파이프라인용 훅: 언제든 GET 하면 최신 프레임
   /stats      ← fps / 지연 / 연결 상태 JSON
        │
        ▼
[노트북 브라우저] viewer.html — 수신 영상 실시간 표시 + fps/지연 표기 (검증용)
```

- **시계 동기화**: 폰↔서버 시계가 다르므로, WS 연결 직후 ping/pong 5회로 offset을 추정해
  폰이 "서버 시계 기준 캡처 시각"을 프레임 헤더에 실어 보냄 → 서버/뷰어에서 e2e 지연 측정 가능.
- **백프레셔**: 폰 쪽에서 `ws.bufferedAmount`가 임계치 넘으면 해당 프레임 skip (지연 누적 방지).
- **HTTPS**: `make_cert.sh`가 현재 LAN IP를 SAN에 넣은 자체 서명 인증서 생성.
  아이폰에서 최초 접속 시 경고 1회 수락. (안 되면 대안: `ngrok http 8443` / tailscale)

### 기존 파이프라인 연결 지점

- 기존 `main.py`의 `frame_buffer`가 웹캠 WS 대신 이 서버의 프레임을 쓰면 됨.
  통합 시 선택지: ① `/frame.jpg` 폴링 ② `/ws/viewer`를 백엔드가 구독 ③ 이 서버 코드를 기존 main.py에 흡수.
  (통합 자체는 AI 쪽 담당 영역이므로 훅만 제공)

### 마일스톤

1. [x] 방식 조사/비교, 채택
2. [x] `phone-stream/server.py` — WS 수신, frame_buffer, viewer fan-out, /frame.jpg, /stats
3. [x] `phone-stream/static/phone.html` — 카메라 캡처/전송 (iOS Safari 대응)
4. [x] `phone-stream/static/viewer.html` — 실시간 수신 확인 + 지연/fps 표시
5. [x] `make_cert.sh` + README (아이폰 접속 절차)
6. [x] 로컬 기동 검증 — 폰 시뮬레이터로 e2e 통과 (프레임 3장: WS 인입 → frame_buffer → 뷰어 수신 → /frame.jpg 바이트 일치, 시계동기화 ping/pong 동작). 실폰 테스트는 사용자가 수행
7. [ ] (후속) 마이크 오디오 PCM 전송 — Gemini Live 입력용
8. [ ] (후속) 기존 main.py frame_buffer와 통합

### 리스크

| 리스크 | 대응 |
|---|---|
| iOS가 자체서명 wss를 거부 | 같은 origin이면 페이지 경고 수락 후 대체로 동작. 실패 시 ngrok/tailscale로 우회 |
| 폰 절전/화면 꺼짐으로 캡처 중단 | 시연 중 화면 켜둠 + Wake Lock API 시도 |
| Wi-Fi 불안정으로 WS 끊김 | 자동 재연결(지수 백오프) 구현 |
| fps 요구가 커질 경우 | 방법 2(WebRTC/aiortc)로 승격 — 서버 훅(`frame_buffer`) 인터페이스는 유지 |
