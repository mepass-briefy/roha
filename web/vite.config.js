import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 같은 컴퓨터의 FastAPI(8000)로 프록시 -> 브라우저는 same-origin(5173)으로 호출하므로 CORS 불필요(API 무수정).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/projects": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
