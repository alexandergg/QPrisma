'use client';

import { useEffect } from 'react';
import { PublicClientApplication } from '@azure/msal-browser';
import { msalConfig } from '@/lib/msal-config';

/**
 * MSAL popup/redirect landing page.
 *
 * For @azure/msal-browser v3+, the popup window must load MSAL and call
 * handleRedirectPromise() so the auth response is broadcast back to the
 * parent window via BroadcastChannel. A blank static HTML page is not
 * sufficient.
 */
export default function RedirectPage() {
  useEffect(() => {
    const instance = new PublicClientApplication(msalConfig);
    instance.initialize().then(() => {
      instance.handleRedirectPromise().catch(() => {
        // Errors are handled by the parent window's MSAL instance.
      });
    });
  }, []);

  return null;
}
