import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8004",
      // 모니터링 화면이 세션을 들여다보는 관전 채널 (ws: true가 없으면
      // 업그레이드 요청이 프록시되지 않아 연결이 그냥 실패한다)
      "/ws": { target: "ws://localhost:8004", ws: true },
    },
  },
});
