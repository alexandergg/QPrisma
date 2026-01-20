# QPrisma Editor - Product Roadmap

> Editor de video conversacional con IA para creadores de contenido.
> **Visión:** "Edita tu video hablando con él. Busca, corta, exporta - todo desde el chat."

**Fecha de inicio:** Enero 2026
**Target:** Creadores de contenido B2C (YouTubers, Podcasters, Educadores)
**Modelo:** Freemium SaaS
**Innovación clave:** Chat-to-Edit - Interfaz unificada de búsqueda + edición conversacional

---

## 🎯 Problema que resolvemos

> "Grabo 1 hora de contenido pero no tengo tiempo de hacer clips para redes"

### Dolor específico
- Editar un podcast de 1h toma 4-8 horas
- Crear clips para TikTok/Reels es tedioso y repetitivo
- Añadir subtítulos manualmente es lento
- Adaptar formatos (horizontal → vertical) requiere re-editar
- **Aprender herramientas de edición tiene curva alta**

### Solución: Chat-to-Edit
En lugar de aprender una interfaz compleja, **hablas con tu video**:
- "Busca donde hablo de marketing" → Encuentra momentos
- "Crea un clip de 30 segundos" → Lo añade al proyecto
- "Ponle subtítulos estilo Hormozi" → Los genera
- "Expórtalo para TikTok" → Listo para subir

---

## 🚀 Innovación: Chat-to-Edit

### Concepto
```
┌─────────────────────────────────────────────────────────────────┐
│                      VIDEO + TIMELINE                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    [VIDEO PREVIEW]                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ──●────[Clip 1]────[Clip 2]────[Clip 3]──────────────────     │
├─────────────────────────────────────────────────────────────────┤
│  CHAT-TO-EDIT                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 🧑 "Busca el momento donde hablo de IA"                  │   │
│  │                                                          │   │
│  │ 🤖 "Encontré 3 momentos:                                 │   │
│  │     • [12:34] Introducción a IA ⭐ Score: 85             │   │
│  │     • [28:15] Caso práctico                              │   │
│  │     • [45:02] Futuro de la IA                            │   │
│  │     ¿Creo clips de alguno?"                              │   │
│  │                                                          │   │
│  │ 🧑 "Crea un clip del primero, 30 segundos"              │   │
│  │                                                          │   │
│  │ 🤖 "✅ Clip creado [12:34-13:04]. ¿Subtítulos?"          │   │
│  │                                                          │   │
│  │ 🧑 "Sí, estilo Hormozi y exporta para TikTok"           │   │
│  │                                                          │   │
│  │ 🤖 "🎬 Exportando... Listo! [Descargar]"                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│  [Escribe o habla...]                                 [Enviar]  │
└─────────────────────────────────────────────────────────────────┘
```

### Comandos naturales soportados
| Dices | La IA hace |
|-------|-----------|
| "Busca donde menciono X" | Búsqueda semántica en el video |
| "Crea un clip de eso" | Añade clip al proyecto |
| "Hazlo más corto/largo" | Ajusta duración |
| "Elimina los silencios" | Detecta y corta silencios |
| "Añade subtítulos estilo X" | Genera subtítulos animados |
| "Exporta para TikTok" | Crop vertical + export |
| "Genera 5 clips virales" | Auto-clips con scores |
| "Quita el segundo clip" | Elimina del proyecto |
| "Muévelo al final" | Reordena timeline |
| "¿De qué habla el video?" | Resumen general |

### Ventaja competitiva
```
                        Control    Facilidad    Velocidad
                        ───────    ─────────    ─────────
CapCut/Premiere         ██████████ ██░░░░░░░░   ██░░░░░░░░
Descript                ████████░░ ██████░░░░   ██████░░░░
Opus Clip               ██░░░░░░░░ ██████████   ██████████
QPrisma Chat-to-Edit    ████████░░ ██████████   ████████░░
                        
Único que combina CONTROL + FACILIDAD
```

---

## 👥 Target Audience

### Persona principal: "Creator Carlos"
- YouTuber/Podcaster con 10k-500k seguidores
- Graba 2-4 videos largos por semana
- Quiere presencia en TikTok/Reels pero no tiene tiempo
- Presupuesto: $15-50/mes en herramientas
- Pain: "Tengo horas de contenido sin aprovechar"

### Persona secundaria: "Freelancer María"
- Editora freelance para múltiples clientes
- Busca eficiencia para entregar más rápido
- Presupuesto: $50-100/mes si ahorra tiempo significativo
- Pain: "Los clientes quieren clips pero pagan poco"

---

## 💰 Modelo de Negocio

### Pricing
| Plan | Precio | Límites | Target |
|------|--------|---------|--------|
| **Free** | $0 | 3 videos/mes, watermark, 720p | Prueba |
| **Creator** | $19/mes | 20 videos/mes, sin watermark, 1080p | Creadores pequeños |
| **Pro** | $49/mes | Ilimitado, 4K, prioridad, API | Creadores grandes |
| **Team** | $99/mes | 5 usuarios, workspace compartido | Agencias pequeñas |

### Unit Economics (estimado)
- Costo por video procesado (1h): ~$0.50-1.50 (Azure OpenAI + Compute)
- Margen bruto objetivo: 70%+

---

## 📊 Progreso General

