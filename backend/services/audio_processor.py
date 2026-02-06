"""
Audio Processing Service
Extrae audio de videos, transcribe con Whisper y genera análisis enriquecido.
Soporta chunking para archivos grandes (>25MB limit de Azure Whisper).
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Any

from openai import APIConnectionError, APIError, AsyncAzureOpenAI, AzureOpenAI, RateLimitError

logger = logging.getLogger(__name__)

# Azure Whisper tiene límite de 25MB
WHISPER_MAX_FILE_SIZE_MB = 25
# Chunk duration objetivo para audio (5 minutos da ~5-8MB en mp3 128kbps)
CHUNK_DURATION_SECONDS = 300  # 5 minutos
# VAD silence detection defaults
VAD_NOISE_THRESHOLD_DB = -30  # dB threshold for silence detection
VAD_MIN_SILENCE_DURATION = 0.5  # minimum silence gap in seconds


class AudioProcessor:
    """
    Procesa audio de videos: extracción, transcripción con Whisper, análisis.
    
    Attributes:
        openai_client: Cliente de Azure OpenAI para Whisper y GPT.
        whisper_deployment: Nombre del deployment de Whisper.
        gpt_deployment: Nombre del deployment de GPT.
        rate_limit_rpm: Límite de requests por minuto para Whisper.
    """

    def __init__(self, openai_client: AzureOpenAI | AsyncAzureOpenAI, rate_limit_rpm: int = 3):
        self.openai_client = openai_client
        self.whisper_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_WHISPER", "whisper")
        self.gpt_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")
        self.rate_limit_rpm = rate_limit_rpm
        self._last_request_time = 0.0

    async def _wait_for_rate_limit(self) -> None:
        """Espera si es necesario para respetar rate limit."""
        if self.rate_limit_rpm <= 0:
            return

        min_interval = 60.0 / self.rate_limit_rpm
        elapsed = time.time() - self._last_request_time

        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            logger.debug(f"Rate limit: esperando {wait_time:.1f}s")
            await asyncio.sleep(wait_time)

        self._last_request_time = time.time()

    def extract_audio_from_video(
        self,
        video_path: str,
        output_path: str | None = None,
        audio_format: str = "mp3",
        audio_bitrate: str = "128k",
    ) -> str:
        """
        Extrae audio de un video usando FFmpeg

        Args:
            video_path: Ruta al video
            output_path: Ruta de salida (si None, crea temporal)
            audio_format: Formato de audio (mp3, wav, m4a)
            audio_bitrate: Bitrate del audio

        Returns:
            Ruta al archivo de audio extraído
        """
        if output_path is None:
            output_path = tempfile.mktemp(suffix=f".{audio_format}")

        # Comando FFmpeg para extraer audio
        cmd = [
            "ffmpeg",
            "-i",
            video_path,
            "-vn",  # Sin video
            "-acodec",
            "libmp3lame" if audio_format == "mp3" else "copy",
            "-ab",
            audio_bitrate,
            "-ar",
            "16000",  # 16kHz es óptimo para Whisper
            "-ac",
            "1",  # Mono
            "-y",  # Sobrescribir
            output_path,
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info(f"Audio extraído: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error extrayendo audio: {e.stderr}")

    def get_audio_duration(self, audio_path: str) -> float:
        """
        Obtiene la duración del audio en segundos usando ffprobe.
        
        Args:
            audio_path: Ruta al archivo de audio.
            
        Returns:
            Duración en segundos, o 0.0 si hay error.
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except subprocess.CalledProcessError as e:
            logger.warning(f"Error obteniendo duración de audio: {e}")
            return 0.0
        except ValueError as e:
            logger.warning(f"Error parseando duración de audio: {e}")
            return 0.0

    def _detect_silence_boundaries(
        self,
        audio_path: str,
        noise_db: float = VAD_NOISE_THRESHOLD_DB,
        min_silence: float = VAD_MIN_SILENCE_DURATION,
    ) -> list[dict[str, float]]:
        """
        Detect silence gaps in audio using FFmpeg silencedetect filter.

        Returns list of silence intervals: [{"start": float, "end": float}, ...]
        """
        cmd = [
            "ffmpeg", "-i", audio_path,
            "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f", "null", "-",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            stderr = result.stderr

            starts = re.findall(r"silence_start: ([\d.]+)", stderr)
            ends = re.findall(r"silence_end: ([\d.]+)", stderr)

            silences = []
            for i in range(min(len(starts), len(ends))):
                silences.append({
                    "start": float(starts[i]),
                    "end": float(ends[i]),
                })
            return silences

        except Exception as e:
            logger.warning(f"Silence detection failed, falling back to fixed chunking: {e}")
            return []

    def _find_vad_split_points(
        self,
        total_duration: float,
        silences: list[dict[str, float]],
        target_chunk: float = CHUNK_DURATION_SECONDS,
        min_chunk: float = 60.0,
    ) -> list[float]:
        """
        Find optimal split points at silence boundaries near target chunk durations.

        Args:
            total_duration: Total audio duration in seconds.
            silences: Silence intervals from _detect_silence_boundaries.
            target_chunk: Target chunk duration (default 300s).
            min_chunk: Minimum chunk size to prevent tiny fragments.

        Returns:
            List of split timestamps (excluding 0 and total_duration).
        """
        if not silences or total_duration <= target_chunk:
            return []

        split_points = []
        current_start = 0.0

        while current_start + target_chunk < total_duration:
            target_time = current_start + target_chunk
            # Search window: 80%-120% of target chunk boundary
            window_start = current_start + target_chunk * 0.8
            window_end = min(current_start + target_chunk * 1.2, total_duration)

            # Find the silence gap closest to the target within the window
            best_split = None
            best_distance = float("inf")

            for silence in silences:
                midpoint = (silence["start"] + silence["end"]) / 2
                if window_start <= midpoint <= window_end:
                    distance = abs(midpoint - target_time)
                    if distance < best_distance:
                        best_distance = distance
                        best_split = midpoint

            if best_split and (best_split - current_start) >= min_chunk:
                split_points.append(best_split)
                current_start = best_split
            else:
                # No silence found in window — fall back to target time
                split_points.append(target_time)
                current_start = target_time

        return split_points

    def split_audio_into_chunks(
        self,
        audio_path: str,
        chunk_duration: float = CHUNK_DURATION_SECONDS,
        output_dir: str | None = None,
        use_vad: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Divide audio en chunks using VAD-based silence detection for natural boundaries.

        Falls back to fixed-duration chunking if VAD detection fails.

        Args:
            audio_path: Ruta al archivo de audio.
            chunk_duration: Duración máxima de cada chunk en segundos.
            output_dir: Directorio para chunks (temporal si None).
            use_vad: Whether to use Voice Activity Detection for smart boundaries.

        Returns:
            Lista de dicts con info de cada chunk: {path, start_time, end_time, index}.
        """
        total_duration = self.get_audio_duration(audio_path)
        if total_duration <= 0:
            return [{"path": audio_path, "start_time": 0, "end_time": 0, "index": 0}]

        # Verificar si necesita chunking
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        if file_size_mb <= WHISPER_MAX_FILE_SIZE_MB and total_duration <= chunk_duration:
            logger.info(f"Audio pequeño ({file_size_mb:.1f}MB), no requiere chunking")
            return [{"path": audio_path, "start_time": 0, "end_time": total_duration, "index": 0}]

        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="audio_chunks_")

        # Determine split points using VAD or fixed intervals
        if use_vad:
            silences = self._detect_silence_boundaries(audio_path)
            split_points = self._find_vad_split_points(
                total_duration, silences, target_chunk=chunk_duration
            )
            if split_points:
                logger.info(
                    f"VAD: found {len(split_points)} silence-based split points "
                    f"for {total_duration:.1f}s audio"
                )
            else:
                logger.info("VAD: no split points found, using fixed intervals")
        else:
            split_points = []

        # Build chunk boundaries from split points
        boundaries = [0.0] + split_points + [total_duration]
        # If no VAD splits, fall back to fixed-duration boundaries
        if len(boundaries) == 2 and total_duration > chunk_duration:
            boundaries = [0.0]
            t = chunk_duration
            while t < total_duration:
                boundaries.append(t)
                t += chunk_duration
            boundaries.append(total_duration)

        chunks: list[dict[str, Any]] = []
        logger.info(
            f"Splitting {total_duration:.1f}s audio into {len(boundaries) - 1} chunks "
            f"({'VAD' if split_points else 'fixed'})"
        )

        for chunk_index in range(len(boundaries) - 1):
            current_time = boundaries[chunk_index]
            end_time = boundaries[chunk_index + 1]
            chunk_path = os.path.join(output_dir, f"chunk_{chunk_index:03d}.mp3")

            cmd = [
                "ffmpeg",
                "-i",
                audio_path,
                "-ss",
                str(current_time),
                "-t",
                str(end_time - current_time),
                "-acodec",
                "libmp3lame",
                "-ab",
                "128k",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-y",
                chunk_path,
            ]

            try:
                subprocess.run(cmd, capture_output=True, check=True)
                chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
                logger.debug(
                    f"Chunk {chunk_index}: {current_time:.1f}s - {end_time:.1f}s ({chunk_size_mb:.1f}MB)"
                )

                chunks.append(
                    {
                        "path": chunk_path,
                        "start_time": current_time,
                        "end_time": end_time,
                        "index": chunk_index,
                        "size_mb": chunk_size_mb,
                    }
                )

            except subprocess.CalledProcessError as e:
                logger.warning(f"Error creando chunk {chunk_index}: {e}")

        logger.info(f"Creados {len(chunks)} chunks")
        return chunks

    async def transcribe_audio(
        self,
        audio_path: str,
        language: str | None = None,
        response_format: str = "verbose_json",
        timestamp_granularities: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Transcribe audio usando Azure OpenAI Whisper.
        
        Para archivos grandes, automáticamente divide en chunks.

        Args:
            audio_path: Ruta al archivo de audio.
            language: Código de idioma (es, en, etc.) - None para detección automática.
            response_format: Formato de respuesta (json, text, srt, verbose_json, vtt).
            timestamp_granularities: Granularidad de timestamps ["word", "segment"].

        Returns:
            Diccionario con transcripción y metadatos.
        """
        logger.info("Transcribiendo audio con Whisper")

        if timestamp_granularities is None:
            timestamp_granularities = ["segment", "word"]

        # Verificar tamaño y decidir si hacer chunking
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        audio_duration = self.get_audio_duration(audio_path)

        logger.info(f"Tamaño: {file_size_mb:.1f}MB, Duración: {audio_duration:.1f}s")

        if file_size_mb > WHISPER_MAX_FILE_SIZE_MB:
            logger.info(f"Archivo excede {WHISPER_MAX_FILE_SIZE_MB}MB, usando chunking")
            return await self._transcribe_with_chunking(
                audio_path, language, response_format, timestamp_granularities
            )

        # Transcripción directa para archivos pequeños
        return await self._transcribe_single_file(
            audio_path, language, response_format, timestamp_granularities, time_offset=0
        )

    async def _transcribe_single_file(
        self,
        audio_path: str,
        language: str | None,
        response_format: str,
        timestamp_granularities: list[str],
        time_offset: float = 0,
    ) -> dict[str, Any]:
        """
        Transcribe un archivo de audio individual.
        
        Args:
            audio_path: Ruta al archivo de audio.
            language: Código de idioma (opcional).
            response_format: Formato de respuesta.
            timestamp_granularities: Granularidad de timestamps.
            time_offset: Offset de tiempo para ajustar timestamps.
            
        Returns:
            Diccionario con resultados de transcripción.
        """
        await self._wait_for_rate_limit()

        try:
            with open(audio_path, "rb") as audio_file:
                start_time = time.time()

                transcription = await self.openai_client.audio.transcriptions.create(
                    model=self.whisper_deployment,
                    file=audio_file,
                    language=language,
                    response_format=response_format,
                    timestamp_granularities=timestamp_granularities,
                )

                elapsed = time.time() - start_time

                # Convertir a dict
                if hasattr(transcription, "model_dump"):
                    result = transcription.model_dump()
                elif hasattr(transcription, "to_dict"):
                    result = transcription.to_dict()
                else:
                    result = dict(transcription)

                # Ajustar timestamps si hay offset
                if time_offset > 0:
                    result = self._adjust_timestamps(result, time_offset)

                logger.info(f"Transcripción completada en {elapsed:.2f}s")
                return result

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error en transcripción: {e}")
            raise
        except OSError as e:
            logger.error(f"Error de archivo en transcripción: {e}")
            raise

    async def _transcribe_with_chunking(
        self,
        audio_path: str,
        language: str | None,
        response_format: str,
        timestamp_granularities: list[str],
    ) -> dict[str, Any]:
        """
        Transcribe audio grande dividiéndolo en chunks.
        
        Args:
            audio_path: Ruta al archivo de audio.
            language: Código de idioma (opcional).
            response_format: Formato de respuesta.
            timestamp_granularities: Granularidad de timestamps.
            
        Returns:
            Diccionario con resultados combinados de transcripción.
        """
        chunks = self.split_audio_into_chunks(audio_path)

        all_segments: list[dict[str, Any]] = []
        all_words: list[dict[str, Any]] = []
        full_text_parts: list[str] = []
        detected_language: str | None = None
        total_duration = 0.0

        logger.info(f"Procesando {len(chunks)} chunks")

        for i, chunk in enumerate(chunks):
            logger.debug(
                f"Chunk {i+1}/{len(chunks)}: {chunk['start_time']:.1f}s - {chunk['end_time']:.1f}s"
            )

            try:
                result = await self._transcribe_single_file(
                    chunk["path"],
                    language,
                    response_format,
                    timestamp_granularities,
                    time_offset=chunk["start_time"],
                )

                # Acumular resultados
                if result.get("text"):
                    full_text_parts.append(result["text"])

                if result.get("segments"):
                    all_segments.extend(result["segments"])

                if result.get("words"):
                    all_words.extend(result["words"])

                if not detected_language and result.get("language"):
                    detected_language = result["language"]

                chunk_duration = result.get("duration", chunk["end_time"] - chunk["start_time"])
                total_duration = max(total_duration, chunk["start_time"] + chunk_duration)

                logger.debug(
                    f"Chunk {i+1}: {len(result.get('text', ''))} chars, {len(result.get('segments', []))} segmentos"
                )

            except (APIError, APIConnectionError, RateLimitError) as e:
                logger.error(f"OpenAI API error en chunk {i}: {e}")
                continue
            except Exception as e:
                logger.exception(f"Error inesperado en chunk {i}: {e}")
                continue
            finally:
                # Limpiar chunk temporal
                if chunk.get("path") != audio_path and os.path.exists(chunk["path"]):
                    try:
                        os.unlink(chunk["path"])
                    except OSError:
                        pass

        # Combinar resultados
        combined_result: dict[str, Any] = {
            "text": " ".join(full_text_parts),
            "language": detected_language,
            "duration": total_duration,
            "segments": all_segments,
            "words": all_words,
            "chunked": True,
            "chunk_count": len(chunks),
        }

        logger.info(
            f"Transcripción combinada completada: {len(combined_result['text'])} chars, "
            f"{len(all_segments)} segmentos, {len(all_words)} palabras"
        )

        return combined_result

    def _adjust_timestamps(self, result: dict[str, Any], offset: float) -> dict[str, Any]:
        """
        Ajusta todos los timestamps añadiendo un offset.
        
        Args:
            result: Diccionario con resultados de transcripción.
            offset: Offset en segundos a añadir a los timestamps.
            
        Returns:
            Diccionario con timestamps ajustados.
        """
        # Ajustar segmentos
        if "segments" in result:
            for segment in result["segments"]:
                if "start" in segment:
                    segment["start"] += offset
                if "end" in segment:
                    segment["end"] += offset

        # Ajustar palabras
        if "words" in result:
            for word in result["words"]:
                if "start" in word:
                    word["start"] += offset
                if "end" in word:
                    word["end"] += offset

        return result

    async def analyze_transcription(
        self, transcription_text: str, video_descriptions: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Analiza la transcripción para extraer insights usando GPT-4.

        Args:
            transcription_text: Texto de la transcripción.
            video_descriptions: Descripciones visuales de frames (opcional).

        Returns:
            Diccionario con análisis enriquecido.
        """
        logger.info("Analizando transcripción con GPT-4o")

        # Construir contexto con descripciones visuales si están disponibles
        context = ""
        if video_descriptions:
            context = "\n\nCONTEXTO VISUAL:\n"
            for i, desc in enumerate(video_descriptions[:10], 1):  # Primeros 10 frames
                context += f"Frame {i}: {desc}\n"

        prompt = f"""Analiza esta transcripción de video y proporciona un análisis estructurado en JSON con:

1. **resumen**: Resumen ejecutivo (2-3 oraciones)
2. **temas_principales**: Lista de temas clave mencionados
3. **entidades**: Personas, lugares, organizaciones mencionadas
4. **sentimiento**: Análisis de sentimiento (positivo/neutral/negativo/mixto)
5. **momentos_clave**: Timestamps importantes con descripción
6. **keywords**: Palabras clave para búsqueda (10-15 términos)
7. **categoria**: Categoría del contenido (educativo, entretenimiento, noticias, etc.)
8. **idioma**: Idioma principal detectado
9. **duracion_estimada**: Duración aproximada en segundos
{context}

TRANSCRIPCIÓN:
{transcription_text}

Responde SOLO con el JSON válido, sin markdown ni explicaciones adicionales."""

        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "Eres un experto en análisis de contenido multimedia. Respondes SOLO con JSON válido.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=1,
                response_format={"type": "json_object"},
            )

            analysis = json.loads(response.choices[0].message.content)

            logger.info(
                f"Análisis completado: {analysis.get('resumen', 'N/A')[:50]}..., "
                f"temas: {len(analysis.get('temas_principales', []))}"
            )

            return analysis

        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error analizando transcripción: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Error parseando JSON de análisis: {e}")
            return {}
        except Exception as e:
            logger.exception(f"Error inesperado analizando transcripción: {e}")
            return {}

    async def process_video_audio(
        self,
        video_path: str,
        language: str | None = None,
        video_descriptions: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Pipeline completo: extrae audio, transcribe y analiza.

        Args:
            video_path: Ruta al video.
            language: Idioma (None para detección automática).
            video_descriptions: Descripciones de frames para contexto.

        Returns:
            Diccionario completo con transcripción y análisis.
        """
        audio_path: str | None = None

        try:
            # 1. Extraer audio
            logger.info("Iniciando procesamiento de audio")

            audio_path = self.extract_audio_from_video(video_path)

            # 2. Transcribir
            transcription = await self.transcribe_audio(audio_path, language=language)

            # 3. Analizar transcripción
            full_text = transcription.get("text", "")
            analysis: dict[str, Any] = {}

            if full_text and len(full_text.strip()) > 50:
                analysis = await self.analyze_transcription(full_text, video_descriptions)
            else:
                logger.warning("Transcripción muy corta o vacía, saltando análisis")

            # 4. Consolidar resultado
            result: dict[str, Any] = {
                "transcription": {
                    "text": full_text,
                    "language": transcription.get("language"),
                    "duration": transcription.get("duration"),
                    "segments": transcription.get("segments", []),
                    "words": transcription.get("words", []),
                },
                "analysis": analysis,
                "stats": {
                    "total_words": len(full_text.split()) if full_text else 0,
                    "total_segments": len(transcription.get("segments", [])),
                    "has_audio": len(full_text.strip()) > 0,
                    "audio_duration": transcription.get("duration", 0),
                },
            }

            logger.info(
                f"Procesamiento de audio completado: {len(full_text)} chars, "
                f"{result['stats']['total_words']} palabras, {result['stats']['total_segments']} segmentos"
            )

            return result

        except (subprocess.SubprocessError, RuntimeError) as e:
            logger.error(f"Error de proceso procesando audio: {e}")
            return {
                "transcription": {
                    "text": "",
                    "language": None,
                    "duration": 0,
                    "segments": [],
                    "words": [],
                },
                "analysis": {},
                "stats": {
                    "total_words": 0,
                    "total_segments": 0,
                    "has_audio": False,
                    "audio_duration": 0,
                },
                "error": str(e),
            }
        except (APIError, APIConnectionError, RateLimitError) as e:
            logger.error(f"OpenAI API error procesando audio: {e}")
            return {
                "transcription": {
                    "text": "",
                    "language": None,
                    "duration": 0,
                    "segments": [],
                    "words": [],
                },
                "analysis": {},
                "stats": {
                    "total_words": 0,
                    "total_segments": 0,
                    "has_audio": False,
                    "audio_duration": 0,
                },
                "error": str(e),
            }
        except Exception as e:
            logger.exception(f"Error inesperado procesando audio: {e}")
            return {
                "transcription": {
                    "text": "",
                    "language": None,
                    "duration": 0,
                    "segments": [],
                    "words": [],
                },
                "analysis": {},
                "stats": {
                    "total_words": 0,
                    "total_segments": 0,
                    "has_audio": False,
                    "audio_duration": 0,
                },
                "error": str(e),
            }

        finally:
            # Limpiar archivo temporal
            if audio_path and os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass
