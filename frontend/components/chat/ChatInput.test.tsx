/**
 * Tests for components/chat/ChatInput.tsx
 *
 * Covers:
 * - Rendering placeholder text
 * - Input value changes
 * - Send button click
 * - Enter key sends, Shift+Enter does not
 * - Disabled state
 * - Loading state
 * - Attached videos display
 * - Cancel button
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import ChatInput from './ChatInput';

const defaultProps = {
  value: '',
  onChange: jest.fn(),
  onSend: jest.fn(),
};

describe('ChatInput', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders with default placeholder for single mode', () => {
    render(<ChatInput {...defaultProps} />);
    expect(
      screen.getByPlaceholderText('Ask anything about your video...'),
    ).toBeInTheDocument();
  });

  it('renders library-mode placeholder', () => {
    render(<ChatInput {...defaultProps} mode="library" />);
    expect(
      screen.getByPlaceholderText('Search across all your videos...'),
    ).toBeInTheDocument();
  });

  it('renders custom placeholder', () => {
    render(<ChatInput {...defaultProps} placeholder="Custom" />);
    expect(screen.getByPlaceholderText('Custom')).toBeInTheDocument();
  });

  it('calls onChange when typing', () => {
    const onChange = jest.fn();
    render(<ChatInput {...defaultProps} onChange={onChange} />);

    const textarea = screen.getByPlaceholderText('Ask anything about your video...');
    fireEvent.change(textarea, { target: { value: 'Hello' } });

    expect(onChange).toHaveBeenCalledWith('Hello');
  });

  it('calls onSend when send button is clicked with content', () => {
    const onSend = jest.fn();
    render(<ChatInput {...defaultProps} value="Hello" onSend={onSend} />);

    const sendButton = screen.getByLabelText('Send message');
    fireEvent.click(sendButton);

    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('disables send button when value is empty', () => {
    render(<ChatInput {...defaultProps} value="" />);
    const sendButton = screen.getByLabelText('Send message');
    expect(sendButton).toBeDisabled();
  });

  it('sends on Enter key press (non-shift)', () => {
    const onSend = jest.fn();
    render(<ChatInput {...defaultProps} value="Hi" onSend={onSend} />);

    const textarea = screen.getByPlaceholderText('Ask anything about your video...');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('does not send on Shift+Enter', () => {
    const onSend = jest.fn();
    render(<ChatInput {...defaultProps} value="Hi" onSend={onSend} />);

    const textarea = screen.getByPlaceholderText('Ask anything about your video...');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  it('disables textarea when isDisabled', () => {
    render(<ChatInput {...defaultProps} isDisabled={true} />);
    const textarea = screen.getByPlaceholderText('Ask anything about your video...');
    expect(textarea).toBeDisabled();
  });

  it('shows disabled hint text when disabled', () => {
    render(<ChatInput {...defaultProps} isDisabled={true} />);
    expect(
      screen.getByText('Select or upload a video to start chatting'),
    ).toBeInTheDocument();
  });

  it('shows loading state and changes aria-label', () => {
    render(<ChatInput {...defaultProps} value="x" isLoading={true} />);
    expect(screen.getByLabelText('Sending message')).toBeInTheDocument();
  });

  it('shows cancel button when loading and onCancel provided', () => {
    const onCancel = jest.fn();
    render(
      <ChatInput {...defaultProps} value="x" isLoading={true} onCancel={onCancel} />,
    );

    const cancelButton = screen.getByLabelText('Stop response');
    fireEvent.click(cancelButton);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('renders attached videos', () => {
    const attachedVideos = [
      { id: 'v1', name: 'Video One.mp4' },
      { id: 'v2', name: 'Video Two.mp4' },
    ];
    render(
      <ChatInput {...defaultProps} attachedVideos={attachedVideos} />,
    );
    expect(screen.getByText('Video One.mp4')).toBeInTheDocument();
    expect(screen.getByText('Video Two.mp4')).toBeInTheDocument();
  });

  it('calls onRemoveVideo when remove button clicked', () => {
    const onRemove = jest.fn();
    const attachedVideos = [{ id: 'v1', name: 'Video One.mp4' }];
    render(
      <ChatInput
        {...defaultProps}
        attachedVideos={attachedVideos}
        onRemoveVideo={onRemove}
      />,
    );

    const removeBtn = screen.getByLabelText('Remove Video One.mp4');
    fireEvent.click(removeBtn);
    expect(onRemove).toHaveBeenCalledWith('v1');
  });
});
