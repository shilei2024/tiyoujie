import { defineConfig } from "vite";
import uni from "@dcloudio/vite-plugin-uni";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

if (process.argv.includes("--ssr") || process.env.UNI_SSR === "true") {
  throw new Error("SSR is not enabled for this client-only toolchain.");
}

export default defineConfig({
  plugins: [
    uni(),
    {
      name: "build-dependency-evidence",
      generateBundle(_options, bundle) {
        const modules = Object.values(bundle).flatMap((item) =>
          item.type === "chunk" ? Object.keys(item.modules) : [],
        );
        const dir = resolve(process.cwd(), "../artifacts");
        mkdirSync(dir, { recursive: true });
        writeFileSync(
          resolve(dir, `frontend-modules-${process.env.UNI_PLATFORM}.json`),
          JSON.stringify({
            platform: process.env.UNI_PLATFORM,
            bracesIncluded: modules.some((id) =>
              /node_modules[/\\]braces[/\\]/.test(id),
            ),
            moduleCount: modules.length,
          }),
        );
      },
    },
  ],
  server: {
    host: "127.0.0.1",
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:18000" } },
  },
});
