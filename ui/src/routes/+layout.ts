// Disable SSR — this is a static SPA served by adapter-static.
// In dev mode, SvelteKit needs this to avoid hanging on SSR requests.
export const ssr = false;
export const prerender = false;
