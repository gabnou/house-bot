<script lang="ts">
	import { onMount } from 'svelte';

	// ── Service Control state ──────────────────────────────────────────────
	type SvcKey = 'fastapi' | 'bridge' | 'scheduler';
	let svcBusy = $state<Record<SvcKey, boolean>>({ fastapi: false, bridge: false, scheduler: false });
	let svcMsg = $state<{ ok: boolean; text: string } | null>(null);

	async function serviceAction(
		service: SvcKey | 'all',
		action: 'restart' | 'stop' | 'start' | 'restart-all' | 'stop-all'
	) {
		svcMsg = null;
		if (service !== 'all') {
			svcBusy[service] = true;
		} else {
			svcBusy.fastapi = true; svcBusy.bridge = true; svcBusy.scheduler = true;
		}
		try {
			const url = service === 'all'
				? `/admin/api/services/${action}`
				: `/admin/api/services/${service}/${action}`;
			const res = await fetch(url, { method: 'POST' });
			const data = await res.json();
			svcMsg = data.ok
				? { ok: true,  text: `${action} → ${service}: done` }
				: { ok: false, text: data.detail ?? 'Action failed' };
		} catch (e: unknown) {
			svcMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			if (service !== 'all') {
				svcBusy[service] = false;
			} else {
				svcBusy.fastapi = false; svcBusy.bridge = false; svcBusy.scheduler = false;
			}
		}
	}

	// ── Google Account state ──────────────────────────────────────────────
	type GoogleStatus = 'unknown' | 'valid' | 'missing' | 'expired' | 'invalid';
	let googleStatus = $state<GoogleStatus>('unknown');
	let googleExpiry = $state<string | null>(null);
	let googleConfiguredCalendar = $state('');

	async function loadGoogleStatus() {
		try {
			const res = await fetch('/admin/api/google-auth/status');
			if (res.ok) {
				const data = await res.json();
				googleStatus = data.status ?? 'unknown';
				googleExpiry = data.expiry ?? null;
				googleConfiguredCalendar = data.configured_calendar ?? '';
			}
		} catch { /* non-fatal */ }
	}

	// ── Ollama AI Engine state ─────────────────────────────────────────────
	let ollamaUp = $state<boolean | null>(null);
	let ollamaActiveModel = $state<string | null>(null);
	let ollamaConfiguredModel = $state('');
	let ollamaBusy = $state(false);
	let ollamaMsg = $state<{ ok: boolean; text: string } | null>(null);

	async function loadOllamaStatus() {
		try {
			const res = await fetch('/admin/api/ollama/status');
			if (res.ok) {
				const data = await res.json();
				ollamaUp = data.up ?? false;
				ollamaActiveModel = data.active_model ?? null;
				ollamaConfiguredModel = data.configured_model ?? '';
			}
		} catch { /* non-fatal */ }
	}

	async function restartOllama() {
		ollamaBusy = true;
		ollamaMsg = null;
		try {
			const res = await fetch('/admin/api/ollama/restart', { method: 'POST' });
			const data = await res.json();
			ollamaMsg = data.ok
				? { ok: true, text: 'Restart initiated — Ollama will be back in a few seconds.' }
				: { ok: false, text: data.detail ?? 'Restart failed.' };
		} catch (e: unknown) {
			ollamaMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			ollamaBusy = false;
		}
	}

	onMount(() => { loadGoogleStatus(); loadOllamaStatus(); });
</script>

