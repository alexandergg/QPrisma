import React from 'react';
import { render, screen } from '@testing-library/react';
import { VideoListItem } from './VideoListItem';
import type { MediaItem } from '@/lib/api';

const video: MediaItem = {
  id: 'video-1',
  original_filename: 'Product demo.mp4',
  file_size: 1048576,
  uploaded_at: '2024-06-15T12:00:00Z',
  processed: true,
  processing_status: 'completed',
  duration: 125,
  frames_analyzed: 42,
  thumbnail_url: 'https://example.test/thumb.jpg',
};

describe('VideoListItem', () => {
  it('renders useful metadata without loading a thumbnail image', () => {
    render(<VideoListItem video={video} isSelected={false} onSelect={jest.fn()} />);

    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText('Product demo.mp4')).toBeInTheDocument();
    expect(screen.getByText('2:05')).toBeInTheDocument();
    expect(screen.getByText('1 MB')).toBeInTheDocument();
    expect(screen.getByText('Jun 15, 2024')).toBeInTheDocument();
    expect(screen.getByText('42 frames')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('shows Pending without a spinner for missing or inactive statuses', () => {
    const pendingVideo: MediaItem = {
      ...video,
      processed: undefined,
      processing_status: undefined,
    };
    const { container, rerender } = render(
      <VideoListItem video={pendingVideo} isSelected={false} onSelect={jest.fn()} />,
    );

    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).not.toBeInTheDocument();

    const uploadedVideo: MediaItem = {
      ...video,
      processed: false,
      processing_status: 'uploaded',
    };
    rerender(
      <VideoListItem video={uploadedVideo} isSelected={false} onSelect={jest.fn()} />,
    );

    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).not.toBeInTheDocument();
  });

  it('shows Queued without a spinner for queued videos', () => {
    const queuedVideo: MediaItem = {
      ...video,
      processed: false,
      processing_status: 'queued',
    };
    const { container } = render(
      <VideoListItem video={queuedVideo} isSelected={false} onSelect={jest.fn()} />,
    );

    expect(screen.getByText('Queued')).toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).not.toBeInTheDocument();
  });

  it('only spins the status icon for active processing videos', () => {
    const processingVideo: MediaItem = {
      ...video,
      processed: false,
      processing_status: 'running',
    };
    const { container } = render(
      <VideoListItem video={processingVideo} isSelected={false} onSelect={jest.fn()} />,
    );

    expect(screen.getByText('Processing')).toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('shows Failed without a spinner for terminal error statuses', () => {
    const failedVideo: MediaItem = {
      ...video,
      processed: false,
      processing_status: 'failed',
    };
    const { container } = render(
      <VideoListItem video={failedVideo} isSelected={false} onSelect={jest.fn()} />,
    );

    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).not.toBeInTheDocument();
  });
});
