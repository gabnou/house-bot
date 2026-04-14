<script lang="ts">
	import { onMount } from 'svelte';

	const SKILLS = [
		{ key: 'shopping', icon: '🛒', label: 'Shopping', desc: 'Item add/remove/bought detection, category extraction.' },
		{ key: 'weather',  icon: '🌤️', label: 'Weather',  desc: 'Forecast intent parsing, city and date extraction.' },
		{ key: 'calendar', icon: '📅', label: 'Calendar', desc: 'Event add/delete/edit, date and time extraction.' },
	];

	interface SkillState {
		original: string;
		text: string;
		isOverride: boolean;
		loading: boolean;
		saving: boolean;
		resetting: boolean;
		msg: { ok: boolean; text: string } | null;
	}

	let states = $state<Record<string, SkillState>>(
		Object.fromEntries(SKILLS.map(s => [s.key, {
			original: '', text: '', isOverride: false,
			loading: true, saving: false, resetting: false, msg: null,
		}]))
	);

	async function loadPrompt(skill: string) {
		states[skill].loading = true;
		states[skill].msg = null;
		try {
			const res = await fetch(`/admin/api/prompts/${skill}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			states[skill].original  = data.text;
			states[skill].text      = data.text;
			states[skill].isOverride = data.is_override;
		} catch (e: unknown) {
			states[skill].msg = { ok: false, text: e instanceof Error ? e.message : 'Load failed' };
		} finally {
			states[skill].loading = false;
		}
	}

	async function savePrompt(skill: string) {
		states[skill].saving = true;
		states[skill].msg = null;
		try {
			const res = await fetch(`/admin/api/prompts/${skill}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ text: states[skill].text }),
			});
			const data = await res.json();
			if (res.ok && data.ok) {
				states[skill].original  = states[skill].text;
				states[skill].isOverride = data.is_override;
				states[skill].msg = { ok: true, text: 'Saved — takes effect on next message.' };
			} else {
				states[skill].msg = { ok: false, text: data.detail ?? 'Save failed' };
			}
		} catch (e: unknown) {
			states[skill].msg = { ok: false, text: e instanceof Error ? e.message : 'Save failed' };
		} finally {
			states[skill].saving = false;
		}
	}

	async function resetPrompt(skill: string) {
		states[skill].resetting = true;
		states[skill].msg = null;
		try {
			const res = await fetch(`/admin/api/prompts/${skill}`, { method: 'DELETE' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			// Reload to get the Python default back
			await loadPrompt(skill);
			states[skill].msg = { ok: true, text: 'Reset to built-in default.' };
		} catch (e: unknown) {
			states[skill].msg = { ok: false, text: e instanceof Error ? e.message : 'Reset failed' };
		} finally {
			states[skill].resetting = false;
		}
	}

	onMount(() => SKILLS.forEach(s => loadPrompt(s.key)));
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center gap-4">
		<span class="text-3xl">✏️</span>
		<div>
			<h2 class="text-lg font-bold">Prompting</h2>
			<p class="text-xs text-surface-400-600 mt-0.5">
				Fine-tune the LLM prompts used by each skill — changes take effect on the next message, no restart needed.
			</p>
		</div>
	</div>

	<!-- Skill editors -->
	{#each SKILLS as skill}
		{@const s = states[skill.key]}
		{@const dirty = s.text !== s.original}
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
			<!-- Card header -->
			<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-3">
				<span class="text-xl">{skill.icon}</span>
				<div class="flex-1 min-w-0">
					<p class="font-semibold text-sm">{skill.label}</p>
					<p class="text-[10px] text-surface-400-600">{skill.desc}</p>
				</div>
				{#if s.isOverride}
					<span class="text-[10px] font-medium px-1.5 py-0.5 rounded bg-warning-500/20 text-warning-400 shrink-0">customised</span>
				{:else}
					<span class="text-[10px] font-medium px-1.5 py-0.5 rounded bg-surface-200-800 text-surface-400-600 shrink-0">default</span>
				{/if}
			</div>

			<!-- Editor body -->
			<div class="p-5 space-y-3">
				{#if s.loading}
					<div class="h-48 rounded-lg bg-surface-100-900 animate-pulse"></div>
				{:else}
					<textarea
						bind:value={s.text}
						rows="16"
						spellcheck="false"
						class="w-full font-mono text-xs bg-surface-900/80 dark:bg-surface-900 border border-surface-700
						rounded-lg p-3 resize-y text-surface-50 leading-relaxed focus:outline-none
						focus:ring-1 focus:ring-primary-500/60 transition-colors"
					></textarea>
				{/if}

				<!-- Actions -->
				<div class="flex items-center gap-2">
					<button
						onclick={() => savePrompt(skill.key)}
						disabled={s.saving || s.loading || !dirty}
						class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
						bg-primary-500/15 text-primary-400 hover:bg-primary-500/30
						disabled:opacity-40 disabled:cursor-not-allowed"
					>
						{s.saving ? 'Saving…' : '💾 Save'}
					</button>
					<button
						onclick={() => { states[skill.key].text = states[skill.key].original; }}
						disabled={!dirty || s.saving}
						class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
						bg-surface-200-800 text-surface-500-500 hover:bg-surface-300-700
						disabled:opacity-40 disabled:cursor-not-allowed"
					>
						↩ Discard
					</button>
					{#if s.isOverride}
						<button
							onclick={() => resetPrompt(skill.key)}
							disabled={s.resetting || s.saving}
							class="ml-auto px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
							bg-error-500/10 text-error-400 hover:bg-error-500/20
							disabled:opacity-40 disabled:cursor-not-allowed"
						>
							{s.resetting ? '…' : '🔄 Reset to default'}
						</button>
					{/if}
				</div>

				{#if s.msg}
					<div class="text-xs px-3 py-2 rounded-lg
						{s.msg.ok ? 'bg-success-500/10 text-success-500' : 'bg-error-500/10 text-error-400'}">
						{s.msg.text}
					</div>
				{/if}
			</div>
		</div>
	{/each}
</div>