```
Fase 0: Fundamentos (QPrisma actual)     [████████████████████] 100% ✅
Fase 1: Chat-to-Edit MVP                 [████████████████████] 100% ✅
Fase 2: Clips & Timeline Visual          [████████████████████] 100% ✅
Fase 3: Subtítulos & Estilos             [████████████████████] 100% ✅
Fase 4: Export Multi-formato             [██████████████████░░]  90% ✅
Fase 4.5: Code Quality & Maintenance     [████████░░░░░░░░░░░░]  40% 🔧
Fase 5: Growth & Monetización            [░░░░░░░░░░░░░░░░░░░░]   0%
```

---

## Fase 0: Fundamentos (COMPLETADO) ✅

Lo que ya tenemos de QPrisma (reutilizable):

- [x] **Agentic Chat con Tools** - Base para Chat-to-Edit
- [x] **VideoRAG Hybrid Search** - Búsqueda semántica en videos
- [x] **Transcripción Whisper** - Audio → texto con timestamps
- [x] **Scene Detection FFmpeg** - Detectar cambios de escena
- [x] **Análisis GPT-4V** - Entender contenido visual
- [x] **Knowledge Graph Neo4j** - Relaciones entre momentos
- [x] **Celery Workers** - Procesamiento async
- [x] **Azure Blob Storage** - Almacenar videos
- [x] **Auth + Usuarios** - Autenticación lista

---

## Fase 1: Chat-to-Edit MVP ✅

**Objetivo:** Editar video completamente desde el chat.
**Duración estimada:** 3-4 semanas
**Prioridad:** 🔴 CRÍTICA
**Estado:** COMPLETADO

### 1.1 Modelo de Proyectos y Clips (Backend) ✅

**Descripción:** Estructura de datos para proyectos de edición.
**Estado:** COMPLETADO

**Modelos PostgreSQL:**
```python
class EditorProjectModel(Base):
    """Proyecto de edición de video."""
    id: str
    user_id: str
    name: str
    source_media_id: str          # Video original (MediaModel)
    status: str                   # draft, exporting, completed
    settings: JSON                # formato, resolución, etc.
    created_at: datetime
    updated_at: datetime

class ClipModel(Base):
    """Clip dentro de un proyecto."""
    id: str
    project_id: str
    start_time: float             # Segundos
    end_time: float               # Segundos
    order: int                    # Posición en timeline
    title: str | None
    
    # Metadata IA
    is_ai_suggested: bool         # Sugerido por IA
    viral_score: float | None     # 0-100
    viral_reasons: JSON           # ["hook", "high_energy", ...]
    
    # Subtítulos
    subtitle_style: str | None    # "hormozi", "mrbeast", etc.
    subtitles_data: JSON          # SRT parseado
    
    # Export
    export_status: str            # pending, processing, done
    export_url: str | None        # URL del clip exportado
```

**Endpoints API:**
```
POST   /editor/projects                    # Crear proyecto desde video
GET    /editor/projects                    # Listar proyectos
GET    /editor/projects/{id}               # Obtener proyecto + clips
DELETE /editor/projects/{id}               # Eliminar proyecto

# Los clips se gestionan vía Chat-to-Edit (no CRUD manual)
```

### 1.2 Herramientas del Agente para Edición ✅

**Descripción:** Nuevas tools para el agente que permiten editar.
**Estado:** COMPLETADO

**Archivos a crear:**
```
backend/agent/tools/
├── editor_tools.py              # Herramientas de edición
│   ├── CreateClipTool           # Crear clip en proyecto
│   ├── ModifyClipTool           # Ajustar start/end de clip
│   ├── DeleteClipTool           # Eliminar clip
│   ├── ReorderClipsTool         # Cambiar orden
│   ├── ListClipsTool            # Ver clips actuales
│   └── AutoClipsTool            # Generar clips automáticos
│
├── subtitle_tools.py            # Herramientas de subtítulos
│   ├── AddSubtitlesTool         # Añadir subtítulos a clip
│   ├── ChangeSubtitleStyleTool  # Cambiar estilo
│   └── RemoveSubtitlesTool      # Quitar subtítulos
│
└── export_tools.py              # Herramientas de export
    ├── ExportClipTool           # Exportar clip individual
    ├── ExportAllClipsTool       # Exportar todos
    └── GetExportStatusTool      # Ver estado de exports
```

**Ejemplo de tool:**
```python
class CreateClipTool(BaseTool):
    name = "create_clip"
    description = "Crea un clip en el proyecto actual"
    
    parameters = {
        "start_time": {"type": "number", "description": "Inicio en segundos"},
        "end_time": {"type": "number", "description": "Fin en segundos"},
        "title": {"type": "string", "description": "Título opcional"},
    }
    
    async def execute(self, start_time: float, end_time: float, title: str = None):
        # Crear clip en DB
        # Retornar confirmación
        return f"✅ Clip creado [{format_time(start_time)} - {format_time(end_time)}]"
```

### 1.3 Prompt del Agente Editor ✅

**Descripción:** System prompt especializado para edición.
**Estado:** COMPLETADO

