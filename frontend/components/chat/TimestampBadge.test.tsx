/**
 * Tests for components/chat/TimestampBadge.tsx
 *
 * Covers:
 * - Rendering formatted timestamp
 * - Different types (visual/audio/entity)
 * - Click handler
 * - Label rendering
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import TimestampBadge from './TimestampBadge';

describe('TimestampBadge', () => {
  it('renders formatted timestamp', () => {
    render(<TimestampBadge timestamp={125} />);
    // formatTime(125) = "2:05"
    expect(screen.getByText('2:05')).toBeInTheDocument();
  });

  it('renders zero timestamp', () => {
    render(<TimestampBadge timestamp={0} />);
    expect(screen.getByText('0:00')).toBeInTheDocument();
  });

  it('renders timestamp over an hour', () => {
    render(<TimestampBadge timestamp={3661} />);
    expect(screen.getByText('1:01:01')).toBeInTheDocument();
  });

  it('renders as a button', () => {
    render(<TimestampBadge timestamp={60} />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('calls onClick when clicked', () => {
    const onClick = jest.fn();
    render(<TimestampBadge timestamp={30} onClick={onClick} />);

    fireEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders optional label', () => {
    render(<TimestampBadge timestamp={30} label="Scene 1" />);
    expect(screen.getByText('Scene 1')).toBeInTheDocument();
  });

  it('applies visual type styling (default)', () => {
    const { container } = render(<TimestampBadge timestamp={30} type="visual" />);
    expect(container.querySelector('.text-indigo-600')).toBeTruthy();
  });

  it('applies audio type styling', () => {
    const { container } = render(<TimestampBadge timestamp={30} type="audio" />);
    expect(container.querySelector('.text-emerald-600')).toBeTruthy();
  });

  it('applies entity type styling', () => {
    const { container } = render(<TimestampBadge timestamp={30} type="entity" />);
    expect(container.querySelector('.text-amber-600')).toBeTruthy();
  });
});
