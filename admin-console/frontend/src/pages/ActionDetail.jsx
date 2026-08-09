import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Button, Field, inputCls } from "../components/ui.jsx";
import { useStore } from "../store.jsx";

const KIND_LABEL = { builtin: "기본 제공", webhook: "외부 연결" };

export default function ActionDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const {
    draft, addAction, updateAction, removeAction,
    toggleActionContact, addContactAndTagAction,
  } = useStore();
  const [adding, setAdding] = useState(false);
  const [cForm, setCForm] = useState({ name: "", relation: "", phone: "" });
  const [cError, setCError] = useState("");

  const isNew = id === "new";
  const action = isNew ? null : draft.actions.find((a) => a.id === id);

  const [form, setForm] = useState(() =>
    action
      ? { name: action.name, description: action.description, kind: action.kind, url: action.url || "" }
      : { name: "", description: "", kind: "builtin", url: "" },
  );
  const [params, setParams] = useState(() =>
    action?.params?.length
      ? action.params.map((p) => ({ name: p.name, desc: p.desc || "" }))
      : [{ name: "", desc: "" }],
  );

  if (!isNew && !action) {
    return (
      <p className="text-muted">
        행동을 찾을 수 없습니다. <Link className="text-accent" to="/actions">목록으로 돌아가기</Link>
      </p>
    );
  }

  /* 이 행동을 쓰는 시나리오 — 수정 화면에서도 관계가 보이게 한다 */
  const usedBy = draft.scenarios.filter((s) =>
    (s.instructions || []).some((x) => x.action === id));
  const tagged = action?.notifyContactIds || [];

  const submitContact = (e) => {
    e.preventDefault();
    const phone = cForm.phone.trim();
    if (!/^01[0-9]-?\d{3,4}-?\d{4}$/.test(phone)) {
      setCError("전화번호 형식이 올바르지 않습니다. 010-0000-0000 형태로 입력해 주세요.");
      return;
    }
    setCError("");
    addContactAndTagAction(id, {
      name: cForm.name.trim(),
      relation: cForm.relation.trim() || "가족",
      phone,
    });
    setCForm({ name: "", relation: "", phone: "" });
    setAdding(false);
  };

  const save = () => {
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      url: form.kind === "webhook" ? form.url.trim() : undefined,
      params: params
        .filter((p) => p.name.trim())
        .map((p) => ({ name: p.name.trim(), type: "글", desc: p.desc.trim() })),
    };
    if (isNew) addAction({ ...payload, kind: form.kind });
    else updateAction(id, payload);
    navigate("/actions");
  };

  const remove = () => {
    removeAction(id);
    navigate("/actions");
  };

  return (
    <>
      <nav className="text-[18px] text-muted mb-4">
        <Link to="/actions" className="hover:text-accent">행동</Link>
        <span className="mx-2">›</span>
        <span className="text-ink">{isNew ? "새 행동" : action.name}</span>
      </nav>

      <header className="flex flex-wrap items-center justify-between gap-4 mb-8">
        <h1 className="text-[34px] font-bold">{isNew ? "행동 추가" : action.name}</h1>
        {!isNew && (
          <span className="inline-block text-[16px] font-bold bg-accentsoft text-accent rounded-full px-4 py-2">
            {KIND_LABEL[action.kind] || action.kind}
          </span>
        )}
      </header>

      <section className="bg-surface border border-line rounded-(--radius-card) px-8 py-7 mb-8">
        <Field label="이름">
          <input
            className={inputCls}
            placeholder="예: 딸에게 문자 보내기"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            autoFocus={isNew}
          />
        </Field>

        <Field
          label="동행이가 이 행동을 쓸 때"
          help="동행이가 이 행동을 실행할 시점을 판단하는 기준입니다. 구체적일수록 정확합니다."
        >
          <textarea
            className={`${inputCls} h-28 py-4 leading-relaxed resize-none`}
            placeholder="예: 낙상이 감지되고 30초간 응답이 없을 때"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </Field>

        <Field label="필요한 정보" help="동행이가 이 행동을 실행할 때 채워 넣는 값입니다.">
          <div className="flex flex-col gap-2">
            {params.map((p, i) => (
              <div key={i} className="flex flex-wrap gap-2">
                <input
                  className={`${inputCls} flex-1 min-w-[150px]`}
                  placeholder="이름 (예: 전달 내용)"
                  value={p.name}
                  onChange={(e) => {
                    const next = [...params];
                    next[i] = { ...p, name: e.target.value };
                    setParams(next);
                  }}
                />
                <input
                  className={`${inputCls} flex-1 min-w-[150px]`}
                  placeholder="설명"
                  value={p.desc}
                  onChange={(e) => {
                    const next = [...params];
                    next[i] = { ...p, desc: e.target.value };
                    setParams(next);
                  }}
                />
                {params.length > 1 && (
                  <button
                    aria-label={`정보 항목 ${i + 1} 삭제`}
                    onClick={() => setParams(params.filter((_, j) => j !== i))}
                    className="w-14 h-14 flex-none inline-flex items-center justify-center rounded-(--radius-ctl) text-muted hover:text-warn hover:bg-warnsoft cursor-pointer"
                  >
                    <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" />
                    </svg>
                  </button>
                )}
              </div>
            ))}
            <Button variant="ghost" className="self-start h-12 text-[16px]"
                    onClick={() => setParams([...params, { name: "", desc: "" }])}>
              + 정보 항목 추가
            </Button>
          </div>
        </Field>

        {!isNew && action.needsContacts && (
          <Field
            label="누구에게 연락할까요"
            help="이 행동이 실행되면 아래 순서대로 연락합니다. 지정하지 않으면 등록된 연락처 전체에 알립니다."
          >
            {draft.contacts.length > 0 && (
              <div className="flex flex-wrap gap-2.5 mb-3">
                {draft.contacts.map((c) => {
                  const on = tagged.includes(c.id);
                  return (
                    <button
                      key={c.id}
                      onClick={() => toggleActionContact(id, c.id)}
                      aria-pressed={on}
                      className={`flex items-center gap-2.5 h-14 px-5 rounded-full border text-[16px] cursor-pointer transition-colors duration-150
                        ${on ? "border-accent bg-accentsoft text-accent font-bold"
                             : "border-line bg-surface text-muted hover:border-accent"}`}
                    >
                      <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold
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
              <form onSubmit={submitContact} className="border border-line rounded-(--radius-card) p-5 bg-bg">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
                  <input className={inputCls} placeholder="이름" aria-label="이름" autoFocus
                    value={cForm.name} onChange={(e) => setCForm({ ...cForm, name: e.target.value })} />
                  <input className={inputCls} placeholder="관계 (예: 딸)" aria-label="관계"
                    value={cForm.relation} onChange={(e) => setCForm({ ...cForm, relation: e.target.value })} />
                  <input className={inputCls} placeholder="010-0000-0000" aria-label="전화번호" inputMode="tel"
                    value={cForm.phone} onChange={(e) => setCForm({ ...cForm, phone: e.target.value })} />
                </div>
                {cError && <p role="alert" className="text-warn text-[16px] mb-3">{cError}</p>}
                <div className="flex gap-2">
                  <Button variant="primary" type="submit"
                          disabled={!cForm.name.trim() || !cForm.phone.trim()}>
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
          </Field>
        )}

        {isNew ? (
          <Field label="실행 방식">
            <select
              className={`${inputCls} cursor-pointer`}
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}
            >
              <option value="builtin">기본 제공 (알림·기록)</option>
              <option value="webhook">외부 연결 (주소 입력)</option>
            </select>
          </Field>
        ) : (
          <p className="text-muted text-[16px] mb-5">
            실행 방식({KIND_LABEL[form.kind]})은 바꿀 수 없습니다.
          </p>
        )}

        {form.kind === "webhook" && (
          <Field label="연결 주소" help="실행 시 이 주소로 요청을 보냅니다.">
            <input
              className={inputCls}
              placeholder="https://…"
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
            />
          </Field>
        )}
      </section>

      {!isNew && (
        <section className="bg-surface border border-line rounded-(--radius-card) px-8 py-7 mb-8">
          <h2 className="text-[21px] font-bold mb-2">이 행동을 쓰는 시나리오</h2>
          {usedBy.length === 0 ? (
            <p className="text-muted text-[16px]">
              아직 어느 시나리오에도 연결되어 있지 않습니다. 시나리오의 “감지 시 실행할 행동”에서 연결하세요.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2.5">
              {usedBy.map((s) => (
                <Link key={s.id} to={`/scenarios/${s.id}`}
                      className="inline-block text-[16px] font-bold bg-accentsoft text-accent rounded-full px-5 py-2.5 hover:underline">
                  {s.name}
                </Link>
              ))}
            </div>
          )}
        </section>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
        <Button variant="primary" onClick={save}
                disabled={!form.name.trim() || !form.description.trim()}>
          {isNew ? "추가하기" : "수정 완료"}
        </Button>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => navigate("/actions")}>취소</Button>
          {!isNew && <Button variant="danger" onClick={remove}>이 행동 삭제</Button>}
        </div>
      </div>
      <p className="text-muted text-[15px] mt-3">
        수정한 내용은 배포해야 동행이에게 적용됩니다.
      </p>
    </>
  );
}
