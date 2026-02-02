"""
FFmpeg Video Processor
Sistema de procesamiento de video ultra-rápido con FFmpeg.
Inspirado en Edconv para máxima customización y performance.
"""

import base64
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import ffmpeg

from models.ffmpeg_config import (
    FFmpegProcessingConfig,
    FrameExtractionMethod,
    ProcessingPipeline,
    ProcessingStatus,
)

logger = logging.getLogger(__name__)


class FFmpegVideoProcessor:
    """Procesador de video con FFmpeg para extracción ultra-rápida de frames"""

    def __init__(self, config: FFmpegProcessingConfig | None = None):
        """
        Inicializar procesador

        Args:
            config: Configuración de procesamiento (None = usar defaults)
        """
        self.config = config or FFmpegProcessingConfig()
        self.status = ProcessingStatus(status="pending")

    def get_video_info(self, video_path: str) -> dict[str, Any]:
        """
        Obtener información del video usando ffprobe

        Args:
            video_path: Ruta al archivo de video

        Returns:
            Diccionario con información del video
        """
        try:
            probe = ffmpeg.probe(video_path)

            # Encontrar stream de video
            video_stream = next((s for s in probe["streams"] if s["codec_type"] == "video"), None)

            if not video_stream:
                raise ValueError("No se encontró stream de video")

            # Extraer información relevante
            format_info = probe.get("format", {})

            info = {
                "duration": float(format_info.get("duration", 0)),
                "size_bytes": int(format_info.get("size", 0)),
                "bit_rate": int(format_info.get("bit_rate", 0)),
                "format_name": format_info.get("format_name", ""),
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "codec_name": video_stream.get("codec_name", ""),
                "codec_long_name": video_stream.get("codec_long_name", ""),
                "pix_fmt": video_stream.get("pix_fmt", ""),
                "level": video_stream.get("level"),
                "profile": video_stream.get("profile", ""),
            }

            # Calcular FPS
            r_frame_rate = video_stream.get("r_frame_rate", "0/1")
            if "/" in r_frame_rate:
                num, den = map(int, r_frame_rate.split("/"))
                info["fps"] = num / den if den != 0 else 0
            else:
                info["fps"] = float(r_frame_rate)

            # Calcular frame count estimado
            if info["fps"] > 0 and info["duration"] > 0:
                info["frame_count"] = int(info["fps"] * info["duration"])
            else:
                info["frame_count"] = int(video_stream.get("nb_frames", 0))

            # Aspect ratio
            if "display_aspect_ratio" in video_stream:
                info["aspect_ratio"] = video_stream["display_aspect_ratio"]
            elif info["width"] > 0 and info["height"] > 0:
                from math import gcd

                g = gcd(info["width"], info["height"])
                info["aspect_ratio"] = f"{info['width']//g}:{info['height']//g}"

            return info

        except Exception as e:
            raise RuntimeError(f"Error obteniendo información del video: {str(e)}")

    def _build_filter_chain(self, video_info: dict[str, Any]) -> list[str]:
        """
        Construir cadena de filtros FFmpeg

        Args:
            video_info: Información del video

        Returns:
            Lista de filtros a aplicar
        """
        filters = []
        vf = self.config.video_filters

        # Crop
        if all(
            [
                vf.crop_x is not None,
                vf.crop_y is not None,
                vf.crop_width is not None,
                vf.crop_height is not None,
            ]
        ):
            filters.append(f"crop={vf.crop_width}:{vf.crop_height}:{vf.crop_x}:{vf.crop_y}")

        # Deinterlace
        if vf.deinterlace:
            filters.append("yadif")

        # HDR to SDR
        if vf.hdr_to_sdr:
            filters.append(
                "zscale=t=linear:npl=100,format=gbrpf32le,"
                "tonemap=hable:desat=0,"
                "zscale=t=bt709:m=bt709:p=bt709:r=tv"
            )

        # Scale
        if vf.scale_width or vf.scale_height:
            w = vf.scale_width or -1
            h = vf.scale_height or -1
            scale_filter = f"scale={w}:{h}"

            # Agregar algoritmo de escalado
            if vf.scaling_filter:
                scale_filter += f":flags={vf.scaling_filter.value}"

            filters.append(scale_filter)

        # Pixel format
        if vf.pixel_format:
            filters.append(f"format={vf.pixel_format.value}")

        # Color adjustments
        eq_params = []
        if vf.brightness is not None:
            eq_params.append(f"brightness={vf.brightness}")
        if vf.contrast is not None:
            eq_params.append(f"contrast={vf.contrast}")
        if vf.saturation is not None:
            eq_params.append(f"saturation={vf.saturation}")

        if eq_params:
            filters.append(f"eq={':'.join(eq_params)}")

        # Rotation
        if vf.rotate:
            if vf.rotate == 90:
                filters.append("transpose=1")
            elif vf.rotate == 180:
                filters.append("transpose=1,transpose=1")
            elif vf.rotate == 270:
                filters.append("transpose=2")

        # Custom filters
        if vf.custom_filters:
            filters.extend(vf.custom_filters)

        return filters

    def _calculate_frame_timestamps(self, video_info: dict[str, Any]) -> list[float]:
        """
        Calcular timestamps de los frames a extraer

        Args:
            video_info: Información del video

        Returns:
            Lista de timestamps en segundos
        """
        extraction = self.config.frame_extraction
        duration = video_info["duration"]

        # Aplicar start/end time
        start = extraction.start_time or 0
        end = min(extraction.end_time or duration, duration)  # No exceder duración real
        effective_duration = end - start

        # Validar que hay duración válida
        if effective_duration <= 0:
            return []

        timestamps = []

        if extraction.method == FrameExtractionMethod.FPS:
            # Extraer a FPS específico
            interval = 1.0 / extraction.fps
            t = start
            while t < end and len(timestamps) < extraction.max_frames:
                timestamps.append(t)
                t += interval

            # Asegurar que no excedemos la duración
            timestamps = [t for t in timestamps if t < duration]

        elif extraction.method == FrameExtractionMethod.INTERVAL:
            # Extraer cada N segundos
            t = start
            while t < end and len(timestamps) < extraction.max_frames:
                timestamps.append(t)
                t += extraction.interval_seconds

            # Asegurar que no excedemos la duración
            timestamps = [t for t in timestamps if t < duration]

        elif extraction.method == FrameExtractionMethod.UNIFORM:
            # Distribuir uniformemente
            num = min(extraction.num_frames, extraction.max_frames)
            if num > 1:
                step = effective_duration / (num - 1)
                timestamps = [start + i * step for i in range(num)]
            else:
                timestamps = [start + effective_duration / 2]

            # Asegurar que no excedemos la duración (ajustar último frame si es necesario)
            timestamps = [min(t, duration - 0.1) for t in timestamps]

        elif extraction.method == FrameExtractionMethod.KEYFRAMES:
            # Esto requiere análisis previo - se maneja diferente
            return []  # Se procesará con select filter

        elif extraction.method == FrameExtractionMethod.SCENE_DETECT:
            # También requiere análisis previo
            return []  # Se procesará con scene detection

        elif extraction.method == FrameExtractionMethod.ADAPTIVE:
            # Calcular configuración óptima según duración
            from models.ffmpeg_config import get_adaptive_config

            adaptive_config = get_adaptive_config(duration)
            # Usar el método calculado (puede ser INTERVAL o HYBRID)
            if adaptive_config.method == FrameExtractionMethod.HYBRID:
                # Delegar a HYBRID
                return self._calculate_hybrid_timestamps(
                    video_info,
                    adaptive_config.scene_threshold or 0.3,
                    adaptive_config.hybrid_scene_ratio or 0.5,
                    adaptive_config.hybrid_min_gap_seconds or 15.0,
                    adaptive_config.max_frames or 500,
                )
            else:
                # Usar INTERVAL con parámetros adaptativos
                t = start
                interval = adaptive_config.interval_seconds or 5.0
                max_frames = adaptive_config.max_frames or 500
                while t < end and len(timestamps) < max_frames:
                    timestamps.append(t)
                    t += interval

        elif extraction.method == FrameExtractionMethod.HYBRID:
            # Modo híbrido: scene detection + uniform fill
            return self._calculate_hybrid_timestamps(
                video_info,
                extraction.scene_threshold or 0.3,
                extraction.hybrid_scene_ratio or 0.5,
                extraction.hybrid_min_gap_seconds or 15.0,
                extraction.max_frames or 500,
            )

        return timestamps[: extraction.max_frames]

    def _calculate_hybrid_timestamps(
        self,
        video_info: dict[str, Any],
        scene_threshold: float,
        scene_ratio: float,
        min_gap_seconds: float,
        max_frames: int,
    ) -> list[float]:
        """
        Calcular timestamps usando método híbrido: scene detection + uniform fill.

        1. Detecta cambios de escena (captura transiciones importantes)
        2. Rellena gaps largos con frames uniformes (no perder contenido estático)

        Args:
            video_info: Información del video
            scene_threshold: Umbral de detección de escena (0-1)
            scene_ratio: Ratio de frames de escenas vs fill (0.6 = 60% escenas)
            min_gap_seconds: Gap mínimo antes de insertar fill frames
            max_frames: Máximo de frames a extraer

        Returns:
            Lista de timestamps ordenados
        """
        duration = video_info["duration"]
        extraction = self.config.frame_extraction
        start = extraction.start_time or 0
        end = min(extraction.end_time or duration, duration)

        # Paso 1: Detectar escenas
        scene_frames_target = int(max_frames * scene_ratio)
        scene_timestamps = self._detect_scene_timestamps(
            video_info.get("path", ""),
            scene_threshold,
            scene_frames_target
        )

        # Si no hay detección de escenas, fallback a uniform
        if not scene_timestamps:
            # Uniform distribution como fallback
            num_frames = max_frames
            step = (end - start) / max(num_frames - 1, 1)
            return [start + i * step for i in range(num_frames)]

        # Paso 2: Identificar gaps y rellenar
        fill_frames_target = max_frames - len(scene_timestamps)
        all_timestamps = sorted(scene_timestamps)

        if fill_frames_target > 0 and len(all_timestamps) > 1:
            gaps = []
            for i in range(len(all_timestamps) - 1):
                gap_start = all_timestamps[i]
                gap_end = all_timestamps[i + 1]
                gap_duration = gap_end - gap_start
                if gap_duration > min_gap_seconds:
                    gaps.append((gap_start, gap_end, gap_duration))

            # Distribuir fill frames proporcionalmente a los gaps
            total_gap_duration = sum(g[2] for g in gaps)
            if total_gap_duration > 0:
                for gap_start, _gap_end, gap_duration in gaps:
                    # Frames a insertar en este gap
                    gap_frames = int((gap_duration / total_gap_duration) * fill_frames_target)
                    if gap_frames > 0:
                        step = gap_duration / (gap_frames + 1)
                        for j in range(1, gap_frames + 1):
                            fill_ts = gap_start + j * step
                            if fill_ts not in all_timestamps:
                                all_timestamps.append(fill_ts)

        # Añadir inicio y fin si no están
        if start not in all_timestamps and start >= 0:
            all_timestamps.append(start)
        if end - 0.5 not in all_timestamps and end <= duration:
            all_timestamps.append(min(end - 0.1, duration - 0.1))

        # Ordenar y limitar
        all_timestamps = sorted(set(all_timestamps))
        return all_timestamps[:max_frames]

    def _detect_scene_timestamps(
        self,
        video_path: str,
        threshold: float,
        max_scenes: int
    ) -> list[float]:
        """
        Detectar timestamps de cambios de escena usando FFmpeg.

        Args:
            video_path: Ruta al video
            threshold: Umbral de detección (0-1)
            max_scenes: Máximo de escenas a detectar

        Returns:
            Lista de timestamps donde hay cambios de escena
        """
        if not video_path or not os.path.exists(video_path):
            return []

        try:
            # Usar FFmpeg para detectar escenas
            cmd = [
                "ffmpeg", "-i", video_path,
                "-vf", f"select='gt(scene,{threshold})',showinfo",
                "-f", "null", "-"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minutos máximo
            )

            # Parsear output para extraer timestamps
            timestamps = []
            for line in result.stderr.split("\n"):
                if "pts_time:" in line:
                    try:
                        # Extraer pts_time del output de showinfo
                        pts_part = line.split("pts_time:")[1].split()[0]
                        ts = float(pts_part)
                        timestamps.append(ts)
                        if len(timestamps) >= max_scenes:
                            break
                    except (IndexError, ValueError):
                        continue

            return timestamps

        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg scene detection timed out")
            return []
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"Error during FFmpeg scene detection: {e}")
            return []

    def extract_frames_ffmpeg(
        self, video_path: str, output_dir: str | None = None, return_as_bytes: bool = True
    ) -> list[dict[str, Any]]:
        """
        Extraer frames usando FFmpeg (método ultra-rápido)

        Args:
            video_path: Ruta al video
            output_dir: Directorio de salida (None = usar temp)
            return_as_bytes: Si True, retorna frames como bytes en memoria

        Returns:
            Lista de diccionarios con información de cada frame:
            {
                'timestamp': float,
                'frame_number': int,
                'image_data': bytes (si return_as_bytes=True),
                'file_path': str (si return_as_bytes=False)
            }
        """
        logger.info(f"extract_frames_ffmpeg iniciado para: {video_path}")
        logger.debug(f"Video existe: {os.path.exists(video_path)}")

        video_info = self.get_video_info(video_path)

        logger.info(
            f"Video Info: duración={video_info.get('duration', 'N/A')}s, "
            f"fps={video_info.get('fps', 'N/A')}, "
            f"resolución={video_info.get('width', 'N/A')}x{video_info.get('height', 'N/A')}"
        )

        # Actualizar status
        self.status.video_duration = video_info["duration"]
        self.status.video_fps = video_info["fps"]
        self.status.video_width = video_info["width"]
        self.status.video_height = video_info["height"]
        self.status.status = "processing"

        # Crear directorio temporal si es necesario
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="qprisma_frames_")
        else:
            os.makedirs(output_dir, exist_ok=True)

        logger.debug(f"Output directory: {output_dir}")

        start_time = time.time()
        frames: list[dict[str, Any]] = []

        try:
            extraction = self.config.frame_extraction

            logger.info(
                f"Extraction config: method={extraction.method}, max_frames={extraction.max_frames}"
            )
            if extraction.method == FrameExtractionMethod.FPS:
                logger.debug(f"FPS: {extraction.fps}")

            # Construir filtros
            filters = self._build_filter_chain(video_info)

            # Añadir path a video_info para métodos que lo necesitan
            video_info["path"] = video_path

            # Método específico de extracción
            if extraction.method == FrameExtractionMethod.KEYFRAMES:
                # Extraer solo keyframes
                filters.append("select='eq(pict_type\\,I)'")
                self._extract_with_select_filter(
                    video_path, output_dir, filters, video_info, frames
                )

            elif extraction.method == FrameExtractionMethod.SCENE_DETECT:
                # Detección de cambio de escena
                scene_filter = f"select='gt(scene\\,{extraction.scene_threshold})'"
                filters.append(scene_filter)
                self._extract_with_select_filter(
                    video_path, output_dir, filters, video_info, frames
                )

            else:
                # Métodos basados en timestamps (FPS, INTERVAL, UNIFORM, ADAPTIVE, HYBRID)
                timestamps = self._calculate_frame_timestamps(video_info)
                self.status.total_frames = len(timestamps)

                logger.info(f"Calculated timestamps: {len(timestamps)} frames")
                if timestamps:
                    logger.debug(f"First timestamp: {timestamps[0]:.2f}s, Last: {timestamps[-1]:.2f}s")

                    # Calcular y mostrar métricas de cobertura
                    coverage = self.calculate_coverage_metrics(timestamps, video_info["duration"])
                    logger.info(
                        f"Coverage score: {coverage['coverage_score']}%, "
                        f"avg_gap={coverage['average_gap']:.1f}s, max_gap={coverage['max_gap']:.1f}s"
                    )
                    if coverage['total_problematic_gaps'] > 0:
                        logger.warning(
                            f"{coverage['total_problematic_gaps']} gaps over {coverage['gap_threshold']}s"
                        )

                self._extract_at_timestamps(video_path, output_dir, timestamps, filters, frames)

            # Cargar imágenes como bytes si se requiere
            if return_as_bytes:
                for frame in frames:
                    if "file_path" in frame:
                        with open(frame["file_path"], "rb") as f:
                            frame["image_data"] = f.read()
                        # Opcionalmente eliminar archivo temporal
                        if output_dir.startswith(tempfile.gettempdir()):
                            os.remove(frame["file_path"])

            # Actualizar status
            elapsed = time.time() - start_time
            self.status.status = "completed"
            self.status.progress = 100.0
            self.status.frames_extracted = len(frames)
            self.status.fps = len(frames) / elapsed if elapsed > 0 else 0

            return frames

        except Exception as e:
            self.status.status = "failed"
            self.status.error = str(e)
            raise RuntimeError(f"Error extrayendo frames: {str(e)}")

    def _extract_with_select_filter(
        self,
        video_path: str,
        output_dir: str,
        filters: list[str],
        video_info: dict[str, Any],
        frames: list[dict[str, Any]],
    ):
        """Extraer frames usando select filter (keyframes/scenes)"""

        # El último filtro debe ser el select
        filter_str = ",".join(filters)

        # Construir comando FFmpeg
        output_pattern = os.path.join(output_dir, "frame_%06d.jpg")

        stream = ffmpeg.input(video_path)
        stream = ffmpeg.filter(stream, "fps", fps=1)  # Placeholder, select override

        if filter_str:
            for f in filters:
                parts = f.split("=", 1)
                if len(parts) == 2:
                    filter_name, filter_args = parts
                    stream = ffmpeg.filter(stream, filter_name, filter_args)

        stream = ffmpeg.output(
            stream,
            output_pattern,
            vsync="vfr",  # Variable frame rate
            q=2,  # Calidad JPEG
            loglevel=self.config.log_level.value,
        )

        # Ejecutar
        ffmpeg.run(stream, overwrite_output=True)

        # Recopilar frames generados
        frame_files = sorted(Path(output_dir).glob("frame_*.jpg"))

        for idx, frame_file in enumerate(frame_files[: self.config.frame_extraction.max_frames]):
            frames.append(
                {
                    "frame_number": idx,
                    "timestamp": None,  # No conocemos timestamp exacto con select
                    "file_path": str(frame_file),
                }
            )

            self.status.current_frame = idx + 1
            self.status.progress = min(
                (idx + 1) / min(len(frame_files), self.config.frame_extraction.max_frames) * 100,
                100.0,
            )

    def _extract_at_timestamps(
        self,
        video_path: str,
        output_dir: str,
        timestamps: list[float],
        filters: list[str],
        frames: list[dict[str, Any]],
    ) -> None:
        """
        Extraer frames en timestamps específicos usando ffmpeg directamente.
        
        Args:
            video_path: Ruta al archivo de video.
            output_dir: Directorio de salida para frames.
            timestamps: Lista de timestamps a extraer.
            filters: Filtros FFmpeg a aplicar.
            frames: Lista donde agregar los frames extraídos.
        """
        logger.info(f"Extrayendo {len(timestamps)} frames en timestamps específicos")
        logger.debug(f"Video: {video_path}, Output dir: {output_dir}")
        if len(timestamps) > 5:
            logger.debug(f"Timestamps: {timestamps[:5]}...")
        else:
            logger.debug(f"Timestamps: {timestamps}")

        for idx, timestamp in enumerate(timestamps):
            try:
                output_file = os.path.join(output_dir, f"frame_{idx:06d}.jpg")

                # Comando FFmpeg simple y confiable
                cmd = [
                    "ffmpeg",
                    "-ss",
                    str(timestamp),  # Seek to timestamp
                    "-i",
                    video_path,
                    "-vframes",
                    "1",  # Extract 1 frame
                    "-q:v",
                    "2",  # Quality (2 = high quality JPEG)
                    "-y",  # Overwrite
                    output_file,
                ]

                # Debug: mostrar comando solo para el primer frame
                if idx == 0:
                    logger.debug(f"Comando FFmpeg: {' '.join(cmd)}")

                # Ejecutar comando
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=os.path.dirname(video_path) or ".",
                )

                # Verificar que el archivo se creó
                if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    frames.append(
                        {"frame_number": idx, "timestamp": timestamp, "file_path": output_file}
                    )

                    # Actualizar progreso
                    self.status.current_frame = idx + 1
                    self.status.progress = (idx + 1) / len(timestamps) * 100

                    # Log cada 10 frames
                    if (idx + 1) % 10 == 0:
                        logger.debug(f"{idx + 1}/{len(timestamps)} frames extraídos")
                else:
                    logger.warning(f"Frame no creado o vacío en t={timestamp}, rc={result.returncode}")
                    if result.stderr:
                        logger.debug(f"FFmpeg stderr: {result.stderr[:500]}")

            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout extrayendo frame en t={timestamp}")
                continue
            except subprocess.SubprocessError as e:
                logger.error(f"Error de subprocess en t={timestamp}: {e}")
                continue
            except Exception as e:
                logger.exception(f"Error inesperado en t={timestamp}: {type(e).__name__}: {e}")
                continue

    def frame_to_base64(self, frame_data: bytes) -> str:
        """
        Convertir frame a base64

        Args:
            frame_data: Datos de la imagen en bytes

        Returns:
            String base64
        """
        return base64.b64encode(frame_data).decode("utf-8")

    def get_processing_pipeline(self) -> ProcessingPipeline:
        """
        Generar representación del pipeline de procesamiento para visualización

        Returns:
            ProcessingPipeline con nodos y edges para el grafo
        """
        nodes = []
        edges = []
        node_id = 0

        # Nodo 1: Input
        # Description del video (con valores por defecto si no se ha procesado aún)
        video_desc = "Video source"
        if self.status.video_width and self.status.video_height and self.status.video_fps:
            video_desc = f"{self.status.video_width}x{self.status.video_height} @ {self.status.video_fps:.2f}fps"

        nodes.append(
            {
                "id": f"node_{node_id}",
                "type": "input",
                "data": {"label": "Video Input", "icon": "📹", "description": video_desc},
                "position": {"x": 100, "y": 100},
            }
        )
        prev_node = node_id
        node_id += 1

        # Nodo 2: Frame Extraction
        extraction = self.config.frame_extraction
        nodes.append(
            {
                "id": f"node_{node_id}",
                "type": "process",
                "data": {
                    "label": "Frame Extraction",
                    "icon": "🎞️",
                    "description": f"Method: {extraction.method.value}",
                    "details": {
                        "method": extraction.method.value,
                        "max_frames": extraction.max_frames,
                        "fps": (
                            extraction.fps
                            if extraction.method == FrameExtractionMethod.FPS
                            else None
                        ),
                        "interval": (
                            extraction.interval_seconds
                            if extraction.method == FrameExtractionMethod.INTERVAL
                            else None
                        ),
                    },
                },
                "position": {"x": 100, "y": 200},
            }
        )
        edges.append(
            {
                "id": f"edge_{prev_node}_{node_id}",
                "source": f"node_{prev_node}",
                "target": f"node_{node_id}",
            }
        )
        prev_node = node_id
        node_id += 1

        # Nodo 3: Video Filters (si hay alguno configurado)
        vf = self.config.video_filters
        has_filters = any(
            [
                vf.scale_width,
                vf.scale_height,
                vf.pixel_format,
                vf.crop_width,
                vf.brightness is not None,
                vf.contrast is not None,
                vf.saturation is not None,
                vf.rotate,
                vf.deinterlace,
                vf.hdr_to_sdr,
            ]
        )

        if has_filters:
            filter_details = []
            if vf.scale_width or vf.scale_height:
                filter_details.append(
                    f'Scale: {vf.scale_width or "auto"}x{vf.scale_height or "auto"}'
                )
            if vf.pixel_format:
                filter_details.append(f"Format: {vf.pixel_format.value}")
            if vf.deinterlace:
                filter_details.append("Deinterlace")
            if vf.hdr_to_sdr:
                filter_details.append("HDR→SDR")

            nodes.append(
                {
                    "id": f"node_{node_id}",
                    "type": "process",
                    "data": {
                        "label": "Video Filters",
                        "icon": "🎨",
                        "description": ", ".join(filter_details[:2]),
                        "details": {"filters": filter_details},
                    },
                    "position": {"x": 100, "y": 300},
                }
            )
            edges.append(
                {
                    "id": f"edge_{prev_node}_{node_id}",
                    "source": f"node_{prev_node}",
                    "target": f"node_{node_id}",
                }
            )
            prev_node = node_id
            node_id += 1

        # Nodo 4: GPT-Vision Analysis
        nodes.append(
            {
                "id": f"node_{node_id}",
                "type": "process",
                "data": {
                    "label": "GPT-Vision Analysis",
                    "icon": "🤖",
                    "description": "Frame content analysis",
                    "details": {"model": "gpt-5-mini", "task": "Visual scene understanding"},
                },
                "position": {"x": 100, "y": 400 if has_filters else 300},
            }
        )
        edges.append(
            {
                "id": f"edge_{prev_node}_{node_id}",
                "source": f"node_{prev_node}",
                "target": f"node_{node_id}",
            }
        )
        prev_node = node_id
        node_id += 1

        # Nodo 5: Embedding Generation
        nodes.append(
            {
                "id": f"node_{node_id}",
                "type": "process",
                "data": {
                    "label": "Embedding Generation",
                    "icon": "🧮",
                    "description": "text-embedding-3-large",
                    "details": {"model": "text-embedding-3-large", "dimensions": 3072},
                },
                "position": {"x": 300, "y": 400 if has_filters else 300},
            }
        )
        edges.append(
            {
                "id": f"edge_{prev_node}_{node_id}",
                "source": f"node_{prev_node}",
                "target": f"node_{node_id}",
            }
        )

        # Nodo 6: Knowledge Graph Indexing
        nodes.append(
            {
                "id": f"node_{node_id + 1}",
                "type": "output",
                "data": {
                    "label": "Index to Knowledge Graph",
                    "icon": "🔍",
                    "description": "Neo4j persistence for retrieval",
                    "details": {"store": "neo4j"},
                },
                "position": {"x": 300, "y": 500 if has_filters else 400},
            }
        )
        edges.append(
            {
                "id": f"edge_{node_id}_{node_id + 1}",
                "source": f"node_{node_id}",
                "target": f"node_{node_id + 1}",
            }
        )

        # Nodo 7: Cosmos DB Storage
        nodes.append(
            {
                "id": f"node_{node_id + 2}",
                "type": "output",
                "data": {
                    "label": "Store in Cosmos DB",
                    "icon": "💾",
                    "description": "Metadata persistence",
                    "details": {"database": "qprisma", "container": "media-metadata"},
                },
                "position": {"x": 500, "y": 500 if has_filters else 400},
            }
        )
        edges.append(
            {
                "id": f"edge_{node_id}_{node_id + 2}",
                "source": f"node_{node_id}",
                "target": f"node_{node_id + 2}",
            }
        )

        return ProcessingPipeline(nodes=nodes, edges=edges, config=self.config)

    def get_status(self) -> ProcessingStatus:
        """Obtener estado actual del procesamiento"""
        return self.status

    def calculate_coverage_metrics(
        self,
        timestamps: list[float],
        video_duration: float
    ) -> dict[str, Any]:
        """
        Calcular métricas de cobertura del video.

        Args:
            timestamps: Lista de timestamps extraídos
            video_duration: Duración total del video en segundos

        Returns:
            Dict con métricas de cobertura:
            - coverage_score: 0-100, qué tan bien cubierto está el video
            - average_gap: Gap promedio entre frames
            - max_gap: Gap máximo (indica posibles "puntos ciegos")
            - gaps_over_threshold: Lista de gaps problemáticos
            - density_per_minute: Frames por minuto promedio
            - recommendations: Sugerencias para mejorar cobertura
        """
        if not timestamps or video_duration <= 0:
            return {
                "coverage_score": 0,
                "average_gap": 0,
                "max_gap": video_duration,
                "gaps_over_threshold": [],
                "density_per_minute": 0,
                "recommendations": ["No frames extracted"],
            }

        sorted_ts = sorted(timestamps)

        # Calcular gaps
        gaps = []
        for i in range(len(sorted_ts) - 1):
            gap = sorted_ts[i + 1] - sorted_ts[i]
            gaps.append({
                "start": sorted_ts[i],
                "end": sorted_ts[i + 1],
                "duration": gap,
            })

        # Añadir gap inicial y final
        if sorted_ts[0] > 1.0:  # Si hay más de 1 segundo al inicio
            gaps.insert(0, {"start": 0, "end": sorted_ts[0], "duration": sorted_ts[0]})
        if video_duration - sorted_ts[-1] > 1.0:
            gaps.append({
                "start": sorted_ts[-1],
                "end": video_duration,
                "duration": video_duration - sorted_ts[-1]
            })

        # Métricas básicas
        gap_durations = [g["duration"] for g in gaps]
        avg_gap = sum(gap_durations) / len(gap_durations) if gap_durations else 0
        max_gap = max(gap_durations) if gap_durations else 0

        # Threshold dinámico basado en duración del video
        # Para videos cortos, gaps >10s son problemáticos
        # Para videos largos, gaps >30s son problemáticos
        if video_duration < 300:  # < 5 min
            gap_threshold = 10.0
        elif video_duration < 1800:  # < 30 min
            gap_threshold = 20.0
        elif video_duration < 3600:  # < 1 hora
            gap_threshold = 30.0
        else:  # > 1 hora
            gap_threshold = 45.0

        problematic_gaps = [g for g in gaps if g["duration"] > gap_threshold]

        # Coverage score (0-100)
        # Basado en: densidad de frames, gaps máximos, distribución
        density = len(timestamps) / (video_duration / 60)  # frames por minuto
        ideal_density = 10  # 10 frames/min es ideal para análisis
        density_score = min(density / ideal_density * 100, 100)

        # Penalización por gaps grandes
        gap_penalty = min(len(problematic_gaps) * 10, 50)
        max_gap_penalty = min((max_gap / gap_threshold - 1) * 20, 30) if max_gap > gap_threshold else 0

        coverage_score = max(0, density_score - gap_penalty - max_gap_penalty)

        # Recomendaciones
        recommendations = []
        if coverage_score < 50:
            recommendations.append("Consider using DEEP_ANALYSIS or ADAPTIVE preset for better coverage")
        if max_gap > gap_threshold * 2:
            recommendations.append(f"Large gap detected ({max_gap:.1f}s) - use HYBRID extraction to fill gaps")
        if density < 5:
            recommendations.append("Low frame density - increase max_frames or reduce interval")
        if len(problematic_gaps) > 5:
            recommendations.append(f"{len(problematic_gaps)} gaps over {gap_threshold}s - content may be missed")
        if not recommendations:
            recommendations.append("Good coverage achieved")

        return {
            "coverage_score": round(coverage_score, 1),
            "average_gap": round(avg_gap, 2),
            "max_gap": round(max_gap, 2),
            "gap_threshold": gap_threshold,
            "gaps_over_threshold": problematic_gaps[:10],  # Limitar a 10
            "total_problematic_gaps": len(problematic_gaps),
            "density_per_minute": round(density, 2),
            "total_frames": len(timestamps),
            "video_duration": video_duration,
            "recommendations": recommendations,
        }


def get_recommended_preset(video_duration: float, content_type: str = "general") -> str:
    """
    Recomendar preset óptimo según duración y tipo de contenido.

    Args:
        video_duration: Duración en segundos
        content_type: Tipo de contenido (general, interview, action, tutorial)

    Returns:
        Nombre del preset recomendado
    """
    duration_minutes = video_duration / 60

    # Por tipo de contenido
    if content_type == "interview":
        return "interview_mode"
    elif content_type == "action":
        return "action_mode"
    elif content_type == "tutorial":
        # Tutoriales necesitan buena cobertura visual
        if duration_minutes < 30:
            return "high_quality"
        else:
            return "deep_analysis"

    # Por duración (general)
    if duration_minutes < 5:
        return "balanced"
    elif duration_minutes < 30:
        return "high_quality"
    elif duration_minutes < 120:
        return "deep_analysis"
    else:
        return "adaptive"
