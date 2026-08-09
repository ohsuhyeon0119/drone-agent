import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { getProfile, login } from "../api.js";
import { useAuth } from "../auth.jsx";
import AuthLayout from "../components/AuthLayout.jsx";
import { Button, Field, inputCls } from "../components/ui.jsx";

export default function Login() {
  const navigate = useNavigate();
  const { status, markLoggedIn } = useAuth();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      markLoggedIn(await login(email.trim(), pw));
      /* 어르신 정보가 아직 없으면 설정 화면 대신 온보딩으로 보낸다 —
         빈 시나리오 목록을 먼저 보여주면 무엇부터 해야 할지 알 수 없다. */
      const { onboarded } = await getProfile();
      navigate(onboarded ? "/scenarios" : "/onboarding", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  // 이미 로그인된 상태로 /login에 오면 되돌린다
  if (status === "ok") return <Navigate to="/scenarios" replace />;

  return (
    <AuthLayout title="로그인" sub="보호자 계정으로 들어오세요.">
      <form onSubmit={submit}>
        <Field label="이메일">
          <input
            className={inputCls}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            autoFocus
          />
        </Field>
        <Field label="비밀번호">
          <input
            className={inputCls}
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            autoComplete="current-password"
          />
        </Field>

        {error && <p role="alert" className="text-warn text-[24px] mb-4">{error}</p>}

        <Button
          variant="primary"
          type="submit"
          disabled={busy || !email.trim() || !pw}
          className="w-full h-16 text-[30px] mt-3"
        >
          {busy ? "확인 중…" : "로그인"}
        </Button>

        <p className="text-muted text-[24px] mt-6 text-center">
          아직 계정이 없으신가요?{" "}
          <Link to="/signup" className="text-accent font-bold hover:underline">회원가입</Link>
        </p>
      </form>
    </AuthLayout>
  );
}
