# QPrisma Frontend UX/UI Redesign Proposal

> ✅ **STATUS: IMPLEMENTED** - This redesign has been implemented. See the new components below.

## 🎯 Objetivo

Transformar QPrisma en la **mejor aplicación de análisis de video con IA del mercado**, combinando:
- Interfaz conversacional intuitiva (inspirada en Vimo/ChatGPT)
- Feedback visual en tiempo real del procesamiento
- Modo de chat con video individual o múltiples videos (Drive)
- Diseño moderno, limpio y profesional

---

## 📐 Nueva Arquitectura de Interfaz

### Layout Principal (3 Columnas)

```
┌─────────────────────────────────────────────────────────────────────┐
│  SIDEBAR (280px)     │  MAIN CONTENT (flex)    │  VIDEO PANEL (40%) │
│                      │                         │                     │
│  ┌─────────────────┐ │  ┌─────────────────────┐│  ┌───────────────┐ │
│  │ 🎬 QPrisma      │ │  │                     ││  │               │ │
│  └─────────────────┘ │  │   CHAT MESSAGES     ││  │  VIDEO PLAYER │ │
│                      │  │                     ││  │               │ │
│  ┌─────────────────┐ │  │   - User messages   ││  │  + Timeline   │ │
│  │ + New Chat      │ │  │   - AI responses    ││  │  + Scenes     │ │
│  └─────────────────┘ │  │   - Video snippets  ││  │               │ │
│                      │  │                     ││  └───────────────┘ │
│  MODO ACTUAL:        │  │                     ││                     │
│  ○ Single Video      │  │                     ││  ┌───────────────┐ │
│  ○ Video Library     │  │                     ││  │  CHAPTERS     │ │
│                      │  │                     ││  │  TRANSCRIPT   │ │
│  ──────────────────  │  └─────────────────────┘│  └───────────────┘ │
│                      │                         │                     │
│  CONVERSATIONS:      │  ┌─────────────────────┐│                     │
│  📹 Video 1 chat     │  │  ╔═══════════════╗  ││                     │
│  📹 Video 2 chat     │  │  ║  INPUT AREA   ║  ││                     │
│  📚 Library search   │  │  ╚═══════════════╝  ││                     │
│                      │  └─────────────────────┘│                     │
│  ──────────────────  │                         │                     │
│  👤 User Profile     │                         │                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🌟 Características Principales

### 1. **Dos Modos de Interacción**

#### Modo 1: Chat con Video Individual
- Seleccionar un video específico de tu biblioteca
- El chat tiene contexto completo de ese video
- Navegación por capítulos/escenas en el panel derecho
- Click en timestamps del chat → salta al momento del video

#### Modo 2: Chat con Video Library (Multi-video)
- Busca información en TODOS tus videos
- Respuestas con referencias a múltiples videos
- "¿En qué video hablo sobre machine learning?"
- Resultados con thumbnails y links a cada video

```tsx
// Selector de modo en el sidebar
<ModeSelector>
  <ModeOption 
    icon={<Film />}
    label="Single Video"
    description="Chat con un video específico"
    active={mode === 'single'}
  />
  <ModeOption 
    icon={<Library />}
    label="Video Library"
    description="Buscar en todos tus videos"
    active={mode === 'library'}
  />
</ModeSelector>
```

---

### 2. **Experiencia de Upload con Feedback en Tiempo Real**

El upload es el primer momento de "magia" para el usuario. Debe ser **espectacular**.

#### Estados de Procesamiento:

```
┌─────────────────────────────────────────────────────────────────┐
│  🎬 video_conference.mp4                                    ⋮  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ████████████████████░░░░░░░░░░  65%                           │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ✓ Uploading to cloud               2.3 GB / 2.3 GB      │   │
│  │ ✓ Extracting audio                 00:45:30 duration    │   │
│  │ ✓ Transcribing speech              1,234 words          │   │
│  │ ● Analyzing visual frames          156 / 240 frames     │   │
│  │ ○ Detecting scenes                 pending              │   │
│  │ ○ Building knowledge graph         pending              │   │
│  │ ○ Generating embeddings            pending              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ⏱️ Estimated: 3 min remaining                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### Componente: ProcessingProgressCard

```tsx
interface ProcessingStep {
  id: string;
  name: string;
  status: 'pending' | 'in_progress' | 'completed' | 'error';
  progress?: number;
  details?: string;
  startTime?: Date;
  endTime?: Date;
}

const PROCESSING_STEPS: ProcessingStep[] = [
  { id: 'upload', name: 'Uploading to cloud', icon: CloudUpload },
  { id: 'audio', name: 'Extracting audio', icon: AudioLines },
  { id: 'transcribe', name: 'Transcribing speech', icon: Mic },
  { id: 'frames', name: 'Analyzing visual frames', icon: Eye },
  { id: 'scenes', name: 'Detecting scenes', icon: Layers },
  { id: 'graph', name: 'Building knowledge graph', icon: Network },
  { id: 'embeddings', name: 'Generating embeddings', icon: Brain },
];
```

