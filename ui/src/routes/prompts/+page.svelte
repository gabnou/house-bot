<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	// ── User Context ─────────────────────────────────────────────────────────

	interface UserContextState {
		language: string;
		instructions: string;
		original: { language: string; instructions: string };
		supportedLanguages: string[];
		loading: boolean;
		saving: boolean;
		clearing: boolean;
		msg: { ok: boolean; text: string } | null;
	}

	let uctx = $state<UserContextState>({
		language: '',
		instructions: '',
		original: { language: '', instructions: '' },
		supportedLanguages: [],
		loading: true,
		saving: false,
		clearing: false,
		msg: null,
	});

	async function loadUserContext() {
		uctx.loading = true;
		uctx.msg = null;
		try {
			const res = await fetch('/admin/api/user-context');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			uctx.language        = data.language ?? '';
			uctx.instructions    = data.instructions ?? '';
			uctx.original        = { language: uctx.language, instructions: uctx.instructions };
			uctx.supportedLanguages = data.supported_languages ?? [];
		} catch (e: unknown) {
			uctx.msg = { ok: false, text: e instanceof Error ? e.message : 'Load failed' };
		} finally {
			uctx.loading = false;
		}
	}

	async function saveUserContext() {
		uctx.saving = true;
		uctx.msg = null;
		try {
			const res = await fetch('/admin/api/user-context', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ language: uctx.language, instructions: uctx.instructions }),
			});
			const data = await res.json();
			if (res.ok && data.ok) {
				uctx.original = { language: uctx.language, instructions: uctx.instructions };
				uctx.msg = { ok: true, text: 'Saved — takes effect on next message.' };
			} else {
				uctx.msg = { ok: false, text: data.detail ?? 'Save failed' };
			}
		} catch (e: unknown) {
			uctx.msg = { ok: false, text: e instanceof Error ? e.message : 'Save failed' };
		} finally {
			uctx.saving = false;
		}
	}

	async function clearUserContext() {
		uctx.clearing = true;
		uctx.msg = null;
		try {
			const res = await fetch('/admin/api/user-context', { method: 'DELETE' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			uctx.language     = '';
			uctx.instructions = '';
			uctx.original     = { language: '', instructions: '' };
			uctx.msg = { ok: true, text: 'User context cleared.' };
		} catch (e: unknown) {
			uctx.msg = { ok: false, text: e instanceof Error ? e.message : 'Clear failed' };
		} finally {
			uctx.clearing = false;
		}
	}

	let uctxDirty = $derived(uctx.language !== uctx.original.language || uctx.instructions !== uctx.original.instructions);
	let uctxActive = $derived(uctx.original.instructions.trim().length > 0);

	const _PLACEHOLDER_EN = "e.g. Requests are almost always in English. Don't translate the name 'kasetta'. The user is mostly interested in weekend weather — always calculate from today's date.";
	let placeholderText = $state(_PLACEHOLDER_EN);
	let placeholderLoading = $state(false);
	const _placeholderCache = new Map<string, string>();

	$effect(() => {
		const lang = uctx.language;
		if (!lang || lang === 'English') {
			placeholderText = _PLACEHOLDER_EN;
			return;
		}
		if (_placeholderCache.has(lang)) {
			placeholderText = _placeholderCache.get(lang)!;
			return;
		}
		placeholderLoading = true;
		fetch('/admin/api/user-context/translate-example', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ language: lang }),
		})
			.then(r => r.json())
			.then(d => {
				const text = d.text ?? _PLACEHOLDER_EN;
				_placeholderCache.set(lang, text);
				if (uctx.language === lang) placeholderText = text;
			})
			.catch(() => { placeholderText = _PLACEHOLDER_EN; })
			.finally(() => { placeholderLoading = false; });
	});

	onMount(() => loadUserContext());
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center gap-4">
		<span class="text-3xl">🗣️</span>
		<div class="flex-1">
			<h2 class="text-lg font-bold">Prompting</h2>
			<p class="text-xs text-surface-400-600 mt-0.5">
				Correct the bot's behaviour when it's not acting as expected. Instructions are sent to the Private AI (LLM) on every message as fine-tuning context.
			</p>
		</div>
		<button
			onclick={() => goto('/')}
			class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-surface-300-700
			text-surface-500-500 hover:bg-surface-100-900 transition-colors"
		>
			← Back
		</button>
	</div>

	<!-- User Context card -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<!-- Card header -->
		<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-3">
			<span class="text-xl">🗣️</span>
			<div class="flex-1 min-w-0">
				<p class="font-semibold text-sm">User Context</p>
				<p class="text-[10px] text-surface-400-600">
					Fine-tune the bot's behaviour when it's not acting as expected. These instructions are sent to the Private AI (LLM) on every message and directly influence how the bot thinks — use them to correct language detection, set default preferences, or teach it domain-specific rules.
				</p>
			</div>
			{#if uctxActive}
				<span class="text-[10px] font-medium px-1.5 py-0.5 rounded bg-warning-500/20 text-warning-400 shrink-0">active</span>
			{:else}
				<span class="text-[10px] font-medium px-1.5 py-0.5 rounded bg-surface-200-800 text-surface-400-600 shrink-0">inactive</span>
			{/if}
		</div>

		<!-- Body -->
		<div class="p-5 space-y-4">
			{#if uctx.loading}
				<div class="h-8 rounded-lg bg-surface-100-900 animate-pulse w-48"></div>
				<div class="h-32 rounded-lg bg-surface-100-900 animate-pulse"></div>
			{:else}
				<!-- Language selector -->
				<div class="flex items-center gap-3">
					<label for="uctx-lang" class="text-xs font-medium text-surface-400-600 shrink-0 w-28">Primary language</label>
					<select
						id="uctx-lang"
						bind:value={uctx.language}
						class="flex-1 text-xs bg-white text-black border border-surface-300 rounded-lg px-3 py-1.5
						focus:outline-none focus:ring-1 focus:ring-primary-500/60 transition-colors"
					>
						<option value="">— not set —</option>
						{#each uctx.supportedLanguages as lang}
							<option value={lang}>{lang}</option>
						{/each}
					</select>
				</div>

				<!-- Instructions textarea -->
				<div>
					<label for="uctx-instructions" class="block text-xs font-medium text-surface-400-600 mb-1.5">
						Instructions <span class="font-normal">(write in your native language — the more examples you give, especially corrections, the better the bot will behave)</span>
					</label>
					<textarea
						id="uctx-instructions"
						bind:value={uctx.instructions}
						rows="7"
						spellcheck="false"
						placeholder={placeholderLoading ? '…' : placeholderText}
						class="w-full text-xs bg-white text-black border border-surface-300
						rounded-lg p-3 resize-y leading-relaxed focus:outline-none
						focus:ring-1 focus:ring-primary-500/60 transition-colors placeholder:text-surface-400"
					></textarea>
				</div>

				<!-- Actions -->
				<div class="flex items-center gap-2">
					<button
						onclick={saveUserContext}
						disabled={uctx.saving || !uctxDirty}
						class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
						bg-primary-500/15 text-primary-400 hover:bg-primary-500/30
						disabled:opacity-40 disabled:cursor-not-allowed"
					>
						{uctx.saving ? 'Saving…' : '💾 Save'}
					</button>
					<button
						onclick={() => { uctx.language = uctx.original.language; uctx.instructions = uctx.original.instructions; }}
						disabled={!uctxDirty || uctx.saving}
						class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
						bg-surface-200-800 text-surface-500-500 hover:bg-surface-300-700
						disabled:opacity-40 disabled:cursor-not-allowed"
					>↩ Discard</button>
					{#if uctxActive}
						<button
							onclick={clearUserContext}
							disabled={uctx.clearing || uctx.saving}
							class="ml-auto px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
							bg-error-500/10 text-error-400 hover:bg-error-500/20
							disabled:opacity-40 disabled:cursor-not-allowed"
						>
							{uctx.clearing ? '…' : '🗑️ Clear'}
						</button>
					{/if}
				</div>

				{#if uctx.msg}
					<div class="text-xs px-3 py-2 rounded-lg
						{uctx.msg.ok ? 'bg-success-500/10 text-success-500' : 'bg-error-500/10 text-error-400'}">
						{uctx.msg.text}
					</div>
				{/if}
			{/if}
		</div>
	</div>
</div>

