'use client';

import React, { useState, useEffect } from 'react';
import { Film, Loader2 } from 'lucide-react';
import { apiClient, EditorProject } from '@/lib/api';

interface NewProjectModalProps {
  onClose: () => void;
  onCreated: (project: EditorProject) => void;
}

interface ProjectVideoSummary {
  id: string;
  original_filename?: string;
  filename?: string;
  name?: string;
  duration?: number;
}

export function NewProjectModal({ onClose, onCreated }: NewProjectModalProps) {
  const [videos, setVideos] = useState<ProjectVideoSummary[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState<string>('');
  const [projectName, setProjectName] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    fetchVideos();
  }, []);

  const fetchVideos = async () => {
    try {
      const data = await apiClient.getMedia();
      setVideos(data.media || []);
    } catch (err) {
      console.error('Failed to fetch videos:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!selectedVideoId) return;

    setIsCreating(true);
    try {
      // Generate a default name if not provided
      const selectedVideo = videos.find((v) => v.id === selectedVideoId);
      const defaultName = selectedVideo?.original_filename 
        ? `Clips - ${selectedVideo.original_filename.replace(/\.[^/.]+$/, '')}`
        : `New Project ${new Date().toLocaleDateString()}`;
      
      const project = await apiClient.createEditorProject(
        selectedVideoId,
        projectName.trim() || defaultName
      );
      onCreated(project);
    } catch (err) {
      console.error('Failed to create project:', err);
      alert('Failed to create project');
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[80vh] overflow-hidden">
        <div className="p-6 border-b border-gray-100">
          <h2 className="text-xl font-bold text-gray-900">New Editor Project</h2>
          <p className="text-gray-500 text-sm mt-1">
            Select a video to create clips from
          </p>
        </div>

        <div className="p-6 space-y-4 overflow-y-auto max-h-[50vh]">
          {/* Project Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Project Name (optional)
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="My Awesome Clips"
              className="w-full px-4 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {/* Video Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Select Source Video
            </label>
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 text-indigo-500 animate-spin" />
              </div>
            ) : videos.length === 0 ? (
              <div className="text-center py-8">
                <Film className="w-10 h-10 text-gray-300 mx-auto mb-2" />
                <p className="text-gray-500 text-sm">
                  No videos in your library. Upload a video first.
                </p>
              </div>
            ) : (
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {videos.map((video) => (
                  <button
                    key={video.id}
                    onClick={() => setSelectedVideoId(video.id)}
                    className={`w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left ${
                      selectedVideoId === video.id
                        ? 'border-indigo-500 bg-indigo-50'
                        : 'border-gray-200 hover:border-indigo-300'
                    }`}
                  >
                    <div className="w-16 h-10 bg-gray-100 rounded flex items-center justify-center flex-shrink-0">
                      <Film className="w-5 h-5 text-gray-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-gray-900 truncate">
                        {video.filename || video.name}
                      </p>
                      {video.duration && (
                        <p className="text-xs text-gray-500">
                          {Math.floor(video.duration / 60)}:{String(Math.floor(video.duration % 60)).padStart(2, '0')}
                        </p>
                      )}
                    </div>
                    {selectedVideoId === video.id && (
                      <div className="w-5 h-5 bg-indigo-500 rounded-full flex items-center justify-center">
                        <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                        </svg>
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="p-6 border-t border-gray-100 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!selectedVideoId || isCreating}
            className="px-4 py-2 bg-gradient-to-r from-indigo-500 to-purple-600 text-white font-medium rounded-lg hover:from-indigo-600 hover:to-purple-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isCreating ? (
              <span className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Creating...
              </span>
            ) : (
              'Create Project'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
