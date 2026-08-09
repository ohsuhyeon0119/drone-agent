import { useEffect, useRef, useState } from "react";
import { getToken } from "../api.js";
import { useAuth } from "../auth.jsx";
import { useLocalDevice } from "../useLocalDevice.js";

/* 카메라가 보고 있는 화면과 그 사이 일어난 일을 함께 본다.
   읽기 전용이다 — 이 화면을 열어둔 것이 어르신과의 대화에 영향을 주지 않는다. */

const MAX_LOG = 200;

/* 이벤트를 사람이 읽을 수 있는 한 줄로 바꾼다. 화면에 필요한 건 "무슨 일이
   있었나"이지 이벤트 타입 이름이 아니다. */
function describe(e) {
  switch (e.type) {
    case "session":
      return e.state === "started"
        ? { tone: "info", title: "대화 시작", body: "기기가 연결되었습니다." }
        : { tone: "info", title: "대화 종료", body: "기기 연결이 끊겼습니다." };
    case "detect_result":
      if (!e.ok) return { tone: "warn", title: `${e.label} 판단 실패`, body: e.error };
      /* 감지되지 않은 판정이 대부분이라, 이것까지 강조하면 정작 중요한 게 묻힌다.
         흐리게 남겨 카메라가 살아 있다는 것만 보이게 한다. */
      /* 시나리오 이름이 이미 "낙상 감지"라서 뒤에 "감지"를 또 붙이면 말이 겹친다.
         이름은 그대로 두고, 감지 여부는 색과 본문으로 구분한다. */
      return e.event && e.event !== "none"
        ? { tone: "hit", title: e.label,
            body: `감지됨 — ${e.reason || ""} (확신도 ${fmt(e.confidence)})` }
        : { tone: "idle", title: e.label, body: `해당 없음 (${fmt(e.confidence)})` };
    case "alert":
      return { tone: "alert", title: "경보", body: e.message };
    case "system_nudge":
      return { tone: "nudge", title: "동행이에게 신호 전달", body: e.text };
    case "tool_result":
      return { tone: "tool", title: `행동 실행 · ${e.tool || e.name || ""}`,
               body: e.message || e.result || JSON.stringify(e) };
    case "memory_update":
      return { tone: "tool", title: "기록 남김", body: e.message };
    case "user":
      return e.text ? { tone: "user", title: "어르신", body: e.text } : null;
    case "gemini":
      return e.text ? { tone: "agent", title: "동행이", body: e.text } : null;
    default:
      return null; // 화면에 뜻이 없는 이벤트는 로그에 남기지 않는다
  }
}

function fmt(v) {
  return typeof v === "number" ? v.toFixed(2) : "—";
}

const TONE = {
  info: "border-line text-muted",
  idle: "border-line text-muted/70",
  hit: "border-accent text-ink",
  alert: "border-warn text-warn",
  nudge: "border-accent text-accent",
  tool: "border-accent/50 text-ink",
  user: "border-line text-ink",
  agent: "border-accent/50 text-ink",
  warn: "border-warn text-warn",
};

