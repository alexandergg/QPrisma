"""
Subtitle Service
================

Service for generating and managing subtitles for video clips.
Extracts word-level timing from Whisper transcriptions and formats
them for real-time preview and FFmpeg burning.
"""

import logging
from typing import Any

from services.database_service import get_database_service

logger = logging.getLogger(__name__)


# Subtitle style configurations with detailed render settings
SUBTITLE_STYLES = {
    "hormozi": {
        "name": "Hormozi",
        "description": "Word-by-word, bold, alternating yellow/white colors",
        "css": {
            "fontFamily": "'Inter', 'Helvetica Neue', sans-serif",
            "fontSize": "32px",
            "fontWeight": "800",
            "textTransform": "uppercase",
            "color": "#FFFFFF",
            "highlightColor": "#FFD700",
            "backgroundColor": "transparent",
            "textShadow": "2px 2px 4px rgba(0,0,0,0.8)",
            "position": "center",  # center, bottom, top
            "animation": "word_by_word",  # word_by_word, sentence, karaoke, pop
            "maxWordsPerLine": 3,
            "lineHeight": "1.4",
        },
        "ffmpeg": {
            "fontfile": "Inter-ExtraBold.ttf",
            "fontsize": 48,
            "fontcolor": "white",
            "borderw": 3,
            "bordercolor": "black",
            "alignment": 10,  # Center-center in ASS
        },
    },
    "mrbeast": {
        "name": "MrBeast",
        "description": "Large, centered, dramatic shadow, all caps",
        "css": {
            "fontFamily": "'Impact', 'Haettenschweiler', sans-serif",
            "fontSize": "48px",
            "fontWeight": "700",
            "textTransform": "uppercase",
            "color": "#FFFFFF",
            "highlightColor": "#FF0000",
            "backgroundColor": "rgba(0,0,0,0.6)",
            "textShadow": "4px 4px 8px rgba(0,0,0,0.9)",
            "position": "center",
            "animation": "pop",
            "maxWordsPerLine": 4,
            "lineHeight": "1.3",
            "padding": "8px 16px",
            "borderRadius": "8px",
        },
        "ffmpeg": {
            "fontfile": "Impact.ttf",
            "fontsize": 64,
            "fontcolor": "white",
            "borderw": 4,
            "bordercolor": "black",
            "box": 1,
            "boxcolor": "black@0.6",
            "alignment": 10,
        },
    },
    "minimal": {
        "name": "Minimal",
        "description": "Small, clean, no background. Professional.",
        "css": {
            "fontFamily": "'Inter', 'Segoe UI', sans-serif",
            "fontSize": "18px",
            "fontWeight": "500",
            "textTransform": "none",
            "color": "#FFFFFF",
            "highlightColor": "#FFFFFF",
            "backgroundColor": "transparent",
            "textShadow": "1px 1px 2px rgba(0,0,0,0.6)",
            "position": "bottom",
            "animation": "fade",
            "maxWordsPerLine": 10,
            "lineHeight": "1.5",
        },
        "ffmpeg": {
            "fontfile": "Inter-Medium.ttf",
            "fontsize": 28,
            "fontcolor": "white",
            "borderw": 1,
            "bordercolor": "black@0.5",
            "alignment": 2,  # Bottom-center
        },
    },
    "karaoke": {
        "name": "Karaoke",
        "description": "Highlights current word being spoken",
        "css": {
            "fontFamily": "'Inter', 'Helvetica', sans-serif",
            "fontSize": "28px",
            "fontWeight": "600",
            "textTransform": "none",
            "color": "rgba(255,255,255,0.5)",
            "highlightColor": "#FFFFFF",
            "activeColor": "#00BFFF",  # Current word
            "backgroundColor": "transparent",
            "textShadow": "2px 2px 4px rgba(0,0,0,0.7)",
            "position": "bottom",
            "animation": "karaoke",
            "maxWordsPerLine": 6,
            "lineHeight": "1.4",
        },
        "ffmpeg": {
            "fontfile": "Inter-SemiBold.ttf",
            "fontsize": 36,
            "fontcolor": "white",
            "borderw": 2,
            "bordercolor": "black",
            "alignment": 2,
        },
    },
    "news": {
        "name": "News",
        "description": "Lower third with solid background",
        "css": {
            "fontFamily": "'Roboto', 'Arial', sans-serif",
            "fontSize": "20px",
            "fontWeight": "500",
            "textTransform": "none",
            "color": "#FFFFFF",
            "highlightColor": "#FFFFFF",
            "backgroundColor": "#1a1a2e",
            "textShadow": "none",
            "position": "bottom-left",
            "animation": "slide",
            "maxWordsPerLine": 12,
            "lineHeight": "1.5",
            "padding": "12px 24px",
            "borderLeft": "4px solid #e94560",
        },
        "ffmpeg": {
            "fontfile": "Roboto-Medium.ttf",
            "fontsize": 30,
            "fontcolor": "white",
            "box": 1,
            "boxcolor": "#1a1a2e",
            "boxborderw": 10,
            "alignment": 1,  # Bottom-left
        },
    },
}


