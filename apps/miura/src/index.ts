import fs from "fs"
import { Command } from "commander"

import { resolveSettings } from "@/lib/config.js"
import { listModels } from "@/lib/client.js"
import { MemoryStore } from "@/lib/memory.js"
import { Store, defaultDbPath } from "@/lib/store.js"
import { runTui } from "@/ui/App.js"

const program = new Command()

program
	.name("miura")
	.description("TUI de chat persistente sobre el proxy Atomic AI (sesiones SQLite+FTS5)")
	.version("0.1.0")

program
	.option("-c, --continue-chat", "continúa la sesión más reciente")
	.option("-r, --resume <id>", "reanuda una sesión por UUID (o prefijo único)")
	.option("-m, --model <model>", "modelo/carril para esta sesión (p. ej. miura-fast)")
	.action(async (options: { continueChat?: boolean; resume?: string; model?: string }) => {
		const settings = resolveSettings()
		const store = new Store()
		const memory = new MemoryStore(store.database)
		try {
			let session
			if (options.resume) {
				session = store.resolveSession(options.resume)
			} else if (options.continueChat) {
				session = store.latestSession() ?? store.createSession(settings.model)
			} else {
				session = store.createSession(options.model || settings.model)
			}
			if (options.model && session.model !== options.model) {
				store.setSessionModel(session.id, options.model)
				session.model = options.model
			}
			await runTui({ store, memory, session, settings })
		} finally {
			store.close()
		}
	})

program
	.command("sessions")
	.description("lista sesiones recientes")
	.action(() => {
		const store = new Store()
		try {
			const rows = store.listSessions(20)
			if (rows.length === 0) {
				console.log("sin sesiones — ejecuta `miura` para empezar a chatear")
				return
			}
			for (const s of rows) {
				const date = s.updated_at.slice(0, 16).replace("T", " ")
				console.log(`${s.id.slice(0, 8)}  ${date}  ${s.title || "(sin título)"}  [${s.message_count} msg]`)
			}
		} finally {
			store.close()
		}
	})

program
	.command("search <query...>")
	.description("busca en el historial de todas las sesiones (FTS5)")
	.action((query: string[]) => {
		const store = new Store()
		try {
			const hits = store.searchMessages(query.join(" "))
			if (hits.length === 0) {
				console.log("sin resultados")
				return
			}
			for (const h of hits) {
				console.log(`${h.session_id.slice(0, 8)}  ${h.snippet}`)
			}
		} finally {
			store.close()
		}
	})

program
	.command("models")
	.description("lista los carriles/modelos que expone el proxy")
	.action(async () => {
		const settings = resolveSettings()
		try {
			const models = await listModels(settings.proxyUrl)
			for (const m of models) {
				console.log(m)
			}
		} catch (err) {
			console.error(`no se pudo consultar ${settings.proxyUrl}/v1/models: ${String(err).slice(0, 200)}`)
			process.exitCode = 1
		}
	})

program
	.command("config")
	.description("muestra la configuración efectiva")
	.action(() => {
		const settings = resolveSettings()
		console.log(`proxyUrl:     ${settings.proxyUrl}`)
		console.log(`model:        ${settings.model}`)
		console.log(`systemPrompt: ${settings.systemPrompt || "(vacío)"}`)
		console.log(`config dir:   ${process.env.MIURA_CONFIG_DIR || "~/.miuracode"}`)
		console.log(`database:     ${defaultDbPath()}`)
		console.log(`db exists:    ${fs.existsSync(defaultDbPath())}`)
	})

await program.parseAsync()
