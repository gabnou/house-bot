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

	onMount(fetchModels);
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

	<!-- ── Google Account (Phase 5) ───────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
			<span>🔑</span>
			<h3 class="font-semibold text-sm">Google Account</h3>
		</div>
		<div class="p-5 flex flex-col sm:flex-row gap-3">
			{#each [
				{ label: 'Re-authorize', icon: '🔒', desc: 'Refresh OAuth token' },
				{ label: 'Revoke Token', icon: '🚫', desc: 'Delete token.json' },
				{ label: 'Token Status', icon: '✅', desc: 'Check expiry + access' },
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
