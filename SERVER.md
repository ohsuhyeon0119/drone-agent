# 배포 서버 정보 (OCI)

> 2026-07-25 확보. phone-stream 등 배포 대상 서버.

## 접속

```bash
ssh oci
```

별칭이 안 먹는 환경일 경우 전체 명령어:

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@64.110.109.126
```

## 사양

| 항목 | 값 |
|---|---|
| 클라우드 | OCI (Oracle Cloud) Ampere A1 |
| 아키텍처 | **ARM / aarch64** |
| OS | Ubuntu 24.04 |
| 자원 | 2 OCPU / 12GB RAM |
| 공인 IP | 64.110.109.126 |
| 유저 | `ubuntu` (비밀번호 없이 sudo 동작) |
| SSH 키 | 이 Mac의 `~/.ssh/id_ed25519` (기본 경로라 `-i` 생략 가능) |

## 주의사항

- **ARM 서버**라서 패키지 설치 시 x86 전용 바이너리는 안 됨 — arm64용을 써야 함
  (Docker 이미지도 `linux/arm64` 지원 여부 확인; python:3.12-slim 등 공식 이미지는 대부분 지원)

## 배포된 서비스 (2026-07-26 기준)

라우팅 (Caddy `/etc/caddy/Caddyfile`, Let's Encrypt 자동 TLS, 로그 `sudo journalctl -u caddy -f`):

| 주소 | 서비스 | 내부 포트 |
|---|---|---|
| **https://droneagent.cloud** | **drone-agent-app (동행이 UI)** — `/fall` `/medication` `/task` | 8003 |
| https://64.110.109.126.sslip.io | phone-stream (폰 카메라/마이크 송출 인입) — `/`(폰 송출) `/viewer` `/stats` | 8080 |

도메인: 가비아 등록 `droneagent.cloud`, A 레코드 `@` → 64.110.109.126 (TTL 600), 네임서버 ns.gabia.co.kr

### drone-agent-app (동행이)

- 위치: `~/drone-agent-app/` (`.venv` 포함), systemd 서비스 `drone-agent` (enable됨, Restart=always)
  - 로그: `sudo journalctl -u drone-agent -f`
- `.env` (chmod 600): `GEMINI_API_KEY`, `OPEN_ROUTER_KEY` ← **키 채워야 AI 동작**,
  `PHONE_STREAM_URL=http://localhost:8080` (같은 서버의 phone-stream 피드 구독), `PORT=8003`
- 키 채운 뒤: `sudo systemctl restart drone-agent`

### phone-stream

- 위치: `~/phone-stream/`, systemd 서비스 `phone-stream` (`PORT=8080` HTTP 모드, enable됨)
  - 로그: `sudo journalctl -u phone-stream -f`
  - 녹화 켜려면: 서비스에 `Environment=RECORD_MODE=mp4` 추가 + `sudo apt install ffmpeg` 후 재시작
- `WS /ws/feed`: 영상+오디오 AI 소비용 출구 — drone-agent-app이 localhost로 구독

### 공통

- 구성: 아이폰(송출) ──wss──> phone-stream ──localhost──> drone-agent-app(감지 VLM + Gemini Live) ──> 브라우저 UI
- 방화벽: iptables 80/443 허용(영구화됨) + OCI 보안 목록에 22/80/443 인그레스 규칙 존재
