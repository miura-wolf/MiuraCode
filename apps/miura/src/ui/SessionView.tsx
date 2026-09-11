import { useCallback, useRef, useState } from "react"
import { Box, Text, useApp, useInput } from "ink"

import { MiuraApiError, streamChat } from "@/lib/client.js"
import type { MiuraSettings } from "@/lib/config.js"
import type { MemoryStore } from "@/lib/memory.js"
import type { MessageRow, SessionRow, Store } from "@/lib/store.js"
import { buildChatContext } from "@/lib/sessions.js"
import { SLASH_COMMANDS, parseRemember } from "@/ui/commands.js"

export interface SessionViewProps {
	store: Store
	memory: MemoryStore
	session: SessionRow
	settings: MiuraSettings
	onNewSession: () => void
}

interface StreamState {
	content: string
	reasoningChars: number
}

/** Vista de chat de una sesión: historial, streaming y slash-commands. */
export function SessionView({ store, memory, session, settings, onNewSession }: SessionViewProps) {
	const { exit } = useApp()
	const [model, setModel] = useState(session.model || settings.model)
	const [messages, setMessages] = useState<MessageRow[]>(() => store.getMessages(session.id))
	const [input, setInput] = useState("")
	const [busy, setBusy] = useState(false)
	const [stream, setStream] = useState<StreamState | null>(null)
	const [error, setError] = useState<string | null>(null)
	const [notice, setNotice] = useState<string | null>(null)
	const inputHistory = useRef<string[]>([])
	const historyIndex = useRef(-1)

	const visible = messages.slice(-100)

	const send = useCallback(
		async (text: string) => {
			const trimmed = text.trim()
			if (!trimmed || busy) {
				return
			}
			if (trimmed.startsWith("/")) {
				handleSlash(trimmed)
				return
			}
			setBusy(true)
			setError(null)
			setNotice(null)
			setStream({ content: "", reasoningChars: 0 })
			const userRow = store.appendMessage(session.id, "user", trimmed)
			setMessages((prev) => [...prev, userRow])

			const chat = buildChatContext(store, memory, session.id, settings.systemPrompt)
			try {
				const result = await streamChat({
					proxyUrl: settings.proxyUrl,
					model,
					messages: chat,
					onContent: (chunk) =>
						setStream((s) => ({
							content: (s?.content ?? "") + chunk,
							reasoningChars: s?.reasoningChars ?? 0,
						})),
					onReasoning: () =>
						setStream((s) => ({ content: s?.content ?? "", reasoningChars: (s?.reasoningChars ?? 0) + 1 })),
				})
				const assistantRow = store.appendMessage(session.id, "assistant", result.content, result.reasoning)
				setMessages((prev) => [...prev, assistantRow])
				if (!result.content) {
					setNotice(
						"⚠ el modelo no emitió contenido (¿razonador puro? prueba /model miura-reasoner o un carril NIM)",
					)
				}
			} catch (err) {
				const msg = err instanceof MiuraApiError ? err.message : String(err)
				setError(msg.slice(0, 400))
				store.appendMessage(session.id, "assistant", `(error: ${msg.slice(0, 200)})`)
			} finally {
				setStream(null)
				setBusy(false)
			}
		},
		[busy, memory, model, session.id, settings.proxyUrl, settings.systemPrompt, store],
	)

	const handleSlash = useCallback(
		(cmd: string) => {
			const parts = cmd.split(/\s+/)
			const name = parts[0]
			const arg = parts.slice(1).join(" ")
			switch (name) {
				case "/help":
					setNotice(SLASH_COMMANDS.map((c) => `${c.usage.padEnd(28)} ${c.description}`).join("\n"))
					break
				case "/exit":
					exit()
					break
				case "/new":
					onNewSession()
					break
				case "/model":
					if (!arg) {
						setNotice(`modelo actual: ${model}`)
					} else {
						setModel(arg)
						store.setSessionModel(session.id, arg)
						setNotice(`modelo → ${arg}`)
					}
					break
				case "/title":
					if (!arg) {
						setNotice(`título actual: ${session.title || "(sin título)"}`)
					} else {
						store.renameSession(session.id, arg)
						session.title = arg
						setNotice(`título → ${arg}`)
					}
					break
				case "/search": {
					if (!arg) {
						setNotice("uso: /search <texto>")
						break
					}
					const hits = store.searchMessages(arg)
					setNotice(
						hits.length === 0
							? `sin resultados para "${arg}"`
							: hits.map((h) => `${h.session_id.slice(0, 8)}  ${h.snippet}`).join("\n"),
					)
					break
				}
				case "/memory": {
					const rows = memory.listMemory(30)
					setNotice(
						rows.length === 0
							? "memoria vacía — usa /remember clave=valor"
							: rows.map((m) => `${m.key}: ${m.value}`).join("\n"),
					)
					break
				}
				case "/remember": {
					const parsed = parseRemember(arg)
					if (!parsed) {
						setNotice("uso: /remember clave=valor")
					} else {
						memory.addMemory(parsed.key, parsed.value)
						setNotice(`recordado: ${parsed.key} = ${parsed.value}`)
					}
					break
				}
				case "/forget":
					if (!arg) {
						setNotice("uso: /forget clave")
					} else {
						setNotice(memory.deleteMemory(arg) ? `olvidado: ${arg}` : `no existía: ${arg}`)
					}
					break
				case "/sessions": {
					const rows = store.listSessions(15)
					setNotice(
						rows
							.map((s) => `${s.id.slice(0, 8)}  ${s.title || "(sin título)"}  [${s.message_count}]`)
							.join("\n"),
					)
					break
				}
				default:
					setNotice(`comando desconocido: ${name} — /help para ayuda`)
			}
		},
		[exit, memory, model, onNewSession, session, store],
	)

	useInput((char, key) => {
		if (key.return) {
			const text = input
			setInput("")
			historyIndex.current = -1
			if (text.trim()) {
				inputHistory.current.push(text)
			}
			void send(text)
			return
		}
		if (key.backspace || key.delete) {
			setInput((t) => t.slice(0, -1))
			return
		}
		if (key.upArrow) {
			const h = inputHistory.current
			if (h.length > 0) {
				const next = Math.min(h.length - 1, historyIndex.current + 1)
				historyIndex.current = next
				setInput(h.at(h.length - 1 - next) ?? "")
			}
			return
		}
		if (key.downArrow) {
			const h = inputHistory.current
			if (historyIndex.current > 0) {
				historyIndex.current -= 1
				setInput(h.at(h.length - 1 - historyIndex.current) ?? "")
			} else {
				historyIndex.current = -1
				setInput("")
			}
			return
		}
		if (key.ctrl && char === "c") {
			if (input) {
				setInput("")
			} else {
				exit()
			}
			return
		}
		if (key.escape) {
			setInput("")
			setNotice(null)
			return
		}
		if (char && !key.ctrl && !key.meta) {
			setInput((t) => t + char)
		}
	})

	return (
		<Box flexDirection="column" height={process.stdout.rows || 30}>
			<Box borderStyle="round" borderColor="magenta" flexDirection="column" paddingX={1}>
				<Text color="magenta">miura</Text>
				<Text color="gray">
					sesión {session.id.slice(0, 8)} · modelo {model} · {messages.length} mensajes · /help
				</Text>
			</Box>
			<Box flexDirection="column" paddingX={1} flexGrow={1} overflow="hidden">
				{visible.map((m) => (
					<Box key={m.id} flexDirection="row">
						<Text color={m.role === "user" ? "cyan" : "magenta"}>
							{m.role === "user" ? "tú ›" : "miura ›"}
						</Text>
						<Box flexDirection="column" marginLeft={1}>
							<Text>{m.content}</Text>
						</Box>
					</Box>
				))}
				{stream && (
					<Box flexDirection="row">
						<Text color="magenta">miura ›</Text>
						{stream.content ? (
							<Text>{stream.content.split("\n").slice(-3).join("\n")}</Text>
						) : (
							<Text color="gray">
								{stream.reasoningChars > 0
									? `razonando… (${stream.reasoningChars} chunks, sin contenido aún)`
									: "conectando…"}
							</Text>
						)}
					</Box>
				)}
				{error && <Text color="red">✘ {error}</Text>}
			</Box>
			{notice && (
				<Box paddingX={1}>
					<Text color="yellow">{notice}</Text>
				</Box>
			)}
			<Box paddingX={1}>
				<Text color="cyan">› </Text>
				<Text>{input}</Text>
				{busy && <Text color="gray"> …</Text>}
			</Box>
		</Box>
	)
}
