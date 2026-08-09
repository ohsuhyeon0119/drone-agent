import { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui.jsx";
import { useStore } from "../store.jsx";

/* 동행이 앱을 콘솔 안에서 바로 띄운다 — 지침을 고치고 그 자리에서 확인하기 위함.
   앱은 별도 서버(FastAPI)라 개발 중에는 포트가 다르다. 배포 시에는 같은 서버가
   서빙하므로 같은 출처가 된다. */
const AGENT_URL = import.meta.env.VITE_AGENT_URL || "http://localhost:8003/";

export default function Agent() {
  const { live, changes } = useStore();
  const [reloadKey, setReloadKey] = useState(0);
  const [reachable, setReachable] = useState(null); // null=확인 중
  const frameRef = useRef(null);

  useEffect(() => {
    let alive = true;
    // iframe은 교차 출처라 로드 성공을 직접 알 수 없다 — 별도로 접근 가능 여부만 확인한다.
    fetch(AGENT_URL, { mode: "no-cors" })
      .then(() => alive && setReachable(true))
      .catch(() => alive && setReachable(false));
    return () => { alive = false; };
  }, [reloadKey]);

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 mb-5">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <h1 className="text-[40px] font-bold">에이전트</h1>
          <span className="inline-block text-[20px] font-bold bg-accentsoft text-accent rounded-full px-4 py-1.5">
            Live v{live.version} 기준
          </span>
          {changes.length > 0 && (
            <span className="text-[20px] text-warn font-semibold">
              수정 {changes.length}건은 배포해야 반영됩니다
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-2 flex-none">
          <Button className="h-12 px-5 text-[20px]" onClick={() => setReloadKey((k) => k + 1)}>
            새로 시작
          </Button>
          <Button variant="primary" className="h-12 px-5 text-[20px]"
                  onClick={() => window.open(AGENT_URL, "_blank")}>
            새 창으로 열기
          </Button>
        </div>
      </div>

      {reachable === false ? (
        <div className="border border-dashed border-line rounded-(--radius-card) py-14 px-8 text-center">
          <p className="text-[26px] font-bold mb-2">에이전트에 연결할 수 없습니다</p>
          <p className="text-muted text-[22px]">
            동행이 앱이 실행 중인지 확인해 주세요. ({AGENT_URL})
          </p>
        </div>
      ) : (
        <div className="rounded-(--radius-card) border border-line overflow-hidden bg-surface">
          <iframe
            key={reloadKey}
            ref={frameRef}
            src={AGENT_URL}
            title="동행이 에이전트"
            allow="camera; microphone; autoplay"
            className="w-full h-[calc(100vh-190px)] min-h-[820px] block border-0"
          />
        </div>
      )}

      <p className="text-muted text-[18px] mt-3">
        카메라·마이크 권한을 묻는 창이 뜨면 허용해 주세요. 권한이 막히면
        “새 창으로 열기”를 사용하세요.
      </p>
    </>
  );
}