```python
EDITOR_SYSTEM_PROMPT = """
Eres un asistente de edición de video inteligente. 
Ayudas a los usuarios a crear clips de sus videos usando lenguaje natural.

CONTEXTO DEL PROYECTO:
- Video: {video_title}
- Duración: {duration}
- Clips actuales: {num_clips}

CAPACIDADES:
1. BUSCAR: Encuentra momentos específicos en el video
2. CREAR CLIPS: Crea clips de momentos encontrados
3. EDITAR: Ajusta duración, reordena, elimina clips
4. SUBTÍTULOS: Añade subtítulos con diferentes estilos
5. EXPORTAR: Exporta clips para diferentes plataformas

ESTILOS DE SUBTÍTULOS DISPONIBLES:
- hormozi: Palabra por palabra, bold, colores alternos
- mrbeast: Grande, centrado, sombra dramática
- minimal: Pequeño, sin fondo
- karaoke: Highlight palabra actual

FORMATOS DE EXPORT:
- tiktok: 9:16, 1080x1920, max 3 min
- reels: 9:16, 1080x1920, max 90s
- shorts: 9:16, 1080x1920, max 60s
- youtube: 16:9, 1920x1080

Cuando el usuario pide crear un clip, SIEMPRE confirma los tiempos.
Cuando sugieras clips, muestra el viral_score si está disponible.
Sé conciso pero amigable.
"""
```

### 1.4 UI Unificada Chat + Preview ✅

**Descripción:** Interfaz que combina chat y preview de video.
**Estado:** COMPLETADO

**Layout:**
```
┌──────────────────────────────────────────────────────────────┐
│  [Logo] QPrisma Editor    [Proyecto: Mi Podcast Ep.42]  [⚙️] │
├──────────────────────────────────────────────────────────────┤
│                    │                                         │
│   VIDEO PANEL      │          CHAT-TO-EDIT                  │
│   (40% width)      │          (60% width)                   │
│                    │                                         │
│  ┌──────────────┐  │  ┌─────────────────────────────────┐   │
│  │              │  │  │                                 │   │
│  │   [VIDEO]    │  │  │   Mensajes del chat             │   │
│  │              │  │  │   con sugerencias               │   │
│  └──────────────┘  │  │   y confirmaciones              │   │
│                    │  │                                 │   │
│  ──●───────────    │  │                                 │   │
│  Timeline mini     │  └─────────────────────────────────┘   │
│                    │                                         │
│  CLIPS (lista)     │  ┌─────────────────────────────────┐   │
│  ┌──────────────┐  │  │ Escribe o habla...    [Enviar] │   │
│  │ Clip 1 0:34  │  │  └─────────────────────────────────┘   │
│  │ Clip 2 1:22  │  │                                         │
│  └──────────────┘  │                                         │
│                    │                                         │
└──────────────────────────────────────────────────────────────┘
```

**Componentes React:**
```
frontend/app/editor/
├── page.tsx                     # Página del editor
├── [projectId]/
│   └── page.tsx                 # Proyecto específico
└── components/
    ├── EditorLayout.tsx         # Layout 2 columnas
    ├── VideoPanel.tsx           # Video + mini timeline
    ├── ClipsList.tsx            # Lista de clips del proyecto
    ├── EditorChat.tsx           # Chat especializado
    └── ClipCard.tsx             # Tarjeta de clip individual
```

### 1.5 Integración Chat ↔ Video ✅

**Descripción:** Sincronizar chat con el video player.
**Estado:** COMPLETADO

**Features:**
- [x] Click en timestamp del chat → Video salta a ese momento
- [x] Cuando IA crea clip → Se muestra en la lista (via `clips_updated` event)
- [x] Preview rápido de clip sin exportar (play solo el segmento del clip)
- [x] Highlight visual del rango del clip en timeline

---

## Fase 2: Clips & Timeline Visual ✅

**Objetivo:** Timeline visual complementario al chat.
**Duración estimada:** 2-3 semanas
**Prioridad:** 🟡 ALTA
**Estado:** COMPLETADO

### 2.1 Timeline con Waveform ✅

**Descripción:** Visualización de audio + clips en timeline.

**Features:**
- [x] Waveform del audio completo (wavesurfer.js v7)
- [x] Clips visualizados como bloques de colores (CSS overlays)
- [x] Drag para ajustar inicio/fin de clips (drag handles)
- [x] Drag para reordenar clips (ClipsList.tsx)
- [x] Zoom in/out (botones + slider)
- [x] Click para posicionar playhead

**Tecnología:**
- wavesurfer.js v7 para waveform
- CSS overlays para clips (más eficiente que Canvas)

**Archivos implementados:**
- `frontend/components/editor/TimelineWaveform.tsx`
- `frontend/components/editor/ClipsList.tsx` (drag & drop)

### 2.2 Auto-Clips con Viral Score ✅

**Descripción:** Generar clips automáticamente con puntuación.

**Algoritmo de Viral Score implementado** (`backend/services/viral_score_service.py`):
```python
class ViralScoreService:
    # Hook Score (25%): Palabras de engagement al inicio
    # Topic Score (20%): Temas de alto interés (dinero, salud, etc.)
    # Pacing Score (15%): Words per minute óptimo (130-170 WPM)
    # Completeness Score (15%): Si tiene idea completa
    # Controversy Score (10%): Opiniones fuertes
    # Duration Score (10%): Duración óptima (21-45s)
    # Visual Score (5%): Presencia de caras, cambios de escena
```

**Tool del agente mejorada:**
- `backend/agent/tools/auto_clip_tools.py` - `GenerateAutoClipsTool`
- Integrado con ViralScoreService
- Fallback a cálculo simple si falla

### 2.3 Edición Directa en Timeline ✅

**Descripción:** Complemento al chat para ajustes finos.

