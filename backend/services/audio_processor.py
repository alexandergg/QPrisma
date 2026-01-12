"""
Audio Processing Service
Extrae audio de videos, transcribe con Whisper y genera análisis enriquecido.
Soporta chunking para archivos grandes (>25MB limit de Azure Whisper).
"""

import json
import os
import subprocess
import tempfile
import time

from openai import AzureOpenAI

# Azure Whisper tiene límite de 25MB
WHISPER_MAX_FILE_SIZE_MB = 25
# Chunk duration objetivo para audio (5 minutos da ~5-8MB en mp3 128kbps)
CHUNK_DURATION_SECONDS = 300  # 5 minutos


class AudioProcessor:
    """Procesa audio de videos: extracción, transcripción con Whisper, análisis"""

    def __init__(self, openai_client: AzureOpenAI, rate_limit_rpm: int = 3):
        self.openai_client = openai_client
        self.whisper_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_WHISPER", "whisper")
        self.gpt_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT", "gpt-4o")
        self.rate_limit_rpm = rate_limit_rpm  # Requests per minute
        self._last_request_time = 0

    def _wait_for_rate_limit(self):
        """Espera si es necesario para respetar rate limit."""
        if self.rate_limit_rpm <= 0:
            return

        min_interval = 60.0 / self.rate_limit_rpm  # segundos entre requests
        elapsed = time.time() - self._last_request_time

        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            print(f"⏳ Rate limit: esperando {wait_time:.1f}s...")
            time.sleep(wait_time)

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
            print(f"✓ Audio extraído: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Error extrayendo audio: {e.stderr}")

    def get_audio_duration(self, audio_path: str) -> float:
        """Obtiene la duración del audio en segundos usando ffprobe."""
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
        except Exception as e:
            print(f"⚠️ Error obteniendo duración: {e}")
            return 0.0

    def split_audio_into_chunks(
        self,
        audio_path: str,
        chunk_duration: float = CHUNK_DURATION_SECONDS,
        output_dir: str | None = None,
    ) -> list[dict]:
        """
        Divide audio en chunks más pequeños para respetar límite de Whisper.

        Args:
            audio_path: Ruta al archivo de audio
            chunk_duration: Duración máxima de cada chunk en segundos
            output_dir: Directorio para chunks (temporal si None)

        Returns:
            Lista de dicts con info de cada chunk: {path, start_time, end_time, index}
        """
        total_duration = self.get_audio_duration(audio_path)
        if total_duration <= 0:
            return [{"path": audio_path, "start_time": 0, "end_time": 0, "index": 0}]

        # Verificar si necesita chunking
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        if file_size_mb <= WHISPER_MAX_FILE_SIZE_MB and total_duration <= chunk_duration:
            print(f"✓ Audio pequeño ({file_size_mb:.1f}MB), no requiere chunking")
            return [{"path": audio_path, "start_time": 0, "end_time": total_duration, "index": 0}]

        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="audio_chunks_")

        chunks = []
        current_time = 0
        chunk_index = 0

        print(f"📦 Dividiendo audio de {total_duration:.1f}s en chunks de {chunk_duration}s...")

        while current_time < total_duration:
            end_time = min(current_time + chunk_duration, total_duration)
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
                print(
                    f"  • Chunk {chunk_index}: {current_time:.1f}s - {end_time:.1f}s ({chunk_size_mb:.1f}MB)"
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
                print(f"⚠️ Error creando chunk {chunk_index}: {e}")

            current_time = end_time
            chunk_index += 1

        print(f"✓ Creados {len(chunks)} chunks")
        return chunks

    def transcribe_audio(
        self,
        audio_path: str,
        language: str | None = None,
        response_format: str = "verbose_json",
        timestamp_granularities: list[str] | None = None,
    ) -> dict:
        """
        Transcribe audio usando Azure OpenAI Whisper.
        Para archivos grandes, automáticamente divide en chunks.

        Args:
            audio_path: Ruta al archivo de audio
            language: Código de idioma (es, en, etc.) - None para detección automática
            response_format: Formato de respuesta (json, text, srt, verbose_json, vtt)
            timestamp_granularities: Granularidad de timestamps ["word", "segment"]

        Returns:
            Diccionario con transcripción y metadatos
        """
        print("🎤 Transcribiendo audio con Whisper...")

        if timestamp_granularities is None:
            timestamp_granularities = ["segment", "word"]

        # Verificar tamaño y decidir si hacer chunking
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        audio_duration = self.get_audio_duration(audio_path)

        print(f"  • Tamaño: {file_size_mb:.1f}MB, Duración: {audio_duration:.1f}s")

        if file_size_mb > WHISPER_MAX_FILE_SIZE_MB:
            print(f"⚠️ Archivo excede {WHISPER_MAX_FILE_SIZE_MB}MB, usando chunking...")
            return self._transcribe_with_chunking(
                audio_path, language, response_format, timestamp_granularities
            )

        # Transcripción directa para archivos pequeños
        return self._transcribe_single_file(
            audio_path, language, response_format, timestamp_granularities, time_offset=0
        )

    def _transcribe_single_file(
        self,
        audio_path: str,
        language: str | None,
        response_format: str,
        timestamp_granularities: list[str],
        time_offset: float = 0,
    ) -> dict:
        """Transcribe un archivo de audio individual."""
        self._wait_for_rate_limit()

        try:
            with open(audio_path, "rb") as audio_file:
                start_time = time.time()

                transcription = self.openai_client.audio.transcriptions.create(
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

                print(f"✓ Transcripción completada en {elapsed:.2f}s")
                return result

        except Exception as e:
            print(f"✗ Error en transcripción: {e}")
            raise

    def _transcribe_with_chunking(
        self,
        audio_path: str,
        language: str | None,
        response_format: str,
        timestamp_granularities: list[str],
    ) -> dict:
        """Transcribe audio grande dividiéndolo en chunks."""
        chunks = self.split_audio_into_chunks(audio_path)

        all_segments = []
        all_words = []
        full_text_parts = []
        detected_language = None
        total_duration = 0

        print(f"\n🔄 Procesando {len(chunks)} chunks...")

        for i, chunk in enumerate(chunks):
            print(
                f"\n📝 Chunk {i+1}/{len(chunks)}: {chunk['start_time']:.1f}s - {chunk['end_time']:.1f}s"
            )

            try:
                result = self._transcribe_single_file(
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

                print(
                    f"  ✓ Texto: {len(result.get('text', ''))} chars, Segmentos: {len(result.get('segments', []))}"
                )

            except Exception as e:
                print(f"  ✗ Error en chunk {i}: {e}")
                continue
            finally:
                # Limpiar chunk temporal
                if chunk.get("path") != audio_path and os.path.exists(chunk["path"]):
                    try:
                        os.unlink(chunk["path"])
                    except:
                        pass

        # Combinar resultados
        combined_result = {
            "text": " ".join(full_text_parts),
            "language": detected_language,
            "duration": total_duration,
            "segments": all_segments,
            "words": all_words,
            "chunked": True,
            "chunk_count": len(chunks),
        }

        print("\n✅ Transcripción combinada completada")
        print(f"  • Texto total: {len(combined_result['text'])} chars")
        print(f"  • Segmentos: {len(all_segments)}")
        print(f"  • Palabras: {len(all_words)}")

        return combined_result

    def _adjust_timestamps(self, result: dict, offset: float) -> dict:
        """Ajusta todos los timestamps añadiendo un offset."""
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

    def analyze_transcription(
        self, transcription_text: str, video_descriptions: list[str] | None = None
    ) -> dict:
        """
        Analiza la transcripción para extraer insights usando GPT-4

        Args:
            transcription_text: Texto de la transcripción
            video_descriptions: Descripciones visuales de frames (opcional)

        Returns:
            Diccionario con análisis enriquecido
        """
        print("🧠 Analizando transcripción con GPT-4o...")

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
            response = self.openai_client.chat.completions.create(
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

            print("✓ Análisis completado")
            print(f"  • Resumen: {analysis.get('resumen', 'N/A')[:100]}...")
            print(f"  • Temas: {', '.join(analysis.get('temas_principales', [])[:5])}")
            print(f"  • Sentimiento: {analysis.get('sentimiento', 'N/A')}")

            return analysis

        except Exception as e:
            print(f"✗ Error analizando transcripción: {e}")
            return {}

    def process_video_audio(
        self,
        video_path: str,
        language: str | None = None,
        video_descriptions: list[str] | None = None,
    ) -> dict:
        """
        Pipeline completo: extrae audio, transcribe y analiza

        Args:
            video_path: Ruta al video
            language: Idioma (None para detección automática)
            video_descriptions: Descripciones de frames para contexto

        Returns:
            Diccionario completo con transcripción y análisis
        """
        audio_path = None

        try:
            # 1. Extraer audio
            print(f"\n{'='*60}")
            print("🎵 PROCESAMIENTO DE AUDIO")
            print(f"{'='*60}")

            audio_path = self.extract_audio_from_video(video_path)

            # 2. Transcribir
            transcription = self.transcribe_audio(audio_path, language=language)

            # 3. Analizar transcripción
            full_text = transcription.get("text", "")
            analysis = {}

            if full_text and len(full_text.strip()) > 50:  # Solo analizar si hay suficiente texto
                analysis = self.analyze_transcription(full_text, video_descriptions)
            else:
                print("⚠️  Transcripción muy corta o vacía, saltando análisis")

            # 4. Consolidar resultado
            result = {
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

            print("\n✅ Procesamiento de audio completado")
            print(f"  • Texto: {len(full_text)} caracteres")
            print(f"  • Palabras: {result['stats']['total_words']}")
            print(f"  • Segmentos: {result['stats']['total_segments']}")

            return result

        except Exception as e:
            print(f"✗ Error procesando audio: {e}")
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
                except:
                    pass
