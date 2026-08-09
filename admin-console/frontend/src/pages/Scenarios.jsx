import { Link, useNavigate } from "react-router-dom";
import { Button, Toggle } from "../components/ui.jsx";
import { useStore } from "../store.jsx";

export default function Scenarios() {
  const { draft, toggleScenario } = useStore();
  const navigate = useNavigate();
  const actionName = (id) => draft.actions.find((a) => a.id === id)?.name;
  /* 지침에 붙은 행동들 — 행동은 시나리오가 아니라 개별 지침에 붙는다 */
  const linkedActions = (s) =>
    [...new Set((s.instructions || []).map((x) => x.action).filter(Boolean))];

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-9">
        <div>
          <h1 className="text-[27px] font-bold [text-wrap:balance]">시나리오</h1>
          <p className="text-muted mt-2 text-[15px]">감지할 상황과 대응 지침을 관리합니다.</p>
        </div>
        <Button variant="primary" className="flex-none"
                onClick={() => navigate("/scenarios/new")}>
          시나리오 추가
        </Button>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-6">
        {draft.scenarios.map((s) => (
          <div
            key={s.id}
            className="bg-surface border border-line rounded-(--radius-card) p-9 hover:border-accent transition-colors duration-150 flex flex-col gap-7 min-h-[304px]"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <Link to={`/scenarios/${s.id}`} className="font-bold text-[22px] hover:text-accent">
                  {s.name}
                </Link>
                <p className="text-muted text-[15px] mt-2">
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
                <li key={i} className="text-[17px] text-ink border-l-[3px] border-accent/50 pl-5 leading-relaxed">
                  {ins.text}
                  {ins.action && (
                    <span className="block mt-1.5 text-[13px] font-semibold text-accent">
                      → {actionName(ins.action)}
                    </span>
                  )}
                </li>
              ))}
            </ul>

            <div className="mt-auto flex items-center justify-between gap-3 flex-wrap border-t border-line/70 pt-6">
              {linkedActions(s).length > 0 ? (
                <span className="flex flex-wrap items-center gap-2">
                  {linkedActions(s).map((a) => (
                    <span key={a}
                          className="inline-block text-[11px] font-semibold bg-accentsoft text-accent rounded-full px-4 py-2">
                      {actionName(a)}
                    </span>
                  ))}
                </span>
              ) : (
                <span className="text-[11px] text-muted/60">연결된 행동 없음</span>
              )}
              <Link
                to={`/scenarios/${s.id}`}
                className="text-accent font-semibold text-[15px] hover:underline"
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