**Features:**
- [x] Arrastrar bordes de clip para ajustar (drag handles en TimelineWaveform)
- [ ] Double-click para dividir clip (pendiente - nice-to-have)
- [ ] Menú contextual (eliminar, duplicar) (pendiente - nice-to-have)
- [ ] Undo/Redo (Ctrl+Z, Ctrl+Y) (pendiente - nice-to-have)

---

## Fase 3: Subtítulos & Estilos ✅

**Objetivo:** Subtítulos animados con estilos populares.
**Duración estimada:** 2-3 semanas
**Prioridad:** 🟡 ALTA
**Estado:** COMPLETADO

### 3.1 Generación de Subtítulos ✅

- [x] Usar transcripción Whisper existente
- [x] Segmentar por oraciones/frases (según estilo)
- [x] Word-level timing para animaciones
- [ ] Corrección automática de errores comunes (pendiente)

### 3.2 Estilos Pre-diseñados ✅

**Estilos implementados:**

| Estilo | Descripción | Ejemplo de uso |
|--------|-------------|----------------|
| `hormozi` | Palabra por palabra, bold, amarillo/blanco | Educativo, coaches |
| `mrbeast` | Grande, centrado, sombra, caps | Entretenimiento |
| `minimal` | Pequeño, sin fondo | Podcasts, elegante |
| `karaoke` | Highlight palabra actual | Música, dinámico |
| `news` | Lower third, fondo sólido | Noticias, profesional |

### 3.3 Personalización (Parcial)

- [ ] Elegir fuente (10 opciones) - pendiente
- [x] Colores (texto, highlight, fondo) - via style_config
- [x] Posición (9 posiciones en grid) - via style_config
- [x] Tamaño (S, M, L, XL) - via fontSize en style_config
- [x] Animación de entrada/salida - word_by_word, pop, fade, karaoke, slide

### 3.4 Preview en Tiempo Real ✅

- [x] Ver subtítulos sobre el video sin exportar (SubtitleOverlay)
- [x] Cambiar estilo y ver inmediatamente (SubtitleEditor)
- [x] Editar texto de subtítulos inline (cue editing)

---

## Fase 4: Export Multi-formato

**Objetivo:** Exportar para todas las plataformas con 1 comando.
**Duración estimada:** 2-3 semanas
**Prioridad:** 🟡 ALTA
**Estado:** CASI COMPLETO (90%)

### 4.1 Presets de Plataformas ✅

**Estado:** COMPLETADO

**Implementación:** `backend/models/export_config.py`

Configuraciones completas para cada plataforma:

| Plataforma | Aspect Ratio | Resolución | Max Duración | Bitrate |
|------------|--------------|------------|--------------|---------|
| TikTok | 9:16 | 1080x1920 | 3 min | 8 Mbps |
| Reels | 9:16 | 1080x1920 | 90s | 8 Mbps |
| Shorts | 9:16 | 1080x1920 | 60s | 10 Mbps |
| YouTube | 16:9 | 1920x1080 | Unlimited | 12 Mbps |
| Twitter | 16:9 | 1280x720 | 2:20 | 5 Mbps |

**Calidades de Export:**
- `draft`: CRF 28, ultrafast (previews rápidos)
- `standard`: CRF 23, medium (recomendado)
- `high`: CRF 20, slow (alta calidad)
- `max`: CRF 18, veryslow (profesional)

**Crop Modes:**
- `none`: Mantener aspect ratio original
- `center`: Crop centrado
- `letterbox`: Añadir barras negras
- `blur_fill`: Fondo difuminado (pendiente)
- `face_track`: Seguir caras (pendiente)

### 4.2 Smart Crop (16:9 → 9:16) ✅

**Descripción:** Convertir horizontal a vertical siguiendo la cara.
**Estado:** COMPLETADO

**Implementación:** `backend/services/face_tracking_service.py`

**Implementado:**
- [x] Center crop automático
- [x] Letterbox (barras negras)
- [x] Cálculo de dimensiones target
- [x] Face detection con OpenCV/MediaPipe
- [x] Calcular centro de atención por frame
- [x] Suavizar movimiento de crop (smoothing 0.7)
- [x] Integración con export pipeline

**Pendiente (nice-to-have):**
- [ ] Preview antes de exportar
- [ ] Override manual de crop position

### 4.3 Pipeline de Export con FFmpeg ✅

**Estado:** COMPLETADO

**Implementación:** `backend/services/export_service.py`

**Flow implementado:**
```
Clip definido
    │
    ├─ Descargar video fuente de Azure Blob
    ├─ Cortar segmento (start → end) con -ss seek
    ├─ Aplicar crop/scale según preset de plataforma
    ├─ Generar ASS y quemar subtítulos (si tiene)
    ├─ Re-encodear con libx264 + aac
    ├─ Optimizar para web (faststart)
    │
    └─ Subir a Azure Blob → URL descarga
```

**Características:**
- Lazy initialization de Azure clients
- Temp directory cleanup automático
- Progress tracking por clip
- Validación de plataforma y calidad
- Error handling robusto

### 4.4 Batch Export ✅

**Estado:** COMPLETADO

**Implementación:**
- `export_clips_batch()` en ExportService
- Endpoint `POST /editor/projects/{id}/export/batch`
- Tool `export_all_clips` para el agente

