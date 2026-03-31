/**
 * MSAL Configuration for Microsoft Entra ID Authentication
 *
 * Requires the following environment variables:
 *   NEXT_PUBLIC_ENTRA_CLIENT_ID  — Frontend SPA app registration client ID
 *   NEXT_PUBLIC_ENTRA_AUTHORITY  — https://login.microsoftonline.com/{tenant_id}
 *   NEXT_PUBLIC_ENTRA_REDIRECT_URI — e.g., http://localhost:3000
 *   NEXT_PUBLIC_ENTRA_API_SCOPE — Backend API scope (e.g., api://<backend-client-id>/access_as_user)
 */

import { type Configuration, LogLevel, type RedirectRequest } from '@azure/msal-browser';

const baseUri = (process.env.NEXT_PUBLIC_ENTRA_REDIRECT_URI || 'http://localhost:3000').replace(/\/+$/, '');

export const msalConfig: Configuration = {
  auth: {
    clientId: process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID || '',
    authority: process.env.NEXT_PUBLIC_ENTRA_AUTHORITY || 'https://login.microsoftonline.com/common',
    redirectUri: `${baseUri}/redirect.html`,
    postLogoutRedirectUri: baseUri,
  },
  cache: {
    cacheLocation: 'sessionStorage',
  },
  system: {
    loggerOptions: {
      logLevel: LogLevel.Warning,
      piiLoggingEnabled: false,
    },
  },
};

export const loginRequest: RedirectRequest = {
  scopes: [
    process.env.NEXT_PUBLIC_ENTRA_API_SCOPE || 'api://qprisma/access_as_user',
  ],
};
