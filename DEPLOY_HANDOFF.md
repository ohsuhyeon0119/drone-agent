# phone-stream OCI 배포 — 작업 인수인계

> 2026-07-25 갱신. **배포 완료.** 남은 것은 실기기 테스트뿐.
> 상세 서버 정보는 `SERVER.md`, 앱 정보는 `phone-stream/README.md` 참고.

## 목표 (달성됨)

`phone-stream/`(폰 카메라·마이크 → 서버 실시간 인입)을 OCI 서버에 상시 HTTPS 서비스로 배포.

**최종 주소: https://droneagent.cloud** (폰 접속 / `/viewer` / `/stats` / `/frame.jpg`)
보조 주소: https://64.110.109.126.sslip.io (같은 서버, 둘 다 유효)

```
아이폰 ──https/wss──> Caddy(443, TLS 종단) ──http──> phone-stream(localhost:8080)   [OCI 서버 안]
```

## 완료된 것 ✅ (전부)

서버: `ssh oci` = ubuntu@64.110.109.126, ARM/aarch64, Ubuntu 24.04.

1. **인스턴스 방화벽(iptables)**: 80/443 허용 + 영구화
2. **앱 배포**: `~/phone-stream/` (server.py, static/, .venv)
3. **systemd 서비스**: `phone-stream` — `PORT=8080` HTTP 모드, enable+start, 정상 동작
4. **Caddy**: `/etc/caddy/Caddyfile`:
   ```
   64.110.109.126.sslip.io, droneagent.cloud {
       reverse_proxy localhost:8080
   }
   ```
5. **OCI 보안 목록에 443 인그레스 추가** (기존 22/ICMP/80 규칙 유지한 채 5개로 갱신)
6. **도메인 연결**: 가비아에서 `droneagent.cloud` 구입, DNS 관리툴에서 A 레코드 `@` → `64.110.109.126` (TTL 600) 등록, 전파 확인
7. **HTTPS 검증 통과**: 두 주소 모두 Let's Encrypt 인증서 자동 발급, `/stats` JSON 200, `/viewer` 200
8. **문서화**: `SERVER.md`·`phone-stream/README.md`에 배포 상태/주소 반영

## 남은 작업 🔧

없음 — **전 과정 완료.**

### 실기기 최종 확인 ✅ (2026-07-25 통과)

- 아이폰 Safari → `https://droneagent.cloud` 인증서 경고 없이 접속, 스트리밍 시작 성공
- `/stats` 폴링 결과: 영상 5.0 fps 안정 수신, 폰→서버 e2e 지연 93~95ms,
  오디오 초당 10청크(100ms 조각) 실시간 인입 — 프레임 109장/오디오 218청크까지 확인

## 참고 컨텍스트

- 오디오 인입 구현 완료 (와이어 포맷: `[1B 'V'|'A'][8B ts][payload]`, 16kHz PCM 100ms 조각). 서버의 server.py는 최신 버전.
- 뷰어(`/viewer`)는 **영상만** 재생. 오디오는 서버 인입까지만 (AI 파이프라인 소비용). 뷰어에서 소리 재생은 미구현.
- 서버 기본 녹화 모드 off (실시간 중계만). 녹화 필요 시 systemd 서비스에 `Environment=RECORD_MODE=mp4` 추가 후 재시작 + `sudo apt install ffmpeg`.
- 트러블슈팅: 서버에서 `sudo journalctl -u caddy -f` (TLS/프록시), `sudo journalctl -u phone-stream -f` (앱).

---

## 새 세션에 줄 프롬프트 (복사용)

```
DEPLOY_HANDOFF.md 읽어. phone-stream이 https://droneagent.cloud 에 배포 완료된 상태야.
남은 건 실기기 테스트뿐이야. 내가 아이폰으로 접속해서 스트리밍을 시작할 테니까,
https://droneagent.cloud/stats 를 폴링하면서 frames_received / audio_chunks_received가
증가하는지 확인하고 결과 알려줘. 문제 있으면 서버(ssh oci)에서 caddy / phone-stream
서비스 로그 확인해서 진단해줘.
```
