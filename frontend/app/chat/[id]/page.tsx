import { redirect } from 'next/navigation';

/**
 * Previously this page loaded a conversation from localStorage by its ID.
 * Conversation persistence has been removed — redirect to the main chat page.
 */

export default function ChatPage() {
  redirect('/chat');
}
