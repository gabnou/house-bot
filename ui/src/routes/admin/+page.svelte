<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	// ── HouseBot Management state ──────────────────────────────────────────────
	type HousebotAction = 'stop' | 'restart';
	let svcPending = $state<HousebotAction | null>(null);
	let svcBusy = $state(false);
	let svcMsg = $state<{ ok: boolean; text: string } | null>(null);
	let svcLog = $state<string[]>([]);
	let svcLogOpen = $state(false);

	async function fetchSvcLogs(): Promise<string[]> {
		const svcs = ['fastapi', 'bridge', 'scheduler'];
		const results = await Promise.all(
			svcs.map(s =>
				fetch(`/admin/api/logs?service=${s}&lines=20`)
					.then(r => r.json())
					.then((d: { lines: string[] }) => d.lines.map(l => `[${s}] ${l}`))
					.catch(() => [] as string[])
			)
		);
		return results.flat();
	}

	async function executeAction(action: HousebotAction) {
		svcPending = null;
		svcBusy = true;
		svcMsg = null;
		svcLog = [];
		svcLogOpen = false;
		try {
			const url = action === 'restart'
				? '/admin/api/services/restart-all'
				: '/admin/api/services/stop-all';
			const res = await fetch(url, { method: 'POST' });
			const data = await res.json();
			if (data.ok) {
				const waitMsg = action === 'restart'
					? 'HouseBot restart initiated. Waiting for services…'
					: 'HouseBot stopped. To start again, run: bash housebot.sh start';
				svcMsg = { ok: true, text: waitMsg };
				// For restart, wait for housebot.sh to complete (≈10s) before fetching logs
				if (action === 'restart') await new Promise(r => setTimeout(r, 10000));
			} else {
				svcMsg = { ok: false, text: data.detail ?? 'Action failed' };
			}
			svcLog = await fetchSvcLogs();
		} catch (e: unknown) {
			svcMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			svcBusy = false;
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

	// ── Ollama update checker ──────────────────────────────────────────────
	let ollamaInstalledVer = $state<string | null>(null);
	let ollamaLatestVer = $state<string | null>(null);
	let ollamaUpdateAvailable = $state<boolean | null>(null);
	let ollamaVersionBusy = $state(false);

	// upgrade progress
	type UpgradeStatus = 'idle' | 'running' | 'done' | 'failed';
	let upgradeStatus = $state<UpgradeStatus>('idle');
	let upgradeLog = $state<string[]>([]);
	let upgradeExitCode = $state<number | null>(null);
	let upgradePollTimer = $state<ReturnType<typeof setInterval> | null>(null);

	function stopUpgradePoll() {
		if (upgradePollTimer !== null) { clearInterval(upgradePollTimer); upgradePollTimer = null; }
	}

	async function pollUpgradeStatus() {
		try {
			const res = await fetch('/admin/api/ollama/upgrade/status');
			if (!res.ok) return;
			const data = await res.json();
			upgradeStatus = data.status ?? 'idle';
			upgradeLog = data.log ?? [];
			upgradeExitCode = data.exit_code ?? null;
			if (upgradeStatus === 'done' || upgradeStatus === 'failed') {
				stopUpgradePoll();
				if (upgradeStatus === 'done') {
					// reset version state so user re-checks after upgrade
					ollamaUpdateAvailable = null;
					ollamaInstalledVer = null;
					ollamaLatestVer = null;
				}
			}
		} catch { /* non-fatal */ }
	}

	async function checkOllamaUpdate() {
		ollamaVersionBusy = true;
		try {
			const res = await fetch('/admin/api/ollama/version');
			if (res.ok) {
				const data = await res.json();
				ollamaInstalledVer = data.installed ?? null;
				ollamaLatestVer = data.latest ?? null;
				ollamaUpdateAvailable = data.update_available ?? false;
			}
		} catch { /* non-fatal */ } finally {
			ollamaVersionBusy = false;
		}
	}

	async function upgradeOllama() {
		upgradeLog = [];
		upgradeStatus = 'running';
		upgradeExitCode = null;
		try {
			const res = await fetch('/admin/api/ollama/upgrade', { method: 'POST' });
			const data = await res.json();
			if (!data.ok) {
				upgradeStatus = 'failed';
				upgradeLog = [data.message ?? 'Upgrade failed.'];
				return;
			}
			// start polling every 2s
			stopUpgradePoll();
			upgradePollTimer = setInterval(pollUpgradeStatus, 2000);
		} catch (e: unknown) {
			upgradeStatus = 'failed';
			upgradeLog = [e instanceof Error ? e.message : 'Request failed'];
		}
	}

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

	// ── HouseBot Software Update state ─────────────────────────────────────
	let hbInstalledTag = $state<string | null>(null);
	let hbLatestTag = $state<string | null>(null);
	let hbUpdateAvailable = $state<boolean | null>(null);
	let hbVersionBusy = $state(false);
	let hbRepoUrl = $state('https://github.com/gabnou/house-bot');

	type HbUpgradeStatus = 'idle' | 'running' | 'done' | 'failed';
	let hbUpgradeStatus = $state<HbUpgradeStatus>('idle');
	let hbUpgradeLog = $state<string[]>([]);
	let hbUpgradeExitCode = $state<number | null>(null);
	let hbPollTimer = $state<ReturnType<typeof setInterval> | null>(null);

	function stopHbPoll() {
		if (hbPollTimer !== null) { clearInterval(hbPollTimer); hbPollTimer = null; }
	}

	async function pollHbUpgradeStatus() {
		try {
			const res = await fetch('/admin/api/housebot/upgrade/status');
			if (!res.ok) return;
			const data = await res.json();
			hbUpgradeStatus = data.status ?? 'idle';
			hbUpgradeLog = data.log ?? [];
			hbUpgradeExitCode = data.exit_code ?? null;
			if (hbUpgradeStatus === 'done' || hbUpgradeStatus === 'failed') {
				stopHbPoll();
				if (hbUpgradeStatus === 'done') {
					hbUpdateAvailable = null;
					hbInstalledTag = null;
					hbLatestTag = null;
				}
			}
		} catch { /* non-fatal */ }
	}

	async function checkHousebotUpdate() {
		hbVersionBusy = true;
		try {
			const res = await fetch('/admin/api/housebot/version');
			if (res.ok) {
				const data = await res.json();
				hbInstalledTag = data.installed ?? null;
				hbLatestTag = data.latest ?? null;
				hbUpdateAvailable = data.update_available ?? false;
				hbRepoUrl = data.repo_url ?? hbRepoUrl;
			}
		} catch { /* non-fatal */ } finally {
			hbVersionBusy = false;
		}
	}

	async function upgradeHousebot() {
		hbUpgradeLog = [];
		hbUpgradeStatus = 'running';
		hbUpgradeExitCode = null;
		try {
			const res = await fetch('/admin/api/housebot/upgrade', { method: 'POST' });
			const data = await res.json();
			if (!data.ok) {
				hbUpgradeStatus = 'failed';
				hbUpgradeLog = [data.message ?? 'Upgrade failed.'];
				return;
			}
			stopHbPoll();
			hbPollTimer = setInterval(pollHbUpgradeStatus, 2000);
		} catch (e: unknown) {
			hbUpgradeStatus = 'failed';
			hbUpgradeLog = [e instanceof Error ? e.message : 'Request failed'];
		}
	}

	onMount(() => { loadGoogleStatus(); loadOllamaStatus(); checkOllamaUpdate(); checkHousebotUpdate(); });
</script>

<div class="space-y-6">

	<!-- Header -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center gap-4">
		<span class="text-3xl">🔧</span>
		<div class="flex-1">
			<h2 class="text-lg font-bold">Admin</h2>
			<p class="text-xs text-surface-400-600 mt-0.5">Service control, account maintenance, and software updates.</p>
		</div>
		<button
			onclick={() => goto('/')}
			class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-surface-300-700
			text-surface-500-500 hover:bg-surface-100-900 transition-colors"
		>
			← Back
		</button>
	</div>

	<!-- ── HouseBot Management ────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>⚡</span>
			<h3 class="font-semibold text-sm">HouseBot Management</h3>
		</div>
		<div class="p-5 space-y-4">
			<!-- Action buttons -->
			<div class="flex gap-3">
				<button
					onclick={() => { svcPending = 'stop'; svcMsg = null; }}
					disabled={svcBusy}
					class="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold
					border border-error-500/40 text-error-400 hover:bg-error-500/10
					transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
				>
					<span class="text-[10px]">⏹</span> {svcBusy ? 'Working…' : 'Stop'}
				</button>
				<button
					onclick={() => { svcPending = 'restart'; svcMsg = null; }}
					disabled={svcBusy}
					class="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold
					border border-primary-500/40 text-primary-400 hover:bg-primary-500/10
					transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
				>
					<span class="text-[10px]">🔄</span> {svcBusy ? 'Working…' : 'Restart'}
				</button>
			</div>

			<!-- Inline confirmation -->
			{#if svcPending}
				<div class="rounded-lg border border-warning-500/40 bg-warning-500/10 px-4 py-3 flex items-center gap-3">
					<span class="text-sm flex-1">
						{#if svcPending === 'stop'}
							This will <strong>stop all HouseBot services</strong>. To start again you will need to run <code class="font-mono text-xs bg-black/20 px-1 rounded">bash housebot.sh start</code> in the bot folder. Proceed?
						{:else}
							Are you sure you want to <strong>restart</strong> HouseBot?
						{/if}
					</span>
					<button
						onclick={() => executeAction(svcPending!)}
						class="px-3 py-1.5 rounded-lg text-xs font-medium bg-warning-500/20 text-warning-400
						hover:bg-warning-500/35 transition-colors"
					>Confirm</button>
					<button
						onclick={() => svcPending = null}
						class="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-100-900 text-surface-500-500
						hover:bg-surface-200-800 transition-colors"
					>Cancel</button>
				</div>
			{/if}

			<!-- Result message -->
			{#if svcMsg}
				<div class="text-xs px-3 py-2 rounded-lg {svcMsg.ok ? 'bg-success-500/10 text-success-500' : 'bg-error-500/10 text-error-400'}">
					{svcMsg.text}
				</div>
			{/if}

			<!-- Log viewer (appears after action, collapsed by default) -->
			{#if svcLog.length > 0}
				<div class="rounded-lg border border-surface-200-800 overflow-hidden">
					<button
						onclick={() => svcLogOpen = !svcLogOpen}
						class="w-full flex items-center gap-2 px-4 py-2.5 bg-surface-100-900 hover:bg-surface-200-800
						transition-colors text-xs font-medium text-surface-500-500 text-left"
					>
						<span class="transition-transform {svcLogOpen ? 'rotate-90' : ''} inline-block">▶</span>
						<span>Service Logs</span>
						<span class="ml-auto opacity-60">{svcLog.length} lines</span>
					</button>
					{#if svcLogOpen}
						<div class="bg-black p-3 max-h-60 overflow-y-auto font-mono text-[11px] leading-relaxed text-white space-y-0.5">
							{#each svcLog as line}
								<div class="whitespace-pre-wrap break-all">{line}</div>
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>

	<!-- ── Ollama AI Engine ──────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>🧠</span>
			<h3 class="font-semibold text-sm">Ollama AI Engine</h3>
			{#if ollamaInstalledVer}
				<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-100-900 text-surface-400-600">v{ollamaInstalledVer}</span>
			{/if}
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

			<!-- Update checker -->
			<div class="pt-3 border-t border-surface-100-900 space-y-2">
				<!-- Version box — mirrors the status box above -->
				<div class="flex items-center gap-3 px-4 py-3 rounded-xl border
					{ollamaInstalledVer === null
						? 'border-surface-200-800 bg-surface-100-900/50'
						: ollamaUpdateAvailable
							? 'border-warning-500/40 bg-warning-500/5'
							: 'border-success-500/40 bg-success-500/5'}">
					<div class="w-2.5 h-2.5 rounded-full shrink-0
						{ollamaInstalledVer === null
							? 'bg-surface-400-600'
							: ollamaUpdateAvailable ? 'bg-warning-400' : 'bg-success-500'}"></div>
					<div class="flex-1">
						<p class="text-xs font-semibold">
							{#if ollamaInstalledVer === null}
								{ollamaVersionBusy ? 'Checking version…' : 'Ollama version'}
							{:else if ollamaUpdateAvailable}
								⚠️ Update available
							{:else}
								✅ Up to date
							{/if}
						</p>
						{#if ollamaInstalledVer}
							<p class="text-[10px] text-surface-400-600 mt-0.5">
								{ollamaUpdateAvailable && ollamaLatestVer
									? `v${ollamaInstalledVer} → v${ollamaLatestVer}`
									: `v${ollamaInstalledVer}`}
							</p>
						{/if}
					</div>
					{#if ollamaUpdateAvailable}
						<button
							onclick={upgradeOllama}
							disabled={upgradeStatus === 'running'}
							class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium
							bg-warning-500/20 text-warning-400 hover:bg-warning-500/30
							transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
						>
							{upgradeStatus === 'running' ? '…' : '⬆️ Upgrade'}
						</button>
					{/if}
				</div>
				<!-- Upgrade progress panel -->
				{#if upgradeStatus !== 'idle'}
					<div class="rounded-xl border overflow-hidden
						{upgradeStatus === 'running' ? 'border-primary-500/30 bg-primary-500/5' :
						 upgradeStatus === 'done'    ? 'border-success-500/40 bg-success-500/5' :
						                              'border-error-500/40 bg-error-500/5'}">
						<!-- Status bar -->
						<div class="flex items-center gap-2 px-4 py-2 border-b
							{upgradeStatus === 'running' ? 'border-primary-500/20' :
							 upgradeStatus === 'done'    ? 'border-success-500/20' :
							                              'border-error-500/20'}">
							{#if upgradeStatus === 'running'}
								<span class="inline-block w-2 h-2 rounded-full bg-primary-400 animate-pulse"></span>
								<span class="text-xs font-semibold text-primary-400">Upgrading…</span>
							{:else if upgradeStatus === 'done'}
								<span class="text-xs font-semibold text-success-500">✅ Upgrade complete</span>
							{:else}
								<span class="text-xs font-semibold text-error-400">❌ Upgrade failed{upgradeExitCode !== null ? ` (exit ${upgradeExitCode})` : ''}</span>
							{/if}
							<button
								onclick={() => { upgradeStatus = 'idle'; upgradeLog = []; upgradeExitCode = null; stopUpgradePoll(); }}
								class="ml-auto text-[10px] text-surface-400-600 hover:text-surface-900-50 transition-colors"
							>✕ dismiss</button>
						</div>
						<!-- Log output -->
						<pre class="font-mono text-[10px] text-surface-400-600 px-4 py-3 max-h-40 overflow-y-auto whitespace-pre-wrap break-all leading-relaxed">{
							upgradeLog.length ? upgradeLog.join('\n') : '(waiting for output…)'
						}</pre>
					</div>
				{/if}
			</div>
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

	<!-- ── HouseBot Software Update ─────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>🔄</span>
			<h3 class="font-semibold text-sm">HouseBot Software Update</h3>
			{#if hbInstalledTag}
				<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-100-900 text-surface-400-600">{hbInstalledTag}</span>
			{/if}
			<a
				href={hbRepoUrl}
				target="_blank"
				rel="noopener noreferrer"
				class="ml-auto text-[10px] px-2 py-1 rounded bg-surface-100-900 hover:bg-surface-200-800
				text-surface-500-500 transition-colors font-medium"
			>GitHub ↗</a>
		</div>
		<div class="p-5 space-y-3">
			<!-- Version box -->
			<div class="flex items-center gap-3 px-4 py-3 rounded-xl border
				{hbInstalledTag === null
					? 'border-surface-200-800 bg-surface-100-900/50'
					: hbUpdateAvailable
						? 'border-warning-500/40 bg-warning-500/5'
						: 'border-success-500/40 bg-success-500/5'}">
				<div class="w-2.5 h-2.5 rounded-full shrink-0
					{hbInstalledTag === null
						? 'bg-surface-400-600'
						: hbUpdateAvailable ? 'bg-warning-400' : 'bg-success-500'}"></div>
				<div class="flex-1">
					<p class="text-xs font-semibold">
						{#if hbInstalledTag === null}
							{hbVersionBusy ? 'Checking version…' : 'Release version'}
						{:else if hbUpdateAvailable}
							⚠️ Update available
						{:else}
							✅ Up to date
						{/if}
					</p>
					{#if hbInstalledTag}
						<p class="text-[10px] text-surface-400-600 mt-0.5">
							{hbUpdateAvailable && hbLatestTag
								? `${hbInstalledTag} → ${hbLatestTag}`
								: hbInstalledTag}
						</p>
					{/if}
				</div>
				{#if hbUpdateAvailable}
					<button
						onclick={upgradeHousebot}
						disabled={hbUpgradeStatus === 'running'}
						class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium
						bg-warning-500/20 text-warning-400 hover:bg-warning-500/30
						transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
					>
						{hbUpgradeStatus === 'running' ? '…' : '⬆️ Update Now'}
					</button>
				{/if}
			</div>

			<!-- Upgrade progress panel -->
			{#if hbUpgradeStatus !== 'idle'}
				<div class="rounded-xl border overflow-hidden
					{hbUpgradeStatus === 'running' ? 'border-primary-500/30 bg-primary-500/5' :
					 hbUpgradeStatus === 'done'    ? 'border-success-500/40 bg-success-500/5' :
					                               'border-error-500/40 bg-error-500/5'}">
					<div class="flex items-center gap-2 px-4 py-2 border-b
						{hbUpgradeStatus === 'running' ? 'border-primary-500/20' :
						 hbUpgradeStatus === 'done'    ? 'border-success-500/20' :
						                               'border-error-500/20'}">
						{#if hbUpgradeStatus === 'running'}
							<span class="inline-block w-2 h-2 rounded-full bg-primary-400 animate-pulse"></span>
							<span class="text-xs font-semibold text-primary-400">Upgrading…</span>
						{:else if hbUpgradeStatus === 'done'}
							<span class="text-xs font-semibold text-success-500">✅ Upgrade complete — HouseBot is restarting</span>
						{:else}
							<span class="text-xs font-semibold text-error-400">❌ Upgrade failed{hbUpgradeExitCode !== null ? ` (exit ${hbUpgradeExitCode})` : ''}</span>
						{/if}
						<button
							onclick={() => { hbUpgradeStatus = 'idle'; hbUpgradeLog = []; hbUpgradeExitCode = null; stopHbPoll(); }}
							class="ml-auto text-[10px] text-surface-400-600 hover:text-surface-900-50 transition-colors"
						>✕ dismiss</button>
					</div>
					<pre class="font-mono text-[10px] text-surface-400-600 px-4 py-3 max-h-48 overflow-y-auto whitespace-pre-wrap break-all leading-relaxed bg-black text-white">{hbUpgradeLog.length ? hbUpgradeLog.join('\n') : '(waiting for output…)'}</pre>
				</div>
			{/if}
		</div>
	</div>

</div>
