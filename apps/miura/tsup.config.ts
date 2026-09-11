import { defineConfig } from "tsup"

export default defineConfig({
	entry: ["src/index.ts"],
	format: ["esm"],
	dts: true,
	clean: true,
	sourcemap: true,
	target: "node23",
	platform: "node",
	// Restaura el import node:sqlite que esbuild reescribe (ver scripts/fix-sqlite.mjs)
	onSuccess: "node scripts/fix-sqlite.mjs",
	banner: {
		js: "#!/usr/bin/env node",
	},
	esbuildOptions(options) {
		// Enable JSX for React/Ink components
		options.jsx = "automatic"
		options.jsxImportSource = "react"
	},
})
