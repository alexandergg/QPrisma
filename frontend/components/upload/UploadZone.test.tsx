/**
 * Tests for components/upload/UploadZone.tsx
 *
 * Covers:
 * - Rendering default text and format info
 * - Disabled state during upload
 * - Drag enter changes text
 * - Multiple file support
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import UploadZone from './UploadZone';

describe('UploadZone', () => {
  const onFilesSelected = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders drop zone text', () => {
    render(<UploadZone onFilesSelected={onFilesSelected} />);
    expect(screen.getByText('Drop videos here')).toBeInTheDocument();
    expect(screen.getByText(/click to browse/)).toBeInTheDocument();
  });

  it('renders accepted format info', () => {
    render(<UploadZone onFilesSelected={onFilesSelected} />);
    expect(screen.getByText(/MP4, MOV, AVI, WebM/)).toBeInTheDocument();
    expect(screen.getByText(/Up to 10 videos/)).toBeInTheDocument();
  });

  it('applies disabled styling when uploading', () => {
    const { container } = render(
      <UploadZone onFilesSelected={onFilesSelected} isUploading={true} />,
    );
    expect(container.querySelector('.opacity-50')).toBeTruthy();
  });

  it('renders hidden file input accepting video/*', () => {
    render(<UploadZone onFilesSelected={onFilesSelected} />);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    expect(fileInput.accept).toBe('video/*');
  });

  it('allows multiple files by default', () => {
    render(<UploadZone onFilesSelected={onFilesSelected} />);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput.multiple).toBe(true);
  });

  it('disallows multiple files when multiple=false', () => {
    render(<UploadZone onFilesSelected={onFilesSelected} multiple={false} />);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput.multiple).toBe(false);
  });

  it('changes text during drag over', () => {
    render(<UploadZone onFilesSelected={onFilesSelected} />);

    const dropZone = screen.getByText('Drop videos here').closest('div[class*="cursor-pointer"]')!;

    fireEvent.dragEnter(dropZone, {
      dataTransfer: { files: [] },
    });

    expect(screen.getByText('Drop your videos here')).toBeInTheDocument();
  });

  it('does not allow drag when uploading', () => {
    render(
      <UploadZone onFilesSelected={onFilesSelected} isUploading={true} />,
    );

    const dropZone = screen.getByText('Drop videos here').closest('div[class*="cursor"]')!;

    fireEvent.dragEnter(dropZone, {
      dataTransfer: { files: [] },
    });

    // Should NOT change text because isUploading=true
    expect(screen.queryByText('Drop your videos here')).not.toBeInTheDocument();
  });

  it('disables file input when uploading', () => {
    render(
      <UploadZone onFilesSelected={onFilesSelected} isUploading={true} />,
    );
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput.disabled).toBe(true);
  });

  it('limits the number of files selected at once and shows feedback', () => {
    render(<UploadZone onFilesSelected={onFilesSelected} maxFiles={2} />);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const files = [
      new File(['a'], 'one.mp4', { type: 'video/mp4' }),
      new File(['b'], 'two.mp4', { type: 'video/mp4' }),
      new File(['c'], 'three.mp4', { type: 'video/mp4' }),
    ];

    fireEvent.change(fileInput, {
      target: { files },
    });

    expect(onFilesSelected).toHaveBeenCalledWith(files.slice(0, 2));
    expect(screen.getByRole('alert')).toHaveTextContent(
      'You can upload up to 2 videos at once. 2 of 3 selected files will be added.',
    );
  });
});
