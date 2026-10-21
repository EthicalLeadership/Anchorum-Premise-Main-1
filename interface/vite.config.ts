import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // pdfjs-dist ships its own worker bundle and is loaded through a `?url`
  // import. Letting Vite pre-bundle it produces a second copy of the worker
  // under a hashed name, and the PDF then fails to render with a
  // "setting up fake worker failed" error. Excluding it keeps the `?url`
  // import pointing at the real asset in dev and in the build.
  optimizeDeps: {
    exclude: ["pdfjs-dist"],
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    // Tests always run against the fixture adapter.
    //
    // Vite loads dotenv files for every mode, `test` included, so a developer
    // pointing the dev UI at a local backend in `.env.local` (for example
    // `VITE_API_BASE_URL=http://127.0.0.1:8011`) also redirected the test suite
    // to the network adapter. Every test that expects fixture data then failed
    // against an unreachable host, and `App` rendered its not-found state, which
    // is something an ambient `.env.local` must never be able to cause.
    //
    // Blanking it here keeps the suite deterministic and leaves `.env.local` to
    // do its job for `npm run dev`.
    env: { VITE_API_BASE_URL: "" },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
