'use client';

import { useLayoutEffect } from 'react';

/**
 * MSAL popup/redirect landing page.
 *
 * The root layout's MsalProvider already calls handleRedirectPromise(),
 * which broadcasts the auth response to the parent window via
 * BroadcastChannel. This page only needs to override the app's dark
 * background so the popup appears blank while MSAL processes the response.
 */
export default function RedirectPage() {
  useLayoutEffect(() => {
    const prevBody = document.body.style.background;
    const prevHtml = document.documentElement.style.background;

    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';

    return () => {
      document.body.style.background = prevBody;
      document.documentElement.style.background = prevHtml;
    };
  }, []);

  return null;
}
