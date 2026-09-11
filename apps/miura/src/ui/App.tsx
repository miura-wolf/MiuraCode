import { useState } from "react"
import { render } from "ink"

import type { MiuraSettings } from "@/lib/config.js"
import type { MemoryStore } from "@/lib/memory.js"
import type { SessionRow, Store } from "@/lib/store.js"
import { SessionView } from "@/ui/SessionView.js"

export interface MiuraAppProps {
	store: Store
	memory: MemoryStore
	session: SessionRow
	settings: MiuraSettings
}

/** Raíz del TUI: mantiene la sesión activa y permite saltar a una nueva (/new). */
export function MiuraApp({ store, memory, session, settings }: MiuraAppProps) {
	const [current, setCurrent] = useState<SessionRow>(session)
	return (
		<SessionView
			key={current.id}
			store={store}
			memory={memory}
			session={current}
			settings={settings}
			onNewSession={() => setCurrent(store.createSession(current.model))}
		/>
	)
}

/** Monta el TUI en el terminal y espera a que el usuario salga. */
export async function runTui(props: MiuraAppProps): Promise<void> {
	const instance = render(<MiuraApp {...props} />)
	await instance.waitUntilExit()
}
