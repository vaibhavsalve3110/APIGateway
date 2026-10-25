import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Where /api goes in development. Override with API_TARGET=http://host:port.
//
// 127.0.0.1:18090 is backend-python as the container stack publishes it, which is the right default
// now: nginx routes every admin route there, and Approvals and APIM users exist only on that
// service. It used to default to :8088, which nothing listens on once the backends run in
// containers — so `npm run dev` proxied into a closed port.
//
// For the Java control plane instead, API_TARGET=http://127.0.0.1:18088.
//
// "^/api/" (not "/api") so SPA routes such as /apis are served by Vite, not proxied.
const target = process.env.API_TARGET ?? "http://127.0.0.1:18090";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "^/api/": target },
  },
  preview: { port: 4173, proxy: { "^/api/": target } },
});
