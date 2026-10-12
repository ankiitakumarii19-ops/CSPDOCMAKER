/**
 * Where the app is served from. Empty locally (http://localhost:3000/); on
 * the server it is "/csp-docmaker" (https://indev.eko.in/csp-docmaker/).
 *
 * Fixed at build time from NEXT_PUBLIC_BASE_PATH, the same value
 * next.config.ts gives Next.js as basePath. Next.js adds it to page links and
 * router navigation itself; anything else that names a path on this site —
 * server requests, images, full-page redirects — goes through withBase().
 */
export const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");

export function withBase(path: string): string {
  return `${BASE_PATH}${path}`;
}
