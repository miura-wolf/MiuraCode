import fs from "fs"
import os from "os"
import path from "path"

export interface MiuraSettings {
	/** URL base del proxy Atomic AI (sin /v1). */
	proxyUrl: string
	/** Modelo/carril por defecto (p. ej. "miura-fast" o el modelo orquestado). */
	model: string
	/** System prompt opcional que se antepone a cada sesión. */
	systemPrompt: string
}

export const DEFAULT_SETTINGS: MiuraSettings = {
	proxyUrl: "http://127.0.0.1:8120",
	model: "miura-fast",
	systemPrompt: "",
}

/** Directorio de configuración (~/.miuracode): settings.json + miura.db.
 * MIURA_CONFIG_DIR permite sobreescribirlo (tests, entornos aislados). */
export function getConfigDir(): string {
	return process.env.MIURA_CONFIG_DIR || path.join(os.homedir(), ".miuracode")
}

export function ensureConfigDir(): void {
	fs.mkdirSync(getConfigDir(), { recursive: true })
}

function getSettingsPath(): string {
	return path.join(getConfigDir(), "settings.json")
}

export function loadSettings(): MiuraSettings {
	try {
		const raw = fs.readFileSync(getSettingsPath(), "utf8")
		const parsed = JSON.parse(raw) as Partial<MiuraSettings>
		return { ...DEFAULT_SETTINGS, ...parsed }
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") {
			return { ...DEFAULT_SETTINGS }
		}
		throw error
	}
}

export function saveSettings(patch: Partial<MiuraSettings>): MiuraSettings {
	const next = { ...loadSettings(), ...patch }
	ensureConfigDir()
	fs.writeFileSync(getSettingsPath(), JSON.stringify(next, null, 2) + "\n")
	return next
}

/** Settings con overrides de entorno (MIURA_PROXY_URL / MIURA_MODEL), para CI y scripts. */
export function resolveSettings(): MiuraSettings {
	const settings = loadSettings()
	return {
		...settings,
		proxyUrl: process.env.MIURA_PROXY_URL || settings.proxyUrl,
		model: process.env.MIURA_MODEL || settings.model,
	}
}
