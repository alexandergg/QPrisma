/**
 * Tests for components/chat/WelcomeScreen.tsx
 *
 * Covers:
 * - New-user view (no videos) with upload CTA and feature cards
 * - Returning-user view (has videos) with recent videos and quick actions
 * - Loading state
 * - Action button callbacks
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import WelcomeScreen from './WelcomeScreen';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Mock useUserVideos hook
const mockUseUserVideos = jest.fn();
jest.mock('@/hooks/useUserVideos', () => ({
  useUserVideos: () => mockUseUserVideos(),
}));

const noVideos = {
  videos: [],
  hasVideos: false,
  videoCount: 0,
  recentVideos: [],
  isLoading: false,
  error: undefined,
};

const withVideos = {
  videos: [
    { id: 'v1', original_filename: 'intro.mp4', duration: 135 },
    { id: 'v2', original_filename: 'demo.mp4', duration: 330 },
  ],
  hasVideos: true,
  videoCount: 2,
  recentVideos: [
    { id: 'v1', original_filename: 'intro.mp4', duration: 135 },
    { id: 'v2', original_filename: 'demo.mp4', duration: 330 },
  ],
  isLoading: false,
  error: undefined,
};

describe('WelcomeScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseUserVideos.mockReturnValue(noVideos);
  });

  // ---- Loading state ----

  it('renders loading skeleton while fetching', () => {
    mockUseUserVideos.mockReturnValue({ ...noVideos, isLoading: true });
    const { container } = render(<WelcomeScreen />);
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  // ---- New-user view ----

  it('renders "Welcome to QPrisma" for new users', () => {
    render(<WelcomeScreen />);
    expect(screen.getByText('Welcome to QPrisma')).toBeInTheDocument();
  });

  it('renders upload CTA and feature cards for new users', () => {
    render(<WelcomeScreen />);
    expect(screen.getByText('Drop your video here or click to browse')).toBeInTheDocument();
    expect(screen.getByText('AI Chat')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Graph')).toBeInTheDocument();
    expect(screen.getByText('Smart Transcript')).toBeInTheDocument();
  });

  it('calls onUploadVideo when upload CTA is clicked (new user)', () => {
    const onUpload = jest.fn();
    render(<WelcomeScreen onUploadVideo={onUpload} />);
    fireEvent.click(screen.getByText('Drop your video here or click to browse'));
    expect(onUpload).toHaveBeenCalledTimes(1);
  });

  // ---- Returning-user view ----

  it('renders personalised greeting for returning user', () => {
    mockUseUserVideos.mockReturnValue(withVideos);
    render(<WelcomeScreen userName="Alice Smith" />);
    expect(screen.getByText('Welcome back, Alice!')).toBeInTheDocument();
  });

  it('renders video count for returning user', () => {
    mockUseUserVideos.mockReturnValue(withVideos);
    render(<WelcomeScreen />);
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText(/You have/i)).toHaveTextContent(/2\s+videos analyzed/);
  });

  it('renders recent video cards', () => {
    mockUseUserVideos.mockReturnValue(withVideos);
    render(<WelcomeScreen />);
    expect(screen.getByText('intro.mp4')).toBeInTheDocument();
    expect(screen.getByText('demo.mp4')).toBeInTheDocument();
  });

  it('renders quick action buttons for returning user', () => {
    mockUseUserVideos.mockReturnValue(withVideos);
    render(<WelcomeScreen />);
    expect(screen.getByText('Upload new video')).toBeInTheDocument();
    expect(screen.getByText('Browse library')).toBeInTheDocument();
    expect(screen.getByText('Compare videos')).toBeInTheDocument();
  });

  it('calls onUploadVideo when upload action is clicked (returning user)', () => {
    mockUseUserVideos.mockReturnValue(withVideos);
    const onUpload = jest.fn();
    render(<WelcomeScreen onUploadVideo={onUpload} />);
    fireEvent.click(screen.getByText('Upload new video'));
    expect(onUpload).toHaveBeenCalledTimes(1);
  });

  it('calls onBrowseLibrary when browse action is clicked', () => {
    mockUseUserVideos.mockReturnValue(withVideos);
    const onBrowse = jest.fn();
    render(<WelcomeScreen onBrowseLibrary={onBrowse} />);
    fireEvent.click(screen.getByText('Browse library'));
    expect(onBrowse).toHaveBeenCalledTimes(1);
  });

  it('navigates to /compare when Compare videos is clicked', () => {
    mockUseUserVideos.mockReturnValue(withVideos);
    render(<WelcomeScreen />);
    fireEvent.click(screen.getByText('Compare videos'));
    expect(mockPush).toHaveBeenCalledWith('/compare');
  });

  it('navigates to chat when a video card is clicked', () => {
    mockUseUserVideos.mockReturnValue(withVideos);
    render(<WelcomeScreen />);
    fireEvent.click(screen.getByText('intro.mp4'));
    expect(mockPush).toHaveBeenCalledWith('/chat?videoId=v1');
  });

  it('calls onSelectVideo instead of navigating when provided', () => {
    mockUseUserVideos.mockReturnValue(withVideos);
    const onSelect = jest.fn();
    render(<WelcomeScreen onSelectVideo={onSelect} />);
    fireEvent.click(screen.getByText('demo.mp4'));
    expect(onSelect).toHaveBeenCalledWith('v2');
    expect(mockPush).not.toHaveBeenCalled();
  });
});
