import { defineConfig } from "vite";

// base "./" — сборка открывается из файла внутри Electron (file://)
export default defineConfig({
  base: "./",
  server: { port: 5173, strictPort: true, host: "127.0.0.1" },
  build: { outDir: "dist", emptyOutDir: true, target: "es2022", assetsInlineLimit: 0 },
  test: {
    environment: "jsdom",
    include: ["../tests/app/**/*.test.ts"],
  },
});