class SubtitleService:
    """Service for generating and managing subtitles from Whisper transcriptions."""

    def __init__(self):
        self.db = get_database_service()

    def get_style_config(self, style: str) -> dict[str, Any]:
        """Get configuration for a subtitle style."""
        return SUBTITLE_STYLES.get(style, SUBTITLE_STYLES["hormozi"])

    def get_available_styles(self) -> list[dict[str, Any]]:
        """Get list of available subtitle styles."""
        return [
            {
                "id": key,
                "name": config["name"],
                "description": config["description"],
            }
            for key, config in SUBTITLE_STYLES.items()
        ]

    def extract_clip_transcription(
        self,
        transcription_data: dict[str, Any],
        start_time: float,
        end_time: float,
    ) -> dict[str, Any]:
        """
        Extract transcription for a specific time range (clip).
        
        Args:
            transcription_data: Full video transcription from Whisper
            start_time: Clip start in seconds
            end_time: Clip end in seconds
            
        Returns:
            Dict with words and segments for the clip range
        """
        result = {
            "text": "",
            "words": [],
            "segments": [],
            "start_time": start_time,
            "end_time": end_time,
            "duration": end_time - start_time,
        }

        transcription = transcription_data.get("transcription", transcription_data)
        
        # Extract words in range (word-level timing)
        all_words = transcription.get("words", [])
        clip_words = []
        
        for word in all_words:
            word_start = word.get("start", 0)
            word_end = word.get("end", word_start)
            
            # Word overlaps with clip range
            if word_end > start_time and word_start < end_time:
                # Adjust timing relative to clip start
                clip_words.append({
                    "word": word.get("word", "").strip(),
                    "start": max(0, word_start - start_time),
                    "end": min(end_time - start_time, word_end - start_time),
                    "original_start": word_start,
                    "original_end": word_end,
                    "confidence": word.get("probability", word.get("confidence", 1.0)),
                })
        
        result["words"] = clip_words
        result["text"] = " ".join(w["word"] for w in clip_words)

        # Extract segments in range
        all_segments = transcription.get("segments", [])
        clip_segments = []
        
        for segment in all_segments:
            seg_start = segment.get("start", 0)
            seg_end = segment.get("end", seg_start)
            
            # Segment overlaps with clip range
            if seg_end > start_time and seg_start < end_time:
                # Extract words from this segment that are in range
                seg_words = []
                for word in segment.get("words", []):
                    w_start = word.get("start", 0)
                    w_end = word.get("end", w_start)
                    if w_end > start_time and w_start < end_time:
                        seg_words.append({
                            "word": word.get("word", "").strip(),
                            "start": max(0, w_start - start_time),
                            "end": min(end_time - start_time, w_end - start_time),
                        })
                
                clip_segments.append({
                    "text": segment.get("text", "").strip(),
                    "start": max(0, seg_start - start_time),
                    "end": min(end_time - start_time, seg_end - start_time),
                    "words": seg_words,
                })
        
        result["segments"] = clip_segments

        # If no word-level timing, fall back to segments
        if not clip_words and clip_segments:
            # Estimate word timing from segment
            for segment in clip_segments:
                words = segment["text"].split()
                if not words:
                    continue
                    
                seg_duration = segment["end"] - segment["start"]
                word_duration = seg_duration / len(words) if words else 0
                
                for i, word in enumerate(words):
                    clip_words.append({
                        "word": word,
                        "start": segment["start"] + (i * word_duration),
                        "end": segment["start"] + ((i + 1) * word_duration),
                        "estimated": True,
                    })
            
            result["words"] = clip_words
            result["text"] = " ".join(w["word"] for w in clip_words)

        return result

    def generate_subtitle_cues(
        self,
        words: list[dict[str, Any]],
        style: str = "hormozi",
        max_words_per_cue: int | None = None,
        max_duration_per_cue: float = 3.0,
    ) -> list[dict[str, Any]]:
        """
        Generate subtitle cues (groups of words) for display.
        
        Different styles have different grouping strategies:
        - hormozi: 1-3 words per cue (word-by-word effect)
        - mrbeast: 3-5 words per cue (impactful chunks)
        - minimal: 6-10 words per cue (sentence-like)
        - karaoke: all words visible, highlight current
        - news: sentence-based
        
        Args:
            words: List of words with timing
            style: Subtitle style name
            max_words_per_cue: Override max words per cue
            max_duration_per_cue: Max duration for a single cue
            
        Returns:
            List of cues with start, end, text, and word highlights
        """
        style_config = self.get_style_config(style)
        css = style_config.get("css", {})
        
        if max_words_per_cue is None:
            max_words_per_cue = css.get("maxWordsPerLine", 4)
        
        cues = []
        current_cue_words = []
        current_start = None
        
        for word in words:
            if current_start is None:
                current_start = word["start"]
            
            current_cue_words.append(word)
            current_end = word["end"]
            current_duration = current_end - current_start
            
            # Check if we should end this cue
            should_end_cue = (
                len(current_cue_words) >= max_words_per_cue or
                current_duration >= max_duration_per_cue or
                word.get("word", "").endswith((".", "!", "?", ","))
            )
            
            if should_end_cue and current_cue_words:
                cues.append({
                    "id": len(cues),
                    "start": current_start,
                    "end": current_end,
                    "text": " ".join(w["word"] for w in current_cue_words),
                    "words": current_cue_words.copy(),
                })
                current_cue_words = []
                current_start = None
        
        # Add remaining words
        if current_cue_words:
            cues.append({
                "id": len(cues),
                "start": current_start,
                "end": current_cue_words[-1]["end"],
                "text": " ".join(w["word"] for w in current_cue_words),
                "words": current_cue_words,
            })
        
        return cues

    def generate_subtitles_for_clip(
        self,
        clip_id: str,
        style: str = "hormozi",
    ) -> dict[str, Any]:
        """
        Generate subtitles for a clip from the source video's transcription.
        
        Args:
            clip_id: ID of the clip
            style: Subtitle style to use
            
        Returns:
            Dict with subtitle data and metadata
        """
        try:
            # Get clip
            clip = self.db.get_clip(clip_id)
            if not clip:
                return {"error": "Clip not found", "success": False}
            
            # Get project to find source media
            project = self.db.get_editor_project(clip.project_id)
            if not project:
                return {"error": "Project not found", "success": False}
            
            # Get source media with transcription
            media = self.db.get_media(project.source_media_id)
            if not media:
                return {"error": "Source media not found", "success": False}
            
            audio_data = media.audio_data
            if not audio_data:
                return {
                    "error": "No transcription available. Process the video first.",
                    "success": False,
                }
            
            # Extract transcription for clip time range
            clip_transcription = self.extract_clip_transcription(
                audio_data,
                clip.start_time,
                clip.end_time,
            )
            
            if not clip_transcription.get("words"):
                return {
                    "error": "No words found in clip time range",
                    "success": False,
                    "clip_range": f"{clip.start_time:.2f}s - {clip.end_time:.2f}s",
                }
            
            # Generate cues based on style
            cues = self.generate_subtitle_cues(
                clip_transcription["words"],
                style=style,
            )
            
            # Get style config
            style_config = self.get_style_config(style)
            
            # Build subtitle data structure
            subtitle_data = {
                "version": "1.0",
                "style": style,
                "style_config": style_config,
                "clip_duration": clip.end_time - clip.start_time,
                "text": clip_transcription["text"],
                "word_count": len(clip_transcription["words"]),
                "cues": cues,
                "words": clip_transcription["words"],
            }
            
            # Update clip with subtitle data
            self.db.update_clip(clip_id, {
                "subtitles_enabled": True,
                "subtitle_style": style,
                "subtitles_data": subtitle_data,
                "subtitle_settings": style_config.get("css", {}),
            })
            
            return {
                "success": True,
                "message": f"Generated {len(cues)} subtitle cues with '{style_config['name']}' style",
                "clip_id": clip_id,
                "subtitle_data": subtitle_data,
                "preview_text": clip_transcription["text"][:100] + "..." if len(clip_transcription["text"]) > 100 else clip_transcription["text"],
            }
            
        except Exception as e:
            logger.error(f"Error generating subtitles: {e}")
            return {"error": str(e), "success": False}

    def update_subtitle_text(
        self,
        clip_id: str,
        cue_id: int,
        new_text: str,
    ) -> dict[str, Any]:
        """
        Update the text of a specific subtitle cue.
        
        Args:
            clip_id: ID of the clip
            cue_id: ID of the cue to update
            new_text: New text for the cue
            
        Returns:
            Updated subtitle data
        """
        try:
            clip = self.db.get_clip(clip_id)
            if not clip:
                return {"error": "Clip not found", "success": False}
            
            if not clip.subtitles_data:
                return {"error": "No subtitle data on clip", "success": False}
            
            subtitle_data = clip.subtitles_data
            cues = subtitle_data.get("cues", [])
            
            # Find and update the cue
            for cue in cues:
                if cue["id"] == cue_id:
                    old_text = cue["text"]
                    cue["text"] = new_text
                    # Update words based on new text
                    new_words = new_text.split()
                    # Keep timing, redistribute across new words
                    if cue["words"]:
                        duration = cue["end"] - cue["start"]
                        word_duration = duration / len(new_words) if new_words else 0
                        cue["words"] = [
                            {
                                "word": word,
                                "start": cue["start"] + (i * word_duration),
                                "end": cue["start"] + ((i + 1) * word_duration),
                                "edited": True,
                            }
                            for i, word in enumerate(new_words)
                        ]
                    break
            else:
                return {"error": f"Cue {cue_id} not found", "success": False}
            
            # Rebuild full text
            subtitle_data["text"] = " ".join(cue["text"] for cue in cues)
            subtitle_data["cues"] = cues
            
            # Update clip
            self.db.update_clip(clip_id, {"subtitles_data": subtitle_data})
            
            return {
                "success": True,
                "message": f"Updated cue {cue_id}",
                "old_text": old_text,
                "new_text": new_text,
            }
            
        except Exception as e:
            logger.error(f"Error updating subtitle: {e}")
            return {"error": str(e), "success": False}

    def generate_srt(self, subtitle_data: dict[str, Any], offset: float = 0) -> str:
        """
        Generate SRT format from subtitle data.
        
        Args:
            subtitle_data: Subtitle data with cues
            offset: Time offset to add (for absolute timing)
            
        Returns:
            SRT formatted string
        """
        def format_time(seconds: float) -> str:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        
        lines = []
        for i, cue in enumerate(subtitle_data.get("cues", []), 1):
            start = cue["start"] + offset
            end = cue["end"] + offset
            text = cue["text"]
            
            lines.append(str(i))
            lines.append(f"{format_time(start)} --> {format_time(end)}")
            lines.append(text)
            lines.append("")
        
        return "\n".join(lines)

    def generate_ass(
        self,
        subtitle_data: dict[str, Any],
        style: str = "hormozi",
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> str:
        """
        Generate ASS (Advanced SubStation Alpha) format for FFmpeg.
        ASS supports advanced styling and animations.
        
        Args:
            subtitle_data: Subtitle data with cues
            style: Style to apply
            video_width: Video width for positioning
            video_height: Video height for positioning
            
        Returns:
            ASS formatted string
        """
        style_config = self.get_style_config(style)
        ffmpeg_config = style_config.get("ffmpeg", {})
        
        # ASS header
        ass = f"""[Script Info]
Title: QPrisma Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{ffmpeg_config.get('fontfile', 'Arial')},{ffmpeg_config.get('fontsize', 40)},&HFFFFFF,&HFFFFFF,&H000000,&H80000000,-1,0,0,0,100,100,0,0,1,{ffmpeg_config.get('borderw', 2)},0,{ffmpeg_config.get('alignment', 2)},10,10,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        def format_time(seconds: float) -> str:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = seconds % 60
            return f"{hours}:{minutes:02d}:{secs:05.2f}"
        
        for cue in subtitle_data.get("cues", []):
            start = format_time(cue["start"])
            end = format_time(cue["end"])
            text = cue["text"].replace("\n", "\\N")
            
            ass += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"
        
        return ass


# Singleton instance
_subtitle_service: SubtitleService | None = None


def get_subtitle_service() -> SubtitleService:
    """Get or create the subtitle service singleton."""
    global _subtitle_service
    if _subtitle_service is None:
        _subtitle_service = SubtitleService()
    return _subtitle_service
