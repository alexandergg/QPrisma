"""
Script para generar un video de prueba simple usando FFmpeg
"""

import os
import subprocess


def create_test_video(output_path: str = "test_video.mp4", duration: int = 5, fps: int = 30):
    """
    Crea un video de prueba con diferentes colores y texto usando FFmpeg

    Args:
        output_path: Ruta donde guardar el video
        duration: Duración en segundos
        fps: Frames por segundo
    """
    # Configuración
    width, height = 1280, 720

    print(f"Generando video de prueba con FFmpeg: {output_path}")
    print(f"Duración: {duration}s | FPS: {fps} | Resolución: {width}x{height}")

    # Crear video con FFmpeg usando filtros de video
    # testsrc2: genera un patrón de prueba colorido
    # drawtext: agrega texto con timestamp
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",  # Sobrescribir si existe
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={width}x{height}:rate={fps}:duration={duration}",
        "-vf",
        (
            "drawtext=fontfile=Arial.ttf:text='QPrisma Test Video':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=50:box=1:boxcolor=black@0.5:boxborderw=5,"
            "drawtext=fontfile=Arial.ttf:text='Time\\: %{pts\\:hms}':fontcolor=white:fontsize=40:x=(w-text_w)/2:y=150:box=1:boxcolor=black@0.5:boxborderw=5,"
            "drawtext=fontfile=Arial.ttf:text='Frame\\: %{n}':fontcolor=yellow:fontsize=30:x=50:y=h-80:box=1:boxcolor=black@0.5:boxborderw=5"
        ),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        output_path,
    ]

    try:
        # Ejecutar FFmpeg con un comando construido por este helper de prueba.
        result = subprocess.run(  # noqa: S603
            ffmpeg_cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        # Verificar que el archivo se creó
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
            total_frames = duration * fps

            print("\n✓ Video generado exitosamente con FFmpeg!")
            print(f"  Archivo: {output_path}")
            print(f"  Tamaño: {file_size:.2f} MB")
            print(f"  Frames totales: ~{total_frames}")
            return output_path
        else:
            print("\n✗ Error: El archivo no se creó")
            return None

    except subprocess.CalledProcessError as e:
        print("\n✗ Error ejecutando FFmpeg:")
        print(f"  {e.stderr}")
        return None
    except FileNotFoundError:
        print("\n✗ Error: FFmpeg no está instalado o no está en el PATH")
        print("  Instala FFmpeg: https://ffmpeg.org/download.html")
        return None


if __name__ == "__main__":
    # Crear directorio de test si no existe
    os.makedirs("test_data", exist_ok=True)

    # Generar video de prueba
    video_path = create_test_video(
        output_path="test_data/test_video.mp4",
        duration=10,
        fps=30,  # 10 segundos
    )

    print("\n🎬 Puedes usar este video para probar el sistema:")
    print(f"   {os.path.abspath(video_path)}")
