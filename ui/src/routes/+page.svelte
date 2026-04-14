<script lang="ts">
	import { browser } from '$app/environment';

	let isDark = $state(false);

	$effect(() => {
		if (!browser) return;
		const stored = localStorage.getItem('colorMode');
		isDark =
			stored === 'dark' ||
			(!stored && window.matchMedia('(prefers-color-scheme: dark)').matches);
	});

	function toggleMode() {
		isDark = !isDark;
		localStorage.setItem('colorMode', isDark ? 'dark' : 'light');
		if (isDark) {
			document.documentElement.classList.add('dark');
		} else {
			document.documentElement.classList.remove('dark');
		}
	}

</script>

<div class="space-y-6">

	<!-- Welcome -->
	<div class="flex items-center gap-8 pt-2 pb-4">
		<img src="/housebot_logo.svg" alt="HouseBot" class="h-72 w-auto shrink-0" />
		<div class="flex-1 flex flex-col gap-4">
			<p class="text-lg text-gray-500 dark:text-gray-400 leading-relaxed">
				Domestic WhatsApp bot — shopping list, weather, and Google Calendar.
				Runs entirely locally with Ollama + faster-whisper.
			</p>
			<button
				onclick={toggleMode}
				class="self-start flex items-center gap-2 px-3 py-2 rounded-lg text-sm
				text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-800
				hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
			>
				<span>{isDark ? '☀️' : '🌙'}</span>
				<span>{isDark ? 'Light mode' : 'Dark mode'}</span>
			</button>
		</div>
	</div>

	<!-- Quick links grid -->
	<div class="grid grid-cols-2 sm:grid-cols-3 gap-4">
		{#each [
			{ href: '/install', icon: '🚀', label: 'Installation',  desc: 'Run or re-run the setup wizard' },
			{ href: '/status',  icon: '⚡', label: 'Status',        desc: 'Live health + logs' },
			{ href: '/admin',   icon: '🔧', label: 'Admin',         desc: 'Services, model manager' },
			{ href: '/prompts', icon: '✏️',  label: 'Prompting',     desc: 'Edit LLM prompts per skill' },
			{ href: '/config',  icon: '⚙️',  label: 'Configuration', desc: 'Edit .env settings' },
		] as link}
			<a
				href={link.href}
				class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex flex-col gap-3
				hover:border-primary-500/40 hover:bg-primary-500/5 transition-colors group"
			>
				<span class="text-3xl">{link.icon}</span>
				<div>
					<p class="font-semibold text-base group-hover:text-primary-400 transition-colors">{link.label}</p>
					<p class="text-sm text-surface-400-600 mt-1">{link.desc}</p>
				</div>
			</a>
		{/each}
	</div>

	<!-- Installation CTA -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex flex-col sm:flex-row items-start sm:items-center gap-4">
		<div class="flex-1">
			<p class="font-semibold text-base">First time here?</p>
			<p class="text-sm text-surface-400-600 mt-1">
				The installation wizard will guide you through prerequisites, <code class="font-mono text-xs">.env</code> configuration,
				Google OAuth, WhatsApp pairing, and a smoke test.
			</p>
		</div>
		<a
			href="/install"
			class="shrink-0 px-4 py-2 rounded-lg text-sm font-medium bg-primary-500/15 text-primary-400
			hover:bg-primary-500/30 transition-colors"
		>
			🚀 Start Installation Wizard
		</a>
	</div>
</div>
