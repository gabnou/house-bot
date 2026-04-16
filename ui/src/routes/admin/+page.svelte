<script lang="ts">
	import { onMount } from 'svelte';

	// ── Types ──────────────────────────────────────────────────────────────
	interface OllamaModel {
		name: string;
		size_gb: number;
		modified: string;
		family: string;
		params: string;
	}

	// ── Model Manager state ────────────────────────────────────────────────
	let models = $state<OllamaModel[]>([]);
	let configured = $state('');
	let activeModel = $state<string | null>(null);
	let modelsLoading = $state(true);
	let modelsError = $state<string | null>(null);
	let switchingTo = $state<string | null>(null);
	let switchMsg = $state<{ ok: boolean; text: string } | null>(null);

	// ── Service Control state ──────────────────────────────────────────────
	type SvcKey = 'fastapi' | 'bridge' | 'scheduler';
	let svcBusy = $state<Record<SvcKey, boolean>>({ fastapi: false, bridge: false, scheduler: false });
	let svcMsg = $state<{ ok: boolean; text: string } | null>(null);

	// ── API helpers ────────────────────────────────────────────────────────
	async function fetchModels() {
		modelsLoading = true;
		modelsError = null;
		try {
			const [mRes, aRes] = await Promise.all([
				fetch('/admin/api/ollama/models'),
				fetch('/admin/api/ollama/active'),
			]);
			if (!mRes.ok) throw new Error(`Models: HTTP ${mRes.status}`);
			const mData = await mRes.json();
			models = mData.models ?? [];
			configured = mData.configured ?? '';
			if (aRes.ok) {
				const aData = await aRes.json();
				activeModel = aData.active ?? null;
			}
		} catch (e: unknown) {
			modelsError = e instanceof Error ? e.message : 'Unknown error';
		} finally {
			modelsLoading = false;
		}
	}

	async function switchModel(name: string) {
		if (switchingTo) return;
		switchingTo = name;
		switchMsg = null;
		try {
			const res = await fetch('/admin/api/ollama/switch', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: name }),
			});
			const data = await res.json();
			if (res.ok && data.ok) {
				configured = name;
				switchMsg = { ok: true, text: `Switched to ${name}. Model loads on next message.` };
			} else {
				switchMsg = { ok: false, text: data.detail ?? 'Switch failed' };
			}
		} catch (e: unknown) {
			switchMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			switchingTo = null;
		}
	}

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

	// ── Google Account state ───────────────────────────────────────────────
	type GoogleStatus = 'unknown' | 'valid' | 'missing' | 'expired' | 'invalid';
	let googleStatus = $state<GoogleStatus>('unknown');
	let googleExpiry = $state<string | null>(null);
	let googleHasRefresh = $state(false);
	let googleCredsExist = $state(true);
	let googleFlowRunning = $state(false);
	let googleAuthUrl = $state<string | null>(null);
	let googleLoading = $state(false);
	let googleMsg = $state<{ ok: boolean; text: string } | null>(null);

	let _googlePollTimer: ReturnType<typeof setInterval> | null = null;

	function _startPolling() {
		if (_googlePollTimer) return;
		_googlePollTimer = setInterval(async () => {
			await loadGoogleStatus();
			if (googleStatus === 'valid') {
				_stopPolling();
				googleAuthUrl = null;
				googleFlowRunning = false;
				googleMsg = { ok: true, text: 'Token saved — authorization complete!' };
			}
		}, 3000);
	}

	function _stopPolling() {
		if (_googlePollTimer) { clearInterval(_googlePollTimer); _googlePollTimer = null; }
	}

	async function loadGoogleStatus() {
		try {
			const res = await fetch('/admin/api/google-auth/status');
			if (res.ok) {
				const data = await res.json();
				googleStatus = data.status ?? 'unknown';
				googleExpiry = data.expiry ?? null;
				googleHasRefresh = data.has_refresh ?? false;
				googleCredsExist = data.credentials_exist ?? true;
				googleFlowRunning = data.flow_running ?? false;
			}
		} catch { /* non-fatal */ }
	}

	async function startGoogleAuth() {
		googleLoading = true;
		googleMsg = null;
		googleAuthUrl = null;
		try {
			const res = await fetch('/admin/api/google-auth', { method: 'POST' });
			const data = await res.json();
			if (res.ok && data.ok) {
				googleAuthUrl = data.auth_url;
				googleFlowRunning = true;
				window.open(data.auth_url, '_blank', 'noopener,noreferrer');
				_startPolling();
			} else {
				googleMsg = { ok: false, text: data.detail ?? 'Failed to start OAuth flow' };
			}
		} catch (e: unknown) {
			googleMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			googleLoading = false;
		}
	}

	async function refreshGoogleToken() {
		googleLoading = true;
		googleMsg = null;
		try {
			const res = await fetch('/admin/api/google-auth/refresh', { method: 'POST' });
			const data = await res.json();
			if (res.ok && data.ok) {
				googleMsg = { ok: true, text: 'Token refreshed successfully.' };
				await loadGoogleStatus();
			} else {
				googleMsg = { ok: false, text: data.detail ?? 'Refresh failed' };
			}
		} catch (e: unknown) {
			googleMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			googleLoading = false;
		}
	}

	async function revokeGoogleToken() {
		googleLoading = true;
		googleMsg = null;
		try {
			const res = await fetch('/admin/api/google-auth', { method: 'DELETE' });
			const data = await res.json();
			if (res.ok) {
				googleMsg = { ok: true, text: 'Token revoked — re-authorization required.' };
				googleStatus = 'missing';
				googleExpiry = null;
				googleAuthUrl = null;
			} else {
				googleMsg = { ok: false, text: data.detail ?? 'Revoke failed' };
			}
		} catch (e: unknown) {
			googleMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			googleLoading = false;
		}
	}

	async function pollGoogleStatus() {
		googleMsg = null;
		await loadGoogleStatus();
		if (googleStatus === 'valid') {
			googleAuthUrl = null;
			googleFlowRunning = false;
			googleMsg = { ok: true, text: 'Token saved — authorization complete!' };
		} else if (googleFlowRunning) {
			googleMsg = { ok: false, text: 'Not yet — complete the sign-in in the browser tab.' };
		}
	}

	onMount(() => { fetchModels(); loadGoogleStatus(); });
