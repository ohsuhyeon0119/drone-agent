import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { signup } from "../api.js";
import { useAuth } from "../auth.jsx";
import AuthLayout from "../components/AuthLayout.jsx";
import { Button, Field, inputCls } from "../components/ui.jsx";

const MIN_PASSWORD = 8;

export default function Signup() {
  const navigate = useNavigate();
  const { status, markLoggedIn } = useAuth();
  const [form, setForm] = useState({ name: "", email: "", password: "", confirm: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  /* 서버도 같은 규칙으로 검증하지만, 여기서 먼저 알려줘야 요청을 보내고 나서야
     틀린 걸 아는 일이 없다. 비밀번호 확인은 서버가 알 수 없으므로 여기서만 본다. */
  const mismatch = form.confirm.length > 0 && form.password !== form.confirm;
  const tooShort = form.password.length > 0 && form.password.length < MIN_PASSWORD;
  const ready =
    form.name.trim() && form.email.trim() && form.password.length >= MIN_PASSWORD &&
    form.password === form.confirm;

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      markLoggedIn(await signup(form.email.trim(), form.password, form.name.trim()));
      /* 가입 직후에는 어르신 정보가 당연히 없으므로 곧장 온보딩으로 보낸다. */
      navigate("/onboarding", { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (status === "ok") return <Navigate to="/scenarios" replace />;

  return (
    <AuthLayout title="회원가입" sub="어르신을 돌보실 보호자 계정을 만듭니다.">
      <form onSubmit={submit}>
        <Field label="이름" help="어르신이 아니라 보호자님 성함입니다.">
          <input
            className={inputCls}
            value={form.name}
            onChange={set("name")}
            autoComplete="name"
            autoFocus
          />
        </Field>

        <Field label="이메일">
          <input
            className={inputCls}
            type="email"
            value={form.email}
            onChange={set("email")}
            autoComplete="email"
          />
        </Field>

        <Field label="비밀번호" help={`${MIN_PASSWORD}자 이상`}>
          <input
            className={inputCls}
            type="password"
            value={form.password}
            onChange={set("password")}
            autoComplete="new-password"
          />
          {tooShort && (
            <span className="block text-warn text-[16px] mt-1.5">
              {MIN_PASSWORD}자 이상으로 만들어 주세요.
            </span>
          )}
        </Field>

        <Field label="비밀번호 확인">
          <input
            className={inputCls}
            type="password"
            value={form.confirm}
            onChange={set("confirm")}
            autoComplete="new-password"
          />
          {mismatch && (
            <span className="block text-warn text-[16px] mt-1.5">
              비밀번호가 서로 다릅니다.
            </span>
          )}
        </Field>

        {error && <p role="alert" className="text-warn text-[18px] mb-4">{error}</p>}

        <Button
          variant="primary"
          type="submit"
          disabled={busy || !ready}
          className="w-full h-16 text-[22px] mt-3"
        >
          {busy ? "만드는 중…" : "가입하고 시작하기"}
        </Button>

        <p className="text-muted text-[18px] mt-6 text-center">
          이미 계정이 있으신가요?{" "}
          <Link to="/login" className="text-accent font-bold hover:underline">로그인</Link>
        </p>
      </form>
    </AuthLayout>
  );
}
