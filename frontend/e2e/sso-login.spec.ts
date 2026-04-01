import { test, expect, type Page, type ConsoleMessage } from '@playwright/test';
import { BACKEND_URL } from '../playwright.config';

const AUTH_URL = '/auth';

/**
 * Diagnostic Playwright test for QPrisma SSO login flow.
 *
 * This test navigates to the deployed auth page, clicks "Sign in with
 * Microsoft", and captures every signal (console logs, network requests,
 * errors, screenshots) so we can diagnose exactly where the SSO flow breaks.
 */

// ─── Helpers ────────────────────────────────────────────────────────────────

interface NetworkEntry {
  method: string;
  url: string;
  status: number | null;
  failure: string | null;
}

function collectConsole(page: Page): string[] {
  const logs: string[] = [];
  page.on('console', (msg: ConsoleMessage) => {
    logs.push(`[${msg.type()}] ${msg.text()}`);
  });
  return logs;
}

function collectNetworkErrors(page: Page): NetworkEntry[] {
  const entries: NetworkEntry[] = [];

  page.on('requestfailed', (req) => {
    entries.push({
      method: req.method(),
      url: req.url(),
      status: null,
      failure: req.failure()?.errorText ?? 'unknown',
    });
  });

  page.on('response', (res) => {
    if (res.status() >= 400) {
      entries.push({
        method: res.request().method(),
        url: res.url(),
        status: res.status(),
        failure: null,
      });
    }
  });

  return entries;
}

function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (err) => {
    errors.push(err.message);
  });
  return errors;
}

// ─── Tests ──────────────────────────────────────────────────────────────────