#### WebSocket Integration (ya tienes la base):

```typescript
// hooks/useProcessingProgress.ts
export function useProcessingProgress(jobId: string) {
  const [steps, setSteps] = useState<ProcessingStep[]>([]);
  const [overallProgress, setOverallProgress] = useState(0);
  
  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/ws/jobs/${jobId}`);
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'job_progress') {
        setOverallProgress(data.payload.progress);
        updateStep(data.payload.stage, {
          status: 'in_progress',
          progress: data.payload.step_progress,
          details: data.payload.message,
        });
      }
      
      if (data.type === 'job_completed') {
        // Celebración! 🎉
        triggerConfetti();
        markAllCompleted();
      }
    };
    
    return () => ws.close();
  }, [jobId]);
  
  return { steps, overallProgress };
}
```

---

### 3. **Interfaz de Chat Renovada**

#### Welcome Screen (Sin conversación activa)

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                          🎬                                     │
│                                                                 │
│              Welcome to QPrisma                                 │
│                                                                 │
│       Unlock intelligent insights from your videos              │
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │  📹 Upload Video │  │  📚 Video Library │                    │
│  │                  │  │                  │                    │
│  │  Start analyzing │  │  Search across   │                    │
│  │  a new video     │  │  all your videos │                    │
│  └──────────────────┘  └──────────────────┘                    │
│                                                                 │
│        ─────────  Quick Suggestions  ─────────                  │
│                                                                 │
│  "Summarize the main topics"  "Find action scenes"              │
│  "Extract key quotes"          "What objects appear?"           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Chat Messages con Referencias Temporales

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                          ┌──────────────────────────────────┐   │
│                          │  What are the main topics        │   │
│                          │  discussed in this video?        │   │
│                          └──────────────────────────────────┘   │
│                                                          You 👤 │
│                                                                 │
│  🤖 QPrisma                                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  The video covers three main topics:                     │   │
│  │                                                          │   │
│  │  1. **Introduction to AI** (0:00 - 5:30)                │   │
│  │     Overview of machine learning concepts                │   │
│  │     ┌────────────┐                                       │   │
│  │     │ 🎬 0:00:45 │ ← Click to jump                      │   │
│  │     └────────────┘                                       │   │
│  │                                                          │   │
│  │  2. **Neural Networks** (5:30 - 15:00)                  │   │
│  │     Deep dive into architecture and training             │   │
│  │     ┌────────────┐ ┌────────────┐                       │   │
│  │     │ 🎬 5:45    │ │ 🎬 12:30   │                       │   │
│  │     └────────────┘ └────────────┘                       │   │
│  │                                                          │   │
│  │  3. **Practical Applications** (15:00 - 25:00)          │   │
│  │     Real-world examples and demos                        │   │
│  │     ┌────────────┐                                       │   │
│  │     │ 🎬 18:20   │                                       │   │
│  │     └────────────┘                                       │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Chat Input Mejorado

```tsx
// components/chat/ChatInput.tsx
<div className="relative">
  {/* Attachments preview */}
  {attachedVideos.length > 0 && (
    <AttachedVideosBar videos={attachedVideos} onRemove={removeVideo} />
  )}
  
  {/* Input area */}
  <div className="flex items-end gap-3 p-4 bg-white rounded-2xl border shadow-lg">
    <button onClick={openVideoSelector} className="p-2 hover:bg-gray-100 rounded-lg">
      <Plus className="w-5 h-5 text-gray-500" />
    </button>
    
    <textarea
      value={input}
      onChange={(e) => setInput(e.target.value)}
      placeholder="Ask anything about your video..."
      className="flex-1 resize-none focus:outline-none"
      rows={1}
    />
    
    <button 
      onClick={sendMessage}
      disabled={!input.trim() || isProcessing}
      className="p-3 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-xl"
    >
      <Send className="w-4 h-4 text-white" />
    </button>
  </div>
  
  <p className="text-xs text-gray-400 text-center mt-2">
    Press Enter to send • Shift+Enter for new line
  </p>
