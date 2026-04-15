<script lang="ts">
	import { goto } from '$app/navigation';

	const steps = [
		{
			n: 1,
			icon: '🤖',
			label: 'Ollama — AI Models',
			desc: 'Select and pull a local LLM model to power the bot (e.g. mistral-small:22b or llama3.1:8b).',
			phase: 5,
		},
		{
			n: 2,
			icon: '⚙️',
			label: 'Configure .env',
			desc: 'Fill in LLM model, WhatsApp JIDs, weather location, and scheduler settings.',
			phase: 5,
		},
		{
			n: 3,
			icon: '🔑',
			label: 'Google OAuth',
			desc: 'Trigger the Google Calendar auth flow and store the token automatically.',
			phase: 5,
		},
		{
			n: 4,
			icon: '📱',
			label: 'WhatsApp Pairing',
			desc: 'Display the QR code and wait for the phone to scan and pair.',
			phase: 5,
		},
		{
			n: 5,
			icon: '👤',
			label: 'JID Detection',
			desc: 'Send a test WhatsApp message to detect and persist partner JIDs automatically.',
			phase: 5,
		},
		{
			n: 6,
			icon: '✅',
			label: 'Smoke Test',
			desc: 'Run a quick end-to-end check: shopping list, weather, and calendar queries.',
			phase: 5,
		},
	];

	let showSkipWarning = $state(false);

	function skip() {
		showSkipWarning = true;
	}

	function confirmSkip() {
		goto('/');
	}
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
			</div>
		{/each}
	</div>
</div>
