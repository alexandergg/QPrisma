# Memory Architecture (QPrisma)

Esta guía define **qué guarda cada capa** y cuál es la **fuente de verdad** para conversaciones del agente.

## Capas de memoria

1. **LangGraph Checkpointer (Backend)**
   - Uso: estado operativo del grafo por conversación (`thread_id`), historial útil, reanudación tras fallos/interrupts.
   - Alcance: por hilo de conversación.
   - Persistencia: saver productivo (PostgreSQL/Redis) según disponibilidad.
   - **Fuente de verdad conversacional**.

2. **Foundry Memory Store (Memoria semántica)**
   - Uso: memoria de largo plazo (preferencias, hechos resumidos, señales persistentes).
   - Alcance: cross-thread por usuario (scoped por Entra ID `{tid}_{oid}`).
   - Persistencia: Azure AI Foundry Memory Store.
   - No sustituye al checkpointer; complementa contexto.
   - **Estado**: el servicio (`FoundryMemoryService`) está disponible como singleton pero **no se invoca automáticamente** en el grafo del agente todavía. La integración automática en nodos del grafo es trabajo futuro.

3. **A2A Task Store**
   - Uso: estado de tareas A2A (`taskId`, estado, artifacts, history de task).
   - Alcance: ciclo de vida de tareas/progreso.
   - Estado actual: en memoria de proceso (in-memory).
   - Objetivo recomendado: persistente para multi-instancia/restarts.

> **Nota**: no hay persistencia de mensajes en el cliente (localStorage). La UI no almacena conversaciones localmente; todo el estado conversacional reside en el backend.

## Fuente de verdad y reconciliación

- Conversación: **Backend checkpointer**.
- Conocimiento semántico de usuario: **Foundry Memory Store** (cuando se habilite la integración automática).
- Si hay conflicto, prevalece backend (checkpointer/task state).

## Mapeo de IDs recomendado

- `contextId` (A2A): en la primera petición es un UUID generado por el cliente. El backend lo reemplaza por el **Foundry conversation ID** devuelto por la API de Conversations, y lo envía de vuelta al cliente en el evento SSE inicial del task. A partir de ahí, `contextId` porta el Foundry conversation ID para continuidad.
- `taskId` (A2A): identidad de ejecución/progreso, no identidad primaria de conversación.

## Flujo por turno

1. Cliente envía mensaje con `contextId` (UUID en el primer turno, Foundry conversation ID en turnos siguientes).
2. Backend resuelve o crea un Foundry conversation ID a partir de `contextId`.
3. Ejecuta la llamada al Foundry Hosted Agent (Responses API con `conversation=conv_id`).
4. Recupera memoria semántica (Foundry Memory Store) relevante para el prompt _(futuro — servicio disponible pero no invocado automáticamente)_.
5. Stream de eventos A2A SSE con `contextId` = Foundry conversation ID.
6. Persiste checkpoint de super-steps.

## Latencia y calidad

- El costo extra del checkpointer suele ser menor que el tiempo LLM/retrieval.
- Para minimizar impacto:
  - co-ubicar API + DB,
  - pool de conexiones,
  - estado compacto (no payloads grandes en checkpoint),
  - métricas p50/p95 por fase.

## Políticas operativas recomendadas

- Retención por entorno (dev/stage/prod).
- Borrado por usuario/conversación (GDPR) usando `delete_thread`.
- Cifrado en reposo del estado sensible cuando aplique.
- Trazabilidad con `contextId`, `taskId`, `thread_id` en logs/metrics.
