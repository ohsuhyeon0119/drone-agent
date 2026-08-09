import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // 백엔드(FastAPI :8004) 연결 시 사용 — 목데이터 단계에서는 미사용
    proxy: { "/api": "http://localhost:8004" },
  },
});