**Features:**
- [x] Exportar todos los clips a la vez
- [x] Elegir formato por clip o mismo para todos
- [x] Tracking de progreso por clip
- [x] Frontend ExportModal con batch mode
- [ ] Download all como ZIP (nice-to-have)
- [ ] Notificación cuando termine (nice-to-have)

### 4.6 Frontend Export UI ✅

**Estado:** COMPLETADO

**Implementación:** `frontend/components/editor/ExportModal.tsx`

**Features:**
- [x] Modal con selección de plataforma
- [x] Selección de calidad
- [x] Opciones avanzadas (crop mode, subtitles)
- [x] Estimación de tamaño de archivo
- [x] Indicador de progreso
- [x] Links de descarga cuando completo
- [x] Botón "Export All" en ClipsList
- [x] Integración con editor page

### 4.5 Export Tools para el Agente ✅

**Implementación:** `backend/agent/tools/export_tools.py`

Tools disponibles:
- `export_clip`: Exportar un clip individual
- `export_all_clips`: Exportar todos los clips
- `get_export_status`: Ver estado y URL de descarga
- `list_export_presets`: Mostrar opciones disponibles

---

## Fase 4.5: Code Quality & Maintenance

**Objetivo:** Código limpio, bien documentado y con buena cobertura de tests.
**Duración estimada:** 1-2 semanas
**Prioridad:** 🔴 ALTA (antes de Growth)
**Estado:** EN PROGRESO (0%)

### 4.5.1 Cleanup Inmediato (Alta Prioridad)

| Tarea | Estado | Impacto |
|-------|--------|---------|
| Eliminar `frontend/app/video/[id]/page-old.tsx` (794 líneas deprecated) | [x] | Alto - Reduce confusión |
| Corregir 11 usos de `any` en TypeScript frontend | [x] | Alto - Type safety |
| Resolver 6 TODO/FIXME comments en el codebase | [ ] | Medio - Deuda técnica |
| Crear `.env.example` para backend y frontend | [x] | Alto - Onboarding |
| Exportar OpenAPI schema (`/docs/openapi.json`) | [x] | Medio - Documentación API |

### 4.5.2 Testing Strategy

**Backend Tests (Existentes: 21 archivos, 74 funciones):**
- [ ] Añadir coverage report (`pytest-cov`)
- [ ] Target: 70% coverage para services críticos
- [ ] Priorizar tests para: `export_service.py`, `face_tracking_service.py`

**Frontend Tests (Actualmente: ninguno):**
- [ ] Configurar Vitest + React Testing Library
- [ ] Tests unitarios para componentes críticos:
  - [ ] `ExportModal.tsx` - lógica de export
  - [ ] `ClipsList.tsx` - drag & drop
  - [ ] `SubtitleEditor.tsx` - edición de cues
- [ ] Tests de integración para API client (`lib/api.ts`)

### 4.5.3 Code Quality Tools

- [ ] Configurar pre-commit hooks (husky + lint-staged)
- [ ] ESLint strict mode para frontend
- [ ] Ruff linting para backend (ya parcial)
- [ ] Type checking CI pipeline

### 4.5.4 Refactoring Candidates

**Servicios grandes a considerar dividir:**
| Servicio | Tamaño | Sugerencia |
|----------|--------|------------|
| `knowledge_graph.py` | 47KB | Dividir: queries, mutations, utils |
| `hierarchical_context_service.py` | 42KB | Extraer builders, formatters |

### 4.5.5 Documentation

- [ ] Actualizar README con nueva arquitectura Editor
- [ ] Documentar export pipeline (diagrama de flujo)
- [ ] API reference actualizada (60+ endpoints)
- [ ] Guía de contribución (`CONTRIBUTING.md`)

### 4.5.6 Git Hygiene

**Estado actual:** 35 archivos uncommitted (23 nuevos de Fase 4)

- [ ] Commit Fase 4 changes con mensaje descriptivo
- [ ] Crear branch `feature/code-quality` para cleanup
- [ ] Revisar archivos en staging area

---

## Fase 5: Growth & Monetización

**Objetivo:** Escalar usuarios y activar pagos.
**Duración estimada:** Ongoing
**Prioridad:** 🟢 MEDIA (post-MVP)

### 5.1 Stripe Integration

- [ ] Checkout para planes Creator/Pro/Team
- [ ] Webhooks para activar/desactivar features
- [ ] Portal de billing para usuarios
- [ ] Trials de 7 días

### 5.2 Límites por Plan

```python
PLAN_LIMITS = {
    "free": {
        "videos_per_month": 3,
        "max_resolution": "720p",
        "watermark": True,
        "export_formats": ["youtube"],
        "subtitle_styles": ["minimal"],
    },
    "creator": {
        "videos_per_month": 20,
        "max_resolution": "1080p",
        "watermark": False,
        "export_formats": ["all"],
        "subtitle_styles": ["all"],
    },
    "pro": {
        "videos_per_month": None,  # Unlimited
        "max_resolution": "4k",
        "watermark": False,
        "export_formats": ["all"],
        "subtitle_styles": ["all"],
        "priority_processing": True,
    },
}
```

### 5.3 Analytics & Retention

- [ ] Dashboard de uso (videos procesados, clips creados)
- [ ] Email: "Tienes 3 videos sin clips"
- [ ] Estadísticas: "Has ahorrado 12 horas este mes"

### 5.4 Viral Loops

- [ ] Watermark "Made with QPrisma" (free tier)
- [ ] Share clip con preview
- [ ] Referral: 1 mes gratis por referido

