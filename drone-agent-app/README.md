# 동행이 — 노인 돌봄 드론 에이전트 PoC

root_readme.md에서 정의한 핵심 시나리오(낙상 감지, 약 복용 확인, 작업 보조)를
**하나의 통합 세션**에서 동시에 처리하는 데모. Gemini Live API(실시간 음성·영상 대화)와
Groq/OpenRouter(빠른 프레임 감지)를 조합해, "카메라가 뭔가를 감지하면 대화 중이던
AI가 스스로 먼저 말을 건다"는 동작을 구현했다.

탭으로 시나리오를 미리 고르지 않는다 — 낙상 감지기와 복약 감지기가 한 세션 안에서
동시에 돌고, 어느 쪽이든 먼저 걸리는 상황에 맞춰 동행이가 알아서 반응한다.

## 화면 하나, 감지기 여러 개

`http://localhost:8003` 접속하면 바로 이 화면이다:

- **실시간 카메라** + "대화 시작" 버튼
- **대화 로그** (텍스트 입력도 가능)
- **감지 로그** — 낙상 감지기(🚨)와 복약 감지기(💊)의 판정이 동시에 찍힘
- **메모리 업데이트 로그** — 복약 확인 시 기록
- **"💊 약 복용 알림 (5초 후)" 버튼** — 누르면 5초 카운트다운 후 동행이가 먼저
  복약을 안내한다. 연결하자마자 자동으로 말을 걸지는 않는다(데모 타이밍을 직접
  제어하기 위함).

## 동작 방식

**1. 감지 — `detection_graph.py` (LangGraph)**

"프레임 → Detect(감지) → Decide(판단) → Nudge(문구 생성)" 3단계를 그래프로
정의해두고, 낙상용·복약용 감지 루프가 이 그래프 하나를 프롬프트/타겟이벤트/
쿨다운/넛지문구만 다르게 넣어서 재사용한다(`main.py`의 `fall_vision_loop`,
`medication_vision_loop`). 감지 모델은 `meta-llama/llama-4-scout`를 OpenRouter
경유로 호출하며 Groq를 우선 라우팅하되(속도), 혼잡 시 자동 대체를 허용한다.

**2. 프로액티브 발화 — `gemini_live.py`**

Gemini Live는 기본적으로 반응형이라 스스로 먼저 말하지 않는다. 감지 그래프가
이벤트를 확정하면 `send_client_content(turn_complete=True)`로 강제로 턴을
발생시켜, 그 순간까지 쌓인 오디오/영상 컨텍스트를 근거로 자연스럽게 먼저
말하게 만든다. 이게 이 프로젝트의 핵심 트릭이다.

**3. 판단과 실행 — Gemini Live 세션 내부**

"낙상이면 괜찮은지 묻고 필요하면 119"나 "복약 확인되면 칭찬"같은 판단은
전부 시스템 프롬프트(`UNIFIED_PERSONA`)에 위임한다. 필요시 `notify_caregiver`
tool을 스스로 호출한다.

**4. 개인화 메모리 — `memory.py`**

처방 정보(이름/약/시간)와 복용 기록을 JSON 파일에 저장. `/api/medication/state`로
조회 가능.

## 실행

```bash
pip install -r requirements.txt   # fastapi uvicorn python-dotenv google-genai openai langgraph websockets
cp .env.example .env              # GEMINI_API_KEY, OPEN_ROUTER_KEY 채우기 (PHONE_STREAM_URL은 선택)
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
- `/ws/unified` 세션 하나에 통합돼 있다 — 낙상·복약 감지기 둘 다 이 영상 소스를 그대로 공유한다.

## 다음 단계 (설계만 하고 아직 미구현)

지금은 낙상·복약 두 시나리오와 tool 하나가 코드에 하드코딩돼 있다. 다음 단계로
논의된 것:

- **시나리오/tool 레지스트리**: 하드코딩된 프롬프트·쿨다운·tool 목록을
  `users/<id>.json` 같은 설정 데이터로 빼서, 노인별로 다른 시나리오 조합을
  코드 수정 없이 켜고 끌 수 있게 함. (단, Gemini Live는 tool을 세션 시작
  시점에만 고정할 수 있어 — 설정을 바꾸면 다음 재연결부터 반영됨)
- **정책(policy) 기반 대응**: "tool 있다/없다"를 넘어 "낙상 시 몇 초 기다렸다가
  누구에게 먼저 연락할지"처럼 대응 방식 자체를 노인별로 다르게 설정. 정책
  데이터를 자연어 지시문으로 컴파일해 세션 페르소나에 주입하는 방식.
- **모니터링/관리 페이지**: 이 노인에게 지금 뭐가 켜져 있는지(설정)와 실제
  무슨 일이 있었는지(활동 로그, `events.jsonl`)를 보여주는 화면. 설정 변경도
  이 화면에서 (아코디언 형태로 시나리오별 세부 정책 입력).
- 추가 시나리오 후보: 침입 감지(Lifenology의 `prompts/intrusion.txt` 재사용
  가능), 식사 확인(복약과 같은 패턴), 외로움 케어(타이머 기반, 카메라 감지 불필요).
