import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { answerInterview, finishInterview, startInterview } from "../api.js";

/* 로그인 직후 한 번 진행하는 온보딩.
   한 화면에 질문 하나만 두고, 고르면 바로 다음으로 넘어간다. 스크롤이 생기면
   선택지가 화면 밖으로 밀려 "다음에 뭘 해야 하는지"가 사라지므로, 이 흐름에서는
   화면을 절대 넘기지 않는 것을 제약으로 둔다.

   그래서 여기서는 콘솔의 기준 글자 크기(26px)에 기대지 않고 px를 직접 쓴다 —
   rem 기반 유틸리티는 이 기준에서 여백 하나가 30~130px이 되어 4지선다를 한
   화면에 담을 수 없다.

   질문·되묻기·순서는 서버(agent/interviewer.py)가 정한다. 화면은 받은 질문을
   그리고 답을 돌려줄 뿐이다. 설계 근거는 personalization.plan.md §3. */

function ProgressBar({ value }) {
  return (
    <div className="h-[3px] w-full bg-line flex-none">
      <div
        className="h-full bg-accent transition-[width] duration-300 ease-out"
        style={{ width: `${Math.min(100, Math.round(value * 100))}%` }}
      />
    </div>
  );
}

function TopBar({ onBack, onQuit, canGoBack }) {
  return (
    <div className="flex-none h-[64px] flex items-center justify-between">
      <button
        onClick={onBack}
        disabled={!canGoBack}
        aria-label="이전 질문"
        className="w-[44px] h-[44px] -ml-[10px] flex items-center justify-center rounded-full
                   text-ink disabled:opacity-25 cursor-pointer disabled:cursor-default"
      >
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m15 18-6-6 6-6" />
        </svg>
      </button>
      <button
        onClick={onQuit}
        className="text-[17px] text-muted hover:text-ink cursor-pointer px-2 py-1"
      >
        나중에 할게요
      </button>
    </div>
  );
}

/* 선택지 — 누르는 즉시 다음 질문으로 넘어간다.
   "선택 후 다음 버튼"은 탭이 두 번 필요해서, 12개 질문이면 12번을 더 누르게 된다. */
function Choice({ label, onPick, disabled, picked }) {
  return (
    <button
      onClick={() => onPick(label)}
      disabled={disabled}
      className={`w-full text-left px-[22px] py-[19px] rounded-[16px] border-2 text-[21px] font-semibold
                  transition-[background-color,border-color,transform] duration-150 cursor-pointer
                  active:scale-[0.985] disabled:cursor-default
                  ${picked
                    ? "border-accent bg-accentsoft text-accent"
                    : "border-line bg-surface text-ink hover:border-accent/60 disabled:opacity-50"}`}
    >
      {label}
    </button>
  );
}

const SUMMARY_ROWS = [
  ["연세", (p) => (p.birth_year ? `${new Date().getFullYear() - p.birth_year + 1}세` : "")],
  ["호칭", (p) => p.address_as],
  ["지내시는 형태", (p) => (p.lives_alone ? "혼자 지내심" : "")],
  ["듣는 것", (p) => p.hearing],
  ["거동", (p) => p.mobility],
  ["기억", (p) => p.memory],
  ["말수", (p) => p.talkativeness],
  ["도움받는 것", (p) => p.help_attitude],
  ["최근 1년 낙상", (p) => (p.fall_history ? "있음" : "")],
  ["조심할 곳", (p) => (p.risk_places || []).join(", ")],
  ["좋아하시는 것", (p) => (p.interests || []).join(", ")],
];

/* 확인 화면만은 내용이 길어질 수 있어 예외로 안쪽 스크롤을 허용한다.
   대신 CTA는 항상 화면 아래에 붙여, 스크롤을 못 봐도 다음으로 갈 수 있게 한다. */