---

## 🛠️ Stack Técnico Actualizado

### Reutilizamos de QPrisma
| Componente | Uso en Editor |
|------------|---------------|
| FastAPI | Backend API |
| Next.js | Frontend |
| PostgreSQL | Proyectos, clips, usuarios |
| Redis | Cache, colas |
| Celery | Export async |
| Azure Blob | Videos, exports |
| Azure OpenAI | GPT-4, Whisper |
| FFmpeg | Procesamiento video |
| **Agentic Chat** | **Chat-to-Edit** |
| **VideoRAG** | **Búsqueda en videos** |

### Añadimos
| Componente | Uso |
|------------|-----|
| wavesurfer.js | Waveform en timeline |
| MediaPipe | Face tracking para crop |
| Stripe | Pagos |
| Remotion (opcional) | Render de subtítulos |

---

## 📅 Timeline Actualizado

```
Enero 2026 (semana 3-4)
    └─ Fase 1.1-1.2: Modelos + Tools del agente

Febrero 2026
    ├─ Semana 1: Fase 1.3: Prompt del agente editor
    ├─ Semana 2: Fase 1.4: UI unificada chat + preview
    ├─ Semana 3: Fase 1.5: Integración chat ↔ video
    └─ Semana 4: Testing + fixes MVP

Marzo 2026
    ├─ Semana 1-2: Fase 2: Timeline visual + auto-clips
    ├─ Semana 3: Fase 3: Subtítulos básicos
    └─ Semana 4: Beta privada (50 usuarios)

Abril 2026
    ├─ Semana 1-2: Fase 4: Export multi-formato
    ├─ Semana 3: Iteración feedback beta
    └─ Semana 4: Stripe integration

Mayo 2026
    └─ 🚀 Launch público
```

---

## 📊 Métricas de Éxito

### MVP (Febrero 2026)
- [ ] Chat-to-Edit funcional end-to-end
- [ ] 20 beta testers usando el producto
- [ ] 100 clips creados vía chat

### Beta (Marzo 2026)
- [ ] 100 usuarios beta
- [ ] NPS > 40
- [ ] Retention D7 > 30%

### Launch (Mayo 2026)
- [ ] 1,000 usuarios registrados
- [ ] 100 usuarios pagando
- [ ] MRR $2,000

---

## Changelog

| Fecha | Cambio |
|-------|--------|
| 2026-01-20 | **Fase 4.5 - 40%** - Completada limpieza inicial de código |
| 2026-01-20 | Eliminado `page-old.tsx` deprecated (794 líneas), corregidos 21 usos de `any` en frontend |
| 2026-01-20 | Añadido script `export_openapi.py` para generar documentación API |
| 2026-01-20 | **Fase 4.5 Añadida** - Plan de Code Quality & Maintenance con cleanup, testing, docs |
| 2026-01-20 | Análisis de codebase: 21 test files backend, 11 TypeScript `any` usages, 1 deprecated file |
| 2026-01-20 | **Fase 4 - Export 90%** - Export completo con face tracking y frontend UI |
| 2026-01-20 | Añadido `face_tracking_service.py` con detección de caras OpenCV/MediaPipe |
| 2026-01-20 | Añadido `ExportModal.tsx` frontend con selección de plataforma/calidad |
| 2026-01-20 | Añadido botón "Export All" en ClipsList |
| 2026-01-20 | Integrado face tracking en export pipeline para smart crop |
| 2026-01-20 | Añadido API methods en frontend: exportClip, exportClipsBatch, getExportPresets |
| 2026-01-20 | **Fase 4 - Export 60%** - FFmpeg pipeline completo, presets de plataformas, batch export |
| 2026-01-20 | Añadido `export_config.py` con presets para 5 plataformas y 4 niveles de calidad |
| 2026-01-20 | Añadido `export_service.py` con pipeline FFmpeg: cut + crop + subtitle burn + encode |
| 2026-01-20 | Añadido endpoints de export: `/clips/{id}/export`, `/projects/{id}/export/batch` |
| 2026-01-20 | Añadido export tools para el agente: `export_clip`, `export_all_clips`, `get_export_status` |
| 2026-01-20 | Actualizado `prompts.py` con documentación de export para el agente |
| 2026-01-19 | **Fase 3 COMPLETADA** - Subtítulos con 5 estilos, preview en tiempo real, edición inline |
| 2026-01-19 | Añadido SubtitleService con generación de cues desde transcripción Whisper |
| 2026-01-19 | Añadido SubtitleOverlay con animaciones (word_by_word, pop, fade, karaoke, slide) |
| 2026-01-19 | Añadido SubtitleEditor con selector de estilos y edición de cues |
| 2026-01-19 | Integrado subtítulos en EditorVideoPanel y página del editor |
| 2026-01-19 | **Fase 2 COMPLETADA** - Timeline visual con waveform, drag handles, viral scores |
| 2026-01-19 | Añadido TimelineWaveform component con wavesurfer.js v7 |
| 2026-01-19 | Implementado ViralScoreService con algoritmo de análisis de contenido |
| 2026-01-19 | Drag & drop para reordenar clips en ClipsList |
| 2026-01-19 | **Fase 1 COMPLETADA** - Chat-to-Edit MVP funcionando end-to-end |
| 2026-01-19 | Añadido preview mode para clips (play solo el segmento) |
| 2026-01-19 | Fix streaming chat endpoint con source_media info |
| 2026-01-19 | Clips list ahora incluye IDs para modify_clip |
| 2026-01-16 | Pivote a Chat-to-Edit como core feature |
| 2026-01-16 | Documento inicial creado |

