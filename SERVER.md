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

## 배포된 서비스

### phone-stream (2026-07-25 배포 완료)

- **주소: https://droneagent.cloud** (폰 접속 / `/viewer` / `/stats` / `/frame.jpg`)
  - 보조 주소: https://64.110.109.126.sslip.io (같은 서버, 둘 다 유효)
  - 도메인: 가비아 등록, A 레코드 `@` → 64.110.109.126 (TTL 600), 네임서버 ns.gabia.co.kr
- 구성: 아이폰 ──https/wss──> Caddy(443, Let's Encrypt TLS 종단) ──http──> phone-stream(localhost:8080)
- 앱 위치: `~/phone-stream/` (`.venv` 포함)
- systemd 서비스: `phone-stream` (`/etc/systemd/system/phone-stream.service`, `PORT=8080` HTTP 모드, enable됨)
  - 로그: `sudo journalctl -u phone-stream -f`
  - 녹화 켜려면: 서비스에 `Environment=RECORD_MODE=mp4` 추가 + `sudo apt install ffmpeg` 후 재시작
- Caddy: `/etc/caddy/Caddyfile` — `64.110.109.126.sslip.io, droneagent.cloud { reverse_proxy localhost:8080 }`
  - 로그: `sudo journalctl -u caddy -f`
- 방화벽: iptables 80/443 허용(영구화됨) + OCI 보안 목록에 22/80/443 인그레스 규칙 존재
- 이후 AI 파이프라인(main.py) 통합 시 같은 서버에서 프레임/오디오 소비 가능
