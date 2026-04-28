<script lang="ts">
	import { browser } from '$app/environment';
	import { onMount } from 'svelte';

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

	// ── Status pills ────────────────────────────────────────────────────────
	type PillState = 'loading' | 'ok' | 'warn';
	let configState  = $state<PillState>('loading');
	let serviceState = $state<PillState>('loading');

	onMount(async () => {
		const [cfgRes, statusRes] = await Promise.all([
			fetch('/admin/api/install/config-status').catch(() => null),
			fetch('/admin/api/status').catch(() => null),
		]);

		// Configured: all 4 steps complete (Ollama, WA paired, senders, location)
		configState = (cfgRes?.ok && (await cfgRes.json().catch(() => ({}))).configured === true)
			? 'ok' : 'warn';

		// Operational: Ollama + Bridge processes are up
		if (statusRes?.ok) {
			const data = await statusRes.json().catch(() => ({}));
			serviceState = (data.ollama?.up === true && data.bridge?.up === true) ? 'ok' : 'warn';
		} else {
			serviceState = 'warn';
		}
	});

</script>

<div class="space-y-6">

	<!-- Welcome -->
	<div class="flex items-center gap-8 pt-2 pb-4">
		<img src={isDark ? '/housebot_logo_v2_dark_small.png' : '/housebot_logo_v2_small.png'} alt="HouseBot" class="h-50 w-auto shrink-0" />
		<div class="flex-1 flex flex-col gap-4">
			<p class="text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
				Your private housebot on WhatsApp.<br />
				Manage shopping lists, Google Calendar events, and real-time weather.<br />
				Privacy-first by design — powered entirely by local AI, your data never leaves home.
			</p>
			<div class="flex flex-wrap items-center gap-2">
				<button
					onclick={toggleMode}
					class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm
					text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-800
					hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
				>
					<span>{isDark ? '☀️' : '🌙'}</span>
					<span>{isDark ? 'Light mode' : 'Dark mode'}</span>
				</button>

				<!-- Configured pill -->
				<a
					href="/config"
					class="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-colors
					{configState === 'loading' ? 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500' :
					 configState === 'ok'      ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50' :
					                             'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 hover:bg-amber-200 dark:hover:bg-amber-900/50'}"
				>
					{#if configState === 'loading'}
						<span class="animate-pulse">⚙️</span><span>Checking…</span>
					{:else if configState === 'ok'}
						<span>✅</span><span>Configured</span>
					{:else}
						<span>⚠️</span><span>Not configured</span>
					{/if}
				</a>

				<!-- Operational pill -->
				<a
					href="/admin"
					class="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-colors
					{serviceState === 'loading' ? 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500' :
					 serviceState === 'ok'      ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50' :
					                              'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50'}"
				>
					{#if serviceState === 'loading'}
						<span class="animate-pulse">🔧</span><span>Checking…</span>
					{:else if serviceState === 'ok'}
						<span>✅</span><span>Operational</span>
					{:else}
						<span>🔴</span><span>Not operational</span>
					{/if}
				</a>
			</div>
		</div>
	</div>

	<!-- Quick links grid -->
	<div class="grid grid-cols-2 sm:grid-cols-3 gap-4">
		{#each [
			{ href: '/config',  icon: '⚙️',  label: 'Configuration',   desc: 'Configure your housebot' },
			{ href: '/skills',  icon: '🧩', label: 'Skills',           desc: 'Enable or disable bot capabilities' },
			{ href: '/admin',   icon: '🔧', label: 'Admin',             desc: 'Manage your housebot services' },
			{ href: '/status',  icon: '⚡', label: 'Status',            desc: 'Live health + logs' },
			{ href: '/prompts', icon: '✏️',  label: 'Prompting',         desc: 'Customize your housebot behaviours' },
			{ href: '/testing', icon: '🧪', label: 'Testing',           desc: 'Run test cases against the bot' },
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

</div>