---

## ✅ Implementación Completada (Fase 1)

### Backend
| Archivo | Descripción |
|---------|-------------|
| `backend/api/routes/editor_routes.py` | CRUD proyectos + streaming chat endpoint |
| `backend/agent/editor_agent.py` | EditorAgent con contexto de proyecto |
| `backend/agent/tools/editor_tools.py` | CreateClip, ModifyClip, DeleteClip, etc. |
| `backend/agent/prompts.py` | System prompt del editor |
| `backend/models/editor.py` | Pydantic models para API |
| `backend/models/database.py` | EditorProjectModel, ClipModel |
| `backend/services/database_service.py` | CRUD para proyectos y clips |

### Frontend
| Archivo | Descripción |
|---------|-------------|
| `frontend/app/editor/page.tsx` | Lista de proyectos |
| `frontend/app/editor/[projectId]/page.tsx` | Editor con video + chat |
| `frontend/components/editor/EditorLayout.tsx` | Layout 2 columnas |
| `frontend/components/editor/EditorVideoPanel.tsx` | Video player + timeline + preview mode |
| `frontend/components/editor/EditorChat.tsx` | Chat con streaming SSE |
| `frontend/components/editor/ClipsList.tsx` | Lista de clips con acciones |
| `frontend/components/editor/ClipCard.tsx` | Tarjeta de clip individual |
| `frontend/lib/api.ts` | Cliente API con streaming |

### Endpoints Implementados
```
POST   /editor/projects                           # Crear proyecto
GET    /editor/projects                           # Listar proyectos del usuario
GET    /editor/projects/{id}                      # Proyecto con clips + source_media
PATCH  /editor/projects/{id}                      # Actualizar proyecto
DELETE /editor/projects/{id}                      # Eliminar proyecto

POST   /editor/projects/{id}/clips                # Crear clip
GET    /editor/projects/{id}/clips                # Listar clips
PATCH  /editor/clips/{id}                         # Actualizar clip
DELETE /editor/clips/{id}                         # Eliminar clip
PUT    /editor/clips/{id}/subtitles               # Actualizar subtítulos
POST   /editor/projects/{id}/clips/reorder        # Reordenar clips
DELETE /editor/projects/{id}/clips/bulk           # Eliminar múltiples clips

POST   /editor/projects/{id}/chat/stream          # Chat-to-Edit (SSE streaming)
```

### Tools del Agente Implementadas
| Tool | Descripción |
|------|-------------|
| `create_clip` | Crear clip con start/end time |
| `modify_clip` | Modificar título, tiempos, extender |
| `delete_clip` | Eliminar clip por ID |
| `list_clips` | Listar clips del proyecto |
| `reorder_clips` | Cambiar orden de clips |
| `add_subtitles` | Activar subtítulos en clip |
| `change_subtitle_style` | Cambiar estilo (hormozi, mrbeast, etc) |
| `remove_subtitles` | Desactivar subtítulos |
| `list_subtitle_styles` | Mostrar estilos disponibles |
| `generate_auto_clips` | Genera clips automáticos con viral scores |

---

## ✅ Implementación Completada (Fase 2)

### Backend
| Archivo | Descripción |
|---------|-------------|
| `backend/services/viral_score_service.py` | Algoritmo de viral score multi-factor |
| `backend/agent/tools/auto_clip_tools.py` | GenerateAutoClipsTool mejorado |

### Frontend
| Archivo | Descripción |
|---------|-------------|
| `frontend/components/editor/TimelineWaveform.tsx` | Waveform + clip overlays + drag handles |
| `frontend/components/editor/ClipsList.tsx` | Drag & drop para reordenar clips |
| `frontend/components/editor/index.ts` | Export de TimelineWaveform |
| `frontend/app/editor/[projectId]/page.tsx` | Integración de timeline + handlers |

---

## ✅ Implementación Completada (Fase 3)

### Backend
| Archivo | Descripción |
|---------|-------------|
| `backend/services/subtitle_service.py` | Generación de subtítulos con 5 estilos pre-diseñados |
| `backend/api/routes/editor_routes.py` | Endpoints de subtítulos (generate, get, update, export SRT) |
| `backend/agent/tools/subtitle_tools.py` | Tools actualizadas con SubtitleService |

### Frontend
| Archivo | Descripción |
|---------|-------------|
| `frontend/components/editor/SubtitleOverlay.tsx` | Preview de subtítulos sobre video con animaciones |
| `frontend/components/editor/SubtitleEditor.tsx` | Editor de subtítulos con lista de cues y estilos |
| `frontend/components/editor/EditorVideoPanel.tsx` | Integración de SubtitleOverlay |
| `frontend/app/editor/[projectId]/page.tsx` | Integración completa de edición de subtítulos |
| `frontend/lib/api.ts` | Cliente API con métodos de subtítulos |

### Endpoints de Subtítulos
```
GET    /editor/subtitle-styles                    # Lista estilos disponibles
POST   /editor/clips/{id}/subtitles/generate      # Genera subtítulos desde transcripción
GET    /editor/clips/{id}/subtitles               # Obtiene datos de subtítulos
PATCH  /editor/clips/{id}/subtitles/cue           # Edita texto de un cue
GET    /editor/clips/{id}/subtitles/srt           # Exporta SRT
```

