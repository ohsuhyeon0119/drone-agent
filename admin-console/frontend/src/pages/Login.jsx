import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Field, inputCls } from "../components/ui.jsx";

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [error, setError] = useState("");

  const submit = (e) => {
    e.preventDefault();
    if (!email.includes("@")) {
      setError("이메일 형식이 올바르지 않습니다.");
      return;
    }
    if (pw.length < 4) {
      setError("비밀번호를 다시 확인해 주세요.");
      return;
    }
    localStorage.setItem("donghaeng-authed", "1");
    navigate("/scenarios");
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-[480px] bg-surface border border-line rounded-(--radius-card) p-10 sm:p-12">
        <div className="mb-10">
          <div className="text-[24px] font-bold tracking-[0.18em] text-accent mb-5">DONGHAENG</div>
          <h1 className="text-[49px] font-bold leading-snug [text-wrap:balance]">
            노후를 함께 나는<br />동행자
          </h1>
          <p className="text-muted mt-3">돌봄 에이전트를 우리 집에 맞게 설계하는 콘솔</p>
        </div>

        <Field label="이메일">
          <input
            className={inputCls}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
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

        {error && (
          <p role="alert" className="text-warn text-[24px] mb-4">{error}</p>
        )}

        <Button variant="primary" type="submit" className="w-full h-14 text-[30px] mt-2">
          로그인
        </Button>
      </form>
    </div>
  );
}
