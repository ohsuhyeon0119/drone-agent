import { useCallback, useEffect, useRef, useState } from "react";

/* 노트북 카메라·마이크를 에이전트에 직접 연결한다.
   휴대폰이나 드론이 없어도 관리 화면만으로 전체 동작(감지 + 대화)을 볼 수 있다.

   미디어 처리(마이크 다운샘플링, 워크릿, 재생 스케줄링)는 에이전트가 이미 쓰는
   /agent-static/media-handler.js를 그대로 불러온다. 콘솔에 복사해두면 한쪽만
   고쳐졌을 때 오디오가 조용히 깨진다 — 소리는 눈에 보이지 않아 늦게 발견된다. */

const HANDLER_URL = "/agent-static/media-handler.js";

/* 코드를 받아서 클래스를 직접 꺼내온다.
   <script> 태그로 넣으면 `class MediaHandler`가 전역 렉시컬 스코프에만 잡혀
   window에 붙지 않는다(var와 다르다). 그래서 window.MediaHandler는 undefined다.
   한 번 받으면 캐시해서 화면을 오갈 때마다 다시 받지 않는다. */
let handlerLoading = null;
function loadMediaHandler() {
  if (!handlerLoading) {
    handlerLoading = fetch(HANDLER_URL)
      .then((r) => {
        if (!r.ok) throw new Error(`미디어 처리 코드를 불러오지 못했습니다 (${r.status})`);
        return r.text();
      })
      .then((src) => new Function(`${src}\nreturn MediaHandler;`)())
      .catch((e) => { handlerLoading = null; throw e; });
  }
  return handlerLoading;
}

/**
 * @param {object} opts
 * @param {number} opts.agentId 어느 어르신의 에이전트인지. 빠지면 1번으로 붙어
 *   내 계정의 설정·프로필이 아니라 남의 것으로 돌고, 모니터에도 안 보인다.
 * @param {boolean} opts.withAudio 마이크·스피커까지 쓸지 (false면 카메라만)
 */
export function useLocalDevice({ agentId, withAudio = true } = {}) {
  const [state, setState] = useState("idle"); // idle | starting | live | error
  const [error, setError] = useState("");
  const videoRef = useRef(null);
  const handlerRef = useRef(null);
  const wsRef = useRef(null);
  /* 정리 중에 onclose가 다시 stop을 부르는 것을 막는다 */
  const stopping = useRef(false);

  const stop = useCallback(() => {
    stopping.current = true;
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && ws.readyState <= 1) ws.close();

    const h = handlerRef.current;
    if (h) {
      try { h.stopAudio(); } catch { /* 이미 정리됨 */ }
      try { h.stopAudioPlayback(); } catch { /* 이미 정리됨 */ }
      try { h.stopVideo(videoRef.current); } catch { /* 이미 정리됨 */ }
    }
    setState("idle");
    stopping.current = false;
  }, []);

  const start = useCallback(async () => {
    setError("");
    setState("starting");
    try {
      const MediaHandler = await loadMediaHandler();
      if (!handlerRef.current) handlerRef.current = new MediaHandler();
      const h = handlerRef.current;

      /* 오디오 컨텍스트는 사용자의 클릭 안에서 열어야 브라우저가 막지 않는다 */
      if (withAudio) await h.initializeAudio();

      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const query = agentId ? `?agent=${encodeURIComponent(agentId)}` : "";
      const ws = new WebSocket(`${proto}//${location.host}/ws/unified${query}`);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = async () => {
        try {
          await h.startVideo(videoRef.current, (base64) => {
            if (ws.readyState === 1) ws.send(JSON.stringify({ type: "image", data: base64 }));
          });
          if (withAudio) {
            await h.startAudio((pcm) => {
              if (ws.readyState === 1) ws.send(pcm);
            });
          }
          setState("live");
        } catch (e) {
          setError(e.message || "카메라·마이크를 열지 못했습니다.");
          setState("error");
          stop();
        }
      };

      ws.onmessage = (msg) => {
        // 동행이의 목소리는 바이너리로 온다
        if (msg.data instanceof ArrayBuffer) {
          if (withAudio) h.playAudio(msg.data);
          return;
        }
        try {
          const data = JSON.parse(msg.data);
          /* 어르신이 말을 시작하면 하던 말을 멈춘다 — 겹쳐 들리면 둘 다 안 들린다 */
          if (data.type === "interrupted" && withAudio) h.stopAudioPlayback();
        } catch { /* 형식이 다른 메시지는 모니터 채널이 따로 받는다 */ }
      };

      ws.onerror = () => {
        if (stopping.current) return;
        setError("에이전트에 연결하지 못했습니다.");
        setState("error");
      };
      ws.onclose = () => {
        if (stopping.current) return;
        setState((s) => (s === "error" ? s : "idle"));
      };
    } catch (e) {
      setError(e.message || "시작하지 못했습니다.");
      setState("error");
    }
  }, [agentId, withAudio, stop]);

  // 화면을 떠날 때 카메라·마이크를 반드시 끈다 (표시등이 켜진 채 남으면 안 된다)
  useEffect(() => () => stop(), [stop]);

  return { videoRef, state, error, start, stop };
}
