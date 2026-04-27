<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { Navigation } from '@skeletonlabs/skeleton-svelte';

	let { children } = $props();

	// Dark / light mode
	let isDark = $state(false);

	$effect(() => {
		const stored = localStorage.getItem('colorMode');
		isDark =
			stored === 'dark' ||
			(!stored && window.matchMedia('(prefers-color-scheme: dark)').matches);
		applyMode(isDark);
	});

	function toggleMode() {
		isDark = !isDark;
		localStorage.setItem('colorMode', isDark ? 'dark' : 'light');
		applyMode(isDark);
	}

	function applyMode(dark: boolean) {
		if (dark) {
			document.documentElement.classList.add('dark');
		} else {
			document.documentElement.classList.remove('dark');
		}
	}

	const navItems = [
		{ href: '/',         label: 'Home',          icon: '🏠', phase: null },
		{ href: '/config',   label: 'Configuration',  icon: '⚙️',  phase: null },
		{ href: '/skills',   label: 'Skills',         icon: '🧩', phase: null },
		{ href: '/prompts',  label: 'Prompting',       icon: '✏️',  phase: null },
		{ href: '/testing',  label: 'Testing',         icon: '🧪', phase: null },
		{ href: '/admin',    label: 'Admin',            icon: '🔧', phase: null },
		{ href: '/status',   label: 'Status',           icon: '⚡', phase: null },
	];

	// Exact match for '/', prefix match for everything else
	function isActive(href: string, pathname: string): boolean {
		return href === '/' ? pathname === '/' : pathname.startsWith(href);
	}

	const currentLabel = $derived(
		navItems.find(n => isActive(n.href, $page.url.pathname))?.label ?? 'HouseBot'
	);

	// Git info — injected at build time by vite.config.ts
	declare const __GIT_HASH__: string;
	declare const __GIT_DATE__: string;
	declare const __GIT_BRANCH__: string;
	declare const __GIT_COMMIT_URL__: string;

	const gitHash       = __GIT_HASH__;
	const gitDate       = __GIT_DATE__;
	const gitBranch     = __GIT_BRANCH__;
	const gitCommitUrl  = __GIT_COMMIT_URL__;

	// Release version — fetched at runtime from release.json (only present for release installs)
	let releaseVersion = $state<string | null>(null);

	onMount(async () => {
		try {
			const res = await fetch('/admin/api/housebot/version');
			if (res.ok) {
				const data = await res.json();
				if (data.installed_source === 'release') releaseVersion = data.installed ?? null;
			}
		} catch { /* non-fatal */ }
	});
</script>

<svelte:head>
	<title>housebot — {currentLabel}</title>
</svelte:head>

<div class="flex h-screen overflow-hidden">
	<!-- Sidebar -->
	<Navigation.Root layout="sidebar" class="flex flex-col w-60 shrink-0 border-r border-surface-200-800">
		<Navigation.Header class="flex items-center gap-3 px-5 py-5 border-b border-surface-200-800">
			<a href="/" class="flex items-center gap-3">
				<img src="/housebot_icon.png" alt="HouseBot" class="w-8 h-8 shrink-0" />
				<div>
					<p class="font-bold text-base leading-tight">HouseBot</p>
					<p class="text-xs text-surface-400-600">Control Panel</p>
				</div>
			</a>
		</Navigation.Header>

		<Navigation.Content class="flex flex-col flex-1 gap-0.5 p-3 overflow-y-auto">
			<Navigation.Group>
				<Navigation.Label class="text-xs font-semibold uppercase tracking-wider text-surface-400-600 px-2 mb-2 mt-1">
					Menu
				</Navigation.Label>
				{#each navItems as item}
					<Navigation.TriggerAnchor
						href={item.href}
						class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors
						{isActive(item.href, $page.url.pathname)
							? 'bg-primary-500/20 text-primary-400'
							: 'text-surface-600-400 hover:bg-surface-100-900 hover:text-surface-950-50'}"
					>
						<span class="text-base w-5 text-center">{item.icon}</span>
						<span class="flex-1">{item.label}</span>
						{#if item.phase}
							<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-200-800 text-surface-400-600">
								P{item.phase}
							</span>
						{/if}
					</Navigation.TriggerAnchor>
				{/each}
			</Navigation.Group>
		</Navigation.Content>

		<Navigation.Footer class="p-3 border-t border-surface-200-800">
			<button
				onclick={toggleMode}
				class="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-surface-600-400
				hover:bg-surface-100-900 hover:text-surface-950-50 transition-colors"
			>
				<span class="text-base w-5 text-center">{isDark ? '☀️' : '🌙'}</span>
				<span>{isDark ? 'Light mode' : 'Dark mode'}</span>
			</button>
		</Navigation.Footer>
	</Navigation.Root>

	<!-- Main content -->
	<div class="flex flex-col flex-1 overflow-hidden bg-white dark:bg-gray-950">
		<!-- Top bar: hidden on home -->
		{#if $page.url.pathname !== '/'}
		<header class="flex items-center px-6 py-3 border-b border-surface-200-800 shrink-0">
			<a href="/" title="Back to home">
				<img src={isDark ? '/housebot_logo_v2_dark_small.png' : '/housebot_logo_v2_small.png'} alt="Home" class="h-9 w-auto opacity-80 hover:opacity-100 transition-opacity" />
			</a>
			<p class="ml-4 text-sm text-surface-400-600">
				Domestic WhatsApp bot — shopping list, weather, and Google Calendar.
				Runs entirely locally with Ollama + faster-whisper.
			</p>
		</header>
		{/if}

		<!-- Page content -->
		<main class="flex-1 overflow-y-auto p-6">
			{@render children()}
		</main>

		<!-- Footer: release version or git info -->
		{#if releaseVersion}
		<footer class="shrink-0 px-6 py-2 border-t border-surface-200-800 flex items-center justify-between">
			<a
				href="https://github.com/gabnou/house-bot/releases/tag/{releaseVersion}"
				target="_blank"
				rel="noopener noreferrer"
				class="inline-flex items-center gap-1.5 font-mono text-[11px]
				text-surface-400-600 hover:text-primary-400 transition-colors"
			>
				<span>🔖</span>
				<span>{releaseVersion}</span>
			</a>
			<span class="font-mono text-[11px] text-surface-400-600 italic">made for learning purposes, and fixing family headaches</span>
		</footer>
		{:else if gitHash}
		<footer class="shrink-0 px-6 py-2 border-t border-surface-200-800 flex items-center justify-between">
			<a
				href={gitCommitUrl || undefined}
				target="_blank"
				rel="noopener noreferrer"
				class="inline-flex items-center gap-1.5 font-mono text-[11px]
				text-surface-400-600 hover:text-primary-400 transition-colors"
			>
				<span>⎇</span>
				<span>{gitBranch}</span>
				<span class="opacity-50">·</span>
				<span>{gitHash}</span>
				<span class="opacity-50">·</span>
				<span>{gitDate}</span>
			</a>
			<span class="font-mono text-[11px] text-surface-400-600 italic">made for learning purposes, and fixing family headaches</span>
		</footer>
		{/if}
	</div>
</div>