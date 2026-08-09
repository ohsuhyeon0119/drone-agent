import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Button, EmptyState, Modal, Toggle, inputCls } from "../components/ui.jsx";
import { useStore } from "../store.jsx";

function MicIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 19v3" />
    </svg>
  );
}

export default function ScenarioDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const {
    draft, toggleScenario, addInstruction, removeInstruction, updateInstruction,
    setInstructionAction, setDetectPrompt, setCooldown,
    removeScenario, changes,
  } = useStore();
  const scenario = draft.scenarios.find((s) => s.id === id);

  const [modal, setModal] = useState(null); // null | "text" | "voice"
  const [editIdx, setEditIdx] = useState(null); // null = 새 지침, 숫자 = 해당 지침 수정
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const [voiceSupported] = useState(
    () => "webkitSpeechRecognition" in window || "SpeechRecognition" in window,
  );
  const recRef = useRef(null);

  if (!scenario) {
    return (
      <p className="text-muted">
        시나리오를 찾을 수 없어요. <Link className="text-accent" to="/scenarios">목록으로 돌아가기</Link>
      </p>
    );
  }

  const startVoice = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    recRef.current = rec;
    rec.lang = "ko-KR";
    rec.interimResults = false;
    rec.onresult = (e) => {
      setText(e.results[0][0].transcript);
      setListening(false);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    setListening(true);
    rec.start();
  };

  const submit = () => {
    const t = text.trim();
    if (!t) return;
    const finalText = t.endsWith(".") ? t : t + ".";
    if (editIdx !== null) {
      updateInstruction(scenario.id, editIdx, finalText);
    } else {
      addInstruction(scenario.id, finalText);
    }
    setText("");
    setEditIdx(null);
    setModal(null);
  };

  return (
    <>
      <nav className="text-[24px] text-muted mb-4">
        <Link to="/scenarios" className="hover:text-accent">시나리오</Link>
        <span className="mx-2">›</span>
        <span className="text-ink">{scenario.name}</span>
      </nav>

      <header className="flex flex-wrap items-center justify-between gap-4 mb-8">
        <h1 className="text-[49px] font-bold">{scenario.name}</h1>
        <div className="flex items-center gap-3">
          <span className="text-[24px] text-muted">{scenario.enabled ? "감시 중" : "꺼짐"}</span>
          <Toggle
            checked={scenario.enabled}
            onChange={(v) => toggleScenario(scenario.id, v)}
            label={`${scenario.name} ${scenario.enabled ? "끄기" : "켜기"}`}
          />
        </div>
      </header>

      {/* 이 시나리오가 언제 발동하는지 — 지침(대응 방식)과 역할이 다르므로 위에 따로 둔다 */}
      <section className="mb-10 bg-surface border border-line rounded-(--radius-card) px-7 py-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <h2 className="text-[32px] font-bold">감지 조건</h2>
          <div className="flex items-center gap-3">
            <span className="text-[22px] text-muted">몇 초마다 판단할까요</span>
            <select
              aria-label="재판정 간격"
              className="h-14 px-4 text-[24px] rounded-(--radius-ctl) border border-line bg-surface cursor-pointer tabular-nums"
              value={scenario.cooldown ?? 10}
              onChange={(e) => setCooldown(scenario.id, Number(e.target.value))}
            >
              {[5, 10, 15, 30, 60].map((v) => (
                <option key={v} value={v}>{v}초</option>
              ))}
            </select>
          </div>
        </div>
        <p className="text-muted text-[22px] mb-4">
          이 조건에 맞으면 아래 지침대로 대응합니다. 무엇은 감지로 보지 않을지도 함께
          적을수록 오작동이 줄어듭니다.
        </p>
        <textarea
          aria-label="감지 조건"
          className={`${inputCls} h-32 py-4 leading-relaxed resize-none`}
          placeholder={"예: 어르신이 알약이나 약봉투를 입 근처로 가져가는지 판단하세요.\n다음은 감지로 보지 않습니다: 약통만 놓여 있는 경우."}
          value={scenario.detectPrompt || ""}
          onChange={(e) => setDetectPrompt(scenario.id, e.target.value)}
        />
        {scenario.detectPrompt ? (
          /* 실제로 모델에 들어가는 것 중 사람이 손댈 필요 없는 부분 — 뭐가 붙는지는 보여준다 */
          <details className="mt-3">
            <summary className="text-muted text-[20px] cursor-pointer select-none">
              카메라에 실제로 전달되는 전체 문장 보기
            </summary>
            <pre className="mt-2 p-4 rounded-(--radius-ctl) bg-bg border border-line text-[19px] leading-relaxed whitespace-pre-wrap font-sans text-muted">
{scenario.detectPrompt}
{"\n반드시 아래 JSON 형식으로만 답하라, 코드펜스 금지:\n"}
{`{"event": "${scenario.id === "fall" ? "fall" : "taken"}" 또는 "none", "confidence": 0.0~1.0, "reason": "판단 근거를 한 문장으로"}`}
            </pre>
            <p className="text-muted text-[19px] mt-2">
              답변 형식은 자동으로 붙습니다. 위 입력칸에는 조건만 쓰면 됩니다.
            </p>
          </details>
        ) : (
          <p className="text-muted text-[20px] mt-2">
            비워 두면 카메라로 감지하지 않고 대화에만 반응합니다.
          </p>
        )}
      </section>

      <section className="mb-10">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="text-[32px] font-bold">지침</h2>
            <p className="text-muted text-[22px] mt-1">감지된 뒤 동행이가 어떻게 말하고 행동할지</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => { setText(""); setEditIdx(null); setModal("text"); }}>지침 추가</Button>
            <Button
              variant="primary"
              onClick={() => { setText(""); setEditIdx(null); setModal("voice"); }}
            >
              <MicIcon /> 말로 추가
            </Button>
          </div>
        </div>

        {scenario.instructions.length === 0 ? (
          <EmptyState>등록된 지침이 없습니다.</EmptyState>
        ) : (
          <ul className="flex flex-col gap-3">
            {scenario.instructions.map((ins, i) => (
              <li
                key={i}
                className="bg-surface border border-line rounded-(--radius-card) border-l-4 border-l-accent px-7 py-6"
              >
                <div className="flex items-start gap-4">
                  <p className="flex-1 text-[28px] leading-relaxed">{ins.text}</p>
                  <div className="flex flex-none gap-1">
                    <button
                      aria-label="지침 수정"
                      onClick={() => { setText(ins.text); setEditIdx(i); setModal("text"); }}
                      className="w-16 h-16 flex items-center justify-center rounded-(--radius-ctl) text-muted hover:text-accent hover:bg-accentsoft cursor-pointer"
                    >
                      <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                      </svg>
                    </button>
                    <button
                      aria-label="지침 삭제"
                      onClick={() => removeInstruction(scenario.id, i)}
                      className="w-16 h-16 flex items-center justify-center rounded-(--radius-ctl) text-muted hover:text-warn hover:bg-warnsoft cursor-pointer"
                    >
                      <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" />
                      </svg>
                    </button>
                  </div>
                </div>

                {/* 모든 지침에 행동이 붙을 필요는 없다 — 말하는 방식에 대한 지침이 대부분이다 */}
                <div className="flex flex-wrap items-center gap-3 mt-4 pt-4 border-t border-line/70">
                  <span className="text-[22px] text-muted">이때 실행할 행동</span>
                  <select
                    aria-label={`지침 ${i + 1}의 행동`}
                    className="h-14 px-4 text-[24px] rounded-(--radius-ctl) border border-line bg-surface cursor-pointer"
                    value={ins.action || ""}
                    onChange={(e) => setInstructionAction(scenario.id, i, e.target.value)}
                  >
                    <option value="">없음 (말로만 대응)</option>
                    {draft.actions.map((a) => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                  {ins.action && (
                    <Link to={`/actions/${ins.action}`}
                          className="text-accent font-semibold text-[22px] hover:underline">
                      연락 대상·설정 보기 →
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3 mt-10 pt-8 border-t border-line">
        <div className="text-muted text-[22px]">
          {changes.length > 0
            ? `수정 ${changes.length}건이 저장되어 있습니다. 배포해야 동행이에게 적용됩니다.`
            : "변경 사항이 없습니다."}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="danger"
                  onClick={() => { removeScenario(scenario.id); navigate("/scenarios"); }}>
            이 시나리오 삭제
          </Button>
          <Button onClick={() => navigate("/scenarios")}>수정 완료</Button>
          {changes.length > 0 && (
            <Button variant="primary" onClick={() => navigate("/deploy")}>
              배포하러 가기
            </Button>
          )}
        </div>
      </div>

      <Modal
        open={modal !== null}
        title={modal === "voice" ? "말로 지침 추가" : editIdx !== null ? "지침 수정" : "지침 추가"}
        onClose={() => { setModal(null); setEditIdx(null); }}
      >
        {modal === "voice" && (
          <div className="mb-4">
            {voiceSupported ? (
              <Button
                variant={listening ? "danger" : "outline"}
                onClick={startVoice}
                className="w-full"
              >
                <MicIcon />
                {listening ? "듣고 있어요… 말씀해 주세요" : "누르고 말하기"}
              </Button>
            ) : (
              <p className="text-muted text-[24px]">
                이 브라우저는 음성 입력을 지원하지 않아요. 아래에 직접 입력해 주세요.
              </p>
            )}
          </div>
        )}
        <textarea
          className={`${inputCls} h-28 py-3 resize-none`}
          placeholder="예: 낙상하면 딸에게 먼저 알려 주세요"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <p className="text-[20px] text-muted mt-2 mb-5">
          등록한 지침은 배포 전까지 적용되지 않습니다.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setModal(null)}>취소</Button>
          <Button variant="primary" onClick={submit} disabled={!text.trim()}>
            이 지침 등록
          </Button>
        </div>
      </Modal>
    </>
  );
}
