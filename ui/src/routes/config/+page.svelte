<script lang="ts">
	const groups = [
		{
			label: 'LLM / Ollama',
			icon: '🧠',
			keys: [
				{ key: 'OLLAMA_URL',   hint: 'e.g. http://localhost:11434/api/generate' },
				{ key: 'OLLAMA_MODEL', hint: 'e.g. mistral-small:22b' },
			],
		},
		{
			label: 'WhatsApp',
			icon: '📱',
			keys: [
				{ key: 'PARTNER_LID',  hint: 'Format: jid:name,jid:name (e.g. 93119253@lid:Alice)' },
			],
		},
		{
			label: 'Google Calendar',
			icon: '📅',
			keys: [
				{ key: 'GOOGLE_CALENDAR_NAME', hint: 'Calendar display name' },
			],
		},
		{
			label: 'Weather',
			icon: '🌤️',
			keys: [
				{ key: 'DEFAULT_CITY',      hint: 'e.g. Rome' },
				{ key: 'DEFAULT_LATITUDE',  hint: 'e.g. 41.9028' },
				{ key: 'DEFAULT_LONGITUDE', hint: 'e.g. 12.4964' },
			],
		},
		{
			label: 'Scheduler',
			icon: '⏰',
			keys: [
				{ key: 'BRIEFING_TIME',     hint: 'HH:MM, e.g. 07:30' },
				{ key: 'BRIEFING_LANGUAGE', hint: 'e.g. Italian' },
				{ key: 'TIMEZONE_DEFAULT',  hint: 'e.g. Europe/Rome' },
			],
		},
		{
			label: 'System',
			icon: '🔧',
			keys: [
				{ key: 'WHISPER_MODEL', hint: 'small / medium / large' },
				{ key: 'LOG_LEVEL',     hint: 'DEBUG / INFO / WARNING / ERROR' },
			],
		},
	];
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center justify-between">
		<div class="flex items-center gap-4">
			<span class="text-3xl">⚙️</span>
			<div>
				<h2 class="text-lg font-bold">Configuration</h2>
				<p class="text-xs text-surface-400-600 mt-0.5">View and edit your <code class="font-mono">.env</code> settings, grouped by feature.</p>
			</div>
		</div>
		<button
			class="opacity-40 cursor-not-allowed px-4 py-2 rounded-lg text-sm font-medium bg-primary-500/20 text-primary-400"
			disabled
		>
			Save changes
		</button>
	</div>

	<!-- Groups -->
	{#each groups as group}
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
			<div class="px-5 py-3.5 border-b border-surface-200-800 flex items-center gap-2">
				<span>{group.icon}</span>
				<h3 class="font-semibold text-sm">{group.label}</h3>
			</div>
			<div class="divide-y divide-surface-100-900">
				{#each group.keys as row}
					<div class="flex items-center gap-4 px-5 py-3">
						<span class="font-mono text-xs text-primary-400 w-52 shrink-0">{row.key}</span>
						<input
							type="text"
							placeholder={row.hint}
							disabled
							class="flex-1 bg-surface-100-900 text-surface-400-600 text-xs font-mono px-3 py-1.5
							rounded border border-surface-200-800 cursor-not-allowed opacity-60"
						/>
					</div>
				{/each}
			</div>
		</div>
	{/each}

</div>
