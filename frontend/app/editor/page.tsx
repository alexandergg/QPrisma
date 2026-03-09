'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import {
  Plus,
  Film,
  Scissors,
  Trash2,
  Clock,
  FolderOpen,
  Search,
  Loader2,
} from 'lucide-react';
import { apiClient, EditorProject } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import RequireAuth from '@/components/RequireAuth';
import { NewProjectModal } from './NewProjectModal';

/**
 * Editor projects list page
 */
export default function EditorPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<EditorProject[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showNewProjectModal, setShowNewProjectModal] = useState(false);

  // Fetch projects on mount
  useEffect(() => {
    fetchProjects();
  }, []);

  const fetchProjects = async () => {
    try {
      setIsLoading(true);
      const data = await apiClient.getEditorProjects();
      setProjects(data);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch projects:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch projects');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteProject = async (projectId: string) => {
    if (!confirm('Are you sure you want to delete this project?')) return;

    try {
      await apiClient.deleteEditorProject(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
    } catch (err) {
      console.error('Failed to delete project:', err);
      alert('Failed to delete project');
    }
  };

  const filteredProjects = projects.filter((p) =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'draft':
        return <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full text-xs">Draft</span>;
      case 'exporting':
        return <span className="px-2 py-0.5 bg-blue-100 text-blue-600 rounded-full text-xs animate-pulse">Exporting</span>;
      case 'completed':
        return <span className="px-2 py-0.5 bg-green-100 text-green-600 rounded-full text-xs">Completed</span>;
      default:
        return null;
    }
  };

  return (
    <RequireAuth>
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-indigo-50/30">
        {/* Decorative Background */}
        <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
          <div className="absolute -top-40 -right-40 w-80 h-80 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl"></div>
          <div className="absolute top-1/2 -left-40 w-80 h-80 bg-gradient-to-br from-blue-200/30 to-cyan-200/30 rounded-full blur-3xl"></div>
        </div>

        <div className="relative z-10 max-w-6xl mx-auto px-4 py-8">
          {/* Header */}
          <div className="flex items-center justify-between mb-8">
            <div className="flex items-center gap-3">
              <div className="p-3 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl">
                <Scissors className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900">Video Editor</h1>
                <p className="text-gray-500">Create clips with Chat-to-Edit</p>
              </div>
            </div>

            <button
              onClick={() => setShowNewProjectModal(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-indigo-500 to-purple-600 text-white font-medium rounded-xl hover:from-indigo-600 hover:to-purple-700 transition-all shadow-lg shadow-indigo-500/25"
            >
              <Plus className="w-5 h-5" />
              New Project
            </button>
          </div>

          {/* Search */}
          <div className="relative mb-6">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
            <input
              type="text"
              placeholder="Search projects..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-12 pr-4 py-3 bg-white border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>

          {/* Content */}
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="w-8 h-8 text-indigo-500 animate-spin mb-3" />
              <p className="text-gray-500">Loading projects...</p>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center py-16">
              <p className="text-red-500 mb-4">{error}</p>
              <button
                onClick={fetchProjects}
                className="px-4 py-2 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 transition-colors"
              >
                Try Again
              </button>
            </div>
          ) : filteredProjects.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-20 h-20 bg-gray-100 rounded-full flex items-center justify-center mb-4">
                <FolderOpen className="w-10 h-10 text-gray-400" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900 mb-2">
                {searchQuery ? 'No projects found' : 'No projects yet'}
              </h3>
              <p className="text-gray-500 mb-6 max-w-md">
                {searchQuery
                  ? 'Try a different search term'
                  : 'Create your first project to start editing videos with AI'}
              </p>
              {!searchQuery && (
                <button
                  onClick={() => setShowNewProjectModal(true)}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-indigo-500 to-purple-600 text-white font-medium rounded-xl hover:from-indigo-600 hover:to-purple-700 transition-all"
                >
                  <Plus className="w-5 h-5" />
                  Create Project
                </button>
              )}
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filteredProjects.map((project) => (
                <div
                  key={project.id}
                  onClick={() => router.push(`/editor/${project.id}`)}
                  className="group bg-white rounded-xl border border-gray-200 p-4 hover:border-indigo-300 hover:shadow-lg hover:shadow-indigo-500/10 transition-all cursor-pointer"
                >
                  {/* Project Thumbnail Placeholder */}
                  <div className="aspect-video bg-gradient-to-br from-gray-100 to-gray-50 rounded-lg mb-4 flex items-center justify-center">
                    <Film className="w-12 h-12 text-gray-300" />
                  </div>

                  {/* Project Info */}
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-gray-900 truncate group-hover:text-indigo-600 transition-colors">
                        {project.name}
                      </h3>
                      <div className="flex items-center gap-2 mt-1 text-sm text-gray-500">
                        <Clock className="w-3.5 h-3.5" />
                        {formatDate(project.updated_at)}
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-2">
                      {getStatusBadge(project.status)}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteProject(project.id);
                        }}
                        className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
                        title="Delete project"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* New Project Modal */}
        {showNewProjectModal && (
          <NewProjectModal
            onClose={() => setShowNewProjectModal(false)}
            onCreated={(project) => {
              setShowNewProjectModal(false);
              router.push(`/editor/${project.id}`);
            }}
          />
        )}
      </div>
    </RequireAuth>
  );
}
