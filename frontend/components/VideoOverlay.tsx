import React, { useMemo } from 'react';

interface Detection {
  label: string;
  box: number[]; // [x1, y1, x2, y2] normalized 0-1
  confidence?: number;
}

interface Point {
  label: string;
  point: { x: number; y: number }; // normalized 0-1
}

interface FrameAnalysis {
  frame_number: number;
  timestamp: number;
  caption: string;
  detections: Detection[];
  points: Point[];
  segmentation: any[];
}

interface VideoOverlayProps {
  frames: FrameAnalysis[];
  currentTime: number;
  width: number;
  height: number;
  showDetections?: boolean;
  showPoints?: boolean;
  showCaptions?: boolean;
  magicMasks?: any[]; // New prop for Magic Tool masks
}

export default function VideoOverlay({
  frames,
  currentTime,
  width,
  height,
  showDetections = true,
  showPoints = true,
  showCaptions = true,
  magicMasks = []
}: VideoOverlayProps) {
  
  // Find the closest frame analysis
  const activeFrame = useMemo(() => {
    if (!frames || frames.length === 0) return null;
    
    // Find frame with closest timestamp
    // Assuming frames are sorted by timestamp
    // Simple linear search is fine for < 1000 frames, otherwise binary search
    let closest = frames[0];
    let minDiff = Math.abs(frames[0].timestamp - currentTime);
    
    for (let i = 1; i < frames.length; i++) {
      const diff = Math.abs(frames[i].timestamp - currentTime);
      if (diff < minDiff) {
        minDiff = diff;
        closest = frames[i];
      }
    }
    
    // Only show if within 1 second (or frame interval)
    if (minDiff > 1.0) return null;
    
    return closest;
  }, [frames, currentTime]);

  return (
    <div 
      className="absolute inset-0 pointer-events-none overflow-hidden"
      style={{ width, height }}
    >
      {/* Magic Tool Layer (SAM Masks) */}
      {magicMasks.length > 0 && (
        <svg className="absolute inset-0 w-full h-full" viewBox={`0 0 ${width} ${height}`}>
          {magicMasks.map((mask, idx) => (
            <polygon
              key={`magic-${idx}`}
              points={mask.polygon.map((p: number[]) => `${p[0] * width},${p[1] * height}`).join(' ')}
              fill="rgba(139, 92, 246, 0.3)" // Violet-500 with opacity
              stroke="#8b5cf6"
              strokeWidth="2"
            />
          ))}
        </svg>
      )}

      {activeFrame && (
        <>
          {/* Detections Layer */}
          {showDetections && activeFrame.detections?.map((det, idx) => {
            const [x1, y1, x2, y2] = det.box;
            return (
              <div
                key={`det-${idx}`}
                className="absolute border-2 border-[#276EF1] bg-[#276EF1]/10 transition-all duration-75"
                style={{
                  left: x1 * width,
                  top: y1 * height,
                  width: (x2 - x1) * width,
                  height: (y2 - y1) * height,
                }}
              >
                <div className="absolute -top-8 left-0 bg-[#276EF1] text-white text-xs px-3 py-1 rounded-full shadow-lg whitespace-nowrap flex items-center gap-2">
                  <span className="font-bold uppercase tracking-wider">{det.label}</span>
                </div>
              </div>
            );
          })}

          {/* Points Layer */}
          {showPoints && activeFrame.points?.map((pt, idx) => (
            <div
              key={`pt-${idx}`}
              className="absolute w-4 h-4 bg-red-500 rounded-full border-2 border-white shadow-lg transform -translate-x-1/2 -translate-y-1/2 transition-all duration-75"
              style={{
                left: pt.point.x * width,
                top: pt.point.y * height,
              }}
            >
              <div className="absolute top-5 left-1/2 -translate-x-1/2 bg-black/80 text-white text-[10px] px-2 py-0.5 rounded whitespace-nowrap">
                {pt.label}
              </div>
            </div>
          ))}

          {/* Caption Layer */}
          {showCaptions && activeFrame.caption && (
            <div className="absolute bottom-8 left-0 right-0 flex justify-center">
              <div className="bg-black/70 backdrop-blur-md text-white px-6 py-3 rounded-full text-sm font-medium shadow-2xl max-w-[80%] text-center border border-white/10">
                {activeFrame.caption}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