test.describe('SSO Login Flow', () => {
  test('auth page loads and renders sign-in button', async ({ page }) => {
    const consoleLogs = collectConsole(page);
    const networkErrors = collectNetworkErrors(page);
    const pageErrors = collectPageErrors(page);

    // Navigate to auth page
    const response = await page.goto(AUTH_URL, { waitUntil: 'networkidle' });

    // Capture page status
    console.log(`\n=== AUTH PAGE LOAD ===`);
    console.log(`Status: ${response?.status()}`);
    console.log(`URL: ${page.url()}`);

    await page.screenshot({ path: './e2e/test-results/01-auth-page-loaded.png', fullPage: true });

    // Verify page loaded
    expect(response?.status()).toBe(200);

    // Check for the QPrisma heading
    const heading = page.locator('h1:has-text("QPrisma")');
    await expect(heading).toBeVisible({ timeout: 15_000 });

    // Check for the Sign in button
    const signInButton = page.getByRole('button', { name: /sign in with microsoft/i });
    await expect(signInButton).toBeVisible();
    expect(await signInButton.isEnabled()).toBe(true);

    // Check for error banners already visible
    const errorBanner = page.locator('.bg-red-50');
    const hasError = await errorBanner.isVisible().catch(() => false);
    if (hasError) {
      const errorText = await errorBanner.textContent();
      console.log(`\n⚠ ERROR BANNER VISIBLE ON LOAD: ${errorText}`);
    }

    // Dump diagnostics
    if (consoleLogs.length) {
      console.log(`\n=== CONSOLE LOGS (${consoleLogs.length}) ===`);
      consoleLogs.forEach((l) => console.log(`  ${l}`));
    }
    if (pageErrors.length) {
      console.log(`\n=== PAGE ERRORS (${pageErrors.length}) ===`);
      pageErrors.forEach((e) => console.log(`  ❌ ${e}`));
    }
    if (networkErrors.length) {
      console.log(`\n=== NETWORK ERRORS (${networkErrors.length}) ===`);
      networkErrors.forEach((e) =>
        console.log(`  ${e.method} ${e.url} → ${e.status ?? e.failure}`),
      );
    }
  });

  test('SSO popup flow — click sign-in and capture Microsoft login', async ({
    page,
    context,
  }) => {
    const consoleLogs = collectConsole(page);
    const networkErrors = collectNetworkErrors(page);
    const pageErrors = collectPageErrors(page);

    // 1. Navigate to /auth
    await page.goto(AUTH_URL, { waitUntil: 'networkidle' });
    console.log(`\n=== STARTING SSO FLOW ===`);
    console.log(`Main page URL: ${page.url()}`);

    // 2. Click "Sign in with Microsoft" and wait for popup
    const signInButton = page.getByRole('button', { name: /sign in with microsoft/i });
    await expect(signInButton).toBeVisible({ timeout: 15_000 });

    let popup: Page | null = null;
    let popupFailed = false;
    let popupError = '';

    try {
      // MSAL uses loginPopup — we expect a new window/tab to open
      [popup] = await Promise.all([
        context.waitForEvent('page', { timeout: 30_000 }),
        signInButton.click(),
      ]);
    } catch (err) {
      popupFailed = true;
      popupError = err instanceof Error ? err.message : String(err);
      console.log(`\n⚠ POPUP DID NOT OPEN: ${popupError}`);
    }

    await page.screenshot({ path: './e2e/test-results/02-after-signin-click.png', fullPage: true });

    if (popup && !popupFailed) {
      // 3. Inspect the popup
      const popupConsoleLogs = collectConsole(popup);
      const popupNetworkErrors = collectNetworkErrors(popup);
      const popupPageErrors = collectPageErrors(popup);

      // Wait for the popup to navigate away from about:blank to the actual login page
      if (popup.url() === 'about:blank') {
        console.log('Popup at about:blank — waiting for navigation...');
        try {
          await popup.waitForURL((url) => url.toString() !== 'about:blank', { timeout: 30_000 });
        } catch {
          console.log('⚠ Popup never navigated away from about:blank');
        }
      }

      try {
        await popup.waitForLoadState('domcontentloaded', { timeout: 30_000 });
      } catch {
        console.log('⚠ Popup did not reach domcontentloaded within timeout');
      }

      const popupUrl = popup.url();
      console.log(`\n=== POPUP OPENED ===`);
      console.log(`Popup URL: ${popupUrl}`);

      await popup.screenshot({
        path: './e2e/test-results/03-popup-microsoft-login.png',
        fullPage: true,
      });

      // Check: did we land on Microsoft login?
      const MICROSOFT_LOGIN_HOSTS = new Set([
        'login.microsoftonline.com',
        'login.live.com',
        'login.microsoft.com',
      ]);
      const isMicrosoftLogin = (() => {
        try {
          return MICROSOFT_LOGIN_HOSTS.has(new URL(popupUrl).hostname);
        } catch {
          return false;
        }
      })();

      console.log(`Is Microsoft login page: ${isMicrosoftLogin}`);

      if (isMicrosoftLogin) {
        // Check for error messages on the Microsoft login page
        const msErrorEl = popup.locator('#usernameError, #passwordError, .alert-error, #errorText');
        const hasMsError = await msErrorEl.first().isVisible().catch(() => false);
        if (hasMsError) {
          const msErrorText = await msErrorEl.first().textContent();
          console.log(`\n⚠ MICROSOFT LOGIN ERROR: ${msErrorText}`);
        }

        // Check if there's an AADSTS error in the URL
        if (popupUrl.includes('error=') || popupUrl.includes('AADSTS')) {
          const urlParams = new URL(popupUrl).searchParams;
          console.log(`\n❌ ENTRA ID ERROR IN URL:`);
          console.log(`  error: ${urlParams.get('error')}`);
          console.log(`  error_description: ${urlParams.get('error_description')}`);
        }

        // Check for email input field
        const emailInput = popup.locator('input[type="email"], input[name="loginfmt"]');
        const hasEmailInput = await emailInput.isVisible().catch(() => false);
        console.log(`Email input visible: ${hasEmailInput}`);

        // Get the page title
        const popupTitle = await popup.title();
        console.log(`Popup title: "${popupTitle}"`);
      } else {
        // Maybe redirected to an error page or unexpected URL
        console.log(`\n⚠ UNEXPECTED POPUP DESTINATION`);
        try {
          const popupContent = await popup.content();
          console.log(`Popup HTML (first 2000 chars):\n${popupContent.substring(0, 2000)}`);
        } catch {
          console.log('Could not read popup content (page still navigating)');
        }
      }

      // Dump popup diagnostics
      if (popupConsoleLogs.length) {
        console.log(`\n=== POPUP CONSOLE LOGS (${popupConsoleLogs.length}) ===`);
        popupConsoleLogs.forEach((l) => console.log(`  ${l}`));
      }
      if (popupPageErrors.length) {
        console.log(`\n=== POPUP PAGE ERRORS (${popupPageErrors.length}) ===`);
        popupPageErrors.forEach((e) => console.log(`  ❌ ${e}`));
      }
      if (popupNetworkErrors.length) {
        console.log(`\n=== POPUP NETWORK ERRORS (${popupNetworkErrors.length}) ===`);
        popupNetworkErrors.forEach((e) =>
          console.log(`  ${e.method} ${e.url} → ${e.status ?? e.failure}`),
        );
      }
    }

    // 4. Check main page state after popup interaction
    // Wait a moment for any MSAL processing
    await page.waitForTimeout(3_000);
    await page.screenshot({ path: './e2e/test-results/04-main-after-popup.png', fullPage: true });

    const mainUrl = page.url();
    console.log(`\n=== MAIN PAGE AFTER POPUP ===`);
    console.log(`URL: ${mainUrl}`);

    // Check if error appeared on main page
    const errorBanner = page.locator('.bg-red-50');
    const hasMainError = await errorBanner.isVisible().catch(() => false);
    if (hasMainError) {
      const errorText = await errorBanner.textContent();
      console.log(`\n❌ MAIN PAGE ERROR BANNER: ${errorText}`);
    }

    // Check if the button changed to "Signing in..."
    const signingIn = page.locator('text=Signing in...');
    const isSigningIn = await signingIn.isVisible().catch(() => false);
    if (isSigningIn) {
      console.log(`Main page shows "Signing in..." spinner`);
    }

    // Main page diagnostics
    if (consoleLogs.length) {
      console.log(`\n=== MAIN CONSOLE LOGS (${consoleLogs.length}) ===`);
      consoleLogs.forEach((l) => console.log(`  ${l}`));
    }
    if (pageErrors.length) {
      console.log(`\n=== MAIN PAGE ERRORS (${pageErrors.length}) ===`);
      pageErrors.forEach((e) => console.log(`  ❌ ${e}`));
    }
    if (networkErrors.length) {
      console.log(`\n=== MAIN NETWORK ERRORS (${networkErrors.length}) ===`);
      networkErrors.forEach((e) =>
        console.log(`  ${e.method} ${e.url} → ${e.status ?? e.failure}`),
      );
    }

    // Summary verdict
    console.log(`\n${'='.repeat(60)}`);
    console.log(`SSO FLOW DIAGNOSTIC SUMMARY`);
    console.log(`${'='.repeat(60)}`);
    console.log(`Auth page loaded: ✅`);
    console.log(`Popup opened: ${popup && !popupFailed ? '✅' : '❌ ' + popupError}`);
    if (popup && !popupFailed) {
      const isMsLogin = (() => {
        try {
          const host = new URL(popup.url()).hostname;
          return host === 'login.microsoftonline.com' || host === 'login.live.com';
        } catch {
          return false;
        }
      })();
      console.log(`Microsoft login reached: ${isMsLogin ? '✅' : '❌'}`);
    }
    console.log(`Page errors: ${pageErrors.length}`);
    console.log(`Network errors: ${networkErrors.length}`);
    console.log(`${'='.repeat(60)}\n`);
  });

  test('check MSAL configuration in browser', async ({ page }) => {
    const consoleLogs = collectConsole(page);

    await page.goto(AUTH_URL, { waitUntil: 'networkidle' });

    // Inspect MSAL config injected into the page
    const msalDiagnostics = await page.evaluate(() => {
      const results: Record<string, unknown> = {};

      // Check sessionStorage for any existing MSAL keys
      const msalKeys: string[] = [];
      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i);
        if (key && key.includes('msal')) {
          msalKeys.push(key);
        }
      }
      results['msalSessionStorageKeys'] = msalKeys;

      // Check if MSAL is loaded
      results['msalBrowserLoaded'] = typeof (window as Record<string, unknown>)['msal'] !== 'undefined';

      // Check meta tags for redirect URI hints
      const metaTags = Array.from(document.querySelectorAll('meta')).map((m) => ({
        name: m.getAttribute('name'),
        content: m.getAttribute('content'),
      }));
      results['metaTags'] = metaTags.filter((m) => m.name);

      // Check for Next.js environment variables exposed in __NEXT_DATA__
      const nextData = (window as Record<string, unknown>).__NEXT_DATA__ as Record<string, unknown> | undefined;
      if (nextData) {
        results['nextDataAvailable'] = true;
        results['nextBuildId'] = nextData.buildId;
      }

      return results;
    });

    console.log('\n=== MSAL BROWSER DIAGNOSTICS ===');
    console.log(JSON.stringify(msalDiagnostics, null, 2));

    // Check that the MSAL authority endpoint is reachable
    const authorityResponse = await page.evaluate(async () => {
      try {
        const resp = await fetch(
          'https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration'
        );
        return { status: resp.status, ok: resp.ok };
      } catch (e) {
        return { error: String(e) };
      }
    });
    console.log('\n=== ENTRA ID OIDC ENDPOINT CHECK ===');
    console.log(JSON.stringify(authorityResponse, null, 2));

    if (consoleLogs.length) {
      console.log(`\n=== CONSOLE LOGS ===`);
      consoleLogs.forEach((l) => console.log(`  ${l}`));
    }
  });

  test('redirect page loads without JS errors', async ({ page }) => {
    const pageErrors = collectPageErrors(page);
    const networkErrors = collectNetworkErrors(page);
    const consoleLogs = collectConsole(page);

    const response = await page.goto('/redirect', { waitUntil: 'networkidle' });

    console.log(`\n=== REDIRECT PAGE ===`);
    console.log(`Status: ${response?.status()}`);
    console.log(`URL: ${page.url()}`);

    await page.screenshot({ path: './e2e/test-results/05-redirect-page.png', fullPage: true });

    if (pageErrors.length) {
      console.log(`\n❌ REDIRECT PAGE JS ERRORS (${pageErrors.length}):`);
      pageErrors.forEach((e) => console.log(`  ${e}`));
    }
    if (networkErrors.length) {
      console.log(`\n❌ REDIRECT NETWORK ERRORS:`);
      networkErrors.forEach((e) =>
        console.log(`  ${e.method} ${e.url} → ${e.status ?? e.failure}`),
      );
    }
    if (consoleLogs.length) {
      console.log(`\n=== REDIRECT CONSOLE ===`);
      consoleLogs.forEach((l) => console.log(`  ${l}`));
    }

    expect(response?.status()).toBe(200);
  });

  test('backend API connectivity and auth config check', async ({ page }) => {
    await page.goto('/auth', { waitUntil: 'networkidle' });

    const apiChecks = await page.evaluate(async (backendUrl: string) => {
      const results: Record<string, unknown> = {};

      // 1. Health check
      try {
        const resp = await fetch(`${backendUrl}/`, { method: 'GET' });
        results['health'] = { status: resp.status, body: await resp.text() };
      } catch (e) {
        results['health'] = { error: String(e) };
      }

      // 2. Auth config (public endpoint)
      try {
        const resp = await fetch(`${backendUrl}/auth/config`, { method: 'GET' });
        results['auth_config'] = { status: resp.status, body: await resp.json() };
      } catch (e) {
        results['auth_config'] = { error: String(e) };
      }

      // 3. /auth/me without token
      try {
        const resp = await fetch(`${backendUrl}/auth/me`, { method: 'GET' });
        results['auth_me_no_token'] = { status: resp.status, body: await resp.json() };
      } catch (e) {
        results['auth_me_no_token'] = { error: String(e) };
      }

      return results;
    }, BACKEND_URL);

    console.log(`\n=== BACKEND API DIAGNOSTICS ===`);
    console.log(JSON.stringify(apiChecks, null, 2));

    // Verify backend is reachable
    expect((apiChecks['health'] as Record<string, unknown>)?.status).toBe(200);

    // ❌ CRITICAL CHECK: Auth config should NOT be empty
    const authConfig = (apiChecks['auth_config'] as Record<string, unknown>)?.body as Record<string, string>;
    console.log(`\n=== AUTH CONFIG VERDICT ===`);
    console.log(`tenant_id: "${authConfig?.tenant_id}" ${authConfig?.tenant_id ? '✅' : '❌ EMPTY'}`);
    console.log(`client_id: "${authConfig?.client_id}" ${authConfig?.client_id ? '✅' : '❌ EMPTY'}`);
    console.log(`api_scope: "${authConfig?.api_scope}" ${authConfig?.api_scope ? '✅' : '❌ EMPTY'}`);

    if (!authConfig?.tenant_id || !authConfig?.client_id || !authConfig?.api_scope) {
      console.log(`\n🔴 ROOT CAUSE: Backend Entra ID config is empty!`);
      console.log(`   The backend cannot validate MSAL tokens without tenant_id/client_id/api_scope.`);
      console.log(`   After SSO popup login, getCurrentUser() calls /auth/me → 401 → user stays null → spinner forever.`);
    }

    // Fail the test to make this visible
    expect(authConfig?.tenant_id, 'Backend tenant_id is empty — Entra ID env vars not configured').toBeTruthy();
    expect(authConfig?.client_id, 'Backend client_id is empty — Entra ID env vars not configured').toBeTruthy();
    expect(authConfig?.api_scope, 'Backend api_scope is empty — Entra ID env vars not configured').toBeTruthy();
  });

  test('monitor post-popup BroadcastChannel and token flow', async ({ page, context }) => {
    const consoleLogs = collectConsole(page);
    const networkErrors = collectNetworkErrors(page);
    const pageErrors = collectPageErrors(page);

    await page.goto('/auth', { waitUntil: 'networkidle' });

    // Instrument fetch to log all requests including /auth/me
    await page.evaluate(() => {
      (window as Record<string, unknown>).__fetchLog = [];
      const origFetch = window.fetch;
      window.fetch = async (...args: Parameters<typeof fetch>) => {
        const url = typeof args[0] === 'string' ? args[0] : (args[0] as Request).url;
        const start = Date.now();
        try {
          const resp = await origFetch(...args);
          ((window as Record<string, unknown>).__fetchLog as unknown[]).push({
            url: url.substring(0, 200), status: resp.status, ms: Date.now() - start,
          });
          return resp;
        } catch (e) {
          ((window as Record<string, unknown>).__fetchLog as unknown[]).push({
            url: url.substring(0, 200), error: String(e), ms: Date.now() - start,
          });
          throw e;
        }
      };
    });

    // Click sign-in
    const signInButton = page.getByRole('button', { name: /sign in with microsoft/i });
    let popup: Page | null = null;
    try {
      [popup] = await Promise.all([
        context.waitForEvent('page', { timeout: 30_000 }),
        signInButton.click(),
      ]);
    } catch {
      console.log('⚠ No popup opened');
      return;
    }

    if (popup!.url() === 'about:blank') {
      try {
        await popup!.waitForURL((url) => url.toString() !== 'about:blank', { timeout: 30_000 });
      } catch { /* continue */ }
    }

    console.log(`\nPopup landed at: ${popup!.url().substring(0, 150)}`);

    // Track popup navigation (especially the redirect back to /redirect)
    const popupNavigations: string[] = [];
    popup!.on('framenavigated', (frame) => {
      if (frame === popup!.mainFrame()) {
        popupNavigations.push(frame.url());
      }
    });

    let popupClosed = false;
    popup!.on('close', () => { popupClosed = true; });

    // Wait 5s to observe
    await page.waitForTimeout(5_000);

    const monitorData = await page.evaluate(() => {
      return {
        fetchLog: (window as Record<string, unknown>).__fetchLog,
        msalKeys: Array.from({ length: sessionStorage.length }, (_, i) => {
          const key = sessionStorage.key(i)!;
          return { key, valueLen: (sessionStorage.getItem(key) ?? '').length };
        }).filter((k) => k.key.includes('msal')),
      };
    });

    console.log(`\n=== POST-CLICK MONITORING (5s) ===`);
    console.log(`Popup closed: ${popupClosed}`);
    console.log(`Popup navigations: ${JSON.stringify(popupNavigations)}`);
    console.log(`Fetch log: ${JSON.stringify(monitorData.fetchLog, null, 2)}`);
    console.log(`MSAL sessionStorage keys: ${JSON.stringify(monitorData.msalKeys, null, 2)}`);

    if (pageErrors.length) {
      console.log(`\n❌ PAGE ERRORS:`);
      pageErrors.forEach((e) => console.log(`  ${e}`));
    }
    if (networkErrors.length) {
      console.log(`\n❌ NETWORK ERRORS:`);
      networkErrors.forEach((e) => console.log(`  ${e.method} ${e.url} → ${e.status ?? e.failure}`));
    }
    if (consoleLogs.length) {
      console.log(`\n=== CONSOLE ===`);
      consoleLogs.forEach((l) => console.log(`  ${l}`));
    }

    await page.screenshot({ path: './e2e/test-results/06-lifecycle-final.png', fullPage: true });
  });
});
