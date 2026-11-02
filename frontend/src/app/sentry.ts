/** Browser error tracking, only when a DSN was provided at build time (VITE_SENTRY_DSN). */
export function initSentry() {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;
  // Loaded on demand so builds without Sentry don't ship it.
  void import('@sentry/react').then((Sentry) =>
    Sentry.init({
      dsn,
      environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || 'production',
      release: import.meta.env.VITE_RELEASE || undefined,
      sendDefaultPii: false,
      tracesSampleRate: 0.05,
    }),
  );
}
