"""
FFmpeg Video Processor
Sistema de procesamiento de video ultra-rápido con FFmpeg.
Inspirado en Edconv para máxima customización y performance.
"""

import base64
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

        return timestamps[: extraction.max_frames]

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
        print("🎬 extract_frames_ffmpeg iniciado")
        print(f"   Video path: {video_path}")
        print(f"   Video existe: {os.path.exists(video_path)}")

        video_info = self.get_video_info(video_path)

        print("📊 Video Info:")
        print(f"   Duración: {video_info.get('duration', 'N/A')}s")
        print(f"   FPS: {video_info.get('fps', 'N/A')}")
        print(f"   Resolución: {video_info.get('width', 'N/A')}x{video_info.get('height', 'N/A')}")

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

        print(f"📁 Output directory: {output_dir}")

        start_time = time.time()
        frames = []

        try:
            extraction = self.config.frame_extraction

            print("⚙️  Extraction config:")
            print(f"   Method: {extraction.method}")
            print(f"   Max frames: {extraction.max_frames}")
            if extraction.method == FrameExtractionMethod.FPS:
                print(f"   FPS: {extraction.fps}")

            # Construir filtros
            filters = self._build_filter_chain(video_info)

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
                # Métodos basados en timestamps (FPS, INTERVAL, UNIFORM)
                timestamps = self._calculate_frame_timestamps(video_info)
                self.status.total_frames = len(timestamps)

                print(f"📐 Calculated timestamps: {len(timestamps)} frames")
                if timestamps:
                    print(f"   First timestamp: {timestamps[0]}")
                    print(f"   Last timestamp: {timestamps[-1]}")

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
    ):
        """Extraer frames en timestamps específicos usando ffmpeg directamente"""

        print(f"🎬 Extrayendo {len(timestamps)} frames en timestamps específicos")
        print(f"   Video: {video_path}")
        print(f"   Output dir: {output_dir}")
        print(
            f"   Timestamps: {timestamps[:5]}..."
            if len(timestamps) > 5
            else f"   Timestamps: {timestamps}"
        )

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
                    print(f"   Comando FFmpeg: {' '.join(cmd)}")

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
                        print(f"   ✓ {idx + 1}/{len(timestamps)} frames extraídos")
                else:
                    print(f"⚠ Warning: Frame no creado o vacío en t={timestamp}")
                    print(f"   Return code: {result.returncode}")
                    if result.stderr:
                        print(f"   FFmpeg stderr: {result.stderr[:500]}")

            except subprocess.TimeoutExpired:
                print(f"Timeout extrayendo frame en t={timestamp}")
                continue
            except Exception as e:
                print(f"Error inesperado en t={timestamp}: {type(e).__name__}: {e}")
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
