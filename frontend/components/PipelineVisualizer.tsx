'use client';

import React, { useCallback, useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  Position,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Film, Scissors, Palette, Bot, Database, Search } from 'lucide-react';

interface PipelineNodeDetails {
  fps?: number;
  maxFrames?: number;
  resolution?: string;
  preset?: string;
  [key: string]: string | number | boolean | undefined;
}

interface PipelineNodeData {
  label: string;
  icon: string;
  description: string;
  details?: PipelineNodeDetails;
}

interface PipelineNode {
  id: string;
  type: string;
  data: PipelineNodeData;
  position: { x: number; y: number };
}

interface PipelineConfig {
  name?: string;
  preset?: string;
  [key: string]: string | number | boolean | undefined;
}

interface PipelineVisualizerProps {
  data: {
    nodes: PipelineNode[];
    edges: Array<{ id: string; source: string; target: string }>;
    config: PipelineConfig;
  };
}

// Custom Node Components
const CustomNode = ({ data }: { data: PipelineNodeData }) => {
  const getIcon = (icon: string) => {
    const iconMap: Record<string, React.ReactNode> = {
      '📹': <Film className="w-6 h-6" />,
      '🎞️': <Scissors className="w-6 h-6" />,
      '🎨': <Palette className="w-6 h-6" />,
      '🤖': <Bot className="w-6 h-6" />,
      '🧮': <Database className="w-6 h-6" />,
      '🔍': <Search className="w-6 h-6" />,
      '💾': <Database className="w-6 h-6" />,
    };
    return iconMap[icon] || <Film className="w-6 h-6" />;
  };

  const getColorClass = (label: string) => {
    if (label.includes('Input')) return 'from-blue-500 to-blue-600';
    if (label.includes('Extraction')) return 'from-purple-500 to-purple-600';
    if (label.includes('Filter')) return 'from-pink-500 to-pink-600';
    if (label.includes('GPT') || label.includes('Analysis')) return 'from-green-500 to-green-600';
    if (label.includes('Embedding')) return 'from-yellow-500 to-yellow-600';
    if (label.includes('Search')) return 'from-red-500 to-red-600';
    if (label.includes('Cosmos')) return 'from-indigo-500 to-indigo-600';
    return 'from-gray-500 to-gray-600';
  };

  return (
    <div className="px-4 py-3 shadow-lg rounded-lg bg-zinc-900 border border-zinc-800 min-w-[200px]">
      <div className="flex items-center gap-3 mb-2">
        <div className={`p-2 rounded-lg bg-gradient-to-br ${getColorClass(data.label)} text-white`}>
          {getIcon(data.icon)}
        </div>
        <div className="flex-1">
          <div className="font-bold text-white text-sm">{data.label}</div>
          <div className="text-xs text-zinc-400">{data.description}</div>
        </div>
      </div>
      
      {data.details && (
        <div className="mt-2 pt-2 border-t border-zinc-800">
          <div className="text-xs text-zinc-400 space-y-1">
            {Object.entries(data.details).map(([key, value]) => {
              if (value === null || value === undefined) return null;
              return (
                <div key={key} className="flex justify-between">
                  <span className="capitalize">{key.replace(/_/g, ' ')}:</span>
                  <span className="text-zinc-300 font-mono">
                    {Array.isArray(value) ? value.join(', ') : String(value)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

const nodeTypes = {
  input: CustomNode,
  process: CustomNode,
  output: CustomNode,
};

export default function PipelineVisualizer({ data }: PipelineVisualizerProps) {
  // Transform data to ReactFlow format
  const initialNodes: Node[] = useMemo(() => {
    return data.nodes.map((node) => ({
      id: node.id,
      type: node.type,
      data: node.data,
      position: node.position,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    }));
  }, [data.nodes]);

  const initialEdges: Edge[] = useMemo(() => {
    return data.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      animated: true,
      style: { stroke: '#60a5fa', strokeWidth: 2 },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#60a5fa',
      },
    }));
  }, [data.edges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Auto-layout nodes
  useCallback(() => {
    const layoutNodes = () => {
      const levels: Record<string, string[]> = {};
      
      // Group nodes by their Y position (level)
      initialNodes.forEach((node) => {
        const level = node.position.y;
        if (!levels[level]) levels[level] = [];
        levels[level].push(node.id);
      });

      // Distribute nodes horizontally within each level
      const newNodes = initialNodes.map((node) => {
        const level = node.position.y;
        const nodesInLevel = levels[level];
        const index = nodesInLevel.indexOf(node.id);
        const spacing = 350;
        const startX = 100 + (nodesInLevel.length - 1) * spacing / 2;
        
        return {
          ...node,
          position: {
            x: startX + index * spacing - (nodesInLevel.length - 1) * spacing / 2,
            y: level,
          },
        };
      });

      setNodes(newNodes);
    };

    layoutNodes();
  }, [initialNodes, setNodes]);

  return (
    <div className="w-full h-[600px] bg-gray-900 rounded-lg overflow-hidden border border-gray-700">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-left"
      >
        <Background color="#374151" gap={16} />
        <Controls className="bg-gray-800 border-gray-700" />
        <MiniMap
          nodeColor={(node) => {
            if (node.type === 'input') return '#3b82f6';
            if (node.type === 'output') return '#ef4444';
            return '#8b5cf6';
          }}
          className="bg-gray-800 border-gray-700"
        />
      </ReactFlow>

      {/* Config Summary */}
      <div className="absolute bottom-4 left-4 bg-gray-800 border border-gray-700 rounded-lg p-4 max-w-md">
        <h3 className="text-sm font-bold text-white mb-2">Configuración Activa</h3>
        <div className="text-xs text-gray-400 space-y-1">
          <div>
            <span className="text-gray-500">Método:</span>{' '}
            <span className="text-blue-400">{data.config?.frame_extraction?.method}</span>
          </div>
          <div>
            <span className="text-gray-500">Max Frames:</span>{' '}
            <span className="text-blue-400">{data.config?.frame_extraction?.max_frames}</span>
          </div>
          {data.config?.frame_extraction?.fps && (
            <div>
              <span className="text-gray-500">FPS:</span>{' '}
              <span className="text-blue-400">{data.config.frame_extraction.fps}</span>
            </div>
          )}
          {data.config?.video_filters?.scale_width && (
            <div>
              <span className="text-gray-500">Resolución:</span>{' '}
              <span className="text-blue-400">
                {data.config.video_filters.scale_width}x{data.config.video_filters.scale_height}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