<div class="space-y-6">

	<!-- Header -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center gap-4">
		<span class="text-3xl">🔧</span>
		<div>
			<h2 class="text-lg font-bold">Admin</h2>
			<p class="text-xs text-surface-400-600 mt-0.5">Service control, account maintenance, and software updates.</p>
		</div>
	</div>

	<!-- ── Service Control ─────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>⚡</span>
			<h3 class="font-semibold text-sm">Service Control</h3>
		</div>
		<div class="p-5 space-y-4">
			{#each ([
				{ key: 'fastapi'   as SvcKey, label: 'FastAPI Bot',     icon: '🐍' },
				{ key: 'bridge'    as SvcKey, label: 'WhatsApp Bridge', icon: '📱' },
				{ key: 'scheduler' as SvcKey, label: 'Scheduler',       icon: '⏰' },
			]) as svc}
				<div class="flex items-center gap-3">
					<span class="text-lg w-6 text-center">{svc.icon}</span>
					<span class="text-sm font-medium flex-1">{svc.label}</span>
					{#each (['restart', 'stop', 'start'] as const) as action}
						<button
							onclick={() => serviceAction(svc.key, action)}
							disabled={svcBusy[svc.key]}
							class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
							{action === 'restart' ? 'bg-primary-500/15 text-primary-400 hover:bg-primary-500/30' :
							 action === 'stop'    ? 'bg-error-500/15 text-error-400 hover:bg-error-500/25' :
							                       'bg-success-500/15 text-success-500 hover:bg-success-500/25'}
							disabled:opacity-40 disabled:cursor-not-allowed"
						>
							{svcBusy[svc.key] ? '…' :
							 action === 'restart' ? '🔄 Restart' :
							 action === 'stop'    ? '⏹ Stop' : '▶ Start'}
						</button>
					{/each}
				</div>
			{/each}

			<!-- Bulk actions -->
			<div class="pt-3 border-t border-surface-100-900 flex gap-3">
				<button
					onclick={() => serviceAction('all', 'restart-all')}
					disabled={svcBusy.fastapi}
					class="flex-1 py-2 rounded-lg text-xs font-medium bg-primary-500/15 text-primary-400
					hover:bg-primary-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
				>
					🔄 Restart All
				</button>
				<button
					onclick={() => serviceAction('all', 'stop-all')}
					disabled={svcBusy.fastapi}
					class="flex-1 py-2 rounded-lg text-xs font-medium bg-error-500/15 text-error-400
					hover:bg-error-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
				>
					⏹ Stop Bridge + Scheduler
				</button>
			</div>

			{#if svcMsg}
				<div class="text-xs px-3 py-2 rounded-lg {svcMsg.ok ? 'bg-success-500/10 text-success-500' : 'bg-error-500/10 text-error-400'}">
					{svcMsg.text}
				</div>
			{/if}
		</div>
	</div>

	<!-- ── Ollama AI Engine ──────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>🧠</span>
			<h3 class="font-semibold text-sm">Ollama AI Engine</h3>
			<button
				onclick={loadOllamaStatus}
				class="ml-auto text-xs px-2 py-1 rounded bg-surface-100-900 hover:bg-surface-200-800
				text-surface-500-500 transition-colors"
			>↻ Refresh</button>
		</div>
		<div class="p-5 space-y-3">
			<!-- Status + Restart row -->
			<div class="flex items-center gap-3 px-4 py-3 rounded-xl border
				{ollamaUp === true  ? 'border-success-500/40 bg-success-500/5' :
				 ollamaUp === false ? 'border-error-500/40 bg-error-500/5' :
				                     'border-surface-200-800 bg-surface-100-900/50'}">
				<div class="w-2.5 h-2.5 rounded-full shrink-0
					{ollamaUp === true  ? 'bg-success-500' :
					 ollamaUp === false ? 'bg-error-400' : 'bg-surface-400-600'}"></div>
				<div class="flex-1">
					<p class="text-xs font-semibold">
						{ollamaUp === null ? 'Checking…' : ollamaUp ? 'Running' : 'Not reachable'}
					</p>
					{#if ollamaActiveModel}
						<p class="text-[10px] text-surface-400-600 mt-0.5">Active: {ollamaActiveModel}</p>
					{:else if ollamaConfiguredModel}
						<p class="text-[10px] text-surface-400-600 mt-0.5">Configured: {ollamaConfiguredModel}</p>
					{/if}
				</div>
				<button
					onclick={restartOllama}
					disabled={ollamaBusy}
					class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium
					bg-primary-500/15 text-primary-400 hover:bg-primary-500/30
					transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
				>
					{ollamaBusy ? '…' : '🔄 Restart'}
				</button>
			</div>

			{#if ollamaMsg}
				<div class="text-xs px-3 py-2 rounded-lg {ollamaMsg.ok ? 'bg-success-500/10 text-success-500' : 'bg-error-500/10 text-error-400'}">
					{ollamaMsg.text}
				</div>
			{/if}

			<!-- Disclaimer -->
			<p class="text-[11px] text-surface-400-600">
				Use Restart only if Ollama is unresponsive or unreachable. To switch to a different model, go to the
				<a href="/config" class="text-primary-400 hover:underline">Configuration page</a>.
			</p>
		</div>
	</div>

	<!-- ── Google Calendar ──────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>🔑</span>
			<h3 class="font-semibold text-sm">Google Calendar</h3>
			<button
				onclick={loadGoogleStatus}
				class="ml-auto text-xs px-2 py-1 rounded bg-surface-100-900 hover:bg-surface-200-800
				text-surface-500-500 transition-colors"
			>↻ Refresh</button>
		</div>
		<div class="p-5 space-y-3">
			<!-- Token status row -->
			<div class="flex items-center gap-3 px-4 py-3 rounded-xl border
				{googleStatus === 'valid'   ? 'border-success-500/40 bg-success-500/5' :
				 googleStatus === 'expired' ? 'border-warning-500/40 bg-warning-500/5' :
				                             'border-surface-200-800 bg-surface-100-900/50'}">
				<div class="w-2.5 h-2.5 rounded-full shrink-0
					{googleStatus === 'valid'   ? 'bg-success-500' :
					 googleStatus === 'expired' ? 'bg-warning-400' :
					 googleStatus === 'missing' ? 'bg-error-400'   : 'bg-surface-400-600'}"></div>
				<div class="flex-1">
					<p class="text-xs font-semibold capitalize">
						Token: {googleStatus === 'unknown' ? 'checking…' : googleStatus}
					</p>
					{#if googleExpiry}
						<p class="text-[10px] text-surface-400-600 mt-0.5">Expiry: {googleExpiry}</p>
					{/if}
				</div>
			</div>
			<!-- Configured calendar name -->
			{#if googleConfiguredCalendar}
				<div class="flex items-center gap-2 px-4 py-2 rounded-lg border border-surface-200-800 bg-surface-100-900/50">
					<span class="text-sm">📅</span>
					<p class="text-xs text-surface-400-600">Calendar: <span class="font-medium text-surface-900-50">{googleConfiguredCalendar}</span></p>
				</div>
			{/if}
			<p class="text-xs text-surface-400-600">
				To change account or calendar, use the
				<a href="/config" class="text-primary-400 hover:underline">Configuration page</a>.
			</p>
		</div>
	</div>

	<!-- ── Software Update (Phase 5) ────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>🔄</span>
			<h3 class="font-semibold text-sm">Software Update</h3>
		</div>
		<div class="p-5 flex items-center gap-4">
			<div class="flex-1">
				<p class="text-sm text-surface-400-600">Pull the latest changes from git, rebuild the UI, restart services automatically.</p>
				<p class="font-mono text-xs text-surface-500-500 mt-1">git pull → ui-build → restart</p>
			</div>
			<button class="px-4 py-2 rounded-lg text-sm font-medium bg-primary-500/20 text-primary-400 opacity-40 cursor-not-allowed" disabled>
				Update Now
			</button>
		</div>
	</div>

</div>
