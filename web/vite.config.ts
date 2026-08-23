import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: `${root}index.html`,
        submit: `${root}submit.html`,
        admin: `${root}admin.html`,
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/healthz": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
