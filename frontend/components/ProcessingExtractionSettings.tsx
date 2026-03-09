'use client';

import React, { useState } from 'react';
import { Scissors } from 'lucide-react';

interface ProcessingPreset {
  name: string;
  description?: string;
  fps?: number;
  max_frames?: number;
}

interface ExtractionSettingsProps {
  selectedPreset: string;
  onPresetChange: (preset: string) => void;
  presets: ProcessingPreset[];
  onConfigChange?: (config: { maxFrames: number }) => void;
}

export function ExtractionSettings({
  selectedPreset,
  onPresetChange,
  presets,
  onConfigChange,
}: ExtractionSettingsProps) {
  const [extractionMethod, setExtractionMethod] = useState('fps');
  const [fps, setFps] = useState(1.0);
  const [maxFrames, setMaxFrames] = useState(100);
  const [intervalSeconds, setIntervalSeconds] = useState(5.0);
  const [numFrames, setNumFrames] = useState(10);
  const [sceneThreshold, setSceneThreshold] = useState(0.4);
  const [hybridSceneRatio, setHybridSceneRatio] = useState(0.6);
  const [hybridMinGap, setHybridMinGap] = useState(15.0);

  const currentPreset = presets.find(p => p.name === selectedPreset);

  return (
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
  );
}
