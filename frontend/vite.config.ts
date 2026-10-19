import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

/** Backend origin used by the dev server proxy. */
const BACKEND = process.env.VITE_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@assets": fileURLToPath(new URL("../assets", import.meta.url)),
    },
  },
  build: {
    // Flask serves this directory directly (see backend/server/app.py).
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    proxy: {
      // MJPEG must not be buffered, so the proxy streams these through as-is.
      "/api": { target: BACKEND, changeOrigin: true },
      "/assets-lib": { target: BACKEND, changeOrigin: true },
      "/socket.io": { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
});
