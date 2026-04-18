import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import { execSync } from 'child_process';

function git(cmd: string): string {
	try { return execSync(cmd, { encoding: 'utf8' }).trim(); }
	catch { return ''; }
}

const GIT_HASH   = git('git rev-parse --short HEAD');
const GIT_DATE   = git('git log -1 --format=%cd --date=short');
const GIT_BRANCH = git('git rev-parse --abbrev-ref HEAD');
const GIT_FULL   = git('git rev-parse HEAD');
const GIT_REMOTE = git('git remote get-url origin').replace(/\.git$/, '');

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	define: {
		__GIT_HASH__:        JSON.stringify(GIT_HASH),
		__GIT_DATE__:        JSON.stringify(GIT_DATE),
		__GIT_BRANCH__:      JSON.stringify(GIT_BRANCH),
		__GIT_COMMIT_URL__:  JSON.stringify(GIT_REMOTE ? `${GIT_REMOTE}/commit/${GIT_FULL}` : ''),
		__GIT_BRANCH_URL__:  JSON.stringify(GIT_REMOTE ? `${GIT_REMOTE}/tree/${GIT_BRANCH}` : ''),
	},
	server: {
		port: 5252,
		host: 'localhost',
		proxy: {
			'/admin/api': {
				target: 'http://localhost:8000',
				changeOrigin: true,
				// When FastAPI is not running, return a 503 JSON response instead of
				// falling through to SvelteKit routing (which would return 404).
				configure: (proxy) => {
					proxy.on('error', (_err, _req, res) => {
						(res as import('http').ServerResponse).writeHead(503, {
							'Content-Type': 'application/json'
						});
						(res as import('http').ServerResponse).end(
							JSON.stringify({ _offline: true })
						);
					});
				}
			}
		}
	}
});
