from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from . import prompts
from .config import settings
from .content import build_multimodal_content
from .knowledge import (
    description_exists as knowledge_description_exists,
)
from .knowledge import save_entry as save_learning_entry
from .knowledge import search_hybrid as search_knowledge_hybrid
from .metrics import metrics
from .routing import detect_specialty, resolve_model, resolve_synthesis_model
from .upstream import UpstreamClient
from .web_research import web_research

Event = tuple[str, Any]  # ("reasoning" | "content", text) | ("tool_calls", list[dict])
Phase = Literal["leaf", "synthesis"]


def _merge_tool_call_delta(acc: dict[int, dict], deltas: list[dict]) -> None:
    for d in deltas:
        idx = d.get("index", 0)
        entry = acc.setdefault(
            idx, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}
        )
        if d.get("id"):
            entry["id"] = d["id"]
        if d.get("type"):
            entry["type"] = d["type"]
        fn = d.get("function") or {}
        if fn.get("name"):
            entry["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            entry["function"]["arguments"] += fn["arguments"]


@dataclass
class TaskNode:
    description: str
    depth: int
    children: list["TaskNode"] = field(default_factory=list)
    is_atomic: bool = False
    result: str | None = None
    specialty: str = "default"


@dataclass
class GoalContext:
    """Resultado de separar una request entrante en sus partes con distinto
    rol: el system prompt del caller (autoridad real, no dato a clasificar),
    la instrucción del turno actual (lo único que se decompone), el contexto
    de turnos previos (fondo, nunca redecompuesto) y las partes de imagen
    encontradas en cualquier mensaje."""

    caller_system: str
    turn_instruction: str
    prior_context: str
    image_parts: list[dict[str, Any]] = field(default_factory=list)


def _parse_decomposition(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"atomic": True, "subtasks": []}


def _is_valid_decomposition_json(raw: str) -> bool:
    """True si `raw` contiene un objeto JSON parseable (aunque sea vía la
    extracción de la primera llave). Distingue 'el modelo respondió JSON' de
    'el modelo respondió prosa/basura', para decidir si vale la pena un
    reintento reforzado (F2) antes de caer al fallback atómico."""
    try:
        return isinstance(json.loads(raw), dict)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if match:
        try:
            return isinstance(json.loads(match.group(0)), dict)
        except json.JSONDecodeError:
            return False
    return False


def _collect_atomic_leaves(node: TaskNode) -> list[TaskNode]:
    if node.is_atomic:
        return [node]
    leaves: list[TaskNode] = []
    for child in node.children:
        leaves.extend(_collect_atomic_leaves(child))
    return leaves


def _render_tree(node: TaskNode, depth: int = 0) -> list[str]:
    lines: list[str] = []
    for child in node.children:
        marker = " (atómica)" if child.is_atomic else ""
        lines.append("  " * depth + f"- {child.description}{marker}")
        lines.extend(_render_tree(child, depth + 1))
    return lines


class AtomicDecompositionEngine:
    def __init__(
        self,
        client: UpstreamClient,
        model: str,
        tools: list[dict] | None = None,
        tool_choice: Any = None,
    ) -> None:
        self._client = client
        self._model = model
        self._tools = tools
        self._tool_choice = tool_choice

        # goal_ctx se asigna una vez por turno externo (ver app/main.py), antes
        # de llamar a run()/resume() — es invariante durante todo ese run, por
        # eso vive como atributo en vez de pasarse por parámetro a cada método.
        self.goal_ctx: GoalContext | None = None

        # Estado del árbol de tareas y de la ejecución, expuesto como atributos
        # públicos para que una sesión persistida pueda restaurarlo entre
        # peticiones HTTP distintas (ver app/session.py) sin rehacer trabajo ya
        # completado.
        self.root: TaskNode | None = None
        self.leaves: list[TaskNode] = []
        self.results: list[str] = []

        # Estado de pausa/reanudación, unificado entre hoja atómica y síntesis
        # final (ambas pueden disparar tool calls y ambas deben poder
        # reanudarse con el historial completo de rondas ya vistas).
        self.pending_phase: Optional[Phase] = None
        self.pending_leaf_index: Optional[int] = None
        self.pending_tool_calls: list[dict[str, Any]] = []
        self.pending_conversation: list[dict[str, Any]] = []
        self.tool_round_count: int = 0

    # ------------------------------------------------------------------
    # Helpers de composición de prompts
    # ------------------------------------------------------------------

    def _compose_system(self, phase_prompt: str) -> str:
        """Antepone el system prompt real del caller (si lo hay) como una capa
        de autoridad sobre el prompt interno de esta fase, en vez de
        sustituirlo — así el caller (p. ej. un agente de código con sus
        propias convenciones) no pierde el control de cómo debe comportarse
        el modelo en cada llamada interna del proxy."""
        caller_system = self.goal_ctx.caller_system if self.goal_ctx else ""
        if not caller_system:
            return phase_prompt
        preamble = prompts.CALLER_SYSTEM_PREAMBLE.format(caller_system=caller_system)
        return f"{preamble}\n\n{phase_prompt}"

    def _build_user_content(self, text: str) -> str | list[dict[str, Any]]:
        image_parts = self.goal_ctx.image_parts if self.goal_ctx else []
        return build_multimodal_content(text, image_parts)

    def _tools_summary(self) -> str:
        """Descripción textual (no funcional) de las tools disponibles, para
        que la Fase 1 sepa que existen sin recibirlas como tools reales —así
        evita el defecto de clasificar como "no atómica" cualquier tarea que
        dependa de un dato que una sola invocación de herramienta resolvería
        (ver <herramientas_y_atomicidad> en decomposition_system.md)."""
        if not self._tools:
            return "(ninguna herramienta disponible)"
        lines = []
        for tool in self._tools:
            fn = tool.get("function", {})
            name = fn.get("name", "?")
            description = fn.get("description", "")
            lines.append(f"- {name}: {description}" if description else f"- {name}")
        return "\n".join(lines)

    async def _fetch_knowledge(self, query: str) -> str:
        """Busca soluciones previas reutilizables en la base de conocimiento
        SQLite para enriquecer el prompt de la tarea atómica. Si la KB local no
        devuelve nada (miss) y la investigación web (F7) está activa, intenta
        una síntesis web con citas vía Gigaxity Deep Research antes de rendirse."""
        metrics.inc("rag_queries")
        try:
            results = await search_knowledge_hybrid(query)
        except Exception:
            results = []
        if results:
            metrics.inc("rag_hits")
            parts: list[str] = []
            for r in results:
                parts.append(
                    f"- Descripción: {r['description']}\n"
                    f"  Categoría: {r.get('category', 'general')}\n"
                    f"  Contenido:\n{r['content']}"
                )
            return "\n\n".join(parts)

        metrics.inc("rag_misses")
        # F7 — fallback de investigación web sobre el miss local. Devuelve None
        # si la feature está desactivada o falla; en ese caso seguimos como antes.
        web_block = await self._web_research_fallback(query)
        if web_block:
            return web_block
        return "(no hay soluciones previas relevantes)"

    async def _save_knowledge_safe(
        self, description: str, content: str, category: str = "general"
    ) -> None:
        """Auto-aprendizaje: guarda una solución exitosa en la base de
        conocimiento para reutilizarla en tareas futuras similares, con tres
        higienes básicas: desactivable por config (AUTO_LEARN_KNOWLEDGE),
        anti-duplicado por descripción normalizada e ignora contenidos
        trivialmente cortos (no memorizan nada útil). Nunca interrumpe el
        flujo principal si algo falla."""
        if not settings.auto_learn_knowledge:
            return
        try:
            normalized = " ".join((description or "").split())
            content_text = (content or "").strip()
            if len(normalized) < 8 or len(content_text) < 20:
                return
            if await knowledge_description_exists(normalized):
                return
            await save_learning_entry(normalized, content_text, category, source="auto_learn")
        except Exception:
            pass

    async def _web_research_fallback(self, query: str) -> str | None:
        """F7 — En un miss del RAG local, lanza una investigación web (Gigaxity
        Deep Research) y devuelve un bloque de contexto con citas listo para
        ``{knowledge}``, o None si la feature está desactivada o falla. Nunca
        interrumpe el flujo principal. Opcionalmente auto-aprende el resultado
        como source='web_research' para que la próxima vez lo resuelva la KB local."""
        try:
            data = await web_research.research(query)
        except Exception:
            data = None
        if not data:
            return None
        block = web_research.format_for_context(data)
        if settings.web_research_auto_learn:
            await self._save_web_research(query, block)
        return block

    async def _save_web_research(self, query: str, block: str) -> None:
        """Auto-aprende una investigación web como entrada de la KB (source y
        category 'web_research'), con las mismas higienes que
        _save_knowledge_safe: respeta el interruptor global de auto-aprendizaje,
        anti-duplicado por descripción normalizada y mínimo de longitud."""
        if not (settings.auto_learn_knowledge and settings.web_research_auto_learn):
            return
        try:
            normalized = " ".join((query or "").split())
            content_text = (block or "").strip()
            if len(normalized) < 8 or len(content_text) < 20:
                return
            if await knowledge_description_exists(normalized):
                return
            await save_learning_entry(normalized, content_text, "web_research", source="web_research")
        except Exception:
            pass

    def _normalize_tool_choice(self) -> tuple[list[dict[str, Any]] | None, Any]:
        """Política única de tools/tool_choice para todas las llamadas
        internas del motor: si el caller no dio tools (o las desactivó con
        "none"), no se ofrecen; si las dio, siempre se ofrecen en modo "auto"
        para las llamadas internas — nunca se fuerza aquí un tool_choice
        específico que el caller haya pedido para su propia respuesta final
        (forzar una función concreta en cada tarea atómica interna no tiene
        sentido semántico)."""
        if not self._tools or self._tool_choice == "none":
            return None, None
        return self._tools, "auto"

    def _enter_pending(self, phase: Phase, leaf_index: Optional[int], payload: dict[str, Any]) -> None:
        self.tool_round_count += 1
        self.pending_conversation.append(
            {"role": "assistant", "content": payload["content"], "tool_calls": payload["tool_calls"]}
        )
        self.pending_tool_calls = payload["tool_calls"]
        self.pending_phase = phase
        self.pending_leaf_index = leaf_index

    def _clear_pending(self) -> None:
        self.pending_phase = None
        self.pending_conversation = []
        self.pending_tool_calls = []
        self.pending_leaf_index = None
        self.tool_round_count = 0

    # ------------------------------------------------------------------
    # Fase 1: descomposición
    # ------------------------------------------------------------------

    async def _decompose_node(self, node: TaskNode) -> AsyncIterator[Event]:
        if node.depth >= settings.max_decomposition_depth:
            node.is_atomic = True
            return

        if node.depth == 0:
            yield ("reasoning", "Pensando en las subtareas iniciales.\n\n")
        else:
            yield ("reasoning", f"Ahora para la subtarea {node.description}, hago sus subtareas.\n\n")

        system = self._compose_system(prompts.DECOMPOSITION_SYSTEM_PROMPT)
        user_text = prompts.DECOMPOSITION_USER_PROMPT.format(
            goal=self.goal_ctx.turn_instruction,
            prior_context=self.goal_ctx.prior_context or "(sin contexto previo)",
            tools=self._tools_summary(),
            task=node.description,
        )
        # La Fase 1 nunca recibe tools *funcionales* (no puede invocarlas): mezclar
        # response_format=json_object con tool-calling es frágil entre proveedores
        # distintos. Pero SÍ recibe su descripción como texto (_tools_summary), para
        # que sepa que existen y no fragmente en pasos una tarea que una sola
        # invocación de herramienta resolvería en Fase 2.
        raw = await self._client.complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": self._build_user_content(user_text)},
            ],
            model=self._model,
            json_mode=True,
        )

        if not _is_valid_decomposition_json(raw):
            # F2: el modelo devolvió algo que no es JSON válido. Un único
            # reintento con formato reforzado antes de rendirse al fallback
            # atómico de _parse_decomposition (que trata la tarea como plana).
            yield (
                "reasoning",
                "La descomposición devolvió JSON inválido; reintento con formato reforzado.\n\n",
            )
            reinforced = user_text + (
                "\n\nIMPORTANTE: tu respuesta anterior no fue JSON válido. Responde ÚNICAMENTE "
                'con un objeto JSON válido de la forma {"atomic": <bool>, "subtasks": [<texto>...]}, '
                "sin texto adicional, explicaciones ni bloques de código."
            )
            raw = await self._client.complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": self._build_user_content(reinforced)},
                ],
                model=self._model,
                json_mode=True,
            )

        parsed = _parse_decomposition(raw)
        subtasks = parsed.get("subtasks") or []

        if parsed.get("atomic", True) or not subtasks:
            yield ("reasoning", "Es atómica, no se subdivide más.\n\n")
            node.is_atomic = True
            return

        subtasks_list = "\n".join(f"- {s}" for s in subtasks)
        yield ("reasoning", f"Subtareas:\n{subtasks_list}\n\n")

        for sub in subtasks:
            child = TaskNode(description=sub, depth=node.depth + 1)
            node.children.append(child)
            async for event in self._decompose_node(child):
                yield event

    async def build_task_tree(self) -> AsyncIterator[Event]:
        assert self.goal_ctx is not None
        self.root = TaskNode(description=self.goal_ctx.turn_instruction, depth=0)
        async for event in self._decompose_node(self.root):
            yield event

    # ------------------------------------------------------------------
    # Motor de streaming compartido por hojas atómicas y síntesis
    # ------------------------------------------------------------------

    async def _run_phase(
        self,
        system: str,
        user_text: str,
        emit_kind: Literal["reasoning", "content"],
        extra_messages: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> AsyncIterator[Event]:
        """Ejecuta una sola ronda de streaming para la fase en curso (hoja
        atómica o síntesis). No sabe cuál de las dos es — solo construye
        mensajes, aplica la política de tools/tool_choice y el límite de
        rondas, y emite ("_tool_calls_pending", {content, tool_calls}) o
        ("_phase_done", texto). La orquestación de qué hacer con eso (guardar
        resultado de hoja, marcar pendiente, seguir con la siguiente hoja...)
        la hacen _execute_from/resume_phase/synthesize_final."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": self._build_user_content(user_text)},
        ]
        if extra_messages:
            messages.extend(extra_messages)

        phase_tools, phase_tool_choice = self._normalize_tool_choice()
        if phase_tools and self.tool_round_count >= settings.max_tool_rounds_per_phase:
            phase_tools, phase_tool_choice = None, None
            yield (
                emit_kind,
                "\n\n[límite de rondas de herramientas alcanzado, respondo con lo que hay disponible]\n\n",
            )

        result_parts: list[str] = []
        tool_call_acc: dict[int, dict] = {}
        async for chunk in self._client.stream_raw(
            messages, model=model or self._model, tools=phase_tools, tool_choice=phase_tool_choice
        ):
            delta = chunk["delta"]
            piece = delta.get("content")
            if piece:
                result_parts.append(piece)
                yield (emit_kind, piece)
            if delta.get("tool_calls"):
                _merge_tool_call_delta(tool_call_acc, delta["tool_calls"])

        result_text = "".join(result_parts)

        if tool_call_acc:
            tool_calls = [tool_call_acc[i] for i in sorted(tool_call_acc)]
            metrics.inc("tool_call_rounds")
            metrics.inc("tool_calls", len(tool_calls))
            if emit_kind == "reasoning":
                yield (
                    "reasoning",
                    "\n\nSe requiere usar una herramienta antes de continuar; interrumpo el resto del proceso.\n\n",
                )
            yield ("_tool_calls_pending", {"content": result_text or None, "tool_calls": tool_calls})
            return

        if emit_kind == "reasoning":
            yield ("reasoning", "\n\n")
        yield ("_phase_done", result_text)

    # ------------------------------------------------------------------
    # Fase 2: ejecución de hojas atómicas
    # ------------------------------------------------------------------

    async def _leaf_phase_inputs(self, leaf: TaskNode) -> tuple[str, str]:
        assert self.goal_ctx is not None
        system = self._compose_system(prompts.EXECUTE_ATOMIC_SYSTEM_PROMPT)
        context = "\n".join(self.results) if self.results else "(ninguno todavía)"
        knowledge = await self._fetch_knowledge(leaf.description)
        user_text = prompts.EXECUTE_ATOMIC_USER_PROMPT.format(
            goal=self.goal_ctx.turn_instruction,
            prior_context=self.goal_ctx.prior_context or "(sin contexto previo)",
            context=context,
            task=leaf.description,
            knowledge=knowledge,
        )
        return system, user_text

    def _resolve_leaf_model(self, leaf: TaskNode) -> str:
        """F1: si el routing por especialidad está activo, clasifica la hoja
        (visión/código/resumen/defecto) y devuelve el modelo del arsenal local
        que debe ejecutarla; en caso contrario devuelve el modelo base del
        turno. La descomposición (Fase 1) nunca pasa por aquí: planificar es la
        tarea más exigente y se queda siempre en el cerebro principal."""
        if not settings.specialty_routing:
            return self._model
        has_images = bool(self.goal_ctx.image_parts) if self.goal_ctx else False
        specialty = detect_specialty(leaf.description, has_images=has_images)
        leaf.specialty = specialty
        return resolve_model(specialty, self._model)

    async def _execute_from(self, start_index: int) -> AsyncIterator[Event]:
        total = len(self.leaves)
        for i in range(start_index, total):
            leaf = self.leaves[i]
            label = leaf.description if leaf.depth > 0 else "la solicitud"
            yield ("reasoning", f"Tarea atómica {i + 1}/{total}: {label}\n\n")

            system, user_text = await self._leaf_phase_inputs(leaf)
            self.tool_round_count = 0
            self.pending_conversation = []

            leaf_model = self._resolve_leaf_model(leaf)
            if settings.specialty_routing and leaf_model != self._model:
                yield (
                    "reasoning",
                    f"[routing] especialidad '{leaf.specialty}' → modelo '{leaf_model}'\n\n",
                )
            yield (
                "progress",
                {"type": "leaf_started", "index": i, "total": total, "description": leaf.description, "model": leaf_model},
            )

            leaf_started = time.monotonic()
            async for kind, payload in self._run_phase(system, user_text, "reasoning", model=leaf_model):
                if kind == "_tool_calls_pending":
                    self._enter_pending("leaf", i, payload)
                    yield ("tool_calls", payload["tool_calls"])
                    return
                if kind == "_phase_done":
                    leaf.result = payload
                    self.results.append(f"- {leaf.description}:\n{payload}")
                    metrics.observe("leaf_execution", time.monotonic() - leaf_started)
                    metrics.inc("leaves_executed")
                    await self._save_knowledge_safe(
                        description=leaf.description,
                        content=payload,
                        category="atomic_task_result",
                    )
                    yield (
                        "progress",
                        {"type": "leaf_done", "index": i, "total": total, "description": leaf.description},
                    )
                    continue
                yield (kind, payload)

    def _can_run_parallel(self) -> bool:
        """F3: la ejecución paralela de hojas solo es segura si está activada,
        hay más de una hoja y no hay tools activas (el mecanismo de pausa/
        reanudación de tool_calls es secuencial por construcción, así que con
        tools se vuelve automáticamente al modo secuencial)."""
        if not settings.parallel_leaves:
            return False
        if len(self.leaves) <= 1:
            return False
        if self._tools and self._tool_choice != "none":
            return False
        return True

    async def _run_leaf_buffered(self, leaf: TaskNode) -> str:
        """F3: ejecuta una hoja atómica sin tools consumiendo su stream
        internamente y devolviendo solo el resultado final (sin retransmitir
        cada token), para poder correr varias hojas en paralelo con
        asyncio.gather sin interleavar el SSE de cada una."""
        system, user_text = await self._leaf_phase_inputs(leaf)
        leaf_model = self._resolve_leaf_model(leaf)
        result = ""
        started = time.monotonic()
        async for kind, payload in self._run_phase(system, user_text, "reasoning", model=leaf_model):
            if kind == "_phase_done":
                result = payload
            # Sin tools activas "_tool_calls_pending" no puede aparecer; se
            # ignora cualquier otro evento intermedio a propósito.
        metrics.observe("leaf_execution", time.monotonic() - started)
        metrics.inc("leaves_executed")
        return result

    async def _execute_parallel(self) -> AsyncIterator[Event]:
        total = len(self.leaves)
        yield (
            "reasoning",
            f"Fase 2 de 3. Ejecuto las {total} tareas atómicas en paralelo.\n\n",
        )
        self.tool_round_count = 0

        async def _run_one(index: int, leaf: TaskNode) -> tuple[int, TaskNode, str]:
            result = await self._run_leaf_buffered(leaf)
            return index, leaf, result

        # asyncio.gather preserva el orden de los resultados según el orden de
        # los awaitables de entrada, independientemente de cuál termine antes.
        outcomes = await asyncio.gather(
            *(_run_one(i, leaf) for i, leaf in enumerate(self.leaves))
        )
        for index, leaf, result in sorted(outcomes, key=lambda item: item[0]):
            leaf.result = result
            self.current_leaf_index = index
            self.results.append(f"- {leaf.description}:\n{result}")
            await self._save_knowledge_safe(
                description=leaf.description,
                content=result,
                category="atomic_task_result",
            )
            yield (
                "progress",
                {"type": "leaf_done", "index": index, "total": total, "description": leaf.description},
            )
            yield ("reasoning", f"Tarea atómica {index + 1}/{total} completada: {leaf.description}\n\n")

    async def execute_tree(self) -> AsyncIterator[Event]:
        self.results = []
        self.leaves = _collect_atomic_leaves(self.root)
        total = len(self.leaves)
        metrics.inc("leaves_decomposed", total)
        parallel = self._can_run_parallel()
        metrics.inc("parallel_executions" if parallel else "sequential_executions")
        yield (
            "progress",
            {"type": "phase_started", "phase": "execution", "leaf_count": total, "parallel": parallel},
        )
        if parallel:
            async for event in self._execute_parallel():
                yield event
            return
        yield ("reasoning", f"Fase 2 de 3. Implemento las {total} tareas atómicas.\n\n")
        async for event in self._execute_from(0):
            yield event

    # ------------------------------------------------------------------
    # Reanudación unificada (hoja o síntesis) tras resultados de tool
    # ------------------------------------------------------------------

    async def resume_phase(self, tool_outputs: dict[str, str]) -> AsyncIterator[Event]:
        """Continúa la fase que quedó pausada esperando resultados de tool,
        agregando la nueva ronda a self.pending_conversation (append-only) en
        vez de reconstruirla desde cero — así una segunda (o tercera...) ronda
        de tool calls dentro de la misma fase no pierde el historial de las
        rondas anteriores. Funciona igual para una hoja atómica que para la
        síntesis final."""
        assert self.pending_phase is not None
        phase = self.pending_phase
        index = self.pending_leaf_index  # solo válido si phase == "leaf"

        for tc in self.pending_tool_calls:
            self.pending_conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": tool_outputs.get(tc.get("id"), ""),
                }
            )

        if phase == "leaf":
            assert index is not None
            leaf = self.leaves[index]
            system, user_text = await self._leaf_phase_inputs(leaf)
            emit_kind: Literal["reasoning", "content"] = "reasoning"
            phase_model = self._resolve_leaf_model(leaf)
        else:
            system, user_text = self._synthesis_phase_inputs()
            emit_kind = "content"
            phase_model = resolve_synthesis_model(self._model)

        extra_messages = list(self.pending_conversation)
        async for kind, payload in self._run_phase(system, user_text, emit_kind, extra_messages=extra_messages, model=phase_model):
            if kind == "_tool_calls_pending":
                self._enter_pending(phase, index, payload)
                yield ("tool_calls", payload["tool_calls"])
                return
            if kind == "_phase_done":
                self._clear_pending()
                if phase == "leaf":
                    leaf.result = payload
                    self.results.append(f"- {leaf.description}:\n{payload}")
                    await self._save_knowledge_safe(
                        description=leaf.description,
                        content=payload,
                        category="atomic_task_result",
                    )
                continue
            yield (kind, payload)

        if phase == "leaf":
            async for event in self._execute_from(index + 1):
                yield event

    # ------------------------------------------------------------------
    # Fase 3: síntesis final
    # ------------------------------------------------------------------

    def _synthesis_phase_inputs(self) -> tuple[str, str]:
        assert self.goal_ctx is not None
        system = self._compose_system(prompts.SYNTHESIS_SYSTEM_PROMPT)
        context = "\n".join(self.results) if self.results else "(sin resultados)"
        user_text = prompts.SYNTHESIS_USER_PROMPT.format(
            goal=self.goal_ctx.turn_instruction,
            prior_context=self.goal_ctx.prior_context or "(sin contexto previo)",
            context=context,
        )
        return system, user_text

    async def synthesize_final(self) -> AsyncIterator[Event]:
        yield ("progress", {"type": "phase_started", "phase": "synthesis"})
        system, user_text = self._synthesis_phase_inputs()
        synth_model = resolve_synthesis_model(self._model)
        self.tool_round_count = 0
        self.pending_conversation = []

        async for kind, payload in self._run_phase(system, user_text, "content", model=synth_model):
            if kind == "_tool_calls_pending":
                self._enter_pending("synthesis", None, payload)
                yield ("tool_calls", payload["tool_calls"])
                return
            if kind == "_phase_done":
                await self._save_knowledge_safe(
                    description=self.goal_ctx.turn_instruction if self.goal_ctx else "síntesis final",
                    content=payload,
                    category="synthesis_result",
                )
                continue
            yield (kind, payload)

    # ------------------------------------------------------------------
    # Orquestación de alto nivel
    # ------------------------------------------------------------------

    async def run(self) -> AsyncIterator[Event]:
        yield ("progress", {"type": "phase_started", "phase": "decomposition"})
        yield ("reasoning", "Fase 1 de 3. Primero comienzo dividiendo la tarea en sus subtareas atómicas.\n\n")
        decomp_started = time.monotonic()
        async for event in self.build_task_tree():
            yield event
        metrics.observe("decomposition", time.monotonic() - decomp_started)
        yield (
            "progress",
            {"type": "phase_done", "phase": "decomposition", "leaf_count": len(_collect_atomic_leaves(self.root))},
        )
        yield ("reasoning", "Listo, tenemos la lista completa del árbol de tareas hasta sus subtareas atómicas.\n\n")
        tree_lines = _render_tree(self.root)
        if tree_lines:
            yield ("reasoning", "\n".join(tree_lines) + "\n\n")

        tool_break = False
        async for event in self.execute_tree():
            if event[0] == "tool_calls":
                tool_break = True
            yield event
        if tool_break:
            return

        yield (
            "reasoning",
            "Fase 3 de 3. Listo, todas las tareas atómicas trabajadas correctamente, procedo a dar la respuesta final.\n",
        )
        synth_started = time.monotonic()
        async for event in self.synthesize_final():
            yield event
        metrics.observe("synthesis", time.monotonic() - synth_started)
        yield ("progress", {"type": "done"})

    async def resume(self, tool_outputs: dict[str, str]) -> AsyncIterator[Event]:
        """Reanuda un run() previamente pausado por una tool call (en una hoja
        o en la síntesis), sin volver a descomponer el objetivo ni reejecutar
        trabajo ya resuelto."""
        resuming_phase = self.pending_phase
        tool_break = False
        async for event in self.resume_phase(tool_outputs):
            if event[0] == "tool_calls":
                tool_break = True
            yield event
        if tool_break:
            return

        if resuming_phase == "synthesis":
            yield ("progress", {"type": "done"})
            return  # resume_phase ya completó la síntesis, no hay nada más

        yield (
            "reasoning",
            "Fase 3 de 3. Listo, todas las tareas atómicas trabajadas correctamente, procedo a dar la respuesta final.\n",
        )
        async for event in self.synthesize_final():
            yield event
        yield ("progress", {"type": "done"})
