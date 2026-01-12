'use client';

import React, { useState } from 'react';
import { Settings, Sliders, Image, Film, Zap, Scissors } from 'lucide-react';

interface ProcessingConfigProps {
  selectedPreset: string;
  onPresetChange: (preset: string) => void;
  presets: any[];
  onConfigChange?: (config: { maxFrames: number }) => void;
}

export default function ProcessingConfig({
  selectedPreset,
  onPresetChange,
  presets,
  onConfigChange,
}: ProcessingConfigProps) {
  const [extractionMethod, setExtractionMethod] = useState('fps');
  const [fps, setFps] = useState(1.0);
  const [maxFrames, setMaxFrames] = useState(100);
  const [intervalSeconds, setIntervalSeconds] = useState(5.0);
  const [numFrames, setNumFrames] = useState(10);
  const [sceneThreshold, setSceneThreshold] = useState(0.4);
  const [hybridSceneRatio, setHybridSceneRatio] = useState(0.6);
  const [hybridMinGap, setHybridMinGap] = useState(15.0);
  
  const [scaleWidth, setScaleWidth] = useState<number | null>(null);
  const [scaleHeight, setScaleHeight] = useState<number | null>(null);
  const [scalingFilter, setScalingFilter] = useState('lanczos');
  const [pixelFormat, setPixelFormat] = useState('yuv420p');
  
  const [deinterlace, setDeinterlace] = useState(false);
  const [hdrToSdr, setHdrToSdr] = useState(false);

  const currentPreset = presets.find(p => p.name === selectedPreset);

  return (
    <div className="p-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column: Extraction Settings */}
        <div className="space-y-6">
          <div>
            <h2 className="text-2xl font-bold text-white mb-4 flex items-center gap-2">
              <Scissors className="w-6 h-6 text-purple-400" />
              Extracción de Frames
            </h2>
          </div>

          {/* Preset Selector */}
          <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800">
            <label className="block text-sm font-medium text-zinc-300 mb-2">
              Preset Predefinido
            </label>
            <select
              value={selectedPreset}
              onChange={(e) => onPresetChange(e.target.value)}
              className="w-full px-4 py-2 bg-black text-white rounded-lg border border-zinc-700 focus:border-white focus:outline-none"
            >
              <option value="">Custom</option>
              {presets.map((preset) => (
                <option key={preset.name} value={preset.name}>
                  {preset.name.replace(/_/g, ' ').toUpperCase()}
                </option>
              ))}
            </select>
            {currentPreset && (
              <p className="mt-2 text-xs text-zinc-400">
                {currentPreset.description}
              </p>
            )}
          </div>

          {/* Extraction Method */}
          <div className="bg-zinc-900 rounded-lg p-4 border border-zinc-800">
            <label className="block text-sm font-medium text-zinc-300 mb-2">
              Método de Extracción
            </label>
            <select
              value={extractionMethod}
              onChange={(e) => setExtractionMethod(e.target.value)}
              className="w-full px-4 py-2 bg-black text-white rounded-lg border border-zinc-700 focus:border-white focus:outline-none mb-4"
            >
              <option value="fps">FPS - Frames por segundo</option>
              <option value="interval">INTERVAL - Intervalo de tiempo</option>
              <option value="uniform">UNIFORM - Distribución uniforme</option>
              <option value="keyframes">KEYFRAMES - Solo keyframes</option>
              <option value="scene_detect">SCENE DETECT - Detección de escenas</option>
              <option value="adaptive">ADAPTIVE - Automático según duración</option>
              <option value="hybrid">HYBRID - Escenas + Relleno uniforme</option>
            </select>

            {/* Conditional Parameters */}
            {extractionMethod === 'fps' && (
              <div>
                <label className="block text-sm text-zinc-400 mb-1">
                  FPS: {fps}
                </label>
                <input
                  type="range"
                  min="0.1"
                  max="10"
                  step="0.1"
                  value={fps}
                  onChange={(e) => setFps(parseFloat(e.target.value))}
                  className="w-full"
                />
              </div>
            )}

            {extractionMethod === 'interval' && (
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Intervalo (segundos): {intervalSeconds}
                </label>
                <input
                  type="range"
                  min="1"
                  max="30"
                  step="0.5"
                  value={intervalSeconds}
                  onChange={(e) => setIntervalSeconds(parseFloat(e.target.value))}
                  className="w-full"
                />
              </div>
            )}

            {extractionMethod === 'uniform' && (
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Número de Frames: {numFrames}
                </label>
                <input
                  type="range"
                  min="5"
                  max="100"
                  step="5"
                  value={numFrames}
                  onChange={(e) => setNumFrames(parseInt(e.target.value))}
                  className="w-full"
                />
              </div>
            )}

            {extractionMethod === 'scene_detect' && (
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Umbral de Detección: {sceneThreshold}
                </label>
                <input
                  type="range"
                  min="0.1"
                  max="1"
                  step="0.05"
                  value={sceneThreshold}
                  onChange={(e) => setSceneThreshold(parseFloat(e.target.value))}
                  className="w-full"
                />
              </div>
            )}

            {extractionMethod === 'adaptive' && (
              <div className="p-3 bg-zinc-800 rounded-lg">
                <p className="text-sm text-emerald-400 mb-2">
                  ✨ Configuración automática según duración del video
                </p>
                <ul className="text-xs text-zinc-400 space-y-1">
                  <li>• &lt;5 min: Alta densidad (150 frames)</li>
                  <li>• 5-30 min: Balanceado (400 frames)</li>
                  <li>• 30-60 min: Híbrido (600 frames)</li>
                  <li>• 1-2 hrs: Híbrido extendido (800 frames)</li>
                  <li>• &gt;2 hrs: Máxima cobertura (1000 frames)</li>
                </ul>
              </div>
            )}

            {extractionMethod === 'hybrid' && (
              <div className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">
                    Umbral de Escena: {sceneThreshold}
                  </label>
                  <input
                    type="range"
                    min="0.1"
                    max="0.8"
                    step="0.05"
                    value={sceneThreshold}
                    onChange={(e) => setSceneThreshold(parseFloat(e.target.value))}
                    className="w-full"
                  />
                  <p className="text-xs text-zinc-500 mt-1">
                    Menor = más sensible a cambios
                  </p>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">
                    Ratio Escenas/Relleno: {Math.round(hybridSceneRatio * 100)}% escenas
                  </label>
                  <input
                    type="range"
                    min="0.3"
                    max="0.8"
                    step="0.1"
                    value={hybridSceneRatio}
                    onChange={(e) => setHybridSceneRatio(parseFloat(e.target.value))}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">
                    Gap mínimo para relleno: {hybridMinGap}s
                  </label>
                  <input
                    type="range"
                    min="5"
                    max="60"
                    step="5"
                    value={hybridMinGap}
                    onChange={(e) => setHybridMinGap(parseFloat(e.target.value))}
                    className="w-full"
                  />
                  <p className="text-xs text-zinc-500 mt-1">
                    Inserta frames uniformes si hay gaps mayores a este valor
                  </p>
                </div>
              </div>
            )}

            <div className="mt-4">
              <label className="block text-sm text-gray-400 mb-1">
                Máximo de Frames: {maxFrames}
              </label>
              <input
                type="range"
                min="10"
                max="2000"
                step="10"
                value={maxFrames}
                onChange={(e) => {
                  const newMax = parseInt(e.target.value);
                  setMaxFrames(newMax);
                  if (onConfigChange) {
                    onConfigChange({ maxFrames: newMax });
                  }
                }}
                className="w-full"
              />
            </div>
          </div>
        </div>

        {/* Right Column: Video Filters */}
        <div className="space-y-6">
          <div>
            <h2 className="text-2xl font-bold text-white mb-4 flex items-center gap-2">
              <Sliders className="w-6 h-6 text-pink-400" />
              Filtros de Video
            </h2>
          </div>

          {/* Resolution */}
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-700">
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Resolución de Salida
            </label>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Ancho</label>
                <input
                  type="number"
                  placeholder="Auto"
                  value={scaleWidth || ''}
                  onChange={(e) => setScaleWidth(e.target.value ? parseInt(e.target.value) : null)}
                  className="w-full px-3 py-2 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Alto</label>
                <input
                  type="number"
                  placeholder="Auto"
                  value={scaleHeight || ''}
                  onChange={(e) => setScaleHeight(e.target.value ? parseInt(e.target.value) : null)}
                  className="w-full px-3 py-2 bg-gray-800 text-white rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
            
            <div className="mt-4 grid grid-cols-3 gap-2">
              <button
                onClick={() => { setScaleWidth(1920); setScaleHeight(1080); }}
                className="px-3 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded text-xs"
              >
                1080p
              </button>
              <button
                onClick={() => { setScaleWidth(1280); setScaleHeight(720); }}
                className="px-3 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded text-xs"
              >
                720p
              </button>
              <button
                onClick={() => { setScaleWidth(640); setScaleHeight(360); }}
                className="px-3 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded text-xs"
              >
                360p
              </button>
            </div>
          </div>

          {/* Scaling Filter */}
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-700">
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Algoritmo de Escalado
            </label>
            <select
              value={scalingFilter}
              onChange={(e) => setScalingFilter(e.target.value)}
              className="w-full px-4 py-2 bg-gray-800 text-white rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none"
            >
              <option value="lanczos">Lanczos (Alta calidad)</option>
              <option value="bicubic">Bicubic (Balance)</option>
              <option value="bilinear">Bilinear (Rápido)</option>
              <option value="spline36">Spline36 (Muy alta calidad)</option>
              <option value="neighbor">Neighbor (Más rápido)</option>
            </select>
          </div>

          {/* Pixel Format */}
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-700">
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Formato de Píxel
            </label>
            <select
              value={pixelFormat}
              onChange={(e) => setPixelFormat(e.target.value)}
              className="w-full px-4 py-2 bg-gray-800 text-white rounded-lg border border-gray-700 focus:border-blue-500 focus:outline-none"
            >
              <option value="yuv420p">YUV420P (8-bit)</option>
              <option value="yuv420p10le">YUV420P10LE (10-bit)</option>
              <option value="yuv422p">YUV422P</option>
              <option value="rgb24">RGB24</option>
              <option value="rgba">RGBA</option>
            </select>
          </div>

          {/* Special Filters */}
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-700">
            <label className="block text-sm font-medium text-gray-300 mb-3">
              Filtros Especiales
            </label>
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={deinterlace}
                  onChange={(e) => setDeinterlace(e.target.checked)}
                  className="w-4 h-4 text-blue-600 bg-gray-800 border-gray-700 rounded focus:ring-blue-500"
                />
                Desentrelazado (Yadif)
              </label>
              
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={hdrToSdr}
                  onChange={(e) => setHdrToSdr(e.target.checked)}
                  className="w-4 h-4 text-blue-600 bg-gray-800 border-gray-700 rounded focus:ring-blue-500"
                />
                Convertir HDR a SDR
              </label>
            </div>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="mt-6 flex gap-4 justify-end">
        <button className="px-6 py-3 bg-gray-700 hover:bg-gray-600 text-white rounded-lg font-medium transition-colors">
          Resetear
        </button>
        <button className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors flex items-center gap-2">
          <Zap className="w-5 h-5" />
          Aplicar Configuración
        </button>
      </div>
    </div>
  );
}