</div>
```

---

### 4. **Video Panel con Información Enriquecida**

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                           │  │
│  │                    VIDEO PLAYER                           │  │
│  │                                                           │  │
│  │                    🎬 ▶️ 12:34 / 45:00                    │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─ Scene Timeline ─────────────────────────────────────────┐  │
│  │ ██████░░██████████░░░░████████░░░░░░██████████████████░░ │  │
│  │ Intro  │ Topic 1   │      Topic 2      │   Conclusion   │  │
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  📑 CHAPTERS        📝 TRANSCRIPT       🏷️ ENTITIES       ││
│  ├─────────────────────────────────────────────────────────────┤│
│  │  ▸ Chapter 1: Introduction              0:00              ││
│  │  ▾ Chapter 2: Main Content              5:30              ││
│  │      Scene 2.1: Setup                   5:30              ││
│  │      Scene 2.2: Demonstration           8:45              ││
│  │  ▸ Chapter 3: Conclusion               20:00              ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 🎨 Sistema de Diseño

### Paleta de Colores

```css
:root {
  /* Primary - Gradient de Indigo a Purple */
  --primary-start: #6366f1;  /* indigo-500 */
  --primary-end: #a855f7;    /* purple-500 */
  
  /* Backgrounds */
  --bg-primary: #ffffff;
  --bg-secondary: #f8fafc;   /* slate-50 */
  --bg-tertiary: #f1f5f9;    /* slate-100 */
  
  /* Accent */
  --accent-success: #22c55e; /* green-500 */
  --accent-warning: #f59e0b; /* amber-500 */
  --accent-error: #ef4444;   /* red-500 */
  --accent-info: #3b82f6;    /* blue-500 */
  
  /* Text */
  --text-primary: #0f172a;   /* slate-900 */
  --text-secondary: #64748b; /* slate-500 */
  --text-muted: #94a3b8;     /* slate-400 */
}
```

### Animaciones

```css
/* Entrada suave de mensajes */
@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Pulso de procesamiento */
@keyframes pulse-ring {
  0% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.1); opacity: 0.5; }
  100% { transform: scale(1); opacity: 1; }
}

/* Typing indicator */
@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); }
  40% { transform: translateY(-5px); }
}
```

---

## 📁 Nueva Estructura de Componentes

```
frontend/
├── app/
│   ├── page.tsx                    # Welcome/Landing
│   ├── chat/
│   │   ├── page.tsx               # New chat
│   │   └── [id]/page.tsx          # Chat conversation
│   ├── library/
│   │   └── page.tsx               # Video library view
│   └── video/
│       └── [id]/page.tsx          # Video detail (legacy)
│
├── components/
│   ├── layout/
│   │   ├── AppLayout.tsx          # Main 3-column layout
│   │   ├── Sidebar.tsx            # Left sidebar
│   │   ├── MainContent.tsx        # Center content area
│   │   └── VideoPanel.tsx         # Right video panel
│   │
│   ├── chat/
│   │   ├── ChatContainer.tsx      # Chat wrapper
│   │   ├── MessageList.tsx        # Messages display
│   │   ├── ChatMessage.tsx        # Individual message
│   │   ├── ChatInput.tsx          # Input area
│   │   ├── WelcomeScreen.tsx      # Empty state
│   │   ├── TypingIndicator.tsx    # Loading state
│   │   └── TimestampBadge.tsx     # Clickable timestamp
│   │
│   ├── video/
│   │   ├── VideoPlayer.tsx        # Video player
│   │   ├── SceneTimeline.tsx      # Visual timeline
│   │   ├── ChapterList.tsx        # Chapters panel
│   │   ├── TranscriptPanel.tsx    # Transcript view
│   │   └── EntityList.tsx         # Detected entities
│   │
│   ├── upload/
│   │   ├── UploadZone.tsx         # Drag & drop area
│   │   ├── ProcessingCard.tsx     # Processing status
│   │   ├── ProcessingStep.tsx     # Individual step
│   │   └── UploadProgress.tsx     # Upload progress bar
│   │
│   ├── library/
│   │   ├── VideoGrid.tsx          # Video thumbnails grid
│   │   ├── VideoCard.tsx          # Individual video card
│   │   └── LibrarySearch.tsx      # Search across videos
│   │
│   └── ui/
│       ├── Button.tsx
│       ├── Input.tsx
│       ├── Modal.tsx
│       ├── Toast.tsx
│       └── ProgressBar.tsx
│
├── hooks/
│   ├── useChat.ts                 # Chat state management
│   ├── useWebSocket.ts            # WebSocket connection
│   ├── useProcessingProgress.ts   # Processing updates
│   ├── useVideoPlayer.ts          # Video player controls
│   └── useVideoLibrary.ts         # Library management
│
├── contexts/
│   ├── AuthContext.tsx            # (existing)
│   ├── ChatContext.tsx            # Chat state
│   └── VideoContext.tsx           # Current video state
│
└── lib/
    ├── api.ts                     # (existing)
    └── websocket.ts               # WebSocket utilities
