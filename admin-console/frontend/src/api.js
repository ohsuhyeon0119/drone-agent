/* 서버(FastAPI /api/admin) 호출.
   시나리오·행동은 아직 store.jsx의 목데이터를 쓰고, 로그인과 온보딩만 실제
   서버를 탄다 — 인터뷰는 답변을 슬롯 값으로 옮기고 프로필을 저장해야 해서
   브라우저 안에서 끝낼 수 없기 때문이다. */

const TOKEN_KEY = "donghaeng-token";

/* 토큰이 만료·위조됐을 때 화면이 알아야 하므로, 401을 받으면 이 이벤트를 쏘고
   AuthProvider가 로그인 화면으로 되돌린다. 예전에는 localStorage의 불리언
   플래그 하나로 판단해서, 한 번 켜지면 서버 상태와 무관하게 계속 통과했다. */
export const UNAUTHORIZED_EVENT = "donghaeng:unauthorized";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("donghaeng-authed"); // 예전 버전이 남긴 값 정리
}

async function request(path, { method = "GET", body } = {}) {
  const res = await fetch(`/api/admin${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

  if (res.status === 401) {
    clearToken();
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new Error("로그인이 필요합니다.");
  }
  if (!res.ok) {
    /* 서버가 detail에 메시지를 담아 보낸다. 없으면 상태 코드라도 보여준다 —
       "알 수 없는 오류"만 띄우면 무엇을 고쳐야 할지 알 수 없다. */
    let detail = `요청이 실패했습니다 (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* 본문이 JSON이 아니면 기본 메시지를 쓴다 */
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function login(email, password) {
  const data = await request("/login", { method: "POST", body: { email, password } });
  localStorage.setItem(TOKEN_KEY, data.token);
  return data;
}

/** 가입하면 바로 로그인된 상태가 된다 — 방금 만든 계정으로 또 로그인시킬 이유가 없다. */
export async function signup(email, password, name) {
  const data = await request("/signup", { method: "POST", body: { email, password, name } });
  localStorage.setItem(TOKEN_KEY, data.token);
  return data;
}

/** 토큰이 아직 유효한지 서버에 물어본다. 화면을 그리기 전 관문. */
export const me = () => request("/me");

export const getConfig = () => request("/config");
export const putDraft = (config) => request("/draft", { method: "PUT", body: { config } });
export const publishConfig = () => request("/publish", { method: "POST" });
export const rollbackTo = (version) => request(`/rollback/${version}`, { method: "POST" });
export const getVersion = (version) => request(`/versions/${version}`);

/* 어르신 폰에 넣을 6자 코드. 보호자는 이메일·비밀번호로 들어오지만 어르신에게
   그걸 시킬 수는 없어서, 폰은 이 코드 하나로 자기가 누구 곁인지 증명한다. */
export const getPairCode = () => request("/pair-code");
export const regeneratePairCode = () => request("/pair-code/regenerate", { method: "POST" });

export const getProfile = () => request("/profile");
export const putProfile = (profile) => request("/profile", { method: "PUT", body: { profile } });

export const startInterview = () => request("/onboarding/start");
export const answerInterview = (payload) =>
  request("/onboarding/answer", { method: "POST", body: payload });
export const finishInterview = (answers) =>
  request("/onboarding/finish", { method: "POST", body: { answers } });
