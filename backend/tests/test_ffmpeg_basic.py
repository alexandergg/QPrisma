"""
Test simple de extracción de frames con FFmpeg
"""

import os
import subprocess


def test_ffmpeg_extraction():
    """Test básico de extracción de un frame"""

    video_path = "test_data/test_video.mp4"
    output_path = "test_data/test_frame.jpg"

    if not os.path.exists(video_path):
        print(f"❌ Video no encontrado: {video_path}")
        return False

    print("🎬 Testing FFmpeg frame extraction")
    print(f"   Video: {video_path}")
    print(f"   Output: {output_path}")

    # Comando simple para extraer un frame en t=5s
    cmd = [
        "ffmpeg",
        "-ss",
        "5.0",  # Seek a 5 segundos
        "-i",
        video_path,
        "-vframes",
        "1",  # Solo 1 frame
        "-q:v",
        "2",  # Calidad alta
        "-y",  # Sobrescribir
        output_path,
    ]

    print(f"\n📝 Comando: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print("✅ Frame extraído exitosamente!")
            print(f"   Archivo: {output_path}")
            print(f"   Tamaño: {size:,} bytes")

            # Mostrar info del video
            print("\n📊 Info del video:")
            info_cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,duration",
                "-of",
                "default=noprint_wrappers=1",
                video_path,
            ]

            info_result = subprocess.run(info_cmd, capture_output=True, text=True)
            print(info_result.stdout)

            return True
        else:
            print("❌ Error: Frame no fue creado")
            print("\n📋 FFmpeg stdout:")
            print(result.stdout)
            print("\n❌ FFmpeg stderr:")
            print(result.stderr)
            return False

    except subprocess.TimeoutExpired:
        print("❌ Timeout: FFmpeg tardó más de 10 segundos")
        return False
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("🧪 Test de FFmpeg - Extracción de Frame")
    print("=" * 70)

    success = test_ffmpeg_extraction()

    print("\n" + "=" * 70)
    if success:
        print("✅ TEST EXITOSO - FFmpeg está funcionando correctamente")
    else:
        print("❌ TEST FALLIDO - Revisar configuración de FFmpeg")
    print("=" * 70)
