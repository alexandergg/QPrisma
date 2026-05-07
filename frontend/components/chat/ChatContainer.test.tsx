import { fireEvent, render, screen } from '@testing-library/react';
import ChatContainer from './ChatContainer';

jest.mock('@/hooks/useChatState', () => ({
  useChatState: () => ({
    messages: [],
    inputValue: '',
    setInputValue: jest.fn(),
    isLoading: false,
    streamingContent: '',
    activeTools: [],
    isThinking: false,
    thinkingStartTime: undefined,
  }),
}));

jest.mock('@/hooks/useStreamingChat', () => ({
  useStreamingChat: () => ({
    handleSend: jest.fn(),
    handleCancel: jest.fn(),
    lastSubmittedPrompt: undefined,
  }),
}));

jest.mock('./MessageList', () => function MockMessageList() {
  return <div>Message list mock</div>;
});

jest.mock('./ChatInput', () => function MockChatInput() {
  return <div>Chat input mock</div>;
});

jest.mock('./WelcomeScreen', () => function MockWelcomeScreen() {
  return <div>Welcome mock</div>;
});

describe('ChatContainer video opening state', () => {
  it('shows opening state instead of welcome while a URL video is loading', () => {
    render(<ChatContainer isOpeningVideo />);

    expect(screen.getByText('Opening video')).toBeInTheDocument();
    expect(screen.queryByText('Welcome mock')).not.toBeInTheDocument();
  });

  it('shows a recoverable error when opening a URL video fails', () => {
    const onRetry = jest.fn();
    const onBrowse = jest.fn();

    render(
      <ChatContainer
        videoOpenError="Could not open this video."
        onRetryOpenVideo={onRetry}
        onBrowseLibrary={onBrowse}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    fireEvent.click(screen.getByRole('button', { name: 'Browse library' }));

    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onBrowse).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Welcome mock')).not.toBeInTheDocument();
  });
});

