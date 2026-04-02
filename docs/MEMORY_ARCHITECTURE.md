# Memory Architecture (QPrisma)

Esta guía define **qué guarda cada capa** y cuál es la **fuente de verdad** para conversaciones del agente.

## Capas de memoria

1. **Frontend Local Storage**
   - Uso: caché de UX (lista de conversaciones, últimos mensajes renderizados, estado visual).
   - Alcance: navegador/dispositivo del usuario.
   - Persistencia: local al cliente.
   - **No es fuente de verdad**.

2. **LangGraph Checkpointer (Backend)**
   - Uso: estado operativo del grafo por conversación (`thread_id`), historial útil, reanudación tras fallos/interrupts.
   - Alcance: por hilo de conversación.
   - Persistencia: saver productivo (PostgreSQL/Redis) según disponibilidad.
   - **Fuente de verdad conversacional**.

3. **Foundry Memory Store (Memoria semántica)**
   - Uso: memoria de largo plazo (preferencias, hechos resumidos, señales persistentes).
   - Alcance: cross-thread por usuario (scoped por Entra ID `{tid}_{oid}`).
   - Persistencia: Azure AI Foundry Memory Store.
   - No sustituye al checkpointer; complementa contexto.

4. **A2A Task Store**
   - Uso: estado de tareas A2A (`taskId`, estado, artifacts, history de task).
   - Alcance: ciclo de vida de tareas/progreso.
   - Estado actual: en memoria de proceso (in-memory).
   - Objetivo recomendado: persistente para multi-instancia/restarts.

## Fuente de verdad y reconciliación

- Conversación: **Backend checkpointer**.
- Conocimiento semántico de usuario: **Foundry Memory Store**.
- Estado visual del chat: **Local Storage**.
- Si hay conflicto, prevalece backend (checkpointer/task state).

## Mapeo de IDs recomendado

- `contextId` (A2A) ↔ `thread_id` (LangGraph): 1:1 para continuidad de conversación.
- `taskId` (A2A): identidad de ejecución/progreso, no identidad primaria de conversación.

## Flujo por turno

1. Cliente envía mensaje con `contextId`.
2. Backend resuelve `thread_id=contextId` y carga estado desde checkpointer.
3. Recupera memoria semántica (Foundry Memory Store) relevante para el prompt.
4. Ejecuta grafo y stream de eventos (A2A SSE).
5. Persiste checkpoint de super-steps.
6. Frontend actualiza caché local para UX rápida.

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
