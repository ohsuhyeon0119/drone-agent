import { Link, useNavigate } from "react-router-dom";
import { Button, EmptyState } from "../components/ui.jsx";
import { useStore } from "../store.jsx";

const KIND_LABEL = { builtin: "기본 제공", webhook: "외부 연결" };

export default function Actions() {
  const { draft, removeAction } = useStore();
  const navigate = useNavigate();

  /* 이 행동을 쓰는 시나리오 — 행동과 시나리오의 관계를 화면에서 바로 보이게 한다 */
  const usedBy = (actionId) =>
    draft.scenarios.filter((s) => (s.instructions || []).some((x) => x.action === actionId));

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-9">
        <div>
          <h1 className="text-[49px] font-bold [text-wrap:balance]">행동</h1>
          <p className="text-muted mt-2 text-[26px]">
            동행이가 실제로 할 수 있는 일입니다. 시나리오에서 “감지 시 실행할 행동”으로 연결해 사용합니다.
          </p>
        </div>
        <Button variant="primary" className="flex-none" onClick={() => navigate("/actions/new")}>행동 추가</Button>
      </div>

      {draft.actions.length === 0 ? (
        <EmptyState>등록된 행동이 없습니다.</EmptyState>
      ) : (
        <div className="overflow-x-auto bg-surface border border-line rounded-(--radius-card)">
          <table className="w-full min-w-[720px] border-collapse">
            <thead>
              <tr className="text-left text-[30px] font-bold text-muted border-b border-line">
                <th className="px-7 py-6">이름</th>
                <th className="px-7 py-6">동행이가 이 행동을 쓸 때</th>
                <th className="px-7 py-6">필요한 정보</th>
                <th className="px-7 py-6">쓰는 시나리오</th>
                <th className="px-4 py-6"><span className="sr-only">수정·삭제</span></th>
              </tr>
            </thead>
            <tbody>
              {draft.actions.map((a) => {
                const users = usedBy(a.id);
                return (
                  <tr key={a.id} className="border-b border-line last:border-b-0 align-top">
                    <td className="px-7 py-7 whitespace-nowrap">
                      <Link to={`/actions/${a.id}`} className="block font-bold text-[28px] hover:text-accent">{a.name}</Link>
                      <span className="inline-block mt-2 text-[20px] font-bold bg-accentsoft text-accent rounded-full px-3.5 py-1.5">
                        {KIND_LABEL[a.kind] || a.kind}
                      </span>
                    </td>
                    <td className="px-7 py-7 text-ink text-[26px] leading-relaxed">{a.description}</td>
                    <td className="px-7 py-7 text-ink text-[26px]">
                      {a.params?.map((p) => p.name).join(", ") || "—"}
                    </td>
                    <td className="px-7 py-7 text-[24px]">
                      {users.length === 0 ? (
                        <span className="text-muted/60">연결 안 됨</span>
                      ) : (
                        <div className="flex flex-col gap-1.5">
                          {users.map((s) => (
                            <Link key={s.id} to={`/scenarios/${s.id}`}
                                  className="text-accent font-semibold hover:underline">
                              {s.name}
                            </Link>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-7 text-right whitespace-nowrap">
                      <button
                        aria-label={`${a.name} 수정`}
                        onClick={() => navigate(`/actions/${a.id}`)}
                        className="w-14 h-14 -mt-3.5 inline-flex items-center justify-center rounded-(--radius-ctl) text-muted hover:text-accent hover:bg-accentsoft cursor-pointer"
                      >
                        <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                        </svg>
                      </button>
                      <button
                        aria-label={`${a.name} 삭제`}
                        onClick={() => removeAction(a.id)}
                        className="w-14 h-14 -mt-3.5 inline-flex items-center justify-center rounded-(--radius-ctl) text-muted hover:text-warn hover:bg-warnsoft cursor-pointer"
                      >
                        <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

    </>
  );
}
