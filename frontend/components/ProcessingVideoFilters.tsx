'use client';

import React, { useState } from 'react';
import { Sliders } from 'lucide-react';

export function VideoFilterSettings() {
  const [scaleWidth, setScaleWidth] = useState<number | null>(null);
  const [scaleHeight, setScaleHeight] = useState<number | null>(null);
  const [scalingFilter, setScalingFilter] = useState('lanczos');
  const [pixelFormat, setPixelFormat] = useState('yuv420p');
  const [deinterlace, setDeinterlace] = useState(false);
  const [hdrToSdr, setHdrToSdr] = useState(false);

  return (
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
  );
}
