'use client';

import { useEffect } from 'react';

/**
 * MSAL popup/redirect landing page.
 *
 * The root layout's MsalProvider already calls handleRedirectPromise(),
 * which broadcasts the auth response to the parent window via
 * BroadcastChannel. This page only needs to override the app's dark
 * background so the popup appears blank while MSAL processes the response.
 */
export default function RedirectPage() {
  useEffect(() => {
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
  }, []);

  return null;
}