### Estilos de Subtítulos
| Estilo | Animación | Descripción |
|--------|-----------|-------------|
| `hormozi` | word_by_word | Palabra por palabra, bold, amarillo/blanco alternante |
| `mrbeast` | pop | Grande, centrado, all-caps, sombra dramática |
| `minimal` | fade | Pequeño, limpio, sin fondo |
| `karaoke` | karaoke | Resalta palabra actual en color diferente |
| `news` | slide | Lower third, fondo semi-transparente |

---

## Próximos pasos inmediatos

### Fase 4: Nice-to-have (Opcional)
1. **Blur Fill Background**: Fondo difuminado para videos verticales (CropMode.BLUR_FILL)
2. **ZIP Download**: Descargar todos los clips en un ZIP
3. **Export Queue con Celery**: Cola de procesamiento asíncrona para mejor UX
4. **Preview antes de export**: Ver el crop/resultado antes de procesar

### Fase 5: Growth & Monetización (Siguiente)
1. **Stripe Integration**: Checkout, webhooks, billing portal
2. **Plan Limits**: Free, Creator, Pro, Team limits
3. **Analytics Dashboard**: Métricas de uso por usuario
4. **Watermark para Free tier**: Branding en videos gratuitos

### Prioridades Técnicas Completadas
- [x] Export real de clips con FFmpeg
- [x] Subtítulos quemados en video (usando ASS generado)
- [x] Smart crop para vertical (face tracking con OpenCV/MediaPipe)
- [x] Frontend UI para export (ExportModal, botones, progreso, descargas)
- [x] Batch export de múltiples clips
- [x] API endpoints completos
- [x] Agent tools para export via chat

---

## 🚧 Implementación En Progreso (Fase 4)

### Backend
| Archivo | Descripción |
|---------|-------------|
| `backend/models/export_config.py` | Presets de plataformas, calidades, crop modes |
| `backend/services/export_service.py` | Pipeline FFmpeg: download → cut → crop → subtitles → encode → upload |
| `backend/api/routes/editor_routes.py` | Endpoints de export (single, batch, status, presets) |
| `backend/agent/tools/export_tools.py` | Tools: export_clip, export_all_clips, get_export_status, list_export_presets |
| `backend/agent/tools/__init__.py` | Registro de export tools |
| `backend/agent/prompts.py` | System prompt con documentación de export |

### Endpoints de Export
```
GET    /editor/export/presets                       # Lista plataformas y calidades
POST   /editor/export/estimate                      # Estima tiempo y tamaño
POST   /editor/clips/{id}/export                    # Exporta clip individual
POST   /editor/projects/{id}/export/batch           # Exporta múltiples clips
GET    /editor/clips/{id}/export/status             # Estado y URL de descarga
```

### Tools del Agente para Export
| Tool | Descripción |
|------|-------------|
| `export_clip` | Exportar clip a plataforma (TikTok, Reels, etc.) |
| `export_all_clips` | Exportar todos los clips del proyecto |
| `get_export_status` | Ver estado y obtener URL de descarga |
| `list_export_presets` | Mostrar opciones de export disponibles |

### Presets de Plataformas Implementados
| Plataforma | Aspect | Resolución | Bitrate | Max Duración |
|------------|--------|------------|---------|--------------|
| TikTok | 9:16 | 1080x1920 | 8 Mbps | 180s |
| Reels | 9:16 | 1080x1920 | 8 Mbps | 90s |
| Shorts | 9:16 | 1080x1920 | 10 Mbps | 60s |
| YouTube | 16:9 | 1920x1080 | 12 Mbps | ∞ |
| Twitter | 16:9 | 1280x720 | 5 Mbps | 140s |

### Presets de Calidad
| Calidad | CRF | Preset FFmpeg | Uso |
|---------|-----|---------------|-----|
| draft | 28 | ultrafast | Previews rápidos |
| standard | 23 | medium | Uso general |
| high | 20 | slow | Alta calidad |
| max | 18 | veryslow | Profesional |

### Face Tracking Service
| Archivo | Descripción |
|---------|-------------|
| `backend/services/face_tracking_service.py` | Detección de caras con OpenCV/MediaPipe |

**Características:**
- MediaPipe Face Detection (preferido, más preciso)
- OpenCV DNN Face Detection (fallback)
- OpenCV Haar Cascades (fallback legacy)
- Análisis de video por frames
- Suavizado de movimiento de crop
- Generación de filtros FFmpeg

### Frontend Export
| Archivo | Descripción |
|---------|-------------|
| `frontend/components/editor/ExportModal.tsx` | Modal de export con todas las opciones |
| `frontend/components/editor/ClipsList.tsx` | Añadido botón "Export All" |
| `frontend/lib/api.ts` | API methods: exportClip, exportClipsBatch, getExportPresets |
| `frontend/app/editor/[projectId]/page.tsx` | Integración de ExportModal |

**Features del ExportModal:**
- Selección visual de plataformas (TikTok, Reels, Shorts, YouTube, Twitter)
- Selección de calidad (draft, standard, high, max)
- Opciones avanzadas: crop mode, burn subtitles
- Estimación de tamaño de archivo
- Indicador de progreso durante export
- Links de descarga cuando completo
- Soporte para single clip y batch export
