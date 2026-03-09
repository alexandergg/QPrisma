'use client';

import React from 'react';
import {
  Download,
  CheckCircle,
  AlertCircle,
  ExternalLink,
} from 'lucide-react';
import { ExportResult, ExportEstimate } from '@/lib/api';
import { formatFileSizeMB as formatFileSize } from '@/lib/utils';

interface ExportResultDisplayProps {
  exportResult: ExportResult | ExportResult[];
  estimate: ExportEstimate | null;
  error: string | null;
}

export function ExportResultDisplay({
  exportResult,
  estimate,
  error,
}: ExportResultDisplayProps) {
  return (
    <>
      {/* Single export result */}
      {!Array.isArray(exportResult) && exportResult.success && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4">
          <div className="flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-medium text-green-900">Export complete!</p>
              <p className="text-sm text-green-700 mt-1">
                {estimate && `${formatFileSize(estimate.estimated_size_mb)} exported`}
              </p>
              {exportResult.output_url && (
                <a
                  href={exportResult.output_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 mt-2 text-sm font-medium text-green-700 hover:text-green-800"
                >
                  <Download className="w-4 h-4" />
                  Download Video
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Batch export results */}
      {Array.isArray(exportResult) && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4">
          <div className="flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-medium text-green-900">
                Exported {exportResult.filter(r => r.success).length} of {exportResult.length} clips
              </p>
              <div className="mt-2 space-y-1 max-h-32 overflow-y-auto">
                {exportResult.map((r, i) => (
                  <div key={r.clip_id} className="flex items-center justify-between text-sm">
                    <span className="text-green-700">Clip {i + 1}</span>
                    {r.output_url && (
                      <a
                        href={r.output_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-green-600 hover:text-green-800"
                      >
                        <Download className="w-4 h-4" />
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-red-900">Export failed</p>
              <p className="text-sm text-red-700 mt-1">{error}</p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
