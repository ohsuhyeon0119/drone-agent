/* 에이전트 설정 저장소 — 서버(FastAPI /api/admin)가 진실의 원천이다.
   예전에는 localStorage에만 저장해서, 화면에서 고치고 "배포됨"이 떠도 동행이는
   아무것도 몰랐다. 실패보다 나쁜 상태였다 — 성공했다고 말하니까.

   편집은 화면에서 즉시 반영하고(낙관적), 잠시 뒤 서버에 draft로 저장한다.
   글자를 칠 때마다 요청을 보내면 타이핑이 끊긴다.

   서버 번들은 snake_case(detect_prompt, notify_contact_ids), 화면은
   camelCase를 쓴다. 여기서만 변환하고, 화면 코드는 몰라도 되게 한다. */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { getConfig, getVersion, publishConfig, putDraft, rollbackTo } from "./api.js";
import { useAuth } from "./auth.jsx";

const EMPTY = { scenarios: [], actions: [], contacts: [] };
const SAVE_DELAY = 700;

function clone(x) {
  return JSON.parse(JSON.stringify(x));
}

/* ── 서버 ↔ 화면 형식 변환 ──────────────────────────────────
   화면이 다루지 않는 값(min_confidence, nudge_template, target_event)은
   _server에 그대로 담아 두었다가 되돌려준다. 빠뜨리면 화면에서 한 번 배포하는
   것만으로 튜닝해둔 감지 기준이 기본값으로 되돌아간다. */
function scenarioToClient(s) {
  return {
    id: s.key,
    name: s.name,
    enabled: s.enabled !== false,
    detectPrompt: s.detect_prompt || "",
    cooldown: s.cooldown ?? 10,
    instructions: (s.instructions || []).map((x) => ({ text: x.text, action: x.action || null })),
    _server: s,
  };
}

function scenarioToServer(s) {
  return {
    ...(s._server || { target_event: "event", min_confidence: 0.7, nudge_template: "" }),
    key: s.id,
    name: s.name,
    enabled: !!s.enabled,
    detect_prompt: s.detectPrompt || "",
    cooldown: Number(s.cooldown ?? 10),
    instructions: (s.instructions || []).map((x) =>
      x.action ? { text: x.text, action: x.action } : { text: x.text }),
  };
}

function actionToClient(a) {
  return {
    id: a.id,
    name: a.name,
    description: a.description || "",
    params: a.params || [],
    kind: a.kind || "builtin",
    url: a.url || "",
    needsContacts: !!a.needs_contacts,
    notifyContactIds: a.notify_contact_ids || [],
    _server: a,
  };
}

function actionToServer(a) {
  return {
    ...(a._server || {}),
    id: a.id,
    name: a.name,
    description: a.description || "",
    params: a.params || [],
    kind: a.kind || "builtin",
    ...(a.url ? { url: a.url } : {}),
    needs_contacts: !!a.needsContacts,
    notify_contact_ids: a.notifyContactIds || [],
  };
}

function toClient(bundle) {
  if (!bundle) return clone(EMPTY);
  return {
    scenarios: (bundle.scenarios || []).map(scenarioToClient),
    actions: (bundle.actions || []).map(actionToClient),
    contacts: (bundle.contacts || []).map((c) => ({ ...c })),
  };
}

function toServer(draft) {
  return {
    scenarios: (draft.scenarios || []).map(scenarioToServer),
    actions: (draft.actions || []).map(actionToServer),
    contacts: (draft.contacts || []).map((c) => ({ ...c })),
  };
}

/* 서버 변경 목록은 {text, tier} — tier는 "즉시 반영"인지 "다음 대화부터"인지다.
   화면은 문장만 쓰므로 여기서 문자열로 편다. */
function changeTexts(list) {
  return (list || []).map((c) => (typeof c === "string" ? c : c.text));
}

/* draft ↔ live의 사람이 읽는 변경 목록.
   서버도 배포할 때 같은 계산을 하지만, 화면 배지가 타이핑 즉시 반응해야 해서
   여기서도 계산한다(서버 응답을 기다리면 한 박자 늦게 뜬다). */
