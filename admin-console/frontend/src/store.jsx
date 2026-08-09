/* 목데이터 스토어 — 백엔드(FastAPI) 연결 전까지 localStorage에 저장.
   API 연결 시 이 파일의 함수 시그니처를 그대로 fetch로 교체하면 된다. */
import { createContext, useContext, useEffect, useState } from "react";

const SEED = {
  scenarios: [
    {
      id: "fall",
      name: "낙상 감지",
      enabled: true,
      detectPrompt: "이 이미지를 보고 사람이 엎드려 있거나 넘어져 있는지 감지하라.",
      cooldown: 10,
      instructions: [
        { text: "쓰러짐이 감지되면 즉시 걱정스러운 톤으로 “괜찮으세요?”라고 물어봅니다." },
        { text: "괜찮지 않다고 답하시거나 응답이 없으면 보호자에게 알립니다.",
          action: "notify_caregiver" },
        { text: "명확히 괜찮다고 답하시면 알리지 않고 안심시키는 말로 마무리합니다." },
      ],
    },
    {
      id: "medication",
      name: "약 복용 확인",
      enabled: true,
      detectPrompt:
        "이 이미지를 보고 사람이 알약, 약봉투, 약통, 물컵을 손에 들고 있거나 " +
        "입 근처로 가져가 약을 복용하는 동작을 하고 있는지 감지하라.",
      cooldown: 15,
      instructions: [
        { text: "복약 시간이 되면 먼저 다정하게 말을 걸어 복용을 권합니다." },
        { text: "약을 복용하는 모습이 확인되면 따뜻하게 칭찬합니다." },
        { text: "아직 안 드셨다고 하시면 부드럽게 다시 권유하고 재차 확인합니다." },
        { text: "어르신이 약을 드셨다고 말씀하시면 기록을 남깁니다.",
          action: "record_medication" },
      ],
    },
    {
      id: "task",
      name: "키오스크·일 처리 도움",
      enabled: true,
      detectPrompt: "",
      cooldown: 10,
      instructions: [
        { text: "화면이나 눈앞의 물건에 대해 물어보면 쉬운 말로 한 단계씩 설명합니다." },
        { text: "어려운 용어는 피하고, 필요하면 되물어 정확히 확인한 뒤 안내합니다." },
      ],
    },
  ],
  actions: [
    {
      id: "notify_caregiver",
      name: "보호자 알림",
      description: "낙상 등 위급 상황이 감지되어 보호자에게 알려야 할 때",
      params: [
        { name: "상황 종류", type: "글", desc: "감지된 상황의 종류" },
        { name: "전달 내용", type: "글", desc: "보호자에게 전달할 요약" },
      ],
      kind: "builtin",
      needsContacts: true,
      notifyContactIds: [],
    },
    {
      id: "record_medication",
      name: "복약 기록",
      description: "어르신이 약을 드셨다고 말씀하셨을 때 기록을 남깁니다. 카메라로 이미 확인된 경우에는 호출하지 않습니다.",
      params: [{ name: "기록 내용", type: "글", desc: "남길 내용" }],
      kind: "builtin",
    },
  ],
  contacts: [],
  alertRule: { scenario: "fall", waitSeconds: 30, notifyRank: 1 },
};

const STORAGE_KEY = "donghaeng-console-v1";

function clone(x) {
  return JSON.parse(JSON.stringify(x));
}

/* 저장된 설정에 시드의 새 필드를 채워 넣는다.
   화면에 항목을 추가할 때마다 예전에 저장된 브라우저에서는 그 항목이 통째로
   사라져 보이는 문제를 막기 위함 (사용자가 입력한 값은 그대로 둔다). */
function normalizeInstructions(list) {
  return (list || []).map((x) =>
    typeof x === "string" ? { text: x, action: null } : { text: x.text, action: x.action || null },
  );
}

