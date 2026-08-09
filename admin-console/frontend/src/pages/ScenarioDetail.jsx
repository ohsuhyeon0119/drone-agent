import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
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
  const {
    draft, toggleScenario, addInstruction, removeInstruction, updateInstruction,
    setOnDetect, toggleScenarioContact, addContactAndTag,
    setDetectPrompt, setCooldown,
  } = useStore();
  const scenario = draft.scenarios.find((s) => s.id === id);

  const [modal, setModal] = useState(null); // null | "text" | "voice"
  const [editIdx, setEditIdx] = useState(null); // null = 새 지침, 숫자 = 해당 지침 수정
  const [text, setText] = useState("");
  const [adding, setAdding] = useState(false); // 연락처 즉시 추가 폼
  const [cForm, setCForm] = useState({ name: "", relation: "", phone: "" });
  const [cError, setCError] = useState("");
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

  const selectedAction = draft.actions.find((a) => a.id === scenario.onDetect);
  const tagged = scenario.notifyContactIds || [];

  const submitContact = (e) => {
    e.preventDefault();
    const phone = cForm.phone.trim();
    if (!/^01[0-9]-?\d{3,4}-?\d{4}$/.test(phone)) {
      setCError("전화번호 형식이 올바르지 않습니다. 010-0000-0000 형태로 입력해 주세요.");
      return;
    }
    setCError("");
    addContactAndTag(scenario.id, {
      name: cForm.name.trim(),
      relation: cForm.relation.trim() || "가족",
      phone,
    });
    setCForm({ name: "", relation: "", phone: "" });
    setAdding(false);
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

      {/* 카메라가 무엇을 찾을지 — 지침(말하는 방식)과 역할이 다르므로 위에 따로 둔다 */}
      <section className="mb-10 bg-surface border border-line rounded-(--radius-card) px-7 py-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <h2 className="text-[32px] font-bold">카메라가 찾을 것</h2>
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
          이 문장을 근거로 카메라 화면을 판단합니다. 구체적으로 쓸수록 정확해집니다.
        </p>
        <textarea
          aria-label="감지 기준"
          className={`${inputCls} h-32 py-4 leading-relaxed resize-none`}
          placeholder="예: 사람이 알약이나 약봉투를 입 근처로 가져가는지 감지하라"
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
              답변 형식은 자동으로 붙습니다. 위 입력칸에는 “무엇을 찾을지”만 쓰면 됩니다.
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
                className="flex items-start gap-4 bg-surface border border-line rounded-(--radius-card) border-l-4 border-l-accent px-7 py-6"
              >
                <p className="flex-1 text-[28px] leading-relaxed">{ins}</p>
                <div className="flex flex-none gap-1">
                  <button
                    aria-label="지침 수정"
                    onClick={() => { setText(ins); setEditIdx(i); setModal("text"); }}
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
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="bg-surface border border-line rounded-(--radius-card) px-7 py-6">
        <div className="flex flex-wrap items-center gap-4">
          <span className="font-semibold text-[27px]">감지 시 실행할 행동</span>
          <select
            aria-label="감지 시 실행할 행동"
            className="h-14 px-4 text-[26px] rounded-(--radius-ctl) border border-line bg-surface cursor-pointer"
            value={scenario.onDetect || ""}
            onChange={(e) => setOnDetect(scenario.id, e.target.value)}
          >
            <option value="">없음</option>
            {draft.actions.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>

        {selectedAction?.needsContacts && (
          <div className="mt-7 pt-7 border-t border-line">
            <h3 className="font-semibold text-[26px] mb-1.5">누구에게 연락할까요</h3>
            <p className="text-muted text-[20px] mb-4">
              여러 명을 선택할 수 있습니다. 선택한 순서대로 연락합니다.
            </p>

            {draft.contacts.length > 0 && (
              <div className="flex flex-wrap gap-2.5 mb-4">
                {draft.contacts.map((c) => {
                  const on = tagged.includes(c.id);
                  return (
                    <button
                      key={c.id}
                      onClick={() => toggleScenarioContact(scenario.id, c.id)}
                      aria-pressed={on}
                      className={`flex items-center gap-2.5 h-14 px-5 rounded-full border text-[22px] cursor-pointer transition-colors duration-150
                        ${on
                          ? "border-accent bg-accentsoft text-accent font-bold"
                          : "border-line bg-surface text-muted hover:border-accent"}`}
                    >
                      <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[15px] font-bold
                        ${on ? "bg-accent text-white" : "border border-line"}`}>
                        {on ? tagged.indexOf(c.id) + 1 : ""}
                      </span>
                      {c.name} <span className="font-normal opacity-70">· {c.relation}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {adding ? (
              <form
                onSubmit={submitContact}
                className="border border-line rounded-(--radius-card) p-5 bg-bg"
              >
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
                  <input className={inputCls} placeholder="이름" aria-label="이름"
                    value={cForm.name} onChange={(e) => setCForm({ ...cForm, name: e.target.value })} autoFocus />
                  <input className={inputCls} placeholder="관계 (예: 딸)" aria-label="관계"
                    value={cForm.relation} onChange={(e) => setCForm({ ...cForm, relation: e.target.value })} />
                  <input className={inputCls} placeholder="010-0000-0000" aria-label="전화번호" inputMode="tel"
                    value={cForm.phone} onChange={(e) => setCForm({ ...cForm, phone: e.target.value })} />
                </div>
                {cError && <p role="alert" className="text-warn text-[22px] mb-3">{cError}</p>}
                <div className="flex gap-2">
                  <Button variant="primary" type="submit" disabled={!cForm.name.trim() || !cForm.phone.trim()}>
                    추가하고 연락 대상에 넣기
                  </Button>
                  <Button variant="ghost" type="button" onClick={() => { setAdding(false); setCError(""); }}>
                    취소
                  </Button>
                </div>
              </form>
            ) : (
              <Button onClick={() => setAdding(true)}>+ 연락처 새로 추가</Button>
            )}

            {draft.contacts.length > 0 && tagged.length === 0 && !adding && (
              <p className="text-warn text-[20px] mt-3">
                연락 대상을 아직 선택하지 않았습니다.
              </p>
            )}
          </div>
        )}
      </section>

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
