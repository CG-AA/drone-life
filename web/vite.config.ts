import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const root = fileURLToPath(new URL(".", import.meta.url));

// dev proxy target: DL_SERVER=http://host:port make dev-web (default local)
const target = process.env.DL_SERVER ?? "http://127.0.0.1:8000";

export default defineConfig({
  // relative asset URLs: one build serves `/` and every `/rN/` room behind the
  // proxy (docs/ROOMS.md); all three pages sit at dist root, so `./assets/…`
  // resolves the same from `/rN/submit` and `/rN/`
  base: "./",
  build: {
    // a classroom failure gets debugged from a projector console: readable traces
    sourcemap: true,
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
      "/api": target,
      "/ws": { target: target.replace(/^http/, "ws"), ws: true },
    },
  },
});