export default function Monitor() {
  const [status, setStatus] = useState({ connected: false });
  const [linkState, setLinkState] = useState("connecting"); // connecting | open | closed
  const [log, setLog] = useState([]);
  const [frameUrl, setFrameUrl] = useState("");
  const frameUrlRef = useRef("");
  /* 어디를 카메라로 쓸지. 휴대폰이 기본이고, 노트북은 기기가 없을 때
     관리 화면만으로 전체 동작을 확인하기 위한 것이다. */
  const [source, setSource] = useState("phone");
  const { user } = useAuth();
  const laptop = useLocalDevice({ agentId: user?.agentId, withAudio: true });

  const switchSource = (next) => {
    if (next === source) return;
    // 두 곳에서 동시에 보내면 프레임이 뒤섞인다 — 옮길 때 반드시 먼저 끈다
    if (source === "laptop") laptop.stop();
    setSource(next);
  };

  useEffect(() => {
    /* 서버가 재시작되거나 잠깐 끊겨도 화면이 죽은 채로 남지 않게 다시 붙는다.
       모니터링은 켜두고 보는 화면이라, 한 번 끊겼다고 새로고침을 요구하면
       정작 봐야 할 순간을 놓친다. */
    let ws = null;
    let retry = null;
    let closed = false;
    let delay = 1000;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(
        `${proto}//${location.host}/ws/monitor?token=${encodeURIComponent(getToken())}`
      );
      ws.binaryType = "blob";

      ws.onopen = () => { setLinkState("open"); delay = 1000; };
      const reconnect = () => {
        if (closed) return;
        setLinkState("closed");
        // 서버가 죽어 있을 때 초당 한 번씩 두드리지 않도록 간격을 늘린다
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 10000);
      };
      ws.onclose = reconnect;
      ws.onerror = () => { try { ws.close(); } catch { /* 이미 닫힘 */ } };

      ws.onmessage = onMessage;
    };

    const onMessage = (msg) => {
      // 영상은 바이너리, 나머지는 JSON — 프레임을 base64로 감싸면 33% 커진다
      if (msg.data instanceof Blob) {
        const url = URL.createObjectURL(msg.data);
        /* 이전 프레임의 objectURL은 반드시 풀어줘야 한다. 초당 2장씩 쌓이면
           몇 분 만에 수백 MB가 잡힌 채 회수되지 않는다. */
        if (frameUrlRef.current) URL.revokeObjectURL(frameUrlRef.current);
        frameUrlRef.current = url;
        setFrameUrl(url);
        return;
      }
      const data = JSON.parse(msg.data);
      if (data.type === "init") {
        setStatus(data.status || { connected: false });
        setLog(buildRows(data.events));
      } else if (data.type === "event") {
        if (data.event?.type === "session") {
          setStatus({ connected: data.event.state === "started" });
        }
        const row = toRow(data.event);
        if (row) setLog((prev) => appendRow(prev, row));
      }
    };

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      if (ws) ws.close();
      if (frameUrlRef.current) URL.revokeObjectURL(frameUrlRef.current);
    };
  }, []);

  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-4 mb-7">
        <div>
          <h1 className="text-[49px] font-bold">모니터링</h1>
          <p className="text-muted mt-2 text-[26px]">
            카메라가 보고 있는 화면과 그 사이 일어난 일입니다.
          </p>
        </div>
        <StatusPill connected={status.connected} link={linkState} />
      </header>

      <SourcePicker source={source} onChange={switchSource} laptop={laptop} />

      <div className="grid grid-cols-1 xl:grid-cols-[1.35fr_1fr] gap-6 items-start">
        <section className="bg-ink rounded-(--radius-card) overflow-hidden">
          <div className="aspect-video w-full flex items-center justify-center relative">
            {/* 노트북일 때는 내 화면을 그대로 보여준다 — 서버를 한 바퀴 돌아온
                초당 2장짜리보다 훨씬 부드럽고, 각도를 맞추기도 쉽다. */}
            <video
              ref={laptop.videoRef}
              autoPlay
              playsInline
              muted
              className={`w-full h-full object-contain ${source === "laptop" ? "" : "hidden"}`}
            />
            {source === "phone" && (frameUrl ? (
              <img src={frameUrl} alt="카메라 화면" className="w-full h-full object-contain" />
            ) : (
              <p className="text-white/55 text-[24px] text-center px-8">
                {status.connected
                  ? "영상이 아직 들어오지 않았습니다."
                  : "휴대폰이 연결되면 여기에 화면이 보입니다."}
              </p>
            ))}
            {source === "laptop" && laptop.state !== "live" && (
              <p className="absolute text-white/55 text-[24px] text-center px-8">
                {laptop.state === "starting" ? "카메라를 켜는 중…" : "‘시작’을 누르면 이 화면이 동행이에게 전달됩니다."}
              </p>
            )}
          </div>
        </section>

        <section className="bg-surface border border-line rounded-(--radius-card) flex flex-col
                            h-[clamp(420px,62vh,760px)]">
          <div className="flex-none flex items-baseline justify-between px-6 py-4 border-b border-line">
            <h2 className="text-[28px] font-bold">로그</h2>
            <span className="text-[19px] text-muted tabular-nums">{log.length}건</span>
          </div>
          <ol className="flex-1 min-h-0 overflow-y-auto px-6 py-4 flex flex-col gap-3">
            {log.length === 0 && (
              <li className="text-muted text-[22px] py-6 text-center">아직 기록이 없습니다.</li>
            )}
            {log.map((row) => (
              <li key={row.id} className={`border-l-[3px] pl-4 ${TONE[row.tone] || TONE.info}`}>
                <div className="flex items-baseline gap-3">
                  <span className="font-bold text-[22px]">{row.title}</span>
                  <span className="text-[18px] text-muted tabular-nums ml-auto">{row.ts}</span>
                </div>
                {row.body && (
                  <p className="text-[20px] leading-relaxed break-words">{row.body}</p>
                )}
              </li>
            ))}
          </ol>
        </section>
      </div>
    </>
  );
}

