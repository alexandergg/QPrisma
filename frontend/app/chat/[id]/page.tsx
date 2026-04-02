'use client';

import { use } from 'react';
import { redirect } from 'next/navigation';

/**
 * Previously this page loaded a conversation from localStorage by its ID.
 * Conversation persistence has been removed — redirect to the main chat page.
 */

interface ChatPageProps {
  params: Promise<{ id: string }>;
}

export default function ChatPage({ params }: ChatPageProps) {
  // Consume the params promise so Next.js doesn't warn about unused params
  use(params);
  redirect('/chat');
}
