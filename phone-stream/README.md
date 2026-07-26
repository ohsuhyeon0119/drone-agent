# phone-stream — 폰 카메라 → 서버 실시간 스트리밍

아이폰 브라우저(Safari)가 카메라 프레임을 JPEG로 인코딩해 WebSocket으로 서버에
실시간 전송한다. 서버는 최신 프레임을 `frame_buffer`로 유지하며, AI 파이프라인이
소비할 수 있는 훅을 제공한다. 방식 선정 배경은 `../phone-streaming.plan.md` 참고.

## 로컬 실행 (원커맨드)

```bash
cd phone-stream
./run.sh
```

`run.sh`가 venv/의존성/인증서(현재 LAN IP 기준, IP 바뀌면 자동 재생성)를 알아서
준비하고 서버를 띄운 뒤, 접속 URL과 **QR 코드**를 출력한다.

- **아이폰**: Mac과 같은 Wi-Fi에서 카메라로 QR을 찍거나 Safari로
  `https://<Mac LAN IP>:8443` 접속 → 인증서 경고 1회 수락 → `▶ 스트리밍 시작`
- **노트북**: `https://<Mac LAN IP>:8443/viewer` 에서 수신 영상 + fps + 폰→서버 지연 실시간 확인
- 종료: `Ctrl-C`

인증서 경고 우회가 안 되는 환경이면 `ngrok http 8443` (또는 tailscale)으로 대체.

## 배포

앱은 12-factor 스타일로 만들어져 있어 그대로 올리면 된다:

- 설정은 전부 환경변수 — `PORT`(기본 8443), `CERT_FILE`/`KEY_FILE`(없으면 HTTP 모드)
- 프론트의 WS 주소는 `location.host` 기준 상대 경로라 어떤 도메인/프록시 뒤에서도 동작
- 상태는 전부 메모리(최신 프레임 버퍼) — 디스크/DB 불필요, 단일 인스턴스 전제

```bash
docker build -t phone-stream .
docker run -p 8080:8080 phone-stream   # HTTP 모드로 뜸
```

TLS는 플랫폼이 종단하는 구성을 권장 (iOS 카메라는 HTTPS 필수):

- **PaaS** (Fly.io / Render / Railway / Cloud Run): Dockerfile 그대로 배포하면
  플랫폼이 HTTPS 도메인 제공. `PORT`만 플랫폼 요구값에 맞추면 끝.
  단, WebSocket 지원 여부 확인 (위 4개는 모두 지원).
- **자체 VM**: Caddy/nginx가 443에서 TLS 종단 후 `localhost:8080`으로 리버스 프록시
  (Caddy면 `reverse_proxy localhost:8080` 한 줄, WS 자동 처리).

### 현재 배포 (OCI, 2026-07-25)

**https://droneagent.cloud** — OCI ARM 서버에 자체 VM 방식으로 배포됨.
가비아 도메인 + Caddy(Let's Encrypt 자동 인증서), systemd 서비스 `phone-stream`(PORT=8080 HTTP 모드).
보조 주소 https://64.110.109.126.sslip.io 도 동작. 서버 상세는 저장소 루트의 `SERVER.md` 참고.

## 녹화

`./run.sh` 시작 시 녹화 모드를 물어본다 (env `RECORD_MODE=off|jpeg|mp4`로 미리 지정 가능):

- **0 (off, 기본)**: 저장 안 함. 프레임은 메모리의 최신 1장만 유지 — AI 실시간 전달 전용.
- **1 (jpeg)**: 수신 프레임 전부를 `recordings/<세션시각>/frames/NNNNNN.jpg`로 저장.
  `frames.jsonl`에 프레임별 캡처/수신 시각 기록.
- **2 (mp4)**: 위처럼 쌓다가 폰 연결이 끊기면 ffmpeg로 `recordings/<세션시각>/video.mp4`
  조립 (실제 수신 간격 기반이라 원래 속도로 재생됨). 성공 시 JPEG는 삭제.
  ffmpeg 필요 (`brew install ffmpeg`).

녹화는 실시간 전달 경로와 독립 — 어느 모드든 `/frame.jpg`, `/ws/viewer`는 동일하게 동작.

## 엔드포인트

| 경로 | 용도 |
|---|---|
| `/` | 폰용 송출 페이지 (카메라 캡처 → WS 전송, 1/5/10fps 선택) |
| `/viewer` | 수신 확인 뷰어 (fps, e2e 지연 표시) |
| `WS /ws/phone` | 폰 → 서버 프레임 인입 |
| `WS /ws/viewer` | 서버 → 뷰어/백엔드 프레임 push 구독 |
| `GET /frame.jpg` | **AI 파이프라인용 훅**: 최신 프레임 1장 (헤더에 캡처/수신 시각) |
| `GET /stats` | 연결 상태, 수신 fps, 최신 프레임 age, e2e 지연 JSON |

## AI 파이프라인(기존 main.py) 연결 방법

기존 `vision_monitor_loop`는 `frame_buffer`에서 최신 프레임을 꺼내 Groq에 보낸다.
웹캠 WS 대신 이 서버의 프레임을 쓰려면 아래 중 하나:

1. **폴링**: 2초 주기 루프에서 `GET /frame.jpg` 로 가져와 base64 인코딩 후 기존 로직 그대로
2. **push 구독**: 백엔드가 `WS /ws/viewer` 를 클라이언트로 구독해 `frame_buffer` 갱신
3. **흡수 통합**: 이 `server.py`의 `/ws/phone` 핸들러와 `get_latest_frame()`을 기존 main.py로 이식

## 프레임 와이어 포맷

- 폰 → 서버: `[8B LE float64: 서버시계 기준 캡처시각(ms)] + [JPEG bytes]`
- 서버 → 뷰어: `[8B capture_ts] + [8B recv_ts] + [JPEG bytes]`
- 시계 동기화: WS 연결 직후 ping/pong 5회로 폰↔서버 clock offset(중앙값) 추정
- 백프레셔: 폰에서 `ws.bufferedAmount > 512KB`면 프레임 skip / 느린 뷰어는 오래된 프레임 drop
