import { Link } from "react-router-dom";
import { PageHeader, Toggle } from "../components/ui.jsx";
import { useStore } from "../store.jsx";

export default function Scenarios() {
  const { draft, toggleScenario } = useStore();
  const actionName = (id) => draft.actions.find((a) => a.id === id)?.name;
  const contactNames = (ids) =>
    (ids || [])
      .map((id) => draft.contacts.find((c) => c.id === id)?.name)
      .filter(Boolean)
      .join(", ");

  return (
    <>
      <PageHeader
        title="시나리오"
        sub="감지할 상황과 대응 지침을 관리합니다."
      />
      <div className="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-6">
        {draft.scenarios.map((s) => (
          <div
            key={s.id}
            className="bg-surface border border-line rounded-(--radius-card) p-9 hover:border-accent transition-colors duration-150 flex flex-col gap-7 min-h-[560px]"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <Link to={`/scenarios/${s.id}`} className="font-bold text-[40px] hover:text-accent">
                  {s.name}
                </Link>
                <p className="text-muted text-[26px] mt-2">
                  지침 {s.instructions.length}개 · {s.enabled ? "감시 중" : "꺼짐"}
                </p>
              </div>
              <Toggle
                checked={s.enabled}
                onChange={(v) => toggleScenario(s.id, v)}
                label={`${s.name} ${s.enabled ? "끄기" : "켜기"}`}
              />
            </div>

            <ul className="flex flex-col gap-5">
              {s.instructions.map((ins, i) => (
                <li key={i} className="text-[28px] text-ink border-l-[3px] border-accent/50 pl-5 leading-relaxed">
                  {ins}
                </li>
              ))}
            </ul>

            <div className="mt-auto flex items-center justify-between gap-3 flex-wrap border-t border-line/70 pt-6">
              {s.onDetect ? (
                <span className="flex flex-wrap items-center gap-2">
                  <span className="inline-block text-[23px] font-semibold bg-accentsoft text-accent rounded-full px-4 py-2">
                    감지되면 → {actionName(s.onDetect)}
                  </span>
                  {contactNames(s.notifyContactIds) && (
                    <span className="text-[21px] text-muted">
                      → {contactNames(s.notifyContactIds)}
                    </span>
                  )}
                </span>
              ) : (
                <span className="text-[23px] text-muted/60">연결된 행동 없음</span>
              )}
              <Link
                to={`/scenarios/${s.id}`}
                className="text-accent font-semibold text-[26px] hover:underline"
              >
                지침 관리 →
              </Link>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
