<script lang="ts">
	import { goto } from '$app/navigation';

	// ── Model catalog ───────────────────────────────────────────────────────
	const MODEL_CATALOG = [
		{ id: 'gemma3:1b',         name: 'Gemma 3 1B',        ram: '2 GB',   family: 'Google' },
		{ id: 'gemma3:4b',         name: 'Gemma 3 4B',        ram: '4 GB',   family: 'Google' },
		{ id: 'gemma3:12b',        name: 'Gemma 3 12B',       ram: '12 GB',  family: 'Google' },
		{ id: 'gemma3:27b',        name: 'Gemma 3 27B',       ram: '24 GB+', family: 'Google' },
		{ id: 'llama3.1:8b',       name: 'Llama 3.1 8B',      ram: '8 GB',   family: 'Meta' },
		{ id: 'mistral-small:22b', name: 'Mistral Small 22B', ram: '16 GB',  family: 'Mistral' },
	];

	// ── Step 1 state ────────────────────────────────────────────────────────────
	let step1Open = $state(false);
	let installedModels = $state<string[]>([]);
	let modelsLoading = $state(false);
	let pullingModel = $state<string | null>(null);
	let pullStatus = $state('');
	let pullProgress = $state<{ completed: number; total: number } | null>(null);
	let pullDone = $state(false);
	let pullError = $state<string | null>(null);

	let chatModel = $state('');
	let chatMessage = $state('');
	let chatResponse = $state('');
	let chatLoading = $state(false);
	let chatError = $state<string | null>(null);

	const step1Done = $derived(installedModels.length > 0);

	// ── Load-time estimator ───────────────────────────────────────────────────
	// Base times (seconds) measured at ~16 GB unified memory with SSD loading.
	const MODEL_BASE_SECONDS: Record<string, number> = {
		'gemma3:1b':         4,
		'gemma3:4b':         8,
		'gemma3:12b':        18,
		'gemma3:27b':        40,
		'llama3.1:8b':       12,
		'mistral-small:22b': 28,
	};

	let ramGb = $state<number | null>(null);

	async function loadSystemInfo() {
		try {
			const res = await fetch('/admin/api/install/system-info');
			if (res.ok) ramGb = (await res.json()).ram_gb ?? null;
		} catch { /* non-fatal */ }
	}

	/**
	 * RAM factor: more RAM = faster model load (less pressure / better bandwidth).
	 *  ≤8 GB  ⇒ ×2.0  (tight, possible swapping)
	 *  16 GB  ⇒ ×1.0  (baseline)
	 *  32 GB  ⇒ ×0.6
	 *  64 GB+ ⇒ ×0.4
	 */
	function ramFactor(gb: number | null): number {
		if (gb === null) return 1.0;
		if (gb <= 8)  return 2.0;
		if (gb <= 16) return 1.0;
		if (gb <= 32) return 0.6;
		return 0.4;
	}

	function estimateLoadSeconds(model: string): number {
		let base = MODEL_BASE_SECONDS[model];
		if (!base) {
			// Fallback: parse param count from tag, e.g. "foo:13b" → 13
			const m = model.match(/(\d+(?:\.\d+)?)[bB]/);
			base = m ? Math.round(Number(m[1]) * 1.6) : 20;
		}
		return Math.max(3, Math.round(base * ramFactor(ramGb)));
	}

	const chatLoadEstimate = $derived(
		chatModel ? `~${estimateLoadSeconds(chatModel)}s` : 'a moment'
	);

	// ── Keep-alive ──────────────────────────────────────────────────────────────
	const KEEP_ALIVE_PRESETS = [
		{ label: 'Default (5 min)', value: '5m',  desc: 'Ollama unloads the model after 5 minutes of inactivity.' },
		{ label: '30 minutes',      value: '30m', desc: 'Good balance for active sessions — keeps the model warm.' },
		{ label: '1 hour',          value: '1h',  desc: 'Ideal for long work sessions; the model stays loaded for an hour.' },
		{ label: 'Never unload',    value: '-1',  desc: 'Model stays in RAM indefinitely — fastest response, highest memory use.' },
	];
	let keepAliveValue = $state('');
	let keepAliveSaving = $state(false);
	let keepAliveSaved = $state(false);
	let keepAliveError = $state<string | null>(null);
	let pendingRestart = $state(false);
	let restarting = $state(false);

	async function loadKeepAlive() {
		try {
			const res = await fetch('/admin/api/install/ollama/keep-alive');
			if (res.ok) {
				const data = await res.json();
				keepAliveValue = data.value ?? '';
			}
		} catch { /* non-fatal */ }
	}

	async function saveKeepAlive(value: string) {
		keepAliveSaving = true;
		keepAliveSaved = false;
		keepAliveError = null;
		try {
			const res = await fetch('/admin/api/install/ollama/keep-alive', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ value }),
			});
			if (res.ok) {
				keepAliveValue = value;
				keepAliveSaved = true;
				pendingRestart = true;
				setTimeout(() => keepAliveSaved = false, 2500);
			} else {
				const err = await res.json().catch(() => ({}));
				keepAliveError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			keepAliveError = e instanceof Error ? e.message : String(e);
		} finally {
			keepAliveSaving = false;
		}
	}

	async function restartFastapi() {
		restarting = true;
		try {
			await fetch('/admin/api/services/fastapi/restart', { method: 'POST' });
			pendingRestart = false;
		} catch { /* non-fatal */ } finally {
			setTimeout(() => restarting = false, 4000);
		}
	}

	async function toggleStep1() {
		step1Open = !step1Open;
		if (step1Open && installedModels.length === 0 && !modelsLoading) {
			await loadInstalledModels();
		}
		if (step1Open && !keepAliveValue) {
			await loadKeepAlive();
		}
		if (step1Open && ramGb === null) {
			await loadSystemInfo();
		}
	}

	async function loadInstalledModels() {
		modelsLoading = true;
		try {
			const res = await fetch('/admin/api/ollama/models');
			if (res.ok) {
				const data = await res.json();
				installedModels = (data.models ?? []).map((m: { name: string }) => m.name);
				if (!chatModel && installedModels.length > 0) chatModel = installedModels[0];
			}
		} catch {
			// non-fatal
		} finally {
			modelsLoading = false;
		}
	}

	async function pullModel(modelId: string) {
		pullingModel = modelId;
		pullStatus = 'Connecting…';
		pullProgress = null;
		pullDone = false;
		pullError = null;
		try {
			const res = await fetch('/admin/api/install/ollama/pull', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: modelId }),
			});
			if (!res.body) throw new Error('No response body');
			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buf = '';
			loop: while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				buf += decoder.decode(value, { stream: true });
				const lines = buf.split('\n');
				buf = lines.pop() ?? '';
				for (const line of lines) {
					if (!line.startsWith('data: ')) continue;
					const raw = line.slice(6).trim();
					if (!raw) continue;
					try {
						const msg = JSON.parse(raw) as Record<string, unknown>;
						if (msg.error) { pullError = String(msg.error); break loop; }
						if (msg.done) { pullDone = true; break loop; }
						if (msg.status) pullStatus = String(msg.status);
						if (typeof msg.total === 'number') {
							pullProgress = { completed: Number(msg.completed ?? 0), total: msg.total };
						}
					} catch { /* skip malformed line */ }
				}
			}
			if (!pullError) { pullDone = true; await loadInstalledModels(); chatModel = modelId; }
		} catch (e) {
			pullError = e instanceof Error ? e.message : String(e);
		} finally {
			pullingModel = null;
		}
	}

	async function sendChat() {
		if (!chatMessage.trim() || !chatModel) return;
		chatLoading = true;
		chatResponse = '';
		chatError = null;
		const msg = chatMessage;
		let receivedTokens = false;
		try {
			const res = await fetch('/admin/api/install/ollama/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: chatModel, message: msg }),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(err.detail ?? `HTTP ${res.status}`);
			}
			if (!res.body) throw new Error('No response body');
			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buf = '';
			loop: while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				buf += decoder.decode(value, { stream: true });
				const lines = buf.split('\n');
				buf = lines.pop() ?? '';
				for (const line of lines) {
					if (!line.startsWith('data: ')) continue;
					const raw = line.slice(6).trim();
					if (!raw) continue;
					try {
						const chunk = JSON.parse(raw) as Record<string, unknown>;
						if (chunk.error) { chatError = String(chunk.error); break loop; }
						if (chunk.done) break loop;
						if (chunk.token) { chatResponse += String(chunk.token); receivedTokens = true; }
					} catch { /* skip */ }
				}
			}
			if (!receivedTokens && !chatError) {
				chatError = 'No response — FastAPI may need a restart after recent changes.';
			}
		} catch (e) {
			chatError = e instanceof Error ? e.message : String(e);
		} finally {
			chatLoading = false;
		}
	}

	// ── Static placeholder steps 2–6 ──────────────────────────────────────────────
	const steps = [
		{ n: 2, icon: '🔑', label: 'Google OAuth',            desc: 'Trigger the Google Calendar auth flow and store the token automatically.' },
		{ n: 3, icon: '📱', label: 'WhatsApp Pairing',        desc: 'Display the QR code and wait for the phone to scan and pair.' },
		{ n: 4, icon: '🛡️', label: 'Sender Restrictions',    desc: 'Identify the WhatsApp JIDs authorised to interact with the bot and save them to .env.' },
		{ n: 5, icon: '✅', label: 'Smoke Test',              desc: 'Run a quick end-to-end check: shopping list, weather, and calendar queries.' },
		{ n: 6, icon: '⚙️', label: 'Configure .env',         desc: 'Review and adjust remaining settings: location, timezone, briefing, Whisper model, and more.' },
	];

	// ── Skip logic ──────────────────────────────────────────────────────────────────
	let showSkipWarning = $state(false);
	function skip() { showSkipWarning = true; }
	function confirmSkip() { goto('/'); }
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center gap-4">
		<span class="text-3xl">🚀</span>
		<div class="flex-1">
			<h2 class="text-lg font-bold">Installation Wizard</h2>
			<p class="text-xs text-surface-400-600 mt-0.5">
				Step-by-step setup — you can always re-run this to fix or reconfigure any step.
			</p>
		</div>
		<button
			onclick={skip}
			class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-surface-300-700
			text-surface-500-500 hover:bg-surface-100-900 transition-colors"
		>
			Skip →
		</button>
	</div>

	<!-- Skip warning banner -->
	{#if showSkipWarning}
		<div class="flex items-start gap-3 px-4 py-4 rounded-xl border border-error-500/40 bg-error-500/10">
			<span class="text-xl mt-0.5">⚠️</span>
			<div class="flex-1">
				<p class="font-semibold text-sm text-error-400">Installation not completed</p>
				<p class="text-xs text-surface-400-600 mt-1">
					Skipping setup means the bot may be partially or fully non-functional — missing credentials,
					misconfigured LLM, or unpaired WhatsApp session. You can return here at any time from the sidebar.
				</p>
			</div>
			<div class="flex flex-col gap-2 shrink-0">
				<button
					onclick={confirmSkip}
					class="px-3 py-1.5 rounded-lg text-xs font-medium bg-error-500/20 text-error-400
					hover:bg-error-500/30 transition-colors"
				>
					Skip anyway
				</button>
				<button
					onclick={() => showSkipWarning = false}
					class="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-200-800 text-surface-500-500
					hover:bg-surface-300-700 transition-colors"
				>
					Stay here
				</button>
			</div>
		</div>
	{/if}

	<!-- Re-run notice -->
	<div class="flex items-start gap-3 px-4 py-3 rounded-lg bg-primary-500/10 border border-primary-500/20 text-sm text-primary-400">
		<span class="mt-0.5">ℹ️</span>
		<span>
			This wizard is non-destructive — re-running any step is safe and will not overwrite data already
			set unless you explicitly change it.
		</span>
	</div>

	<!-- Steps -->
	<div class="space-y-3">

		<!-- ── Step 1: Ollama — AI Models (interactive) ──────────────────────────── -->
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">

			<!-- Accordion header -->
			<button
				onclick={toggleStep1}
				class="w-full p-4 flex items-center gap-4 text-left hover:bg-surface-100-900/50 transition-colors"
			>
				<div class="w-9 h-9 rounded-full bg-surface-100-900 border border-surface-200-800 flex items-center justify-center text-lg shrink-0">
					🧠
				</div>
				<div class="flex-1 min-w-0">
					<p class="font-semibold text-sm">
						<span class="text-surface-400-600 font-mono text-xs mr-2">1.</span>
						Ollama — AI Models
					</p>
					<p class="text-xs text-surface-400-600 mt-0.5">Select and pull a local LLM model to power the bot.</p>
				</div>
				{#if installedModels.length > 0}
					<span class="text-xs text-success-400 shrink-0 mr-1">{installedModels.length} installed</span>
				{:else if !modelsLoading}
					<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-error-500/10 text-error-400/70 shrink-0 mr-1">pending</span>
				{/if}
				<span class="text-surface-400-600 text-xs shrink-0">{step1Open ? '▲' : '▼'}</span>
			</button>

			<!-- Expanded panel -->
			{#if step1Open}
				<div class="border-t border-surface-200-800 p-4 space-y-5">

					{#if modelsLoading}
						<p class="text-xs text-surface-400-600">Checking installed models…</p>
					{/if}

					<!-- Model rows -->
					<div class="space-y-2">
						{#each MODEL_CATALOG as model}
							{@const isInstalled = installedModels.includes(model.id)}
							{@const isPulling = pullingModel === model.id}
							<div class="flex items-center gap-3 p-3 rounded-lg border border-surface-200-800 bg-surface-100-900/40">
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2 flex-wrap">
										<span class="text-xs font-semibold">{model.name}</span>
										<span class="text-xs text-surface-400-600 font-mono">{model.id}</span>
										{#if isInstalled}
											<span class="px-1.5 py-0.5 rounded text-xs bg-success-500/15 text-success-400">installed</span>
										{/if}
									</div>
									<p class="text-xs text-surface-400-600 mt-0.5">{model.ram} RAM required · {model.family}</p>
									<!-- Inline pull progress -->
									{#if isPulling}
										<div class="mt-2 space-y-1">
											<p class="text-xs text-primary-400">{pullStatus}</p>
											{#if pullProgress && pullProgress.total > 0}
												<div class="w-full h-1.5 bg-surface-200-800 rounded-full overflow-hidden">
													<div
														class="h-full bg-primary-500 rounded-full transition-all duration-300"
														style="width: {Math.round((pullProgress.completed / pullProgress.total) * 100)}%"
													></div>
												</div>
												<p class="text-xs text-surface-400-600">
													{(pullProgress.completed / 1e9).toFixed(2)} / {(pullProgress.total / 1e9).toFixed(2)} GB
												</p>
											{/if}
										</div>
									{/if}
								</div>
								<button
									onclick={() => pullModel(model.id)}
									disabled={!!pullingModel}
									class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-40
										{isInstalled
											? 'border-success-500/40 text-success-400 hover:bg-success-500/10'
											: 'border-primary-500/40 text-primary-400 hover:bg-primary-500/10'}"
								>
									{isPulling ? 'Pulling…' : isInstalled ? 'Re-pull' : 'Pull'}
								</button>
							</div>
						{/each}
					</div>

					<!-- Result banners -->
					{#if pullDone && !pullingModel}
						<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-success-500/10 border border-success-500/30">
							<span>✅</span>
							<p class="text-xs text-success-400">Model pulled successfully — you can test it below.</p>
						</div>
					{/if}
					{#if pullError && !pullingModel}
						<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-error-500/10 border border-error-500/30">
							<span>❌</span>
							<p class="text-xs text-error-400">{pullError}</p>
						</div>
					{/if}

					<!-- More models link -->
					<p class="text-xs text-surface-400-600">
						Looking for a different model?
						<a
							href="https://ollama.com/library"
							target="_blank"
							rel="noopener noreferrer"
							class="text-primary-400 hover:underline"
						>Browse all models on ollama.com →</a>
					</p>

					<!-- Keep-alive setting -->
					<div class="space-y-3 pt-3 border-t border-surface-200-800">
						<div>
							<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Model keep-alive</p>
							<p class="text-xs text-surface-400-600 mt-1">
								Ollama unloads the model from RAM after a period of inactivity.
								A longer keep-alive means faster responses but higher constant memory usage.
								Set to <span class="font-mono">-1</span> to never unload
								or leave at the default <span class="font-mono">5m</span> to free RAM when idle.
							</p>
						</div>
						<div class="flex flex-wrap gap-2">
							{#each KEEP_ALIVE_PRESETS as preset}
								{@const isActive = keepAliveValue === preset.value || (preset.value === '5m' && !keepAliveValue)}
								<button
									title={preset.desc}
									onclick={() => saveKeepAlive(preset.value)}
									disabled={keepAliveSaving}
									class="px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-40
										{isActive
											? 'border-primary-500/60 bg-primary-500/15 text-primary-400'
											: 'border-surface-300-700 text-surface-500-500 hover:bg-surface-100-900'}"
								>
									{preset.label}
								</button>
							{/each}
						</div>
						<div class="flex items-center gap-3">
							<p class="text-xs text-surface-400-600">
								Current: <span class="font-mono text-surface-900-50">{keepAliveValue || '5m (default)'}</span>
							</p>
							{#if keepAliveSaved}
								<span class="text-xs text-success-400">✓ Saved to .env</span>
							{/if}
						</div>
						{#if keepAliveError}
							<p class="text-xs text-error-400">❌ {keepAliveError}</p>
						{/if}
						<p class="text-xs text-surface-400-600/70">
							⚠️ A restart of HouseBot is required for this change to take effect.
						</p>
						{#if pendingRestart}
							<button
								onclick={restartFastapi}
								disabled={restarting}
								class="self-start px-4 py-2 rounded-lg text-xs font-semibold bg-warning-500/20 text-warning-400
								       border border-warning-500/40 hover:bg-warning-500/30 transition-colors disabled:opacity-50"
							>
								{restarting ? 'Restarting…' : '🔄 Restart HouseBot now'}
							</button>
						{/if}
					</div>

					<!-- Chat test -->
					{#if installedModels.length > 0}
						<div class="space-y-3 pt-3 border-t border-surface-200-800">
							<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Test the model</p>

							<!-- Model selector -->
							<div class="flex items-center gap-2">
								<label for="chat-model" class="text-xs text-surface-400-600 shrink-0">Model:</label>
								<select
									id="chat-model"
									bind:value={chatModel}
									class="flex-1 text-xs rounded-lg px-2 py-1.5 bg-surface-100-900 border border-surface-200-800
									       text-surface-900-50 focus:outline-none focus:border-primary-500/60"
								>
									{#each installedModels as m}
										<option value={m}>{m}</option>
									{/each}
								</select>
							</div>

							<!-- Input + send -->
							<div class="flex gap-2">
								<input
									type="text"
									bind:value={chatMessage}
									placeholder="Ask something…"
									onkeydown={(e) => { if (e.key === 'Enter') sendChat(); }}
									class="flex-1 text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
									       text-surface-900-50 placeholder:text-surface-400-600
									       focus:outline-none focus:border-primary-500/60"
								/>
								<button
									onclick={sendChat}
									disabled={chatLoading || !chatMessage.trim()}
									class="shrink-0 px-3 py-2 rounded-lg text-xs font-medium bg-primary-500/20 text-primary-400
									       hover:bg-primary-500/30 transition-colors disabled:opacity-40"
								>
									{chatLoading ? '…' : 'Send'}
								</button>
							</div>

							<!-- Response -->
							{#if chatResponse !== ''}
								<div class="px-3 py-2 rounded-lg bg-surface-100-900 border border-surface-200-800 max-h-48 overflow-y-auto">
									<p class="text-xs text-surface-400-600 whitespace-pre-wrap break-words">{chatResponse}{#if chatLoading}<span class="animate-pulse">▋</span>{/if}</p>
								</div>
							{:else if chatLoading}
								<div class="px-3 py-2 rounded-lg bg-surface-100-900 border border-surface-200-800">
									<p class="text-xs text-surface-400-600">Loading model<span class="animate-pulse">…</span> <span class="text-surface-400-600/60">(first request only after the keep-alive expires, takes {chatLoadEstimate}{ramGb ? ` on your ${ramGb} GB machine` : ''})</span></p>
								</div>
							{/if}
							{#if chatError}
								<p class="text-xs text-error-400">Error: {chatError}</p>
							{/if}
						</div>
					{/if}

				</div>
			{/if}
		</div>

		<!-- ── Steps 2–6 (static placeholders) ───────────────────────────────────── -->
		{#each steps as step}
			<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-4 flex items-center gap-4">
				<div class="w-9 h-9 rounded-full bg-surface-100-900 border border-surface-200-800 flex items-center justify-center text-lg shrink-0">
					{step.icon}
				</div>
				<div class="flex-1 min-w-0">
					<p class="font-semibold text-sm">
						<span class="text-surface-400-600 font-mono text-xs mr-2">{step.n}.</span>
						{step.label}
					</p>
					<p class="text-xs text-surface-400-600 mt-0.5 truncate">{step.desc}</p>
				</div>
				<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-error-500/10 text-error-400/70 shrink-0">pending</span>
			</div>
		{/each}

	</div>
</div>
