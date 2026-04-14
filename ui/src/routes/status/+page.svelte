<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	// ── Types ──────────────────────────────────────────────────────────────
	interface ServiceStatus {
		up: boolean;
		active_model?: string | null;
	}
	interface ConfigRow {
		key: string;
		label: string;
		value: string;
	}
	interface StatusData {
		fastapi?: ServiceStatus;
		ollama?: ServiceStatus;
		bridge?: ServiceStatus;
		config?: ConfigRow[];
	}

	// ── State ──────────────────────────────────────────────────────────────
	let statusData = $state<StatusData | null>(null);
	let statusError = $state<string | null>(null);
	let statusLoading = $state(true);
	let botOffline = $state(false);
	let lastRefreshed = $state<Date | null>(null);

	let logService = $state('fastapi');
	let logLines = $state<string[]>([]);
	let logLoading = $state(false);
	let logError = $state<string | null>(null);
	let logExists = $state(true);
	let autoRefresh = $state(false);
	let logEl = $state<HTMLElement | null>(null);

	let refreshTimer: ReturnType<typeof setInterval> | null = null;
	let logTimer: ReturnType<typeof setInterval> | null = null;

	const services = [
		{ key: 'fastapi', label: 'FastAPI Bot',       icon: '🐍', hint: ':8000' },
		{ key: 'ollama',  label: 'Ollama LLM',        icon: '🧠', hint: ':11434' },
		{ key: 'bridge',  label: 'WhatsApp Bridge',   icon: '📱', hint: ':3001' },
	] as const;

	const logServices = ['fastapi', 'bridge', 'scheduler', 'watchdog'];

	// ── API helpers ────────────────────────────────────────────────────────
	async function fetchStatus() {
		try {
			statusLoading = true;
			statusError = null;
			botOffline = false;
			const res = await fetch('/admin/api/status');
			const data = await res.json();
			if (res.status === 503 || data._offline) {
				botOffline = true;
				statusData = null;
			} else if (!res.ok) {
				throw new Error(`HTTP ${res.status}`);
			} else {
				statusData = data;
				lastRefreshed = new Date();
			}
		} catch (e: unknown) {
			statusError = e instanceof Error ? e.message : 'Unknown error';
		} finally {
			statusLoading = false;
		}
	}

	async function fetchLogs() {
		logLoading = true;
		logError = null;
		try {
			const res = await fetch(`/admin/api/logs?service=${logService}&lines=200`);
			if (res.status === 503) {
				logLines = [];
				logExists = false;
				return;
			}
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			logLines = data.lines ?? [];
			logExists = data.exists ?? false;
			// Auto-scroll to bottom
			if (autoRefresh) {
				setTimeout(() => { if (logEl) logEl.scrollTop = logEl.scrollHeight; }, 50);
			}
		} catch (e: unknown) {
			logError = e instanceof Error ? e.message : 'Unknown error';
		} finally {
			logLoading = false;
		}
	}

	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			fetchLogs();
			logTimer = setInterval(fetchLogs, 4000);
		} else {
			if (logTimer) { clearInterval(logTimer); logTimer = null; }
		}
	}

	function scrollToBottom() {
		if (logEl) logEl.scrollTop = logEl.scrollHeight;
	}

	$effect(() => {
		// Re-fetch logs when service changes
		logService;
		fetchLogs();
	});

	onMount(() => {
		fetchStatus();
		// Auto-refresh status every 30 s
		refreshTimer = setInterval(fetchStatus, 30_000);
	});

	onDestroy(() => {
		if (refreshTimer) clearInterval(refreshTimer);
		if (logTimer) clearInterval(logTimer);
	});

	// ── Helpers ────────────────────────────────────────────────────────────
	function svcData(key: string): ServiceStatus | undefined {
		return statusData?.[key as keyof StatusData] as ServiceStatus | undefined;
	}

	function colorLine(line: string): string {
		if (/ERROR|CRITICAL/i.test(line)) return 'text-error-400';
		if (/WARNING|WARN/i.test(line)) return 'text-warning-400';
		if (/INFO/i.test(line)) return 'text-surface-300-700';
		if (/DEBUG/i.test(line)) return 'text-surface-500-500';
		return 'text-surface-400-600';
	}
