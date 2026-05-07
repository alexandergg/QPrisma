/**
 * Tests for components/library/VideoCard.tsx
 *
 * Covers:
 * - Rendering video name, size, date, status
 * - Thumbnail-free metadata layout
 * - Click handler (onSelect)
 * - Processing state
 * - Context menu open and delete action
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import VideoCard from './VideoCard';

const baseProps = {
  id: 'vid-1',
  name: 'My Video.mp4',
  duration: 125, // 2:05
  size: 1048576, // 1 MB
  uploadedAt: new Date('2024-06-15'),
  isProcessed: true,
};

describe('VideoCard', () => {
  it('renders video name', () => {
    render(<VideoCard {...baseProps} />);
    expect(screen.getByText('My Video.mp4')).toBeInTheDocument();
  });

  it('renders formatted file size', () => {
    render(<VideoCard {...baseProps} />);
    expect(screen.getByText('1 MB')).toBeInTheDocument();
  });

  it('renders formatted duration badge', () => {
    render(<VideoCard {...baseProps} />);
    expect(screen.getByText('2:05')).toBeInTheDocument();
  });

  it('does not render a thumbnail image', () => {
    render(<VideoCard {...baseProps} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('shows Ready status when processed', () => {
    render(<VideoCard {...baseProps} isProcessed={true} />);
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('shows Processing status when processing', () => {
    render(<VideoCard {...baseProps} isProcessed={false} isProcessing={true} />);
    expect(screen.getByText('Processing')).toBeInTheDocument();
    expect(screen.getByText('Processing...')).toBeInTheDocument();
  });

  it('shows Pending status when not processed and not processing', () => {
    render(<VideoCard {...baseProps} isProcessed={false} isProcessing={false} />);
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });

  it('shows frames analysed count', () => {
    render(<VideoCard {...baseProps} framesAnalyzed={42} />);
    expect(screen.getByText('42 frames')).toBeInTheDocument();
  });

  it('calls onSelect when card is clicked', () => {
    const onSelect = jest.fn();
    render(<VideoCard {...baseProps} onSelect={onSelect} />);

    fireEvent.click(screen.getByText('My Video.mp4'));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('opens context menu and calls onDelete', () => {
    const onDelete = jest.fn();
    const onSelect = jest.fn();
    render(
      <VideoCard {...baseProps} onSelect={onSelect} onDelete={onDelete} />,
    );

    // Click the menu button (aria-label = "Video options")
    const menuButton = screen.getByLabelText('Video options');
    fireEvent.click(menuButton);

    // onSelect should NOT have been called (stopPropagation)
    expect(onSelect).not.toHaveBeenCalled();

    // Delete item should be visible
    const deleteButton = screen.getByRole('menuitem');
    expect(deleteButton).toHaveTextContent('Delete');

    fireEvent.click(deleteButton);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it('does not render delete button when onDelete is not provided', () => {
    render(<VideoCard {...baseProps} />);

    const menuButton = screen.getByLabelText('Video options');
    fireEvent.click(menuButton);

    expect(screen.queryByRole('menuitem')).not.toBeInTheDocument();
  });
});
