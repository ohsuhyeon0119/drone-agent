import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8004",
      // 모니터링에서 노트북 카메라·마이크를 쓸 때 에이전트의 미디어 처리 코드를
      // 그대로 불러온다 — 복사해두면 한쪽만 고쳐졌을 때 오디오가 조용히 깨진다
      "/agent-static": "http://localhost:8004",
      // 모니터링 화면이 세션을 들여다보는 관전 채널 (ws: true가 없으면
      // 업그레이드 요청이 프록시되지 않아 연결이 그냥 실패한다)
      "/ws": {
        target: "ws://localhost:8004",
        ws: true,
        // 관전 소켓이 끊길 때(에이전트 서버 재시작, 폰이 대화 종료) 나는
        // ECONNRESET을 받아주지 않으면 dev 서버 프로세스가 통째로 죽는다.
        // 개발 중에 서버를 다시 띄울 때마다 콘솔이 사라지는 원인이었다.
        configure: (proxy) => {
          proxy.on("error", (err) => {
            console.warn(`[proxy] 관전 소켓 오류(무시): ${err.message}`);
          });
        },
      },
    },
  },
});