function Summary({ profile, onConfirm, onRedo, busy }) {
  const rows = SUMMARY_ROWS.map(([label, get]) => [label, get(profile)]).filter(([, v]) => v);
  return (
    <div className="h-screen flex flex-col overflow-hidden max-w-[560px] mx-auto px-[24px]">
      <div className="flex-none pt-[40px] pb-[20px]">
        <h1 className="text-[32px] font-bold leading-[1.3] [text-wrap:balance]">
          {profile.name ? `${profile.name} 어르신을` : "어르신을"}<br />이렇게 이해했어요
        </h1>
        <p className="text-[17px] text-muted mt-[10px]">
          동행이가 이 내용을 바탕으로 말을 겁니다.
        </p>
      </div>

      {/* 이 화면만 안쪽 스크롤을 허용하므로, 아래가 잘린 게 아니라 더 있다는 걸
          보이게 한다 — 끝인 줄 알고 넘어가면 확인하라고 만든 화면이 무의미해진다. */}
      <div className="relative flex-1 min-h-0">
        <div className="h-full overflow-y-auto -mx-[4px] px-[4px] pb-[18px]">
          <dl className="bg-surface border border-line rounded-[16px] divide-y divide-line">
            {rows.map(([label, value]) => (
              <div key={label} className="flex items-baseline gap-[16px] px-[20px] py-[13px]">
                <dt className="w-[124px] flex-none text-[16px] text-muted">{label}</dt>
                <dd className="text-[19px] font-semibold">{value}</dd>
              </div>
            ))}
          </dl>

        {(profile.notes || []).length > 0 && (
          <div className="mt-[12px] bg-accentsoft rounded-[16px] px-[20px] py-[16px]">
            <p className="text-[16px] font-bold text-accent mb-[8px]">특별히 신경 쓸 점</p>
            <ul className="flex flex-col gap-[8px]">
              {profile.notes.map((n, i) => (
                <li key={i} className="text-[17px] leading-[1.55]">{n}</li>
              ))}
            </ul>
          </div>
        )}

          {(profile.unknown || []).length > 0 && (
            <p className="text-[15px] text-muted mt-[12px] mb-[4px]">
              알려주지 않으신 {profile.unknown.length}개는 비워 두었습니다. 나중에 채우셔도 됩니다.
            </p>
          )}
        </div>
        {/* 목록이 화면보다 길 때만 아래쪽을 흐리게 해 "더 있다"는 신호를 준다 */}
        <div className="pointer-events-none absolute bottom-0 inset-x-0 h-[28px]
                        bg-gradient-to-t from-bg to-transparent" />
      </div>

      <div className="flex-none pt-[16px] pb-[28px] flex flex-col gap-[10px]">
        <button
          onClick={onConfirm}
          disabled={busy}
          className="w-full h-[60px] rounded-[16px] bg-accent text-white text-[20px] font-bold
                     cursor-pointer disabled:opacity-40 active:scale-[0.99] transition-transform"
        >
          {busy ? "저장 중…" : "네, 맞아요"}
        </button>
        <button onClick={onRedo} className="w-full h-[46px] text-[17px] text-muted cursor-pointer">
          다시 알려줄게요
        </button>
      </div>
    </div>
  );
}

