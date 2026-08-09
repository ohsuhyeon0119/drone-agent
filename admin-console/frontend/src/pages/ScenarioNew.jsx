import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Field, inputCls } from "../components/ui.jsx";
import { useStore } from "../store.jsx";

/* 식별자는 설정 파일 이름이자 감지 이벤트 이름이 되므로 영문 소문자만 쓴다.
   한글 이름에서는 뽑아낼 글자가 없어 자동 생성이 의미 없는 값이 되므로,
   비워 두면 순번을 붙이되 화면에서 직접 고칠 수 있게 한다. */
function suggestKey(name, taken) {
  const base =
    name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  let key = base || `scenario_${taken.size + 1}`;
  let n = 2;
  while (taken.has(key)) key = `${base || "scenario"}_${n++}`;
  return key;
}

export default function ScenarioNew() {
  const navigate = useNavigate();
  const { draft, addScenario } = useStore();
  const [name, setName] = useState("");
  const [detectPrompt, setDetectPrompt] = useState("");
  const [nudge, setNudge] = useState("");
  const [cooldown, setCooldown] = useState(15);
  const [key, setKey] = useState("");

  const taken = new Set(draft.scenarios.map((s) => s.id));
  const finalKey = (key.trim() || suggestKey(name, taken)).toLowerCase();
  const keyError =
    key.trim() && !/^[a-z0-9_]+$/.test(key.trim())
      ? "영문 소문자, 숫자, 밑줄만 쓸 수 있습니다."
      : taken.has(finalKey)
        ? "이미 쓰고 있는 식별자입니다."
        : "";

  const create = () => {
    addScenario({
      id: finalKey,
      name: name.trim(),
      detectPrompt: detectPrompt.trim(),
      nudgeTemplate: nudge.trim() ||
        `[SYSTEM] ${name.trim()} 상황이 감지되었습니다. 어르신께 확인해 보세요.`,
      cooldown: Number(cooldown),
      instructions: [],
    });
    navigate(`/scenarios/${finalKey}`);
  };

  return (
    <>
      <nav className="text-[24px] text-muted mb-4">
        <Link to="/scenarios" className="hover:text-accent">시나리오</Link>
        <span className="mx-2">›</span>
        <span className="text-ink">새 시나리오</span>
      </nav>

      <h1 className="text-[49px] font-bold mb-2">시나리오 추가</h1>
      <p className="text-muted text-[26px] mb-9">
        카메라가 무엇을 찾을지 정하면, 감지됐을 때 동행이가 어떻게 대응할지는 다음 화면에서 지침으로 정합니다.
      </p>

      <section className="bg-surface border border-line rounded-(--radius-card) px-8 py-7 mb-8">
        <Field label="이름" help="보호자에게 보이는 이름입니다. 예: 침입 감지, 식사 확인">
          <input
            className={inputCls}
            placeholder="예: 식사 확인"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </Field>

        <Field
          label="영문 식별자"
          help="설정 파일 이름이자 감지 이벤트 이름으로 쓰입니다. 비워 두면 자동으로 정해집니다."
        >
          <input
            className={inputCls}
            placeholder={suggestKey(name, taken)}
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          {keyError && <span className="block text-warn text-[20px] mt-1.5">{keyError}</span>}
        </Field>

        <Field
          label="카메라가 찾을 것"
          help="이 문장을 근거로 카메라 화면을 판단합니다. 무엇이 보이면 감지로 볼지, 무엇은 아닌지 함께 적을수록 오작동이 줄어듭니다."
        >
          <textarea
            className={`${inputCls} h-40 py-4 leading-relaxed resize-none`}
            placeholder={"예: 어르신이 식탁에 앉아 수저를 들고 음식을 드시는 중인지 판단하세요.\n다음은 감지로 보지 않습니다: 식탁에 음식만 놓여 있는 경우, 물만 마시는 경우."}
            value={detectPrompt}
            onChange={(e) => setDetectPrompt(e.target.value)}
          />
        </Field>

        <Field
          label="감지되면 동행이에게 전할 신호"
          help="비워 두면 자동으로 만들어집니다. 동행이가 이 신호를 받고 먼저 말을 겁니다."
        >
          <textarea
            className={`${inputCls} h-28 py-4 leading-relaxed resize-none`}
            placeholder={`[SYSTEM] ${name.trim() || "이 상황"}이 감지되었습니다. 어르신께 확인해 보세요.`}
            value={nudge}
            onChange={(e) => setNudge(e.target.value)}
          />
        </Field>

        <Field label="몇 초마다 판단할까요">
          <select
            className={`${inputCls} cursor-pointer tabular-nums`}
            value={cooldown}
            onChange={(e) => setCooldown(Number(e.target.value))}
          >
            {[5, 10, 15, 30, 60].map((v) => (
              <option key={v} value={v}>{v}초</option>
            ))}
          </select>
        </Field>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="primary" onClick={create}
                disabled={!name.trim() || !detectPrompt.trim() || !!keyError}>
          만들고 지침 정하기
        </Button>
        <Button variant="ghost" onClick={() => navigate("/scenarios")}>취소</Button>
      </div>
      <p className="text-muted text-[20px] mt-3">
        만든 시나리오는 배포해야 동행이가 실제로 감시하기 시작합니다.
      </p>
    </>
  );
}