</script>

<div class="space-y-6">

	<!-- ── Header ──────────────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center justify-between">
		<div class="flex items-center gap-4">
			<span class="text-3xl">⚡</span>
			<div>
				<h2 class="text-lg font-bold">System Status</h2>
				<p class="text-xs text-surface-400-600 mt-0.5">
					{lastRefreshed ? `Last refreshed ${lastRefreshed.toLocaleTimeString()}` : 'Checking…'}
				</p>
			</div>
		</div>
		<button
			onclick={fetchStatus}
			class="btn bg-surface-100-900 hover:bg-surface-200-800 text-surface-700-300 text-sm px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
			disabled={statusLoading}
		>
			<span class={statusLoading ? 'animate-spin inline-block' : ''}>↻</span>
			Refresh
		</button>
	</div>

	<!-- ── Service Health Cards ────────────────────────────────────────── -->
	{#if botOffline}
		<!-- Bot server is not running -->
		<div class="card bg-warning-500/10 border border-warning-500/30 rounded-xl p-5 flex items-center gap-4">
			<span class="text-2xl">⚠️</span>
			<div>
				<p class="font-semibold text-warning-400">Bot server is offline</p>
				<p class="text-xs text-surface-400-600 mt-0.5">
					Start FastAPI to see live health data: <code class="font-mono bg-surface-100-900 px-1 py-0.5 rounded text-xs">./housebot.sh start</code>
				</p>
			</div>
		</div>
		<div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
			{#each services as svc}
				<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5">
					<div class="flex items-start justify-between">
						<div class="flex items-center gap-3">
							<span class="text-2xl">{svc.icon}</span>
							<div>
								<p class="font-semibold text-sm">{svc.label}</p>
								<p class="text-xs text-surface-400-600">{svc.hint}</p>
							</div>
						</div>
						<div class="w-2.5 h-2.5 rounded-full bg-surface-400-600 mt-1"></div>
					</div>
					<p class="mt-2 text-xs text-surface-400-600 italic">Unknown</p>
				</div>
			{/each}
		</div>
	{:else if statusError}
		<div class="card bg-error-500/10 border border-error-500/30 rounded-xl p-4 text-error-400 text-sm">
			⚠️ Unexpected error: {statusError}
		</div>
	{:else}
		<div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
			{#each services as svc}
				{@const d = svcData(svc.key)}
				{@const up = statusLoading ? null : (d?.up ?? false)}
				<div class="card bg-surface-50-950 border rounded-xl p-5 transition-colors
					{up === true ? 'border-success-500/40' : up === false ? 'border-error-500/40' : 'border-surface-200-800'}">
					<div class="flex items-start justify-between">
						<div class="flex items-center gap-3">
							<span class="text-2xl">{svc.icon}</span>
							<div>
								<p class="font-semibold text-sm">{svc.label}</p>
								<p class="text-xs text-surface-400-600">{svc.hint}</p>
							</div>
						</div>
						<!-- Status dot -->
						{#if statusLoading}
							<div class="w-2.5 h-2.5 rounded-full bg-surface-400-600 animate-pulse mt-1"></div>
						{:else if up}
							<div class="w-2.5 h-2.5 rounded-full bg-success-500 mt-1 shadow-[0_0_6px_2px_rgba(34,197,94,.4)]"></div>
						{:else}
							<div class="w-2.5 h-2.5 rounded-full bg-error-500 mt-1 shadow-[0_0_6px_2px_rgba(239,68,68,.4)]"></div>
						{/if}
					</div>
					<!-- Sub-info -->
					{#if svc.key === 'ollama' && d?.active_model}
						<p class="mt-3 text-xs font-mono bg-surface-100-900 px-2 py-1 rounded text-primary-400 truncate">
							{d.active_model}
						</p>
					{:else if svc.key === 'ollama' && up === true && !d?.active_model}
						<p class="mt-3 text-xs text-surface-400-600 italic">No model loaded in memory</p>
					{/if}
					{#if !statusLoading}
						<p class="mt-2 text-xs font-medium {up ? 'text-success-500' : 'text-error-400'}">
							{up ? 'Online' : 'Offline'}
						</p>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	<!-- ── Config Summary ──────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-4 border-b border-surface-200-800">
			<h3 class="font-semibold text-sm">Configuration</h3>
			<p class="text-xs text-surface-400-600 mt-0.5">Current <code class="font-mono">.env</code> values (no secrets shown)</p>
		</div>
		{#if statusLoading}
			<div class="p-6 text-center text-surface-400-600 text-sm">Loading…</div>
		{:else if botOffline}
			<div class="p-6 text-center text-surface-400-600 text-sm italic">Bot server offline — config unavailable</div>
		{:else if statusData?.config && statusData.config.length > 0}
			<table class="w-full text-sm">
				<tbody>
					{#each statusData.config as row, i}
						<tr class="{i % 2 === 0 ? 'bg-surface-50-950' : 'bg-surface-100-900/40'}">
							<td class="px-5 py-2.5 font-medium text-surface-600-400 w-44">{row.label}</td>
							<td class="px-5 py-2.5">
								{#if row.value}
									<span class="font-mono text-xs bg-surface-100-900 px-1.5 py-0.5 rounded text-primary-400">
										{row.value}
									</span>
								{:else}
									<span class="text-surface-400-600 italic text-xs">not set</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{:else}
			<div class="p-6 text-center text-surface-400-600 text-sm italic">No config data</div>
		{/if}
	</div>

	<!-- ── Log Viewer ─────────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<!-- Log toolbar -->
		<div class="px-5 py-4 border-b border-surface-200-800 flex flex-wrap items-center gap-3">
			<h3 class="font-semibold text-sm mr-auto">Logs</h3>

			<!-- Service selector -->
			<div class="flex gap-1.5">
				{#each logServices as s}
					<button
						onclick={() => { logService = s; }}
						class="px-3 py-1 rounded-md text-xs font-medium transition-colors
						{logService === s
							? 'bg-primary-500/20 text-primary-400 ring-1 ring-primary-500/40'
							: 'bg-surface-100-900 text-surface-500-500 hover:bg-surface-200-800'}"
					>
						{s}
					</button>
				{/each}
			</div>

			<!-- Controls -->
			<button
				onclick={fetchLogs}
				class="px-3 py-1 rounded-md text-xs bg-surface-100-900 hover:bg-surface-200-800 text-surface-600-400 transition-colors"
				disabled={logLoading}
			>
				{logLoading ? '…' : '↻ Refresh'}
			</button>
			<button
				onclick={toggleAutoRefresh}
				class="px-3 py-1 rounded-md text-xs font-medium transition-colors
				{autoRefresh
					? 'bg-success-500/20 text-success-500 ring-1 ring-success-500/30'
					: 'bg-surface-100-900 text-surface-500-500 hover:bg-surface-200-800'}"
			>
				{autoRefresh ? '⏸ Live' : '▶ Live'}
			</button>
			<button
				onclick={scrollToBottom}
				class="px-3 py-1 rounded-md text-xs bg-surface-100-900 hover:bg-surface-200-800 text-surface-600-400 transition-colors"
			>
				↓ Bottom
			</button>
		</div>

		<!-- Log body -->
		{#if botOffline}
			<div class="p-8 text-center text-surface-400-600 text-sm italic bg-[#0d0d0f]">
				Bot server offline — logs unavailable.
			</div>
		{:else if logError}
			<div class="p-4 text-error-400 text-xs">{logError}</div>
		{:else if !logExists}
			<div class="p-6 text-center text-surface-400-600 text-sm italic">
				Log file for <strong>{logService}</strong> not found yet.
			</div>
		{:else}
			<div
				bind:this={logEl}
				class="h-96 overflow-y-auto p-4 font-mono text-xs leading-relaxed space-y-0.5 bg-[#0d0d0f] scrollbar-thin"
			>
				{#each logLines as line}
					<div class="{colorLine(line)} whitespace-pre-wrap break-all">{line}</div>
				{:else}
					<div class="text-surface-500-500 italic">No log entries.</div>
				{/each}
			</div>
		{/if}
	</div>

</div>