function withSeedDefaults(config) {
  if (!config || typeof config !== "object") return clone(SEED);
  const merged = { ...clone(SEED), ...config };
  const seedScen = Object.fromEntries(SEED.scenarios.map((s) => [s.id, s]));
  merged.scenarios = (config.scenarios || SEED.scenarios).map((s) => {
    const m = { ...(seedScen[s.id] || {}), ...s };
    m.instructions = normalizeInstructions(m.instructions);
    // 예전에는 행동이 시나리오에 붙어 있었다 — 남아 있으면 지침 쪽으로 옮긴다
    if (m.onDetect && !m.instructions.some((x) => x.action)) {
      const last = m.instructions[m.instructions.length - 1];
      if (last) last.action = m.onDetect;
    }
    delete m.onDetect;
    delete m.notifyContactIds;
    return m;
  });
  const seedAct = Object.fromEntries(SEED.actions.map((a) => [a.id, a]));
  merged.actions = (config.actions || SEED.actions).map((a) => ({
    ...(seedAct[a.id] || {}), ...a,
  }));
  merged.contacts = config.contacts || [];
  return merged;
}

function initialState() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      const st = JSON.parse(saved);
      return {
        ...st,
        draft: withSeedDefaults(st.draft),
        live: { ...st.live, config: withSeedDefaults(st.live?.config) },
      };
    } catch { /* 손상 시 초기화 */ }
  }
  return {
    draft: clone(SEED),
    live: { version: 1, publishedAt: "2026-08-05 21:00", config: clone(SEED) },
    versions: [
      { version: 1, publishedAt: "2026-08-05 21:00", changes: ["초기 설정"], config: clone(SEED) },
    ],
  };
}

/* draft ↔ live의 사람이 읽는 변경 목록 — 배포 화면의 주인공 */
export function computeChanges(draft, liveConfig) {
  const changes = [];
  const liveScen = Object.fromEntries(liveConfig.scenarios.map((s) => [s.id, s]));
  for (const s of draft.scenarios) {
    const ls = liveScen[s.id];
    if (!ls) { changes.push(`시나리오 추가됨 — ${s.name}`); continue; }
    if (s.enabled !== ls.enabled) changes.push(`${s.name} ${s.enabled ? "켜짐" : "꺼짐"}`);
    const actName = (aid) => (draft.actions.find((a) => a.id === aid) || {}).name || aid;
    const dIns = Object.fromEntries((s.instructions || []).map((x) => [x.text, x]));
    const lIns = Object.fromEntries((ls.instructions || []).map((x) => [x.text, x]));
    for (const [text, x] of Object.entries(dIns)) {
      if (!(text in lIns)) changes.push(`지침 추가됨 (${s.name}) — “${text}”`);
      else if ((x.action || null) !== (lIns[text].action || null))
        changes.push(`지침의 행동 변경됨 (${s.name}) — “${text}” → ${x.action ? actName(x.action) : "없음"}`);
    }
    for (const text of Object.keys(lIns))
      if (!(text in dIns)) changes.push(`지침 삭제됨 (${s.name}) — “${text}”`);
    if ((s.detectPrompt || "") !== (ls.detectPrompt || ""))
      changes.push(`${s.name} 감지 기준 변경됨`);
    if (Number(s.cooldown) !== Number(ls.cooldown))
      changes.push(`${s.name} 재판정 간격 ${s.cooldown}초로 변경됨`);
  }
  const liveAct = Object.fromEntries(liveConfig.actions.map((a) => [a.id, a]));
  const cname = (ids) => (ids || []).map((id) =>
    (draft.contacts.find((c) => c.id === id) || liveConfig.contacts.find((c) => c.id === id) || {}).name || "?");
  for (const a of draft.actions) {
    if (!liveAct[a.id]) { changes.push(`행동 추가됨 — ${a.name}`); continue; }
    const la = liveAct[a.id];
    if (a.name !== la.name || a.description !== la.description)
      changes.push(`행동 수정됨 — ${a.name}`);
    const x = cname(a.notifyContactIds).join(", ");
    const y = cname(la.notifyContactIds).join(", ");
    if (x !== y) changes.push(`${a.name} 연락 대상 변경됨 — ${x || "없음"}`);
  }
  for (const a of liveConfig.actions)
    if (!draft.actions.some((d) => d.id === a.id)) changes.push(`행동 삭제됨 — ${a.name}`);

  const liveCt = Object.fromEntries(liveConfig.contacts.map((c) => [c.id, c]));
  for (const c of draft.contacts)
    if (!liveCt[c.id]) changes.push(`연락처 등록됨 — ${c.name} (${c.relation})`);
  for (const c of liveConfig.contacts)
    if (!draft.contacts.some((d) => d.id === c.id)) changes.push(`연락처 삭제됨 — ${c.name}`);
  const draftIds = draft.contacts.map((c) => c.id).join(",");
  const liveIds = liveConfig.contacts.map((c) => c.id).join(",");
  if (draftIds !== liveIds && !changes.some((c) => c.startsWith("연락처")))
    changes.push("연락처 우선순위 변경됨");

  if (JSON.stringify(draft.alertRule) !== JSON.stringify(liveConfig.alertRule))
    changes.push("알림 규칙 변경됨");
  return changes;
}

