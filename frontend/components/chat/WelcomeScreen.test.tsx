/**
 * Tests for components/chat/WelcomeScreen.tsx
 *
 * Covers:
 * - Rendering greeting text
 * - Mode-dependent suggestions (single vs library)
 * - Action button callbacks
 * - Quick suggestion callbacks
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import WelcomeScreen from './WelcomeScreen';

describe('WelcomeScreen', () => {
  it('renders default greeting when no userName', () => {
    render(<WelcomeScreen />);
    expect(screen.getByText('Welcome to QPrisma')).toBeInTheDocument();
  });

  it('renders personalised greeting with userName', () => {
    render(<WelcomeScreen userName="Alice Smith" />);
    expect(screen.getByText('Welcome back, Alice!')).toBeInTheDocument();
  });

  it('renders single-mode description by default', () => {
    render(<WelcomeScreen />);
    expect(
      screen.getByText('Unlock intelligent insights from your videos'),
    ).toBeInTheDocument();
  });

  it('renders library-mode description', () => {
    render(<WelcomeScreen mode="library" />);
    expect(
      screen.getByText('Search and analyze across your entire video library'),
    ).toBeInTheDocument();
  });

  it('renders Upload Video and Video Library action cards', () => {
    render(<WelcomeScreen />);
    expect(screen.getByText('Upload Video')).toBeInTheDocument();
    expect(screen.getByText('Video Library')).toBeInTheDocument();
  });

  it('renders single-mode suggestions', () => {
    render(<WelcomeScreen mode="single" />);
    expect(
      screen.getByText('Summarize the main topics of this video'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('What are the key takeaways?'),
    ).toBeInTheDocument();
  });

  it('renders library-mode suggestions', () => {
    render(<WelcomeScreen mode="library" />);
    expect(
      screen.getByText('In which videos do I talk about AI?'),
    ).toBeInTheDocument();
  });

  it('calls onUploadVideo when upload card is clicked', () => {
    const onUpload = jest.fn();
    render(<WelcomeScreen onUploadVideo={onUpload} />);

    fireEvent.click(screen.getByText('Upload Video'));
    expect(onUpload).toHaveBeenCalledTimes(1);
  });

  it('calls onBrowseLibrary when library card is clicked', () => {
    const onBrowse = jest.fn();
    render(<WelcomeScreen onBrowseLibrary={onBrowse} />);

    fireEvent.click(screen.getByText('Video Library'));
    expect(onBrowse).toHaveBeenCalledTimes(1);
  });

  it('calls onQuickSuggestion with suggestion text when clicked', () => {
    const onSuggestion = jest.fn();
    render(<WelcomeScreen onQuickSuggestion={onSuggestion} />);

    fireEvent.click(screen.getByText('What are the key takeaways?'));
    expect(onSuggestion).toHaveBeenCalledWith('What are the key takeaways?');
  });

  it('renders footer hint for single mode', () => {
    render(<WelcomeScreen mode="single" />);
    expect(
      screen.getByText('Select a video to start chatting about its content'),
    ).toBeInTheDocument();
  });

  it('renders footer hint for library mode', () => {
    render(<WelcomeScreen mode="library" />);
    expect(
      screen.getByText('Your questions will search across all your processed videos'),
    ).toBeInTheDocument();
  });
});