</script>

<div class="space-y-6">

	<!-- Header -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center gap-4">
		<span class="text-3xl">🔧</span>
		<div>
			<h2 class="text-lg font-bold">Admin</h2>
			<p class="text-xs text-surface-400-600 mt-0.5">Service control, model management, account maintenance, and software updates.</p>
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

	<!-- ── Model Manager ───────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>🧠</span>
			<h3 class="font-semibold text-sm">Model Manager</h3>
			<button
				onclick={fetchModels}
				disabled={modelsLoading}
				class="ml-auto text-xs px-2 py-1 rounded bg-surface-100-900 hover:bg-surface-200-800
				text-surface-500-500 transition-colors disabled:opacity-40"
			>
				{modelsLoading ? '…' : '↻ Refresh'}
			</button>
		</div>
		<div class="p-5">
			{#if modelsError}
				<div class="text-xs text-error-400 bg-error-500/10 px-3 py-2 rounded-lg">
					{modelsError.includes('502') || modelsError.includes('503')
						? '⚠️ Ollama is offline' : modelsError}
				</div>
			{:else if modelsLoading}
				<div class="space-y-2">
					{#each [1,2,3] as _}
						<div class="h-12 rounded-lg bg-surface-100-900 animate-pulse"></div>
					{/each}
				</div>
			{:else if models.length === 0}
				<p class="text-sm text-surface-400-600 italic">
					No models found. Pull one with <code class="font-mono text-xs">ollama pull &lt;model&gt;</code>
				</p>
			{:else}
				<div class="space-y-2">
					{#each models as m}
						{@const isCfg    = m.name === configured}
						{@const isActive = m.name === activeModel}
						<div class="flex items-center gap-3 px-4 py-3 rounded-xl border transition-colors
							{isCfg
								? 'border-primary-500/40 bg-primary-500/5'
								: 'border-surface-200-800 bg-surface-100-900/50'}">

							<!-- Status dot -->
							<div class="w-2 h-2 rounded-full shrink-0
								{isActive
									? 'bg-success-500 shadow-[0_0_5px_1px_rgba(34,197,94,.5)]'
									: isCfg ? 'bg-primary-400' : 'bg-surface-300-700'}">
							</div>

							<!-- Name + meta -->
							<div class="flex-1 min-w-0">
								<p class="font-mono text-xs font-medium truncate">{m.name}</p>
								<p class="text-[10px] text-surface-400-600 mt-0.5">
									{m.size_gb} GB
									{#if m.params} · {m.params}{/if}
									{#if m.family} · {m.family}{/if}
								</p>
							</div>

							<!-- Badges -->
							{#if isActive}
								<span class="text-[10px] font-medium px-1.5 py-0.5 rounded bg-success-500/20 text-success-500 shrink-0">in memory</span>
							{/if}
							{#if isCfg}
								<span class="text-[10px] font-medium px-1.5 py-0.5 rounded bg-primary-500/20 text-primary-400 shrink-0">configured</span>
							{/if}

							<!-- Switch button -->
							<button
								onclick={() => switchModel(m.name)}
								disabled={isCfg || !!switchingTo}
								class="text-xs px-3 py-1.5 rounded-lg font-medium transition-colors shrink-0
								{isCfg
									? 'bg-surface-200-800 text-surface-400-600 cursor-default'
									: 'bg-primary-500/15 text-primary-400 hover:bg-primary-500/30'}
								disabled:opacity-40 disabled:cursor-not-allowed"
							>
								{switchingTo === m.name ? '…' : isCfg ? 'Active' : 'Use'}
							</button>
						</div>
					{/each}
				</div>

				{#if switchMsg}
					<div class="mt-3 text-xs px-3 py-2 rounded-lg
						{switchMsg.ok ? 'bg-success-500/10 text-success-500' : 'bg-error-500/10 text-error-400'}">
						{switchMsg.text}
					</div>
				{/if}

				<p class="mt-3 text-[10px] text-surface-400-600">
					<span class="inline-block w-2 h-2 rounded-full bg-success-500 mr-1 align-middle"></span>in memory
					&nbsp;&nbsp;
					<span class="inline-block w-2 h-2 rounded-full bg-primary-400 mr-1 align-middle"></span>configured in .env
				</p>
			{/if}
		</div>
	</div>

	<!-- ── WhatsApp / Baileys (Phase 5) ───────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>📱</span>
			<h3 class="font-semibold text-sm">WhatsApp / Baileys</h3>
		</div>
		<div class="p-5 flex flex-col sm:flex-row gap-3">
			{#each [
				{ label: 'Show QR Code',     icon: '📷', desc: 'Re-pair device' },
				{ label: 'Clear Auth State', icon: '🗑️',  desc: 'Full reset + re-pair' },
				{ label: 'Detect JIDs',      icon: '👤', desc: 'Auto-detect partner' },
			] as action}
				<div class="flex-1 flex items-center gap-3 px-4 py-3 rounded-xl border border-surface-200-800 bg-surface-100-900 opacity-50">
					<span class="text-xl">{action.icon}</span>
					<div>
						<p class="font-semibold text-xs">{action.label}</p>
						<p class="text-[10px] text-surface-400-600">{action.desc}</p>
					</div>
				</div>
			{/each}
		</div>
	</div>

	<!-- ── Google Account ────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>🔑</span>
			<h3 class="font-semibold text-sm">Google Account</h3>
			<button
				onclick={loadGoogleStatus}
				class="ml-auto text-xs px-2 py-1 rounded bg-surface-100-900 hover:bg-surface-200-800
				text-surface-500-500 transition-colors"
			>↻ Refresh</button>
		</div>
		<div class="p-5 space-y-4">

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

			<!-- Pending auth banner -->
			{#if googleFlowRunning && googleAuthUrl}
				<div class="flex items-start gap-3 px-4 py-3 rounded-xl border border-primary-500/30 bg-primary-500/5">
					<span class="text-lg mt-0.5">🌐</span>
					<div class="flex-1 min-w-0">
						<p class="text-xs font-semibold text-primary-400">Waiting for authorization…</p>
						<p class="text-xs text-surface-400-600 mt-1">
							Complete the sign-in in the browser tab. If it didn't open,
							<a href={googleAuthUrl} target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">click here</a>.
						</p>
					</div>
					<button
						onclick={pollGoogleStatus}
						class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium bg-primary-500/20 text-primary-400
						hover:bg-primary-500/30 transition-colors"
					>Check again</button>
				</div>
			{/if}

			<!-- Action buttons -->
			<div class="flex flex-wrap gap-2">
				<!-- Create / Re-authorize -->
				<button
					onclick={startGoogleAuth}
					disabled={googleLoading || googleFlowRunning || !googleCredsExist}
					class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
					{googleStatus === 'valid'
						? 'bg-primary-500/15 text-primary-400 hover:bg-primary-500/30'
						: 'bg-primary-500/20 text-primary-400 hover:bg-primary-500/30 border border-primary-500/40'}
					disabled:opacity-40 disabled:cursor-not-allowed"
				>
					{googleLoading ? '…' : googleFlowRunning ? '⏳ Waiting…' :
					 googleStatus === 'valid' ? '🔑 Re-authorize' : '🔑 Create Token'}
				</button>

				<!-- Refresh (only when expired with refresh token) -->
				{#if googleStatus === 'expired' && googleHasRefresh}
					<button
						onclick={refreshGoogleToken}
						disabled={googleLoading}
						class="px-3 py-1.5 rounded-lg text-xs font-medium bg-success-500/15 text-success-500
						hover:bg-success-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
					>
						{googleLoading ? '…' : '🔄 Refresh Token'}
					</button>
				{/if}

				<!-- Token Status -->
				<button
					onclick={loadGoogleStatus}
					class="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-100-900 hover:bg-surface-200-800
					text-surface-500-500 transition-colors"
				>
					✅ Token Status
				</button>

				<!-- Revoke -->
				{#if googleStatus !== 'missing'}
					<button
						onclick={revokeGoogleToken}
						disabled={googleLoading}
						class="px-3 py-1.5 rounded-lg text-xs font-medium bg-error-500/15 text-error-400
						hover:bg-error-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
					>
						{googleLoading ? '…' : '🚫 Revoke Token'}
					</button>
				{/if}
			</div>

			{#if !googleCredsExist}
				<p class="text-xs text-warning-400">
					⚠️ <span class="font-mono">creds/client_google_api_calendar.json</span> not found —
					place your Google OAuth credentials file there first.
				</p>
			{/if}

			{#if googleMsg}
				<div class="text-xs px-3 py-2 rounded-lg
					{googleMsg.ok ? 'bg-success-500/10 text-success-500' : 'bg-error-500/10 text-error-400'}">
					{googleMsg.text}
				</div>
			{/if}

		</div>
	</div>

	<!-- ── Software Update (Phase 5) ──────────────────────────────────── -->
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
