import { useState } from "react";
import { Button, EmptyState, Modal, PageHeader } from "../components/ui.jsx";
import { useStore } from "../store.jsx";

export default function Deploy() {
  const { live, changes, versions, publish, rollback, rollbackNow } = useStore();
  const [confirm, setConfirm] = useState(false);
  const [rollbackTo, setRollbackTo] = useState(null);
  const [busy, setBusy] = useState(false);
  const nextVersion = live.version + 1;

  return (
    <>
      <PageHeader
        title="배포"
        sub="변경 사항을 확인하고 적용합니다. 배포 전까지 실제 동작은 바뀌지 않습니다."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
        <div className="bg-surface border border-line rounded-(--radius-card) p-7">
          <div className="text-[13px] tracking-wide text-muted mb-1.5">현재 적용 버전</div>
          <div className="text-[19px] font-bold tabular-nums">Live v{live.version}</div>
          <div className="text-muted text-[14px] tabular-nums mt-1">{live.publishedAt} 배포됨</div>
        </div>
        <div className={`rounded-(--radius-card) p-7 border ${changes.length ? "bg-warnsoft border-warn/40" : "bg-surface border-line"}`}>
          <div className="text-[13px] tracking-wide text-muted mb-1.5">편집 중</div>
          <div className="text-[19px] font-bold">
            {changes.length ? <span className="text-warn">수정 {changes.length}건</span> : "변경 없음"}
          </div>
          <div className="text-muted text-[14px]">배포 후 적용됩니다</div>
        </div>
      </div>

      <section className="mb-8">
        <h2 className="text-[19px] font-bold mb-4">변경 사항</h2>
        {changes.length === 0 ? (
          <EmptyState>변경 사항이 없습니다. 시나리오나 연락처를 수정하면 여기에 표시됩니다.</EmptyState>
        ) : (
          <>
            <ul className="flex flex-col gap-2 mb-5">
              {changes.map((c, i) => (
                <li
                  key={i}
                  className="bg-surface border border-line rounded-(--radius-card) border-l-4 border-l-accent px-7 py-6 text-[15px] leading-relaxed"
                >
                  {c}
                </li>
              ))}
            </ul>
            <Button variant="primary" onClick={() => setConfirm(true)}>
              v{nextVersion}으로 배포하기
            </Button>
          </>
        )}
      </section>

      <section>
        <h2 className="text-[19px] font-bold mb-4">배포 기록</h2>
        <div className="overflow-x-auto bg-surface border border-line rounded-(--radius-card)">
          <table className="w-full min-w-[432px] border-collapse">
            <thead>
              <tr className="text-left text-[13px] tracking-wide text-muted border-b border-line">
                <th className="font-semibold px-6 py-5">버전</th>
                <th className="font-semibold px-6 py-5">배포 시각</th>
                <th className="font-semibold px-6 py-5">변경 내용</th>
                <th className="px-6 py-5"><span className="sr-only">되돌리기</span></th>
              </tr>
            </thead>
            <tbody>
              {[...versions].reverse().map((v) => (
                <tr key={v.version} className="border-b border-line last:border-b-0 align-top">
                  <td className="px-7 py-7 font-bold text-[17px] tabular-nums whitespace-nowrap">
                    v{v.version}
                    {v.version === live.version && (
                      <span className="ml-3 text-[13px] font-bold bg-accentsoft text-accent rounded-full px-2.5 py-0.5 align-middle">Live</span>
                    )}
                  </td>
                  <td className="px-7 py-7 text-ink text-[15px] tabular-nums whitespace-nowrap">{v.publishedAt}</td>
                  <td className="px-7 py-7 text-[15px] text-ink leading-relaxed">
                    {v.changes.slice(0, 2).map((c, i) => <div key={i}>{c}</div>)}
                    {v.changes.length > 2 && <div>외 {v.changes.length - 2}건</div>}
                  </td>
                  <td className="px-7 py-7 whitespace-nowrap text-right">
                    {/* 목록에는 변경 요약만 온다. 설정 내용은 롤백을 고른 뒤
                        서버에서 따로 가져온다. */}
                    {v.version !== live.version && (
                      <Button
                        onClick={() => setRollbackTo(v.version)}
                        className="h-14 px-5 text-[14px]"
                      >
                        이 버전으로 롤백
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Modal open={confirm} title={`v${nextVersion}으로 배포할까요?`} onClose={() => setConfirm(false)}>
        <p className="text-muted mb-6">
          배포 즉시 에이전트가 새 지침대로 동작합니다. 변경 {changes.length}건이 적용됩니다.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirm(false)} disabled={busy}>취소</Button>
          {/* 배포는 서버 왕복이라 시간이 걸린다. 끝나기 전에 창을 닫으면 성공했는지
              실패했는지 모른 채 넘어가므로, 끝날 때까지 열어두고 상태를 보여준다. */}
          <Button variant="primary" disabled={busy}
                  onClick={async () => { setBusy(true); await publish(); setBusy(false); setConfirm(false); }}>
            {busy ? "배포 중…" : "배포하기"}
          </Button>
        </div>
      </Modal>

      <Modal
        open={rollbackTo !== null}
        title={`v${rollbackTo}으로 롤백`}
        onClose={() => setRollbackTo(null)}
      >
        <p className="mb-7 leading-relaxed">
          두 가지 방법 중 하나를 선택하세요.
        </p>
        <div className="flex flex-col gap-3 mb-7">
          <div className="border border-line rounded-(--radius-card) p-5">
            <div className="font-bold mb-1">지금 바로 적용</div>
            <p className="text-muted text-[14px]">
              v{rollbackTo} 설정을 v{nextVersion}으로 즉시 배포합니다. 문제가 생겼을 때 가장 빠른 복구 방법입니다.
            </p>
            <Button
              variant="primary"
              className="mt-4 w-full"
              disabled={busy}
              onClick={async () => {
                setBusy(true); await rollbackNow(rollbackTo); setBusy(false); setRollbackTo(null);
              }}
            >
              {busy ? "롤백 중…" : "지금 롤백하고 배포"}
            </Button>
          </div>
          <div className="border border-line rounded-(--radius-card) p-5">
            <div className="font-bold mb-1">불러와서 확인 후 배포</div>
            <p className="text-muted text-[14px]">
              v{rollbackTo} 설정을 편집 상태로 불러옵니다. 내용을 확인하고 직접 배포합니다.
            </p>
            <Button
              className="mt-4 w-full"
              onClick={() => { rollback(rollbackTo); setRollbackTo(null); }}
            >
              편집 상태로 불러오기
            </Button>
          </div>
        </div>
        <div className="flex justify-end">
          <Button variant="ghost" onClick={() => setRollbackTo(null)}>취소</Button>
        </div>
      </Modal>
    </>
  );
}
