import path from "path"
import { defineConfig } from "vitest/config"

export default defineConfig({
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
		},
	},
	test: {
		globals: true,
		environment: "node",
		watch: false,
		testTimeout: 60_000,
		include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
	},
})
