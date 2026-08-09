import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { UNAUTHORIZED_EVENT, clearToken, getToken, me } from "./api.js";

/* 로그인 여부는 서버에 물어서 정한다.
   브라우저에 남은 값만 보고 통과시키면 로그인한 적 없는 사람도 주소를 직접
   치면 관리 화면이 열리고, 토큰이 만료돼도 계속 열려 있게 된다. */

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // checking → 서버 확인 중, ok → 로그인됨, no → 로그인 필요
  const [status, setStatus] = useState(() => (getToken() ? "checking" : "no"));
  /* 지금 어느 계정으로 들어와 있는지는 화면에 보여야 한다 — 계정마다 돌보는
     어르신이 다르므로, 잘못된 계정으로 설정을 고치면 엉뚱한 곳에 배포된다. */
  const [user, setUser] = useState(null);

  const verify = useCallback(async () => {
    if (!getToken()) {
      setStatus("no");
      return;
    }
    try {
      const data = await me();
      setUser({ email: data.email, name: data.name });
      setStatus("ok");
    } catch {
      /* 401이면 api.js가 토큰을 이미 지웠다. 서버가 꺼져 있는 등 다른 이유로
         실패한 경우에도 통과시키지 않는다 — 확인되지 않으면 못 들어간다. */
      clearToken();
      setUser(null);
      setStatus("no");
    }
  }, []);

  useEffect(() => { verify(); }, [verify]);

  // 화면을 쓰던 중 토큰이 만료되면 어느 요청에서든 즉시 로그인으로 돌린다
  useEffect(() => {
    const onUnauthorized = () => { setUser(null); setStatus("no"); };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const value = {
    status,
    user,
    markLoggedIn: (info) => {
      if (info) setUser({ email: info.email, name: info.name });
      setStatus("ok");
    },
    logout: () => { clearToken(); setUser(null); setStatus("no"); },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth는 AuthProvider 안에서만 쓸 수 있습니다.");
  return ctx;
}

export function RequireAuth({ children }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "checking") {
    /* 확인이 끝나기 전에 화면을 그리면, 로그인되지 않은 사람에게도 관리 화면이
       한순간 보였다가 사라진다. */
    return (
      <div className="min-h-screen flex items-center justify-center text-muted text-[26px]">
        확인 중…
      </div>
    );
  }
  if (status === "no") {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return children;
}