const StoreCtx = createContext(null);

export function StoreProvider({ children }) {
  const [state, setState] = useState(initialState);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  const update = (fn) =>
    setState((prev) => {
      const next = clone(prev);
      fn(next.draft);
      return next;
    });

  const api = {
    draft: state.draft,
    live: state.live,
    versions: state.versions,
    changes: computeChanges(state.draft, state.live.config),

    addScenario: (sc) =>
      update((d) => {
        d.scenarios.push({
          id: sc.id, name: sc.name, enabled: true,
          detectPrompt: sc.detectPrompt || "",
          cooldown: sc.cooldown ?? 10,
          instructions: sc.instructions || [],
        });
      }),
    removeScenario: (id) =>
      update((d) => { d.scenarios = d.scenarios.filter((s) => s.id !== id); }),
    renameScenario: (id, name) =>
      update((d) => { d.scenarios.find((s) => s.id === id).name = name; }),
    toggleScenario: (id, enabled) =>
      update((d) => { d.scenarios.find((s) => s.id === id).enabled = enabled; }),
    addInstruction: (id, text, action = null) =>
      update((d) => { d.scenarios.find((s) => s.id === id).instructions.push({ text, action }); }),
    removeInstruction: (id, idx) =>
      update((d) => { d.scenarios.find((s) => s.id === id).instructions.splice(idx, 1); }),
    updateInstruction: (id, idx, text) =>
      update((d) => { d.scenarios.find((s) => s.id === id).instructions[idx].text = text; }),
    /* 행동은 시나리오가 아니라 개별 지침에 붙는다 — 모든 지침에 붙을 필요는 없다 */
    setInstructionAction: (id, idx, actionId) =>
      update((d) => { d.scenarios.find((s) => s.id === id).instructions[idx].action = actionId || null; }),
    setDetectPrompt: (id, text) =>
      update((d) => { d.scenarios.find((s) => s.id === id).detectPrompt = text; }),
    setCooldown: (id, seconds) =>
      update((d) => { d.scenarios.find((s) => s.id === id).cooldown = seconds; }),

    addAction: (action) =>
      update((d) => { d.actions.push({ ...action, id: `custom_${Date.now()}`, kind: action.kind || "builtin" }); }),
    /* id는 실행 코드와 이어지는 키라 바꾸지 않는다 — 나머지는 지침처럼 자유롭게 수정 */
    updateAction: (id, patch) =>
      update((d) => {
        const a = d.actions.find((x) => x.id === id);
        if (a) Object.assign(a, patch, { id: a.id, kind: a.kind });
      }),
    toggleActionContact: (actionId, contactId) =>
      update((d) => {
        const a = d.actions.find((x) => x.id === actionId);
        if (!a) return;
        const cur = a.notifyContactIds || [];
        a.notifyContactIds = cur.includes(contactId)
          ? cur.filter((x) => x !== contactId)
          : [...cur, contactId];
      }),
    /* 연락처를 새로 만들면서 곧바로 이 행동의 연락 대상으로 지정 */
    addContactAndTagAction: (actionId, c) =>
      update((d) => {
        const cid = `ct_${Date.now()}`;
        d.contacts.push({ ...c, id: cid });
        const a = d.actions.find((x) => x.id === actionId);
        if (a) a.notifyContactIds = [...(a.notifyContactIds || []), cid];
      }),
    removeAction: (id) =>
      update((d) => {
        d.actions = d.actions.filter((a) => a.id !== id);
        // 이 행동을 쓰던 지침의 연결도 함께 끊는다
        for (const s of d.scenarios)
          for (const x of s.instructions) if (x.action === id) x.action = null;
      }),

    addContact: (c) =>
      update((d) => { d.contacts.push({ ...c, id: `ct_${Date.now()}` }); }),
    removeContact: (id) =>
      update((d) => {
        d.contacts = d.contacts.filter((c) => c.id !== id);
        for (const a of d.actions)
          if (a.notifyContactIds) a.notifyContactIds = a.notifyContactIds.filter((x) => x !== id);
      }),
    moveContact: (id, dir) =>
      update((d) => {
        const i = d.contacts.findIndex((c) => c.id === id);
        const j = i + dir;
        if (j < 0 || j >= d.contacts.length) return;
        [d.contacts[i], d.contacts[j]] = [d.contacts[j], d.contacts[i]];
      }),
    setAlertRule: (rule) => update((d) => { d.alertRule = rule; }),

    publish: () =>
      setState((prev) => {
        const changes = computeChanges(prev.draft, prev.live.config);
        const version = prev.live.version + 1;
        const publishedAt = new Date().toLocaleString("ko-KR", {
          year: "numeric", month: "2-digit", day: "2-digit",
          hour: "2-digit", minute: "2-digit", hour12: false,
        });
        return {
          draft: clone(prev.draft),
          live: { version, publishedAt, config: clone(prev.draft) },
          versions: [...prev.versions, { version, publishedAt, changes: changes.length ? changes : ["변경 없음"], config: clone(prev.draft) }],
        };
      }),
    /* 편집 상태로만 불러오기 (확인 후 직접 배포) */
    rollback: (version) =>
      setState((prev) => {
        const snap = prev.versions.find((v) => v.version === version);
        if (!snap || !snap.config) return prev;
        return { ...prev, draft: clone(snap.config) };
      }),

    /* 즉시 롤백 — 해당 버전 설정을 새 버전으로 바로 배포 */
    rollbackNow: (version) =>
      setState((prev) => {
        const snap = prev.versions.find((v) => v.version === version);
        if (!snap || !snap.config) return prev;
        const newVersion = prev.live.version + 1;
        const publishedAt = new Date().toLocaleString("ko-KR", {
          year: "numeric", month: "2-digit", day: "2-digit",
          hour: "2-digit", minute: "2-digit", hour12: false,
        });
        return {
          draft: clone(snap.config),
          live: { version: newVersion, publishedAt, config: clone(snap.config) },
          versions: [
            ...prev.versions,
            {
              version: newVersion,
              publishedAt,
              changes: [`v${version} 설정으로 롤백`],
              config: clone(snap.config),
              rolledBackFrom: version,
            },
          ],
        };
      }),
  };

  return <StoreCtx.Provider value={api}>{children}</StoreCtx.Provider>;
}

export function useStore() {
  return useContext(StoreCtx);
}
