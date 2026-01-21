"""
Face Tracking Service
=====================

Service for detecting and tracking faces in video frames.
Used for smart crop functionality when converting horizontal
videos to vertical format (16:9 → 9:16).

Supports:
- MediaPipe Face Detection (preferred, more accurate)
- OpenCV DNN Face Detection (fallback)
- OpenCV Haar Cascades (legacy fallback)
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Try to import MediaPipe
try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    logger.info("MediaPipe not available, using OpenCV for face detection")


@dataclass
class FaceDetection:
    """Detected face with bounding box and confidence."""
    x: int  # Top-left x
    y: int  # Top-left y
    width: int
    height: int
    confidence: float
    center_x: int  # Center of face
    center_y: int  # Center of face


@dataclass
class CropKeyframe:
    """Crop position at a specific timestamp."""
    timestamp: float  # Seconds
    crop_x: int  # Crop region top-left x
    crop_y: int  # Crop region top-left y
    crop_width: int
    crop_height: int
    has_face: bool  # Whether a face was detected


@dataclass
class SmartCropResult:
    """Result of smart crop analysis."""
    keyframes: list[CropKeyframe]
    source_width: int
    source_height: int
    target_width: int
    target_height: int
    faces_detected: int
    frames_analyzed: int


class FaceTrackingService:
    """
    Service for face detection and tracking in video frames.

    Uses MediaPipe if available, falls back to OpenCV DNN or Haar cascades.
    """

    def __init__(self):
        self._face_detector = None
        self._detection_method = None
        self._initialize_detector()

    def _initialize_detector(self):
        """Initialize the best available face detector."""
        if MEDIAPIPE_AVAILABLE:
            try:
                self._face_detector = mp.solutions.face_detection.FaceDetection(
                    model_selection=1,  # Full range model (better for different distances)
                    min_detection_confidence=0.5,
                )
                self._detection_method = "mediapipe"
                logger.info("Using MediaPipe for face detection")
                return
            except Exception as e:
                logger.warning(f"Failed to initialize MediaPipe: {e}")

        # Try OpenCV DNN
        try:
            model_path = self._get_opencv_dnn_model()
            if model_path:
                self._face_detector = cv2.dnn.readNetFromCaffe(
                    str(model_path / "deploy.prototxt"),
                    str(model_path / "res10_300x300_ssd_iter_140000.caffemodel"),
                )
                self._detection_method = "opencv_dnn"
                logger.info("Using OpenCV DNN for face detection")
                return
        except Exception as e:
            logger.warning(f"Failed to initialize OpenCV DNN: {e}")

        # Fallback to Haar cascades
        try:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._face_detector = cv2.CascadeClassifier(cascade_path)
            self._detection_method = "haar"
            logger.info("Using OpenCV Haar cascades for face detection")
        except Exception as e:
            logger.error(f"Failed to initialize any face detector: {e}")
            self._detection_method = None

    def _get_opencv_dnn_model(self) -> Path | None:
        """Get path to OpenCV DNN face detection model if available."""
        # Common locations for the model
        possible_paths = [
            Path(__file__).parent / "models" / "face_detection",
            Path.home() / ".cache" / "opencv" / "face_detection",
            Path("/usr/share/opencv4/haarcascades"),
        ]

        for path in possible_paths:
            if (path / "deploy.prototxt").exists():
                return path

        return None

    def detect_faces(self, frame: np.ndarray) -> list[FaceDetection]:
        """
        Detect faces in a single frame.

        Args:
            frame: BGR image as numpy array

        Returns:
            List of detected faces
        """
        if self._face_detector is None:
            return []

        height, width = frame.shape[:2]
        faces = []

        try:
            if self._detection_method == "mediapipe":
                faces = self._detect_mediapipe(frame, width, height)
            elif self._detection_method == "opencv_dnn":
                faces = self._detect_opencv_dnn(frame, width, height)
            elif self._detection_method == "haar":
                faces = self._detect_haar(frame, width, height)
        except Exception as e:
            logger.warning(f"Face detection error: {e}")

        return faces

    def _detect_mediapipe(
        self, frame: np.ndarray, width: int, height: int
    ) -> list[FaceDetection]:
        """Detect faces using MediaPipe."""
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._face_detector.process(rgb_frame)

        faces = []
        if results.detections:
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                x = int(bbox.xmin * width)
                y = int(bbox.ymin * height)
                w = int(bbox.width * width)
                h = int(bbox.height * height)

                # Clamp to frame bounds
                x = max(0, min(x, width - 1))
                y = max(0, min(y, height - 1))
                w = min(w, width - x)
                h = min(h, height - y)

                faces.append(FaceDetection(
                    x=x, y=y, width=w, height=h,
                    confidence=detection.score[0],
                    center_x=x + w // 2,
                    center_y=y + h // 2,
                ))

        return faces

    def _detect_opencv_dnn(
        self, frame: np.ndarray, width: int, height: int
    ) -> list[FaceDetection]:
        """Detect faces using OpenCV DNN."""
        blob = cv2.dnn.blobFromImage(
            cv2.resize(frame, (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0)
        )
        self._face_detector.setInput(blob)
        detections = self._face_detector.forward()

        faces = []
        for i in range(detections.shape[2]):
            confidence = detections[0, 0, i, 2]
            if confidence > 0.5:
                box = detections[0, 0, i, 3:7] * np.array([width, height, width, height])
                x1, y1, x2, y2 = box.astype("int")

                # Clamp to frame bounds
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(width, x2)
                y2 = min(height, y2)

                w = x2 - x1
                h = y2 - y1

                if w > 0 and h > 0:
                    faces.append(FaceDetection(
                        x=x1, y=y1, width=w, height=h,
                        confidence=float(confidence),
                        center_x=x1 + w // 2,
                        center_y=y1 + h // 2,
                    ))

        return faces

    def _detect_haar(
        self, frame: np.ndarray, width: int, height: int
    ) -> list[FaceDetection]:
        """Detect faces using Haar cascades."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detections = self._face_detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )

        faces = []
        for (x, y, w, h) in detections:
            faces.append(FaceDetection(
                x=x, y=y, width=w, height=h,
                confidence=0.8,  # Haar doesn't provide confidence
                center_x=x + w // 2,
                center_y=y + h // 2,
            ))

        return faces

    def extract_frames_for_analysis(
        self,
        video_path: str,
        start_time: float,
        end_time: float,
        sample_interval: float = 0.5,
    ) -> list[tuple[float, np.ndarray]]:
        """
        Extract frames from video at regular intervals for face analysis.

        Args:
            video_path: Path to video file
            start_time: Start time in seconds
            end_time: End time in seconds
            sample_interval: Time between samples in seconds

        Returns:
            List of (timestamp, frame) tuples
        """
        frames = []
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            logger.error(f"Could not open video: {video_path}")
            return frames

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30  # Default fallback

        try:
            current_time = start_time
            while current_time <= end_time:
                # Seek to frame
                frame_num = int(current_time * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)

                ret, frame = cap.read()
                if not ret:
                    break

                frames.append((current_time, frame))
                current_time += sample_interval

        finally:
            cap.release()

        return frames

    def analyze_video_for_smart_crop(
        self,
        video_path: str,
        start_time: float,
        end_time: float,
        target_aspect_ratio: float = 9 / 16,  # Vertical (9:16)
        sample_interval: float = 0.5,
    ) -> SmartCropResult:
        """
        Analyze video segment for smart crop with face tracking.

        Args:
            video_path: Path to video file
            start_time: Clip start time
            end_time: Clip end time
            target_aspect_ratio: Target width/height ratio (9/16 for vertical)
            sample_interval: Time between face detection samples

        Returns:
            SmartCropResult with keyframes for FFmpeg
        """
        # Get video info
        cap = cv2.VideoCapture(video_path)
        source_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        source_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        if source_width == 0 or source_height == 0:
            logger.error("Could not get video dimensions")
            return SmartCropResult(
                keyframes=[],
                source_width=0,
                source_height=0,
                target_width=0,
                target_height=0,
                faces_detected=0,
                frames_analyzed=0,
            )

        # Calculate target crop dimensions
        source_aspect = source_width / source_height

        if source_aspect > target_aspect_ratio:
            # Source is wider than target - crop width
            target_height = source_height
            target_width = int(source_height * target_aspect_ratio)
        else:
            # Source is taller than target - crop height
            target_width = source_width
            target_height = int(source_width / target_aspect_ratio)

        # Extract frames for analysis
        frames = self.extract_frames_for_analysis(
            video_path, start_time, end_time, sample_interval
        )

        if not frames:
            logger.warning("No frames extracted for analysis")
            # Return center crop as fallback
            center_x = (source_width - target_width) // 2
            center_y = (source_height - target_height) // 2
            return SmartCropResult(
                keyframes=[CropKeyframe(
                    timestamp=start_time,
                    crop_x=center_x,
                    crop_y=center_y,
                    crop_width=target_width,
                    crop_height=target_height,
                    has_face=False,
                )],
                source_width=source_width,
                source_height=source_height,
                target_width=target_width,
                target_height=target_height,
                faces_detected=0,
                frames_analyzed=0,
            )

        # Detect faces in each frame
        keyframes = []
        total_faces = 0
        previous_crop_x = None
        previous_crop_y = None

        for timestamp, frame in frames:
            faces = self.detect_faces(frame)
            has_face = len(faces) > 0
            total_faces += len(faces)

            if has_face:
                # Use the largest/most confident face
                main_face = max(faces, key=lambda f: f.width * f.height * f.confidence)

                # Calculate crop position to center the face
                crop_x = main_face.center_x - target_width // 2
                crop_y = main_face.center_y - target_height // 2
            else:
                # No face - use center of frame or previous position
                if previous_crop_x is not None:
                    crop_x = previous_crop_x
                    crop_y = previous_crop_y
                else:
                    crop_x = (source_width - target_width) // 2
                    crop_y = (source_height - target_height) // 2

            # Clamp crop position to valid range
            crop_x = max(0, min(crop_x, source_width - target_width))
            crop_y = max(0, min(crop_y, source_height - target_height))

            # Smooth the crop movement (reduce jitter)
            if previous_crop_x is not None:
                smoothing = 0.7  # Higher = more smoothing
                crop_x = int(previous_crop_x * smoothing + crop_x * (1 - smoothing))
                crop_y = int(previous_crop_y * smoothing + crop_y * (1 - smoothing))

                # Clamp again after smoothing
                crop_x = max(0, min(crop_x, source_width - target_width))
                crop_y = max(0, min(crop_y, source_height - target_height))

            previous_crop_x = crop_x
            previous_crop_y = crop_y

            keyframes.append(CropKeyframe(
                timestamp=timestamp - start_time,  # Relative to clip start
                crop_x=crop_x,
                crop_y=crop_y,
                crop_width=target_width,
                crop_height=target_height,
                has_face=has_face,
            ))

        return SmartCropResult(
            keyframes=keyframes,
            source_width=source_width,
            source_height=source_height,
            target_width=target_width,
            target_height=target_height,
            faces_detected=total_faces,
            frames_analyzed=len(frames),
        )

    def generate_ffmpeg_crop_filter(
        self,
        result: SmartCropResult,
        use_keyframes: bool = True,
    ) -> str:
        """
        Generate FFmpeg filter string for smart crop.

        Args:
            result: SmartCropResult from analysis
            use_keyframes: If True, generate animated crop. If False, use static crop.

        Returns:
            FFmpeg filter string
        """
        if not result.keyframes:
            # Fallback to center crop
            x = (result.source_width - result.target_width) // 2
            y = (result.source_height - result.target_height) // 2
            return f"crop={result.target_width}:{result.target_height}:{x}:{y}"

        if not use_keyframes or len(result.keyframes) == 1:
            # Static crop using first keyframe
            kf = result.keyframes[0]
            return f"crop={kf.crop_width}:{kf.crop_height}:{kf.crop_x}:{kf.crop_y}"

        # Animated crop using sendcmd
        # This is complex - for now, use the average position
        avg_x = int(sum(kf.crop_x for kf in result.keyframes) / len(result.keyframes))
        avg_y = int(sum(kf.crop_y for kf in result.keyframes) / len(result.keyframes))

        return f"crop={result.target_width}:{result.target_height}:{avg_x}:{avg_y}"

    def generate_crop_with_keyframes(
        self,
        result: SmartCropResult,
    ) -> tuple[str, str | None]:
        """
        Generate FFmpeg filter with keyframe interpolation for smooth tracking.

        Returns:
            Tuple of (filter_string, sendcmd_file_path or None)
        """
        if not result.keyframes or len(result.keyframes) <= 1:
            return self.generate_ffmpeg_crop_filter(result, use_keyframes=False), None

        # Create sendcmd file for animated crop
        # FFmpeg sendcmd allows changing filter parameters over time

        # For complex keyframe animation, we need zoompan or a more sophisticated approach
        # For now, use a simplified version with the weighted average based on face presence

        face_keyframes = [kf for kf in result.keyframes if kf.has_face]

        if face_keyframes:
            # Weight positions by face detection
            total_weight = len(face_keyframes)
            avg_x = int(sum(kf.crop_x for kf in face_keyframes) / total_weight)
            avg_y = int(sum(kf.crop_y for kf in face_keyframes) / total_weight)
        else:
            # No faces detected, use center
            avg_x = (result.source_width - result.target_width) // 2
            avg_y = (result.source_height - result.target_height) // 2

        filter_str = f"crop={result.target_width}:{result.target_height}:{avg_x}:{avg_y}"

        return filter_str, None


# Singleton instance
_face_tracking_service: FaceTrackingService | None = None


def get_face_tracking_service() -> FaceTrackingService:
    """Get or create the face tracking service singleton."""
    global _face_tracking_service
    if _face_tracking_service is None:
        _face_tracking_service = FaceTrackingService()
    return _face_tracking_service
