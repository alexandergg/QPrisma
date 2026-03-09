'use client';

import React from 'react';
import type { GraphNode } from '@/types';

interface NodeDetailPanelProps {
  selectedNode: GraphNode;
  onSeek?: (time: number) => void;
}

export function NodeDetailPanel({ selectedNode, onSeek }: NodeDetailPanelProps) {
  return (
    <div className="absolute top-2 right-2 w-56 bg-white/95 backdrop-blur rounded-lg shadow-lg border border-gray-200 p-3 text-xs">
      <div className="flex items-center gap-2 mb-2">
        <div
          className="w-3 h-3 rounded-full shrink-0"
          style={{ backgroundColor: selectedNode.color }}
        />
        <span className="font-semibold text-gray-900 truncate">
          {selectedNode.caption}
        </span>
      </div>
      <div className="space-y-1 text-gray-500">
        <p>
          <span className="text-gray-700 font-medium">Type:</span>{' '}
          {selectedNode.node_type}
          {selectedNode.entity_type ? ` (${selectedNode.entity_type})` : ''}
        </p>
        {selectedNode.properties.description != null && (
          <p className="line-clamp-3">
            {String(selectedNode.properties.description)}
          </p>
        )}
        {selectedNode.properties.timestamp != null && (
          <p>
            <span className="text-gray-700 font-medium">Time:</span>{' '}
            {Number(selectedNode.properties.timestamp).toFixed(1)}s
          </p>
        )}
        {selectedNode.properties.start_time != null && (
          <p>
            <span className="text-gray-700 font-medium">Range:</span>{' '}
            {Number(selectedNode.properties.start_time).toFixed(1)}s –{' '}
            {Number(selectedNode.properties.end_time).toFixed(1)}s
          </p>
        )}
      </div>
      {onSeek && selectedNode.properties.timestamp != null && (
        <button
          onClick={() => onSeek(Number(selectedNode.properties.timestamp))}
          className="mt-2 w-full text-center text-indigo-600 hover:text-indigo-700 font-medium"
        >
          Seek to timestamp →
        </button>
      )}
      {onSeek && selectedNode.properties.start_time != null && !selectedNode.properties.timestamp && (
        <button
          onClick={() => onSeek(Number(selectedNode.properties.start_time))}
          className="mt-2 w-full text-center text-indigo-600 hover:text-indigo-700 font-medium"
        >
          Seek to start →
        </button>
      )}
    </div>
  );
}