const SOURCES = [
  { key: "laptop", label: "내 노트북", desc: "이 컴퓨터의 카메라와 마이크로 직접 대화합니다" },
  { key: "phone", label: "연결된 휴대폰", desc: "휴대폰이 보내는 화면을 지켜봅니다" },
];

function SourcePicker({ source, onChange, laptop }) {
  return (
    <section className="mb-6 bg-surface border border-line rounded-(--radius-card) px-6 py-5">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
        <span className="text-[24px] font-bold">카메라</span>
        <div className="flex flex-wrap gap-3">
          {SOURCES.map((s, i) => (
            <button
              key={s.key}
              onClick={() => onChange(s.key)}
              title={s.desc}
              className={`px-6 py-3 rounded-full text-[23px] font-bold cursor-pointer border-2
                transition-colors duration-150
                ${source === s.key
                  ? "border-accent bg-accentsoft text-accent"
                  : "border-line bg-surface text-muted hover:text-ink"}`}
            >
              {i + 1}. {s.label}
            </button>
          ))}
        </div>

        {source === "laptop" && (
          <div className="flex items-center gap-4 ml-auto">
            {laptop.state === "live" ? (
              <button
                onClick={laptop.stop}
                className="h-14 px-6 rounded-(--radius-ctl) border border-warn/40 text-warn bg-surface
                           hover:bg-warnsoft text-[24px] font-bold cursor-pointer"
              >
                중지
              </button>
            ) : (
              <button
                onClick={laptop.start}
                disabled={laptop.state === "starting"}
                className="h-14 px-6 rounded-(--radius-ctl) bg-accent text-white text-[24px] font-bold
                           cursor-pointer disabled:opacity-40"
              >
                {laptop.state === "starting" ? "여는 중…" : "시작"}
              </button>
            )}
          </div>
        )}
      </div>

      <p className="text-muted text-[21px] mt-3">
        {source === "laptop"
          ? "이 컴퓨터의 카메라·마이크가 동행이에게 연결됩니다. 말을 걸면 대답하고, 낙상·복약 감지도 함께 돕니다."
          : "휴대폰이 보내는 화면을 지켜보기만 합니다. 이 화면에서 말을 걸 수는 없습니다."}
      </p>
      {laptop.error && source === "laptop" && (
        <p role="alert" className="text-warn text-[22px] mt-2">{laptop.error}</p>
      )}
    </section>
  );
}

function StatusPill({ connected, link }) {
  /* 두 가지를 구분해야 한다 — 콘솔이 서버에 못 붙은 것과, 서버는 붙었는데
     기기가 아직 대화를 시작하지 않은 것. 원인이 다르므로 할 일도 다르다. */
  const state = link !== "open"
    ? { label: "콘솔 연결 끊김", cls: "bg-warnsoft text-warn" }
    : connected
      ? { label: "기기 연결됨", cls: "bg-accentsoft text-accent" }
      : { label: "기기 대기 중", cls: "bg-bg text-muted border border-line" };
  return (
    <span className={`inline-flex items-center gap-2.5 px-5 py-2.5 rounded-full text-[22px] font-bold ${state.cls}`}>
      <span className={`w-2.5 h-2.5 rounded-full ${link === "open" && connected ? "bg-accent" : "bg-current opacity-50"}`} />
      {state.label}
    </span>
  );
}

let seq = 0;
function toRow(event) {
  const d = describe(event);
  if (!d) return null;
  return { id: `${event.ts}-${seq++}`, ts: event.ts, ...d };
}

const SPEECH = new Set(["user", "agent"]);
const MAX_BODY = 600;

/* 모델의 말은 토큰 단위로 쪼개져 도착한다("혹시", "직접", "움직이실"…).
   그대로 한 줄씩 쌓으면 로그가 조각으로 뒤덮여 정작 감지·경보가 묻힌다.
   같은 화자의 연속된 말은 한 줄로 이어 붙인다. */
function appendRow(prev, row) {
  const head = prev[0];
  if (head && SPEECH.has(row.tone) && head.tone === row.tone && head.title === row.title) {
    const body = `${head.body} ${row.body}`.trim().slice(-MAX_BODY);
    return [{ ...head, ts: row.ts, body }, ...prev.slice(1)];
  }
  return [row, ...prev].slice(0, MAX_LOG);
}

function buildRows(events) {
  return (events || []).reduce((acc, e) => {
    const row = toRow(e);
    return row ? appendRow(acc, row) : acc;
  }, []);
}
