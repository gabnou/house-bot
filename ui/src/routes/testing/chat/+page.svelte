<script lang="ts">
	import { onMount } from 'svelte';

	// ── Types ──────────────────────────────────────────────────────────────
	interface Exchange {
		id: number;
		userMsg: string;
		botReply: string | null;
		pending: boolean;
		rating: 'acceptable' | 'wrong' | null;
		duration: number | null; // ms
	}

	// ── State ──────────────────────────────────────────────────────────────
	let exchanges = $state<Exchange[]>([]);
	let input = $state('');
	let sending = $state(false);
	let sendError = $state<string | null>(null);
	let nextId = 1;

	// ── User Context (collapsible panel) ───────────────────────────────────
	let overrideOpen = $state(false);
	let loadingContext = $state(true);
	let productionLanguage = $state('');
	let productionInstructions = $state('');
	let overrideInstructions = $state('');
	// active when instructions differ from production (language is always production)
	const contextOverride = $derived<Record<string, string> | null>(
		overrideInstructions !== productionInstructions
			? { language: productionLanguage, instructions: overrideInstructions.trim() }
			: null
	);

	// ── Save to production ──────────────────────────────────────────────────
	let showSaveConfirm = $state(false);
	let savingToProduction = $state(false);
	let saveMsg = $state<{ ok: boolean; text: string } | null>(null);

	async function saveToProduction() {
		savingToProduction = true;
		saveMsg = null;
		try {
			const res = await fetch('/admin/api/user-context', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ instructions: overrideInstructions }),
			});
			const data = await res.json();
			if (res.ok && data.ok) {
				productionInstructions = overrideInstructions;
				saveMsg = { ok: true, text: 'Saved to production — takes effect on next message.' };
			} else {
				saveMsg = { ok: false, text: data.detail ?? 'Save failed.' };
			}
		} catch (e: unknown) {
			saveMsg = { ok: false, text: e instanceof Error ? e.message : 'Save failed.' };
		} finally {
			savingToProduction = false;
			showSaveConfirm = false;
		}
	}

	// ── Score ──────────────────────────────────────────────────────────────
	const rated    = $derived(exchanges.filter(e => e.rating !== null));
	const accepted = $derived(rated.filter(e => e.rating === 'acceptable').length);
	const scoreStr = $derived(
		rated.length === 0
			? null
			: `${accepted} / ${rated.length} acceptable (${Math.round((accepted / rated.length) * 100)}%)`
	);

	// ── Load production context as default ─────────────────────────────────
	onMount(async () => {
		try {
			const res = await fetch('/admin/api/user-context');
			if (res.ok) {
				const data = await res.json();
				productionLanguage = data.language ?? '';
				productionInstructions = data.instructions_original ?? data.instructions ?? '';
				overrideInstructions = productionInstructions;
			}
		} catch { /* silent — panel uses empty defaults */ }
		finally { loadingContext = false; }
	});

	// ── Actions ─────────────────────────────────────────────────────────────
	async function send() {
		const text = input.trim();
		if (!text || sending) return;
		input = '';
		sendError = null;
		sending = true;

		const entry: Exchange = { id: nextId++, userMsg: text, botReply: null, pending: true, rating: null, duration: null };
		exchanges = [...exchanges, entry];
		const t0 = Date.now();

		try {
			const body: Record<string, unknown> = { text, sender: '__manual_test__' };
			if (contextOverride !== null) body.user_context_override = contextOverride;
			const res = await fetch('/message', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			const elapsed = Date.now() - t0;
			exchanges = exchanges.map(e =>
				e.id === entry.id ? { ...e, botReply: (data.reply ?? '(no reply)').trim(), pending: false, duration: elapsed } : e
			);
		} catch (err) {
			sendError = err instanceof Error ? err.message : String(err);
			exchanges = exchanges.map(e =>
				e.id === entry.id ? { ...e, botReply: '⚠ Error — bot unreachable', pending: false, duration: Date.now() - t0 } : e
			);
		} finally {
			sending = false;
		}
	}

	function rate(id: number, verdict: 'acceptable' | 'wrong') {
		exchanges = exchanges.map(e => e.id === id ? { ...e, rating: verdict } : e);
	}

	function clearSession() {
		exchanges = [];
		input = '';
		sendError = null;
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
	}
</script>

<!-- ── Page ─────────────────────────────────────────────────────────────── -->
<div class="space-y-6">

	<!-- Title banner -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center gap-4">
		<span class="text-3xl">🧪</span>
		<div class="flex-1">
			<h2 class="text-lg font-bold">Testing</h2>
			<p class="text-xs text-surface-400-600 mt-0.5">Run scripted tests against the bot or chat interactively to verify its behaviour.</p>
		</div>
		<a
			href="/"
			class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-surface-300-700 text-surface-500-500 hover:bg-surface-100-900 transition-colors"
		>← Back</a>
	</div>

	<!-- Tab bar -->
	<div class="flex gap-1 border-b border-surface-200-800">
		<a href="/testing" class="px-4 py-2 text-sm font-medium text-surface-400-600 hover:text-surface-700-300 border-b-2 border-transparent transition-colors">Scripted Tests</a>
		<a href="/testing/chat" class="px-4 py-2 text-sm font-medium border-b-2 border-primary-500 text-primary-500 -mb-px">Interactive Tests</a>
	</div>

	<!-- Header -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-2xl font-bold">Interactive Tests</h1>
			<p class="text-sm text-surface-400-600 mt-0.5">Chat with the bot in your language and rate each response.</p>
			<p class="text-xs text-surface-400-600 mt-0.5">Responses are not sent to WhatsApp. Your session score is tracked below.</p>
		</div>
		<div class="flex items-center gap-3">
			{#if scoreStr}
			<span class="text-sm font-medium {accepted === rated.length ? 'text-green-600 dark:text-green-400' : rated.length > 0 && accepted / rated.length < 0.5 ? 'text-red-500' : 'text-surface-500'}">
				{scoreStr}
			</span>
			{/if}
			{#if exchanges.length > 0}
			<button
				onclick={clearSession}
				class="px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 hover:bg-surface-100-900 transition-colors"
			>Clear</button>
			{/if}
		</div>
	</div>

	<!-- Language card (read-only) -->
	<div class="rounded-xl border border-surface-200-800 px-4 py-3 flex items-center gap-3 bg-surface-50-950">
		<span class="text-xs font-semibold text-surface-500 uppercase shrink-0">Language</span>
		{#if loadingContext}
		<span class="text-xs text-surface-400-600 animate-pulse">Loading…</span>
		{:else}
		<span class="px-3 py-1 text-sm rounded-lg border border-surface-200-800 bg-surface-100-900 text-surface-600-400 select-none">{productionLanguage || '—'}</span>
		<span class="text-xs text-surface-400-600">Set in <a href="/config" class="underline hover:text-primary-500 transition-colors">Config / Location</a></span>
		{/if}
	</div>

	<!-- User Context panel -->
	<div class="rounded-xl border border-surface-200-800 overflow-hidden">
		<button
			onclick={() => overrideOpen = !overrideOpen}
			class="w-full flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-surface-50-950 transition-colors"
		>
			<span class="flex items-center gap-2">
				<span>User Context</span>
				{#if loadingContext}
				<span class="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-surface-100-900 text-surface-400-600 uppercase tracking-wide animate-pulse">loading…</span>
				{:else if contextOverride !== null}
				<span class="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 uppercase tracking-wide">modified</span>
				{:else}
				<span class="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-surface-100-900 text-surface-400-600 uppercase tracking-wide">production</span>
				{/if}
			</span>
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" class="w-3.5 h-3.5 text-surface-400-600 transition-transform {overrideOpen ? 'rotate-180' : ''}" fill="currentColor" aria-hidden="true">
				<path d="M4.427 7.427l3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427Z"/>
			</svg>
		</button>
		{#if overrideOpen}
		<div class="px-4 pb-4 pt-2 flex flex-col gap-3 border-t border-surface-200-800 bg-surface-50-950">
			{#if loadingContext}
			<p class="text-xs text-surface-400-600 animate-pulse py-2">Loading user context…</p>
			{:else}
			<p class="text-xs text-surface-400-600">Instructions can be edited for this test session only — production settings are never modified unless you explicitly save them.</p>

			<!-- Instructions (full width) -->
			<label class="flex flex-col gap-1">
				<span class="text-xs font-semibold text-surface-500 uppercase">Instructions</span>
				<textarea
					bind:value={overrideInstructions}
					rows={6}
					placeholder="Custom instructions for the bot…"
					class="px-3 py-2 text-xs rounded-lg border border-surface-300-700 bg-white dark:bg-gray-900 resize-y focus:outline-none focus:ring-2 focus:ring-primary-500"
				></textarea>
			</label>

			<!-- Save feedback -->
			{#if saveMsg}
			<p class="text-xs {saveMsg.ok ? 'text-green-600 dark:text-green-400' : 'text-red-500'}">{saveMsg.text}</p>
			{/if}

			<!-- Action buttons -->
			{#if showSaveConfirm}
			<!-- Confirmation banner -->
			<div class="rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 flex flex-col gap-2">
				<p class="text-xs font-semibold text-amber-800 dark:text-amber-300">⚠ This will overwrite the production instructions used by all live messages.</p>
				<p class="text-xs text-amber-700 dark:text-amber-400">This change will be permanent and take effect immediately. Are you sure?</p>
				<div class="flex gap-2 justify-end">
					<button
						onclick={() => showSaveConfirm = false}
						class="px-3 py-1 text-xs rounded-lg border border-surface-300-700 hover:bg-surface-100-900 transition-colors"
					>Cancel</button>
					<button
						onclick={saveToProduction}
						disabled={savingToProduction}
						class="px-3 py-1 text-xs font-semibold rounded-lg bg-amber-600 hover:bg-amber-700 text-white disabled:opacity-50 transition-colors"
					>{savingToProduction ? 'Saving…' : 'Yes, save to production'}</button>
				</div>
			</div>
			{:else}
			<div class="flex items-center justify-between">
				<button
					onclick={() => { overrideInstructions = productionInstructions; saveMsg = null; }}
					class="px-3 py-1 text-xs rounded-lg border border-surface-300-700 hover:bg-surface-100-900 transition-colors"
				>Restore original</button>
				<button
					onclick={() => { showSaveConfirm = true; saveMsg = null; }}
					disabled={contextOverride === null}
					class="px-3 py-1 text-xs font-semibold rounded-lg border border-amber-400 text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-900/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
				>Save to production</button>
			</div>
			{/if}
			{/if}
		</div>
		{/if}
	</div>

	<!-- Input bar -->
	<div class="flex gap-2 items-end">
		<textarea
			bind:value={input}
			onkeydown={onKeydown}
			disabled={sending}
			rows={2}
			placeholder="Type a message… (Enter to send, Shift+Enter for new line)"
			class="flex-1 px-4 py-2.5 text-sm rounded-xl border border-surface-300-700 bg-white dark:bg-gray-900 resize-none focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50 transition-colors"
		></textarea>
		<button
			onclick={send}
			disabled={!input.trim() || sending}
			class="px-4 py-2.5 text-sm font-semibold rounded-xl bg-primary-500 hover:bg-primary-600 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
		>Send</button>
	</div>

	{#if sendError}
	<div class="p-3 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
		{sendError}
	</div>
	{/if}

	{#if exchanges.length > 0}
	<div class="flex flex-col gap-4">
		{#each [...exchanges].reverse() as ex (ex.id)}

		<!-- User message -->
		<div class="flex justify-end">
			<div class="max-w-[75%] px-4 py-2.5 rounded-2xl rounded-br-sm bg-primary-500 text-white text-xs">
				{ex.userMsg}
			</div>
		</div>

		<!-- Bot reply -->
		<div class="flex flex-col gap-1">
			<div class="flex items-end gap-2">
				<div class="max-w-[75%] px-4 py-2.5 rounded-2xl rounded-bl-sm bg-surface-100-900 text-xs
					{ex.pending ? 'animate-pulse text-surface-400-600' : 'whitespace-pre-wrap'}">
					{#if ex.pending}Typing…{:else}{ex.botReply}{/if}
				</div>
			</div>
			{#if !ex.pending && ex.duration !== null}
			<span class="pl-1 text-[10px] text-surface-400-600">{(ex.duration / 1000).toFixed(1)} s</span>
			{/if}

			<!-- Rating buttons -->
			{#if !ex.pending && ex.rating === null}
			<div class="flex gap-2 pl-1">
				<button
					onclick={() => rate(ex.id, 'acceptable')}
					class="px-3 py-1 text-xs font-semibold rounded-full border border-green-400 text-green-600 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors"
				>✓ Acceptable</button>
				<button
					onclick={() => rate(ex.id, 'wrong')}
					class="px-3 py-1 text-xs font-semibold rounded-full border border-red-400 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
				>✗ Wrong</button>
			</div>
			{:else if ex.rating !== null}
			<div class="pl-1">
				<span class="text-xs font-semibold px-2.5 py-0.5 rounded-full
					{ex.rating === 'acceptable'
						? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300'
						: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300'}">
					{ex.rating === 'acceptable' ? '✓ Acceptable' : '✗ Wrong'}
				</span>
			</div>
			{/if}
		</div>

		{/each}
	</div>
	{:else}
	{/if}

</div>
