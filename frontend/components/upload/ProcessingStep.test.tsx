/**
 * Tests for components/upload/ProcessingStep.tsx
 *
 * Covers:
 * - Rendering step name
 * - Status-dependent icon rendering
 * - Progress bar for in_progress
 * - Details text
 * - Time elapsed for completed steps
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import ProcessingStep, { type ProcessingStepData } from './ProcessingStep';

function makeStep(overrides: Partial<ProcessingStepData> = {}): ProcessingStepData {
  return {
    id: 'upload',
    name: 'Uploading to cloud',
    status: 'pending',
    ...overrides,
  };
}

describe('ProcessingStep', () => {
  it('renders step name', () => {
    render(<ProcessingStep step={makeStep()} />);
    expect(screen.getByText('Uploading to cloud')).toBeInTheDocument();
  });

  it('renders pending style', () => {
    const { container } = render(<ProcessingStep step={makeStep({ status: 'pending' })} />);
    expect(container.querySelector('.text-gray-400')).toBeTruthy();
  });

  it('renders in_progress style with progress percentage', () => {
    render(
      <ProcessingStep
        step={makeStep({ status: 'in_progress', progress: 65 })}
      />,
    );
    expect(screen.getByText('65%')).toBeInTheDocument();
  });

  it('renders progress bar when in_progress', () => {
    const { container } = render(
      <ProcessingStep
        step={makeStep({ status: 'in_progress', progress: 50 })}
      />,
    );
    const progressBar = container.querySelector('[style*="width: 50%"]');
    expect(progressBar).toBeTruthy();
  });

  it('renders details text', () => {
    render(
      <ProcessingStep
        step={makeStep({ status: 'in_progress', details: '12.5 MB/s' })}
      />,
    );
    expect(screen.getByText('12.5 MB/s')).toBeInTheDocument();
  });

  it('renders completed status with elapsed time', () => {
    const start = new Date('2024-06-01T12:00:00Z');
    const end = new Date('2024-06-01T12:00:03.500Z');

    render(
      <ProcessingStep
        step={makeStep({
          status: 'completed',
          startTime: start,
          endTime: end,
        })}
      />,
    );
    expect(screen.getByText('3.5s')).toBeInTheDocument();
  });

  it('renders error status', () => {
    const { container } = render(
      <ProcessingStep step={makeStep({ status: 'error' })} />,
    );
    expect(container.querySelector('.text-red-600')).toBeTruthy();
  });

  it('renders connecting line when isLast=false (default)', () => {
    const { container } = render(
      <ProcessingStep step={makeStep()} />,
    );
    // The connecting line has w-0.5 class
    const line = container.querySelector('.w-0\\.5');
    expect(line).toBeTruthy();
  });

  it('does not render connecting line when isLast=true', () => {
    const { container } = render(
      <ProcessingStep step={makeStep()} isLast={true} />,
    );
    const line = container.querySelector('.w-0\\.5');
    expect(line).toBeNull();
  });
});
