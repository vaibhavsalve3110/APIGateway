import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on :8088 by default; override with API_TARGET=http://host:port.
// "^/api/" (not "/api") so SPA routes such as /apis are served by Vite, not proxied.
const target = process.env.API_TARGET ?? "http://localhost:8088";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "^/api/": target },
  },
  preview: { port: 4173, proxy: { "^/api/": target } },
});
