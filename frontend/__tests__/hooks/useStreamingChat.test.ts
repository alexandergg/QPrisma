import { act, renderHook } from '@testing-library/react';
import { useChatState } from '@/hooks/useChatState';
import { useStreamingChat } from '@/hooks/useStreamingChat';
import { apiClient } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  apiClient: {
    chatWithAgentStream: jest.fn(),
  },
}));

const mockedChatWithAgentStream = jest.mocked(apiClient.chatWithAgentStream);

function useStreamingChatHarness() {
  const chatState = useChatState();
  const streamingChat = useStreamingChat({
    ...chatState,
    mode: 'single',
    videoId: 'video-1',
    videoName: 'Test Video',
  });

  return {
    ...chatState,
    ...streamingChat,
  };
}

describe('useStreamingChat', () => {
  beforeEach(() => {
    mockedChatWithAgentStream.mockReset();
  });

  it('commits the assistant message as soon as the done event arrives', async () => {
    mockedChatWithAgentStream.mockImplementation(async function* () {
      yield {
        event: 'session' as const,
        data: { session_id: 'session-123' },
      };
      yield {
        event: 'token' as const,
        data: { token: 'Partial response' },
      };
      yield {
        event: 'done' as const,
        data: {
          response: 'Final response',
          tool_calls_made: 2,
        },
      };

      await new Promise(() => {
        // Simulate an SSE connection that does not close immediately.
      });
    });

    const { result } = renderHook(() => useStreamingChatHarness());

    await act(async () => {
      await result.current.handleSend('Summarize this video.');
    });

    expect(mockedChatWithAgentStream).toHaveBeenCalledWith(
      'Summarize this video.',
      'video-1',
      [],
      undefined,
      undefined,
      expect.any(AbortSignal),
    );
    expect(result.current.sessionId).toBe('session-123');
    expect(result.current.isLoading).toBe(false);
    expect(result.current.streamingContent).toBe('');
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({
      role: 'user',
      content: 'Summarize this video.',
      videoName: 'Test Video',
    });
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      content: 'Final response',
      toolCalls: 2,
    });
  });
});