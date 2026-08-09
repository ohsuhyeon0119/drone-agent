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
/* 카메라·마이크 권한을 한 번에 물어본다.
   media-handler는 영상과 소리를 따로 요청하는데, 그러면 허용 창이 두 번 뜬다.
   두 번째(마이크)를 놓치거나 닫으면 "카메라는 되는데 마이크만 안 되는" 상태가
   되고, 화면에는 아무 설명도 남지 않는다. */
async function requestPermission(withAudio) {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: true, audio: withAudio,
  });
  stream.getTracks().forEach((t) => t.stop());
}

function permissionMessage(e) {
  switch (e?.name) {
    case "NotAllowedError":
      return "카메라·마이크 사용이 차단되어 있습니다. 주소창 왼쪽의 자물쇠를 눌러 허용해 주세요.";
    case "NotFoundError":
      return "카메라나 마이크를 찾지 못했습니다. 연결 상태를 확인해 주세요.";
    case "NotReadableError":
      return "다른 프로그램이 카메라·마이크를 쓰고 있습니다. 그 프로그램을 끄고 다시 시도해 주세요.";
    default:
      return e?.message || "카메라·마이크를 열지 못했습니다.";
  }
}

export function useLocalDevice({ agentId, withAudio = true } = {}) {
  const [state, setState] = useState("idle"); // idle | starting | live | error
  const [error, setError] = useState("");
  /* 마이크가 실제로 소리를 받고 있는지 눈으로 확인할 수 있게 한다.
     소리는 보이지 않아서, 표시가 없으면 안 되는 건지 조용한 건지 알 수 없다. */
  const [micLevel, setMicLevel] = useState(0);
  const [micOn, setMicOn] = useState(false);
  const videoRef = useRef(null);
  const handlerRef = useRef(null);
  const wsRef = useRef(null);
  const meterRef = useRef(null);
  /* 정리 중에 onclose가 다시 stop을 부르는 것을 막는다 */
  const stopping = useRef(false);

  const stop = useCallback(() => {
    stopping.current = true;
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && ws.readyState <= 1) ws.close();

    if (meterRef.current) { cancelAnimationFrame(meterRef.current); meterRef.current = null; }
    setMicLevel(0);
    setMicOn(false);

    const h = handlerRef.current;
    if (h) {
      try { h.stopAudio(); } catch { /* 이미 정리됨 */ }
      try { h.stopAudioPlayback(); } catch { /* 이미 정리됨 */ }
      try { h.stopVideo(videoRef.current); } catch { /* 이미 정리됨 */ }
    }
    setState("idle");
    stopping.current = false;
  }, []);

  /* 마이크가 실제로 소리를 받고 있는지 화면에 보여준다.
     보내는 쪽에서 조용히 실패하면 "말했는데 반응이 없다"는 것만 남고 원인을
     알 수 없다. 입력 크기를 그리면 마이크 문제인지 그 뒤 문제인지 갈린다. */
  const startMeter = useCallback((h) => {
    if (!h.audioContext || !h.mediaStream) return;
    const analyser = h.audioContext.createAnalyser();
    analyser.fftSize = 512;
    h.audioContext.createMediaStreamSource(h.mediaStream).connect(analyser);
    const buf = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteTimeDomainData(buf);
      let peak = 0;
      for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
      setMicLevel(Math.min(1, peak / 40)); // 말소리 크기에서 눈에 띄게
      meterRef.current = requestAnimationFrame(tick);
    };
    setMicOn(true);
    tick();
  }, []);

  const start = useCallback(async () => {
    setError("");
    setState("starting");
    try {
      const MediaHandler = await loadMediaHandler();
      if (!handlerRef.current) handlerRef.current = new MediaHandler();
      const h = handlerRef.current;

      /* 허용 창을 한 번만 띄운다. 뒤에서 영상·소리를 따로 요청하지만 이미
         허용된 뒤라 다시 묻지 않는다. */
      try {
        await requestPermission(withAudio);
      } catch (e) {
        setError(permissionMessage(e));
        setState("error");
        return;
      }

      /* 오디오 컨텍스트는 사용자의 클릭 안에서 열어야 브라우저가 막지 않는다 */
      if (withAudio) await h.initializeAudio();

      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const query = agentId ? `?agent=${encodeURIComponent(agentId)}` : "";
      const ws = new WebSocket(`${proto}//${location.host}/ws/unified${query}`);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = async () => {
        try {
          /* 마이크를 먼저 연다. 카메라부터 열면 그 사이 한 말이 통째로 빠지는데,
             쓰는 사람은 "시작을 눌렀으니 듣고 있겠지" 하고 바로 말을 건다. */
          if (withAudio) {
            try {
              await h.startAudio((pcm) => {
                if (ws.readyState === 1) ws.send(pcm);
              });
              startMeter(h);
            } catch (e) {
              /* 마이크만 실패했다고 카메라까지 끄지 않는다. 감지는 계속 돌아야
                 하고, 무엇이 안 되는지도 화면에 남아야 한다. */
              setError(`${permissionMessage(e)} (소리 없이 감지만 동작합니다)`);
            }
          }
          await h.startVideo(videoRef.current, (base64) => {
            if (ws.readyState === 1) ws.send(JSON.stringify({ type: "image", data: base64 }));
          });
          setState("live");
        } catch (e) {
          setError(permissionMessage(e));
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
  }, [agentId, withAudio, stop, startMeter]);

  // 화면을 떠날 때 카메라·마이크를 반드시 끈다 (표시등이 켜진 채 남으면 안 된다)
  useEffect(() => () => stop(), [stop]);

  return { videoRef, state, error, micOn, micLevel, start, stop };
}
