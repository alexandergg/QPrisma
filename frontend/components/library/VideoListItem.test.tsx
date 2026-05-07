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
});
