'use client';

import { useEffect } from 'react';
import { broadcastResponseToMainFrame } from '@azure/msal-browser/redirect-bridge';

/**
 * MSAL v5 popup redirect bridge page.
 *
 * After the user authenticates, Microsoft redirects the popup here with
 * the auth code in the URL.  broadcastResponseToMainFrame() sends the
 * response to the parent window via BroadcastChannel, which resolves
 * the parent's loginPopup() promise and closes this popup automatically.
 *
 * IMPORTANT: This page must NOT be wrapped in MsalProvider — the
 * AuthProvider in layout.tsx detects pathname === '/redirect' and
 * renders children without MsalProvider so the hash is not consumed
 * before the bridge can process it.
 */
export default function RedirectPage() {
  useEffect(() => {
    broadcastResponseToMainFrame();
  }, []);

  return null;
}
