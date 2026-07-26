# 동행이 — 노인 돌봄 드론 에이전트 PoC

root_readme.md에서 정의한 핵심 시나리오 3가지를 하나의 앱으로 통합한 데모.
Gemini Live API(실시간 음성·영상 대화)와 Groq/OpenRouter(빠른 프레임 감지)를 조합해,
"카메라가 뭔가를 감지하면 대화 중이던 AI가 스스로 먼저 말을 건다"는 동작을
세 시나리오에서 각각 구현했다.

세 페이지 모두 카메라가 실시간으로 보이고, 우측 상단 탭으로 전환할 수 있다.

## 시나리오 A — `/fall` 낙상 감지

대화 중 카메라가 낙상을 감지하면(Groq VLM, 2초 주기 판정) 동행이가 대화를 멈추고
"괜찮으세요?"라고 먼저 묻는다. 사용자가 신고를 원하거나, 괜찮지 않다고 답하거나,
응답이 없으면 `notify_caregiver` 도구를 호출해 119 신고 상황을 기록하고 화면에
토스트 알림을 띄운다. 괜찮다고 명확히 답하면 신고 없이 대화로 넘어간다.

## 시나리오 B — `/task` 작업 보조

감지 로직 없이, 카메라로 보이는 것에 대해 자연스럽게 음성으로 묻고 답하는 단순
VLM 대화. 키오스크·서류 등 노인이 어려워하는 것을 같이 보면서 설명해주는 용도.

## 시나리오 C — `/medication` 약 복용 확인

연결 직후 동행이가 먼저 말을 건다("OO님, 20시입니다. 혈압약을 드셔야 해요") —
개인화된 처방 정보(`memory.json`)를 근거로 한 것. 이후 카메라가 복용 동작을
감지하면(Groq VLM, 2초 주기) 메모리에 기록하고 "잘하셨어요!"라고 격려하며,
대시보드 우측 패널에 메모리 업데이트가 실시간으로 표시된다.

## 공통 설계

- **페르소나**: 카메라로 보고 목소리로만 말할 수 있고, 팔다리가 없어 물건을
  직접 만지거나 가져다줄 수 없다는 제약을 세 시나리오 공통 시스템 프롬프트에 명시.
- **프로액티브 발화 메커니즘**: Gemini Live는 기본적으로 반응형이라 스스로 먼저
  말하지 않는다. 감지 루프(Groq/OpenRouter)가 이벤트를 판단하면
  `send_client_content(turn_complete=True)`로 강제로 턴을 발생시켜, 그 순간까지
  쌓인 오디오/영상 컨텍스트를 근거로 자연스럽게 먼저 말하게 만든다 (`gemini_live.py`).
- **감지 모델**: `meta-llama/llama-4-scout`를 OpenRouter 경유로 호출하며
  Groq를 우선 라우팅하되(속도), 혼잡 시 자동 대체를 허용한다(안정성).

## 실행

```bash
pip install -r requirements.txt   # fastapi uvicorn python-dotenv google-genai openai websockets
cp .env.example .env              # GEMINI_API_KEY, OPEN_ROUTER_KEY 채우기
python main.py                    # http://localhost:8003
```

## 영상 소스: 브라우저 웹캠 + 폰 스트림 (스마트 폴백)

기본은 브라우저 웹캠/마이크(getUserMedia)다. `.env`에 `PHONE_STREAM_URL`을 설정하면
phone-stream 서버의 폰(드론 카메라) 피드가 **송출 중일 때만** 자동으로 모델 입력이 되고,
송출이 없으면 브라우저 입력을 그대로 쓴다 — 페이지 하나로 두 사용법이 공존한다.

```
PHONE_STREAM_URL=http://localhost:8080   # 같은 서버에 배포된 경우
```

- 서버의 `WS /ws/feed`를 구독해 영상(JPEG)은 `frame_buffer`(감지 VLM, 매 프레임)와
  Gemini Live(~1fps 제한)에, 오디오(16kHz PCM)는 Gemini Live에 주입한다 (`_pump_phone_stream`).
- 폰 패킷이 최근 3초(`PHONE_ACTIVE_WINDOW`) 안에 들어왔으면 브라우저의 웹캠
  이미지·마이크 오디오는 무시(이중 입력 방지), 아니면 브라우저 입력 사용.
- 연결이 끊기면 3초 간격으로 자동 재접속. 비우면 항상 브라우저 방식.
