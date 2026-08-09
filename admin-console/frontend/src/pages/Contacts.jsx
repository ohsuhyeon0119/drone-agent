import { useState } from "react";
import { Button, EmptyState, PageHeader, inputCls } from "../components/ui.jsx";
import { useStore } from "../store.jsx";

export default function Contacts() {
  const { draft, addContact, removeContact, moveContact } = useStore();
  const [form, setForm] = useState({ name: "", relation: "", phone: "" });
  const [error, setError] = useState("");

  const submit = (e) => {
    e.preventDefault();
    const phone = form.phone.trim();
    if (!/^01[0-9]-?\d{3,4}-?\d{4}$/.test(phone)) {
      setError("전화번호 형식이 올바르지 않습니다. 010-0000-0000 형태로 입력해 주세요.");
      return;
    }
    setError("");
    addContact({ name: form.name.trim(), relation: form.relation.trim() || "가족", phone });
    setForm({ name: "", relation: "", phone: "" });
  };

  return (
    <>
      <PageHeader
        title="알림 연락처"
        sub="위급 상황 알림을 받을 연락처와 순서를 관리합니다. 1순위부터 차례로 연락합니다."
      />

      <form onSubmit={submit} className="bg-surface border border-line rounded-(--radius-card) p-5 mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
          <input
            className={inputCls}
            placeholder="이름"
            aria-label="이름"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            className={inputCls}
            placeholder="관계 (예: 딸)"
            aria-label="관계"
            value={form.relation}
            onChange={(e) => setForm({ ...form, relation: e.target.value })}
          />
          <input
            className={inputCls}
            placeholder="010-0000-0000"
            aria-label="전화번호"
            inputMode="tel"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
          />
        </div>
        {error && <p role="alert" className="text-warn text-[24px] mb-3">{error}</p>}
        <Button variant="primary" type="submit" disabled={!form.name.trim() || !form.phone.trim()}>
          연락처 등록
        </Button>
      </form>

      {draft.contacts.length === 0 ? (
        <EmptyState>등록된 연락처가 없습니다.</EmptyState>
      ) : (
        <ul className="flex flex-col gap-3 mb-8">
          {draft.contacts.map((c, i) => (
            <li
              key={c.id}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 bg-surface border border-line rounded-(--radius-card) px-6 py-5"
            >
              <span
                className={`flex-none w-16 text-center text-[20px] font-bold rounded-full px-2 py-1
                  ${i === 0 ? "bg-accentsoft text-accent" : "bg-bg text-muted"}`}
              >
                {i + 1}순위
              </span>
              <div className="flex-1 min-w-[140px]">
                <span className="font-bold text-[28px]">{c.name}</span>
                <span className="text-muted text-[24px]"> · {c.relation}</span>
                <div className="text-ink/75 text-[26px] tabular-nums">{c.phone}</div>
              </div>
              <div className="flex gap-1">
                <button
                  aria-label="순위 올리기"
                  onClick={() => moveContact(c.id, -1)}
                  disabled={i === 0}
                  className="w-14 h-14 flex items-center justify-center rounded-(--radius-ctl) text-muted hover:text-ink disabled:opacity-30 cursor-pointer disabled:cursor-default"
                >▲</button>
                <button
                  aria-label="순위 내리기"
                  onClick={() => moveContact(c.id, +1)}
                  disabled={i === draft.contacts.length - 1}
                  className="w-14 h-14 flex items-center justify-center rounded-(--radius-ctl) text-muted hover:text-ink disabled:opacity-30 cursor-pointer disabled:cursor-default"
                >▼</button>
                <button
                  aria-label={`${c.name} 삭제`}
                  onClick={() => removeContact(c.id)}
                  className="w-16 h-16 flex items-center justify-center rounded-(--radius-ctl) text-muted hover:text-warn hover:bg-warnsoft cursor-pointer"
                >
                  <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                  </svg>
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
