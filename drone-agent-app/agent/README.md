# agent/

'동행이' 에이전트를 정의하는 것들 — 페르소나(지침), tool(행동) 정의, 프론트엔드
JS를 한 곳에 모아둔 디렉토리. `main.py`는 이 모듈들을 가져다 쓰기만 한다.

## 구성

- **`scenarios.py`** + **`scenarios/*.yaml`** — 시나리오(낙상/복약)의 구조화된
  정의: 감지 프롬프트(`detect_prompt`), 재판정 주기(`cooldown`), 감지 시
  Gemini에게 강제로 주입하는 신호(`nudge_template`), 그리고 감지되면 에이전트가
  지켜야 할 대응 지침 목록(`instructions`).
  - `scenarios/fall.yaml`, `scenarios/medication.yaml`이 실제로 편집하는
    대상이다 — 여기 `instructions` 리스트에 항목을 추가/삭제/수정하면 된다.
  - 파일이 없거나 형식이 잘못돼도 `load_scenarios()`가 `DEFAULT_SCENARIOS`(기존에
    하드코딩돼 있던 값 그대로)로 자동 대체한다 — 즉 아무것도 건드리지 않으면
    지금까지와 완전히 동일하게 동작한다.
  - **서버를 재시작할 필요 없다.** `main.py`의 `ws_unified()`가 새 WebSocket
    연결이 들어올 때마다 `load_scenarios()`를 새로 호출하므로, yaml을 고친 뒤
    세션을 다시 시작(재연결)하기만 하면 반영된다. `POST /api/scenarios/reload`가
    이 "재연결"을 대신 트리거해주는 버튼용 엔드포인트다 — 현재 연결된 세션이
    있으면 끊어서, 사용자가 "대화 시작"을 다시 누르면 새 지침이 적용되게 한다.
- **`persona.py`** — 시스템 프롬프트(지침) 조립.
  - `PERSONA_BASE`: 동행이의 기본 정체성/말투/제약(팔다리 없음 등). 이 부분은
    시나리오와 무관하게 고정이다.
  - `build_unified_persona(scenarios)`: `PERSONA_BASE` + 넘겨받은 시나리오별
    `instructions`를 번호 매겨 이어 붙인 문자열을 반환한다. 일부러 모듈
    임포트 시점에 한 번만 계산해두지 않는다 — `main.py`가 매 연결마다
    `load_scenarios()` 결과를 새로 넘겨줘야 yaml 수정이 반영되기 때문이다.
- **`tools.py`** — Gemini Live에 등록하는 tool(function calling) 정의.
  - `NOTIFY_CAREGIVER_TOOL`: 함수 스키마(`function_declarations`).
  - `notify_caregiver()`: 실제 실행 로직. 지금은 로그만 남기는 스텁이다.
- **`static/`** — 브라우저에서 동작하는 프론트엔드 JS. `main.py`가
  `/agent-static/`로 서빙한다(`static/unified.html`이 여기서 로드).
  - `gemini-client.js`: 서버 WebSocket(`/ws/unified`)과 통신.
  - `media-handler.js`: 웹캠/마이크 캡처, PCM 인코딩.
  - `pcm-processor.js`: AudioWorklet(오디오 스트리밍용 프로세서).

## 왜 나뉘어 있나

`main.py`는 라우팅·세션 생명주기 같은 서버 로직만 담당하고, "에이전트가 뭘
알고 있고 뭘 할 수 있는지"(페르소나·tool)는 여기 `agent/`에 둬서 분리했다.
그중 시나리오 지침(`scenarios/*.yaml`)은 이미 코드 밖 데이터로 뺐고, tool
정의(`tools.py`)는 아직 Python 상수다. 향후 사용자별로 tool까지 설정 데이터로
빼서 관리하는 방향(README 루트의 "다음 단계" 참고)을 고려해 이 경계를 미리
잡아둔 것이다.
