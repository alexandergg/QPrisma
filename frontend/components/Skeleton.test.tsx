/**
 * Tests for components/Skeleton.tsx
 *
 * Covers:
 * - Skeleton base renders with animation
 * - Skeleton without animation
 * - SkeletonText renders correct number of lines
 * - SkeletonAvatar sizes
 * - SkeletonVideoCard structure
 * - SkeletonChatMessage user/assistant variants
 */

import React from 'react';
import { render } from '@testing-library/react';
import {
  Skeleton,
  SkeletonText,
  SkeletonAvatar,
  SkeletonVideoCard,
  SkeletonChatMessage,
  SkeletonTableRow,
  SkeletonPage,
} from './Skeleton';

describe('Skeleton', () => {
  it('renders with animation by default', () => {
    const { container } = render(<Skeleton />);
    const el = container.firstElementChild!;
    expect(el.className).toContain('animate-pulse');
    expect(el.className).toContain('bg-gray-200');
  });

  it('renders without animation when animate=false', () => {
    const { container } = render(<Skeleton animate={false} />);
    const el = container.firstElementChild!;
    expect(el.className).not.toContain('animate-pulse');
  });

  it('applies custom className', () => {
    const { container } = render(<Skeleton className="h-4 w-32" />);
    const el = container.firstElementChild!;
    expect(el.className).toContain('h-4');
    expect(el.className).toContain('w-32');
  });
});

describe('SkeletonText', () => {
  it('renders 3 lines by default', () => {
    const { container } = render(<SkeletonText />);
    const lines = container.querySelectorAll('.bg-gray-200');
    expect(lines).toHaveLength(3);
  });

  it('renders specified number of lines', () => {
    const { container } = render(<SkeletonText lines={5} />);
    const lines = container.querySelectorAll('.bg-gray-200');
    expect(lines).toHaveLength(5);
  });

  it('makes last line shorter (w-3/4)', () => {
    const { container } = render(<SkeletonText lines={2} />);
    const lines = container.querySelectorAll('.bg-gray-200');
    expect(lines[1].className).toContain('w-3/4');
  });
});

describe('SkeletonAvatar', () => {
  it('renders small avatar', () => {
    const { container } = render(<SkeletonAvatar size="sm" />);
    const el = container.firstElementChild!;
    expect(el.className).toContain('w-8');
    expect(el.className).toContain('rounded-full');
  });

  it('renders medium avatar by default', () => {
    const { container } = render(<SkeletonAvatar />);
    const el = container.firstElementChild!;
    expect(el.className).toContain('w-12');
  });

  it('renders large avatar', () => {
    const { container } = render(<SkeletonAvatar size="lg" />);
    const el = container.firstElementChild!;
    expect(el.className).toContain('w-16');
  });
});

describe('SkeletonVideoCard', () => {
  it('renders thumbnail and content areas', () => {
    const { container } = render(<SkeletonVideoCard />);
    expect(container.querySelector('.aspect-video')).toBeTruthy();
    const skeletons = container.querySelectorAll('.bg-gray-200');
    expect(skeletons.length).toBeGreaterThanOrEqual(3);
  });
});

describe('SkeletonChatMessage', () => {
  it('renders assistant message (default)', () => {
    const { container } = render(<SkeletonChatMessage />);
    expect(container.querySelector('.rounded-full')).toBeTruthy();
  });

  it('renders user message with reversed layout', () => {
    const { container } = render(<SkeletonChatMessage isUser={true} />);
    expect(container.querySelector('.flex-row-reverse')).toBeTruthy();
  });
});

describe('SkeletonTableRow', () => {
  it('renders 4 columns by default', () => {
    const { container } = render(<SkeletonTableRow />);
    const cells = container.querySelectorAll('.bg-gray-200');
    expect(cells).toHaveLength(4);
  });

  it('renders specified number of columns', () => {
    const { container } = render(<SkeletonTableRow columns={6} />);
    const cells = container.querySelectorAll('.bg-gray-200');
    expect(cells).toHaveLength(6);
  });
});

describe('SkeletonPage', () => {
  it('renders grid of video card skeletons', () => {
    const { container } = render(<SkeletonPage />);
    const videoCards = container.querySelectorAll('.aspect-video');
    expect(videoCards.length).toBe(6);
  });
});