```

---

## 🔄 Flujos de Usuario

### Flujo 1: Usuario Nuevo

```
1. Llega a la app → Ve Welcome Screen
2. Click "Upload Video" → Drag & drop o file picker
3. Video se sube → Ve ProcessingCard con pasos en tiempo real
4. Procesamiento completo → 🎉 Confetti + "Tu video está listo!"
5. Automáticamente entra en modo Chat con ese video
6. Quick suggestions le ayudan a empezar
```

### Flujo 2: Buscar en Biblioteca

```
1. Usuario tiene 10+ videos procesados
2. Click en modo "Video Library"
3. Escribe: "¿En qué videos hablo sobre React?"
4. QPrisma busca en todos los videos
5. Respuesta muestra clips de 3 videos diferentes con timestamps
6. Click en un resultado → Abre ese video en el momento exacto
```

### Flujo 3: Análisis Profundo de Video

```
1. Usuario selecciona un video específico
2. Chat mode: Single Video
3. Pregunta: "Dame un resumen ejecutivo de 5 puntos"
4. QPrisma responde con bullets + timestamps clickeables
5. Usuario hace click en timestamp → Video salta a ese momento
6. Puede ver chapters en el panel derecho
7. Sigue preguntando sobre detalles específicos
```

---

## 🚀 Implementación por Fases

### Fase 1: Foundation (1 semana)
- [ ] Nuevo layout de 3 columnas
- [ ] Componente Sidebar con navegación
- [ ] Welcome Screen rediseñado
- [ ] Migrar upload existente

### Fase 2: Chat Interface (1 semana)
- [ ] MessageList con nuevo diseño
- [ ] ChatInput mejorado
- [ ] TimestampBadge clickeable
- [ ] Typing indicator

### Fase 3: Processing Experience (3-4 días)
- [ ] ProcessingCard con pasos visuales
- [ ] Integración WebSocket para updates
- [ ] Animaciones de progreso
- [ ] Notificación de completado

### Fase 4: Video Panel (4-5 días)
- [ ] Video player integrado
- [ ] Scene timeline visual
- [ ] Chapter navigation
- [ ] Transcript panel

### Fase 5: Multi-Video Mode (1 semana)
- [ ] Video Library grid
- [ ] Búsqueda cross-video
- [ ] Resultados multi-fuente
- [ ] Mode selector en sidebar

---

## 💡 Ideas Adicionales para Destacar

### 1. **"Video Moments" - Clips Compartibles**
- Usuario puede seleccionar un rango de tiempo
- Genera un link compartible a ese momento
- Preview con thumbnail + timestamp

### 2. **"AI Highlights" - Resumen Automático**
- Al procesar, genera automáticamente:
  - 5 momentos clave del video
  - Thumbnail de cada momento
  - Descripción breve
- Aparece como "Quick Highlights" en el panel

### 3. **"Smart Chapters" - Navegación Visual**
- Timeline con preview de frames
- Hover para ver preview del momento
- Drag para recorrer rápido

### 4. **"Voice Chat" - Hablar con tu Video**
- Botón de micrófono en el input
- Preguntas por voz, respuestas escritas
- Ideal para manos ocupadas

### 5. **"Export Report" - Documentación**
- Genera PDF/Markdown con:
  - Resumen completo
  - Transcripción
  - Timestamps de momentos clave
  - Entidades detectadas

---

## 🔧 Tecnologías Sugeridas

| Característica | Tecnología |
|----------------|------------|
| Animaciones | Framer Motion |
| Video Player | react-player o video.js |
| Iconos | Lucide React (ya instalado) |
| Tooltips | @radix-ui/react-tooltip |
| Toasts | react-hot-toast o sonner |
| Confetti | canvas-confetti |
| Markdown | react-markdown |
| Virtual List | react-window (para chats largos) |

---

## ✅ Checklist de UX

- [ ] **Feedback inmediato**: Toda acción tiene feedback visual
- [ ] **Estados de carga**: Siempre mostrar qué está pasando
- [ ] **Errores claros**: Mensajes de error útiles y accionables
- [ ] **Shortcuts de teclado**: Enter para enviar, Esc para cerrar
- [ ] **Responsive**: Funciona en tablet y desktop
- [ ] **Accesibilidad**: Labels ARIA, focus management
- [ ] **Animaciones suaves**: 60fps, no intrusivas
- [ ] **Empty states**: Guían al usuario cuando no hay contenido

---

## 📝 Conclusión

Esta propuesta transforma QPrisma de una herramienta de procesamiento de video a una **experiencia conversacional de análisis de video**. Los puntos clave son:

1. **Chat-first**: La interfaz principal es conversacional
2. **Feedback real-time**: WebSockets para updates de procesamiento
3. **Multi-modo**: Un video o toda la biblioteca
4. **Navegación temporal**: Timestamps clickeables en todo
5. **Diseño premium**: Gradientes, animaciones, micro-interacciones

La implementación aprovecha tu infraestructura existente (WebSockets, chat routes, procesamiento) pero con una capa de UX moderna que hace la diferencia.

---

*Documento creado: Enero 2026*
*Versión: 1.0*
