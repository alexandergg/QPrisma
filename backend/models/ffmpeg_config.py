"""
FFmpeg Configuration Models
Modelos Pydantic para configuración de procesamiento de video con FFmpeg.
Inspirado en la arquitectura de Edconv para máxima customización.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LogLevel(str, Enum):
    """Niveles de log de FFmpeg"""

    QUIET = "quiet"
    PANIC = "panic"
    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    VERBOSE = "verbose"
    DEBUG = "debug"
    TRACE = "trace"


class PixelFormat(str, Enum):
    """Formatos de píxel soportados"""

    YUV420P = "yuv420p"  # 8-bit
    YUV420P10LE = "yuv420p10le"  # 10-bit
    YUV422P = "yuv422p"
    YUV444P = "yuv444p"
    RGB24 = "rgb24"
    RGBA = "rgba"
    GRAY = "gray"


class VideoCodec(str, Enum):
    """Codecs de video soportados"""

    H264 = "libx264"
    H265 = "libx265"
    VP9 = "libvpx-vp9"
    AV1 = "libsvtav1"
    COPY = "copy"


class ScalingFilter(str, Enum):
    """Filtros de escalado"""

    BILINEAR = "bilinear"
    BICUBIC = "bicubic"
    LANCZOS = "lanczos"
    SPLINE16 = "spline16"
    SPLINE36 = "spline36"
    NEIGHBOR = "neighbor"


class FrameExtractionMethod(str, Enum):
    """Métodos de extracción de frames"""

    FPS = "fps"  # Extraer a N FPS
    INTERVAL = "interval"  # Extraer cada N segundos
    KEYFRAMES = "keyframes"  # Solo keyframes
    SCENE_DETECT = "scene_detect"  # Detección de cambio de escena
    UNIFORM = "uniform"  # N frames uniformemente distribuidos
    ADAPTIVE = "adaptive"  # Adaptativo según duración del video
    HYBRID = "hybrid"  # Combinación de scene_detect + uniform fill


class FrameExtractionConfig(BaseModel):
    """Configuración de extracción de frames"""

    method: FrameExtractionMethod = Field(
        default=FrameExtractionMethod.FPS, description="Método de extracción de frames"
    )

    # Para método FPS
    fps: float | None = Field(
        default=1.0, description="Frames por segundo a extraer (método FPS)", gt=0, le=60
    )

    # Para método INTERVAL
    interval_seconds: float | None = Field(
        default=5.0, description="Intervalo en segundos entre frames (método INTERVAL)", gt=0
    )

    # Para método UNIFORM
    num_frames: int | None = Field(
        default=10, description="Número total de frames a extraer (método UNIFORM)", gt=0, le=1000
    )

    # Para método SCENE_DETECT
    scene_threshold: float | None = Field(
        default=0.4, description="Umbral de detección de escena (0-1)", ge=0, le=1
    )

    # Para método HYBRID (scene_detect + uniform fill)
    hybrid_scene_ratio: float | None = Field(
        default=0.6, description="Ratio de frames de escenas vs uniform (0.6 = 60% escenas, 40% fill)", ge=0, le=1
    )
    hybrid_min_gap_seconds: float | None = Field(
        default=10.0, description="Gap mínimo en segundos entre frames antes de insertar fill frames", gt=0
    )

    # Límites generales
    max_frames: int | None = Field(
        default=100, description="Número máximo de frames a extraer", gt=0
    )

    start_time: float | None = Field(
        default=None, description="Tiempo de inicio en segundos (None = desde el principio)", ge=0
    )

    end_time: float | None = Field(
        default=None, description="Tiempo de fin en segundos (None = hasta el final)", gt=0
    )

    @field_validator("end_time")
    @classmethod
    def end_time_must_be_after_start(cls, v: float | None, info) -> float | None:
        """Validar que end_time > start_time"""
        if v is not None and info.data.get("start_time") is not None and v <= info.data["start_time"]:
            raise ValueError("end_time debe ser mayor que start_time")
        return v


class VideoFilterConfig(BaseModel):
    """Configuración de filtros de video"""

    # Escalado
    scale_width: int | None = Field(
        default=None, description="Ancho de escalado (None = mantener original)", gt=0
    )
    scale_height: int | None = Field(
        default=None, description="Alto de escalado (None = mantener original)", gt=0
    )
    scaling_filter: ScalingFilter = Field(
        default=ScalingFilter.LANCZOS, description="Algoritmo de escalado"
    )

    # Formato de píxel
    pixel_format: PixelFormat | None = Field(default=None, description="Formato de píxel de salida")

    # Recorte
    crop_x: int | None = Field(default=None, description="Posición X de recorte", ge=0)
    crop_y: int | None = Field(default=None, description="Posición Y de recorte", ge=0)
    crop_width: int | None = Field(default=None, description="Ancho de recorte", gt=0)
    crop_height: int | None = Field(default=None, description="Alto de recorte", gt=0)

    # Ajustes de color
    brightness: float | None = Field(
        default=None, description="Ajuste de brillo (-1 a 1)", ge=-1, le=1
    )
    contrast: float | None = Field(
        default=None, description="Ajuste de contraste (0 a 4)", ge=0, le=4
    )
    saturation: float | None = Field(
        default=None, description="Ajuste de saturación (0 a 3)", ge=0, le=3
    )

    # Rotación
    rotate: int | None = Field(default=None, description="Rotación en grados (0, 90, 180, 270)")

    # Desentrelazado
    deinterlace: bool = Field(default=False, description="Aplicar desentrelazado")

    # HDR a SDR
    hdr_to_sdr: bool = Field(default=False, description="Convertir HDR a SDR")

    # Filtros personalizados
    custom_filters: list[str] | None = Field(
        default=None, description="Filtros FFmpeg personalizados adicionales"
    )

    @field_validator("rotate")
    @classmethod
    def validate_rotation(cls, v: int | None) -> int | None:
        """Validar rotación"""
        if v is not None and v not in [0, 90, 180, 270]:
            raise ValueError("rotate debe ser 0, 90, 180 o 270")
        return v


class QualityPreset(str, Enum):
    """Presets de calidad"""

    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    SLOWER = "slower"
    VERYSLOW = "veryslow"


class VideoEncodingConfig(BaseModel):
    """Configuración de encoding de video"""

    codec: VideoCodec = Field(default=VideoCodec.H264, description="Codec de video")

    preset: QualityPreset = Field(
        default=QualityPreset.MEDIUM, description="Preset de velocidad/calidad"
    )

    crf: int | None = Field(
        default=23, description="Constant Rate Factor (calidad, menor = mejor)", ge=0, le=51
    )

    bitrate: str | None = Field(default=None, description="Bitrate objetivo (ej: '5M', '1000k')")

    max_bitrate: str | None = Field(default=None, description="Bitrate máximo")

    buffer_size: str | None = Field(default=None, description="Tamaño del buffer")

    gop_size: int | None = Field(
        default=None, description="Tamaño del GOP (Group of Pictures)", gt=0
    )

    profile: str | None = Field(default=None, description="Perfil del codec (ej: 'high', 'main')")

    level: str | None = Field(default=None, description="Nivel del codec (ej: '4.0', '5.1')")


class FFmpegProcessingConfig(BaseModel):
    """Configuración completa de procesamiento FFmpeg"""

    # Extracción de frames
    frame_extraction: FrameExtractionConfig = Field(
        default_factory=FrameExtractionConfig, description="Configuración de extracción de frames"
    )

    # Filtros de video
    video_filters: VideoFilterConfig = Field(
        default_factory=VideoFilterConfig, description="Configuración de filtros de video"
    )

    # Encoding (opcional, para generar clips)
    encoding: VideoEncodingConfig | None = Field(
        default=None, description="Configuración de encoding (si se generan videos de salida)"
    )

    # Configuración general de FFmpeg
    log_level: LogLevel = Field(default=LogLevel.ERROR, description="Nivel de logging de FFmpeg")

    threads: int | None = Field(
        default=None, description="Número de threads (None = auto)", gt=0, le=32
    )

    hardware_accel: str | None = Field(
        default=None,
        description="Hardware acceleration: 'auto' (detect), 'cuda', 'qsv', 'vaapi', 'videotoolbox', or None (CPU only)",
    )

    # Opciones avanzadas
    custom_input_args: dict[str, Any] | None = Field(
        default=None, description="Argumentos personalizados de entrada"
    )

    custom_output_args: dict[str, Any] | None = Field(
        default=None, description="Argumentos personalizados de salida"
    )

    # Metadatos
    metadata: dict[str, str] | None = Field(
        default=None, description="Metadatos a incluir en el output"
    )

    model_config = {"use_enum_values": True}


class ProcessingPreset(str, Enum):
    """Presets predefinidos de procesamiento"""

    FAST_PREVIEW = "fast_preview"  # Extracción rápida, baja calidad
    BALANCED = "balanced"  # Balance velocidad/calidad
    HIGH_QUALITY = "high_quality"  # Máxima calidad
    KEYFRAMES_ONLY = "keyframes_only"  # Solo keyframes
    SCENE_ANALYSIS = "scene_analysis"  # Análisis de escenas
    TIMELINE_PREVIEW = "timeline_preview"  # Preview de timeline
    # Nuevos presets
    DEEP_ANALYSIS = "deep_analysis"  # Videos largos, máxima cobertura
    ULTRA_DEEP = "ultra_deep"  # Videos muy largos (4+ horas), máxima extracción
    INTERVIEW_MODE = "interview_mode"  # Prioriza audio, menos frames visuales
    ACTION_MODE = "action_mode"  # Más frames en escenas con movimiento
    ADAPTIVE = "adaptive"  # Ajuste automático según duración


def get_adaptive_config(duration_seconds: float) -> FrameExtractionConfig:
    """
    Calcula configuración óptima de extracción según la duración del video.

    Args:
        duration_seconds: Duración del video en segundos

    Returns:
        FrameExtractionConfig optimizada para la duración
    """
    duration_minutes = duration_seconds / 60

    if duration_minutes < 5:
        # Videos muy cortos: alta densidad
        return FrameExtractionConfig(
            method=FrameExtractionMethod.INTERVAL,
            interval_seconds=2.0,
            max_frames=150,
        )
    elif duration_minutes < 30:
        # Videos cortos-medianos
        return FrameExtractionConfig(
            method=FrameExtractionMethod.INTERVAL,
            interval_seconds=3.0,
            max_frames=400,
        )
    elif duration_minutes < 60:
        # Videos de ~1 hora
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=4.0,
            scene_threshold=0.35,
            hybrid_scene_ratio=0.6,
            hybrid_min_gap_seconds=15.0,
            max_frames=600,
        )
    elif duration_minutes < 120:
        # Videos de 1-2 horas
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=5.0,
            scene_threshold=0.3,
            hybrid_scene_ratio=0.5,
            hybrid_min_gap_seconds=20.0,
            max_frames=800,
        )
    elif duration_minutes < 240:
        # Videos de 2-4 horas
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=6.0,
            scene_threshold=0.25,
            hybrid_scene_ratio=0.4,
            hybrid_min_gap_seconds=30.0,
            max_frames=1200,
        )
    elif duration_minutes < 480:
        # Videos de 4-8 horas
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=8.0,
            scene_threshold=0.2,
            hybrid_scene_ratio=0.5,
            hybrid_min_gap_seconds=45.0,
            max_frames=1500,
        )
    else:
        # Videos muy largos (>8 horas)
        return FrameExtractionConfig(
            method=FrameExtractionMethod.HYBRID,
            interval_seconds=10.0,
            scene_threshold=0.15,
            hybrid_scene_ratio=0.5,
            hybrid_min_gap_seconds=60.0,
            max_frames=2000,
        )


def get_preset_config(preset: ProcessingPreset) -> FFmpegProcessingConfig:
    """
    Obtener configuración predefinida según preset

    Args:
        preset: Preset a usar

    Returns:
        Configuración de FFmpeg
    """
    if preset == ProcessingPreset.FAST_PREVIEW:
        # Increased from 20 to 50 frames for better coverage
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.INTERVAL, interval_seconds=10.0, max_frames=50
            ),
            video_filters=VideoFilterConfig(
                scale_width=640, scale_height=360, pixel_format=PixelFormat.YUV420P
            ),
        )

    elif preset == ProcessingPreset.BALANCED:
        # Increased from 100 to 200 frames, with adaptive interval
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.INTERVAL, interval_seconds=5.0, max_frames=200
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280, scale_height=720, scaling_filter=ScalingFilter.LANCZOS
            ),
        )

    elif preset == ProcessingPreset.HIGH_QUALITY:
        # Increased from 500 to 600 frames for comprehensive coverage
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.INTERVAL, interval_seconds=3.0, max_frames=600
            ),
            video_filters=VideoFilterConfig(
                scaling_filter=ScalingFilter.LANCZOS, pixel_format=PixelFormat.YUV420P
            ),
            threads=8,
        )

    elif preset == ProcessingPreset.KEYFRAMES_ONLY:
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.KEYFRAMES, max_frames=200
            )
        )

    elif preset == ProcessingPreset.SCENE_ANALYSIS:
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.SCENE_DETECT, scene_threshold=0.4, max_frames=150
            ),
            video_filters=VideoFilterConfig(scale_width=1280, scale_height=720),
        )

    elif preset == ProcessingPreset.TIMELINE_PREVIEW:
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.UNIFORM, num_frames=30
            ),
            video_filters=VideoFilterConfig(scale_width=320, scale_height=180),
        )

    elif preset == ProcessingPreset.DEEP_ANALYSIS:
        # Para videos largos - máxima cobertura con modo híbrido
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.HYBRID,
                scene_threshold=0.3,
                hybrid_scene_ratio=0.5,
                hybrid_min_gap_seconds=20.0,
                max_frames=1000,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280, scale_height=720, scaling_filter=ScalingFilter.LANCZOS
            ),
            threads=8,
        )

    elif preset == ProcessingPreset.ULTRA_DEEP:
        # Para videos muy largos (4+ horas) - máxima extracción
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.HYBRID,
                scene_threshold=0.2,
                hybrid_scene_ratio=0.5,
                hybrid_min_gap_seconds=30.0,
                max_frames=2000,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280, scale_height=720, scaling_filter=ScalingFilter.LANCZOS
            ),
            threads=8,
        )

    elif preset == ProcessingPreset.INTERVIEW_MODE:
        # Prioriza audio - menos frames visuales, intervalos largos
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.INTERVAL,
                interval_seconds=10.0,
                max_frames=200,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280, scale_height=720,
            ),
        )

    elif preset == ProcessingPreset.ACTION_MODE:
        # Más frames, detección de escenas agresiva para capturar movimiento
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.HYBRID,
                scene_threshold=0.2,  # Más sensible a cambios
                hybrid_scene_ratio=0.7,  # Más peso a detección de escenas
                hybrid_min_gap_seconds=5.0,  # Menos tolerancia a gaps
                max_frames=800,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1920, scale_height=1080, scaling_filter=ScalingFilter.LANCZOS
            ),
            threads=8,
        )

    elif preset == ProcessingPreset.ADAPTIVE:
        # Placeholder - se configura dinámicamente según duración
        # Usar get_adaptive_config(duration) para obtener la config real
        return FFmpegProcessingConfig(
            frame_extraction=FrameExtractionConfig(
                method=FrameExtractionMethod.ADAPTIVE,
                max_frames=500,
            ),
            video_filters=VideoFilterConfig(
                scale_width=1280, scale_height=720, scaling_filter=ScalingFilter.LANCZOS
            ),
        )

    else:
        return FFmpegProcessingConfig()


class ProcessingStatus(BaseModel):
    """Estado del procesamiento"""

    status: str = Field(description="Estado actual (pending, processing, completed, failed)")
    progress: float = Field(default=0.0, description="Progreso 0-100", ge=0, le=100)
    current_frame: int = Field(default=0, description="Frame actual procesado")
    total_frames: int = Field(default=0, description="Total de frames a procesar")
    fps: float | None = Field(default=None, description="FPS de procesamiento")
    eta_seconds: float | None = Field(
        default=None, description="Tiempo estimado restante en segundos"
    )
    error: str | None = Field(default=None, description="Mensaje de error si status=failed")

    # Información del video fuente
    video_duration: float | None = Field(default=None, description="Duración del video en segundos")
    video_fps: float | None = Field(default=None, description="FPS del video fuente")
    video_width: int | None = Field(default=None, description="Ancho del video")
    video_height: int | None = Field(default=None, description="Alto del video")

    # Resultados
    frames_extracted: int = Field(default=0, description="Frames extraídos exitosamente")
    frames_analyzed: int = Field(default=0, description="Frames analizados con GPT-Vision")
    storage_used_mb: float | None = Field(default=None, description="Almacenamiento usado en MB")


class ProcessingPipeline(BaseModel):
    """Representación del pipeline de procesamiento para el grafo"""

    nodes: list[dict[str, Any]] = Field(
        default_factory=list, description="Nodos del grafo (pasos del pipeline)"
    )
    edges: list[dict[str, Any]] = Field(default_factory=list, description="Conexiones entre nodos")
    config: FFmpegProcessingConfig = Field(description="Configuración aplicada")