export function computeChanges(draft, liveConfig) {
  if (!draft || !liveConfig) return [];
  const changes = [];
  const liveScen = Object.fromEntries((liveConfig.scenarios || []).map((s) => [s.id, s]));
  for (const s of draft.scenarios || []) {
    const ls = liveScen[s.id];
    if (!ls) { changes.push(`시나리오 추가됨 — ${s.name}`); continue; }
    if (s.enabled !== ls.enabled) changes.push(`${s.name} ${s.enabled ? "켜짐" : "꺼짐"}`);
    if (s.name !== ls.name) changes.push(`시나리오 이름 변경됨 — ${ls.name} → ${s.name}`);
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
      changes.push(`${s.name} 감지 조건 변경됨`);
    if (Number(s.cooldown) !== Number(ls.cooldown))
      changes.push(`${s.name} 재판정 간격 ${s.cooldown}초로 변경됨`);
  }
  for (const s of liveConfig.scenarios || [])
    if (!(draft.scenarios || []).some((d) => d.id === s.id))
      changes.push(`시나리오 삭제됨 — ${s.name}`);

  const liveAct = Object.fromEntries((liveConfig.actions || []).map((a) => [a.id, a]));
  const cname = (ids) => (ids || []).map((id) =>
    ((draft.contacts || []).find((c) => c.id === id)
      || (liveConfig.contacts || []).find((c) => c.id === id) || {}).name || "?");
  for (const a of draft.actions || []) {
    if (!liveAct[a.id]) { changes.push(`행동 추가됨 — ${a.name}`); continue; }
    const la = liveAct[a.id];
    if (a.name !== la.name || a.description !== la.description)
      changes.push(`행동 수정됨 — ${a.name}`);
    const x = cname(a.notifyContactIds).join(", ");
    const y = cname(la.notifyContactIds).join(", ");
    if (x !== y) changes.push(`${a.name} 연락 대상 변경됨 — ${x || "없음"}`);
  }
  for (const a of liveConfig.actions || [])
    if (!(draft.actions || []).some((d) => d.id === a.id)) changes.push(`행동 삭제됨 — ${a.name}`);

  const liveCt = Object.fromEntries((liveConfig.contacts || []).map((c) => [c.id, c]));
  for (const c of draft.contacts || [])
    if (!liveCt[c.id]) changes.push(`연락처 등록됨 — ${c.name} (${c.relation})`);
  for (const c of liveConfig.contacts || [])
    if (!(draft.contacts || []).some((d) => d.id === c.id)) changes.push(`연락처 삭제됨 — ${c.name}`);
  const draftIds = (draft.contacts || []).map((c) => c.id).join(",");
  const liveIds = (liveConfig.contacts || []).map((c) => c.id).join(",");
  if (draftIds !== liveIds && !changes.some((c) => c.startsWith("연락처")))
    changes.push("연락처 우선순위 변경됨");
  return changes;
}

const StoreCtx = createContext(null);

export function StoreProvider({ children }) {
  const { status } = useAuth();
  const [draft, setDraft] = useState(() => clone(EMPTY));
  const [live, setLive] = useState({ version: 0, publishedAt: "", config: clone(EMPTY) });
  const [versions, setVersions] = useState([]);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const timer = useRef(null);
  const pending = useRef(null);

  const load = useCallback(async () => {
    try {
      const data = await getConfig();
      setDraft(toClient(data.draft));

      /* /config는 배포된 설정의 요약(버전·시각)만 준다. 변경 목록을 화면에서
         계산하려면 배포된 내용 자체가 필요하므로 현재 버전을 따로 가져온다. */
      const version = data.live?.version ?? 0;
      let liveConfig = clone(EMPTY);
      if (version) {
        try {
          liveConfig = toClient((await getVersion(version)).config);
        } catch {
          /* 내용을 못 가져와도 화면은 열어둔다. 변경 목록이 과하게 표시될 뿐이다. */
        }
      }
      setLive({ version, publishedAt: data.live?.published_at || "", config: liveConfig });
      setVersions((data.versions || []).map((v) => ({
        version: v.version,
        publishedAt: v.published_at,
        changes: changeTexts(v.changes),
        rolledBackFrom: v.rolled_back_from,
      })));
      setReady(true);
      setError("");
    } catch (e) {
      setError(e.message);
      setReady(true); // 화면은 열어두고 오류를 보여준다 — 빈 화면보다 낫다
    }
  }, []);

  useEffect(() => {
    if (status === "ok") load();
    if (status === "no") { setReady(false); setDraft(clone(EMPTY)); }
  }, [status, load]);

  /* 편집을 서버에 저장한다. 타이핑 중에는 미뤘다가 잠잠해지면 한 번 보낸다. */
  const scheduleSave = useCallback((next) => {
    pending.current = next;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const bundle = pending.current;
      pending.current = null;
      setSaving(true);
      try {
        await putDraft(toServer(bundle));
        setError("");
      } catch (e) {
        setError(`저장하지 못했습니다 — ${e.message}`);
      } finally {
        setSaving(false);
      }
    }, SAVE_DELAY);
  }, []);

  /* 배포처럼 저장이 반영돼야 하는 동작 전에는 밀린 것을 먼저 보낸다 */
  const flush = useCallback(async () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    if (!pending.current) return;
    const bundle = pending.current;
    pending.current = null;
    await putDraft(toServer(bundle));
  }, []);

  const update = (fn) =>
    setDraft((prev) => {
      const next = clone(prev);
      fn(next);
      scheduleSave(next);
      return next;
    });

  const api = {
    ready,
    saving,
    error,
    draft,
    live,
    versions,
    changes: computeChanges(draft, live.config),
    reload: load,

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

    publish: async () => {
      setError("");
      try {
        await flush();
        await publishConfig();
        await load();
      } catch (e) {
        /* 검증 실패는 detail.errors로 온다. 무엇이 잘못됐는지 그대로 보여준다 —
           "배포 실패"만 띄우면 무엇을 고쳐야 할지 알 수 없다. */
        setError(`배포하지 못했습니다 — ${e.message}`);
      }
    },

    /* 편집 상태로만 불러오기 (확인 후 직접 배포) */
    rollback: async (version) => {
      try {
        const v = await getVersion(version);
        const next = toClient(v.config);
        setDraft(next);
        scheduleSave(next);
      } catch (e) {
        setError(e.message);
      }
    },

    /* 즉시 롤백 — 해당 버전 설정을 새 버전으로 바로 배포 */
    rollbackNow: async (version) => {
      setError("");
      try {
        await flush();
        await rollbackTo(version);
        await load();
      } catch (e) {
        setError(`롤백하지 못했습니다 — ${e.message}`);
      }
    },
  };

  return <StoreCtx.Provider value={api}>{children}</StoreCtx.Provider>;
}

export function useStore() {
  return useContext(StoreCtx);
}