export default function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState("intro"); // intro | question | done
  const [greeting, setGreeting] = useState("");
  const [current, setCurrent] = useState(null);
  const [answers, setAnswers] = useState({});
  const [history, setHistory] = useState([]); // 뒤로 가기용 (current, answers) 스냅샷
  const [text, setText] = useState("");
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [profile, setProfile] = useState(null);
  const inputRef = useRef(null);
  /* busy는 state라 setBusy(true) 직후 리렌더 전까지는 아직 false다. 그 틈에 한 번
     더 누르면 같은 답이 두 번 전송되면서 질문이 어긋난다. ref는 즉시 바뀐다. */
  const sending = useRef(false);

  useEffect(() => {
    startInterview()
      .then((data) => { setGreeting(data.greeting); setCurrent(data); })
      .catch((e) => setError(e.message));
  }, []);

  // 글자로 답하는 질문에서는 바로 입력할 수 있게 한다
  useEffect(() => {
    if (step === "question" && current && !(current.options || []).length) {
      inputRef.current?.focus();
    }
  }, [step, current]);

  const send = async (value) => {
    const said = (value ?? text).trim();
    if (!said || sending.current || !current) return;
    sending.current = true;
    setPicked(value ?? "");
    setBusy(true);
    setError("");
    try {
      const next = await answerInterview({
        answers,
        slot: current.slot,
        text: said,
        followup_key: current.followup_key || "",
      });
      setHistory((h) => [...h, { current, answers }]);
      setAnswers(next.answers || {});
      setText("");
      if (next.done) {
        const result = await finishInterview(next.answers || {});
        setProfile(result.profile);
        setStep("done");
      } else {
        setCurrent(next);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setPicked("");
      sending.current = false;
      setBusy(false);
    }
  };

  const back = () => {
    if (!history.length || sending.current) return;
    const prev = history[history.length - 1];
    setHistory((h) => h.slice(0, -1));
    setCurrent(prev.current);
    setAnswers(prev.answers);
    setText("");
    setError("");
  };

  const quit = async () => {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    try {
      const result = await finishInterview(answers);
      setProfile(result.profile);
      setStep("done");
    } catch (e) {
      setError(e.message);
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };

  const restart = () => {
    setProfile(null); setAnswers({}); setHistory([]); setText("");
    setStep("intro"); setError("");
    startInterview().then((d) => { setGreeting(d.greeting); setCurrent(d); });
  };

  if (step === "done" && profile) {
    return (
      <Summary
        profile={profile}
        busy={busy}
        onRedo={restart}
        onConfirm={() => navigate("/scenarios", { replace: true })}
      />
    );
  }

  if (step === "intro") {
    return (
      <div className="h-screen flex flex-col overflow-hidden max-w-[560px] mx-auto px-[24px]">
        <div className="flex-1 min-h-0 flex flex-col justify-center">
          <div className="text-[19px] font-bold tracking-[0.2em] text-accent mb-[20px]">
            DONGHAENG
          </div>
          <h1 className="text-[34px] font-bold leading-[1.32] [text-wrap:balance]">
            어르신에 대해<br />몇 가지만 여쭤볼게요
          </h1>
          <p className="text-[18px] text-muted mt-[16px] leading-[1.6]">
            {greeting
              ? "3분이면 됩니다. 모르시는 건 '모르겠어요'를 고르셔도 되고, 언제든 그만두셔도 됩니다."
              : "준비 중…"}
          </p>
        </div>
        <div className="flex-none pb-[28px]">
          {error && <p role="alert" className="text-warn text-[17px] mb-[12px]">{error}</p>}
          <button
            onClick={() => setStep("question")}
            disabled={!current}
            className="w-full h-[60px] rounded-[16px] bg-accent text-white text-[20px] font-bold
                       cursor-pointer disabled:opacity-40 active:scale-[0.99] transition-transform"
          >
            시작하기
          </button>
        </div>
      </div>
    );
  }

  const options = current?.options || [];
  /* 선택지와 입력은 배타적이지 않다. "넘어지실까 걱정되는 곳" 같은 질문은
     장소를 적어야 하는데 선택지("딱히 없어요")는 빠져나갈 지름길일 뿐이라,
     둘 중 하나만 그리면 답할 방법이 사라진다. */
  const showText = current?.allow_text ?? options.length === 0;
  const total = current?.progress?.total ?? 12;
  const filled = current?.progress?.filled ?? 0;

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <ProgressBar value={total ? filled / total : 0} />
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden max-w-[560px] w-full mx-auto px-[24px]">
        <TopBar onBack={back} onQuit={quit} canGoBack={history.length > 0} />

        {/* 질문과 선택지를 한 덩어리로 묶어 화면 가운데에 둔다.
            위에 붙이면 선택지 아래로 빈 공간이 크게 남아 화면이 비어 보인다. */}
        <div className="flex-1 min-h-0 flex flex-col justify-center overflow-hidden">
          <div className="flex-none pb-[28px]">
            <h1 className="text-[30px] font-bold leading-[1.35] [text-wrap:balance]">
              {current?.question}
            </h1>
            {current?.hint && (
              <p className="text-[17px] text-muted mt-[10px]">{current.hint}</p>
            )}
          </div>

          <div className="flex-none flex flex-col gap-[10px]">
          {showText && (
            <input
              ref={inputRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") send(); }}
              disabled={busy}
              placeholder="여기에 입력해 주세요"
              className="w-full h-[64px] flex-none px-[20px] rounded-[16px] border-2 border-line
                         bg-surface text-[22px] focus:border-accent placeholder:text-muted/50"
            />
          )}
          {options.map((opt) => (
            <Choice
              key={opt}
              label={opt}
              onPick={send}
              disabled={busy}
              picked={picked === opt}
            />
          ))}
          </div>
        </div>

        <div className="flex-none pt-[12px] pb-[28px]">
          {error && <p role="alert" className="text-warn text-[17px] mb-[10px]">{error}</p>}
          {showText && (
            <button
              onClick={() => send()}
              disabled={busy || !text.trim()}
              className="w-full h-[60px] rounded-[16px] bg-accent text-white text-[20px] font-bold
                         cursor-pointer disabled:opacity-30 active:scale-[0.99] transition-transform"
            >
              다음
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
