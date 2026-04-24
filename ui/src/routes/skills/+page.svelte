<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	// ── Skills state ──────────────────────────────────────────────────────────
	type SkillKey = 'calendar' | 'shopping' | 'weather';

	const SKILL_META: Record<SkillKey, { name: string; icon: string; description: string }> = {
		calendar: {
			name: 'Google Calendar',
			icon: '📅',
			description: 'View, add, edit and delete events on your Google Calendar via natural language.',
		},
		shopping: {
			name: 'Shopping List',
			icon: '🛒',
			description: 'Manage a shared shopping list — add items, mark them as bought, and clear the list.',
		},
		weather: {
			name: 'Weather Forecast',
			icon: '⛅',
			description: 'Get current conditions, hourly breakdowns and multi-day forecasts for any city.',
		},
	};

	let skillEnabled = $state<Record<SkillKey, boolean>>({
		calendar: true,
		shopping: true,
		weather: true,
	});
	let skillToggling = $state<Record<SkillKey, boolean>>({
		calendar: false,
		shopping: false,
		weather: false,
	});
	let skillMsg = $state<Record<SkillKey, { ok: boolean; text: string } | null>>({
		calendar: null,
		shopping: null,
		weather: null,
	});
	let skillOpen = $state<Record<SkillKey, boolean>>({
		calendar: false,
		shopping: false,
		weather: false,
	});

	async function loadSkills() {
		try {
			const res = await fetch('/admin/api/skills');
			if (res.ok) {
				const data = await res.json();
				for (const key of Object.keys(SKILL_META) as SkillKey[]) {
					if (data.skills[key] !== undefined) {
						skillEnabled[key] = data.skills[key].enabled;
					}
				}
			}
		} catch { /* non-fatal */ }
	}

	async function toggleSkill(key: SkillKey) {
		skillToggling[key] = true;
		skillMsg[key] = null;
		const newValue = !skillEnabled[key];
		try {
			const res = await fetch(`/admin/api/skills/${key}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ enabled: newValue }),
			});
			const data = await res.json();
			if (res.ok && data.ok) {
				skillEnabled[key] = newValue;
			} else {
				skillMsg[key] = { ok: false, text: data.detail ?? 'Failed to update skill.' };
			}
		} catch (e) {
			skillMsg[key] = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			skillToggling[key] = false;
		}
	}

	// ── Google Calendar OAuth state ───────────────────────────────────────────
	type GoogleStatus = 'unknown' | 'valid' | 'missing' | 'expired' | 'invalid';
	let googleStatus = $state<GoogleStatus>('unknown');
	let googleExpiry = $state<string | null>(null);
	let googleHasRefresh = $state(false);
	let googleCredsExist = $state(false);
	let googleFlowRunning = $state(false);
	let googleAuthUrl = $state<string | null>(null);
	let googleLoading = $state(false);
	let googleMsg = $state<{ ok: boolean; text: string } | null>(null);

	// Credentials paste-and-upload state
	let googleClientId = $state('');
	let googleClientSecret = $state('');
	let googleCredsSubmitting = $state(false);
	let googleCredsMsg = $state<{ ok: boolean; text: string } | null>(null);

	// Calendar picker state
	let googleCalendars = $state<{ id: string; name: string; primary: boolean }[]>([]);
	let googleCalendarsLoading = $state(false);
	let googleCalendarsError = $state<string | null>(null);
	let googleConfiguredCalendar = $state('');
	let googleSelectedCalendar = $state('');
	let calendarQuery = $state('');
	let googleCalendarSaving = $state(false);

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
				await loadCalendars();
			}
		}, 3000);
	}

	function _stopPolling() {
		if (_googlePollTimer) { clearInterval(_googlePollTimer); _googlePollTimer = null; }
	}

	async function loadGoogleStatus() {
		try {
			const res = await fetch('/admin/api/install/google-auth/status');
			if (res.ok) {
				const data = await res.json();
				googleStatus = data.status ?? 'unknown';
				googleExpiry = data.expiry ?? null;
				googleHasRefresh = data.has_refresh ?? false;
				googleCredsExist = data.credentials_exist ?? false;
				googleFlowRunning = data.flow_running ?? false;
				if (data.configured_calendar) googleConfiguredCalendar = data.configured_calendar;
			}
		} catch { /* non-fatal */ }
	}

	async function loadCalendars() {
		googleCalendarsLoading = true;
		googleCalendarsError = null;
		try {
			const res = await fetch('/admin/api/install/google-auth/calendars');
			if (res.ok) {
				const data = await res.json();
				googleCalendars = data.calendars ?? [];
				googleConfiguredCalendar = data.configured ?? '';
				googleSelectedCalendar = googleConfiguredCalendar;
				calendarQuery = '';
			} else {
				const err = await res.json().catch(() => ({}));
				googleCalendarsError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			googleCalendarsError = e instanceof Error ? e.message : 'Request failed';
		} finally {
			googleCalendarsLoading = false;
		}
	}

	async function saveGoogleCredentials() {
		googleCredsMsg = null;
		googleCredsSubmitting = true;
		try {
			const json = JSON.stringify({
				installed: {
					client_id: googleClientId.trim(),
					client_secret: googleClientSecret.trim(),
					auth_uri: 'https://accounts.google.com/o/oauth2/auth',
					token_uri: 'https://oauth2.googleapis.com/token',
					auth_provider_x509_cert_url: 'https://www.googleapis.com/oauth2/v1/certs',
					redirect_uris: ['http://localhost'],
				},
			});
			const res = await fetch('/admin/api/install/google-auth/credentials', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ content: json }),
			});
			const data = await res.json();
			if (res.ok && data.ok) {
				googleCredsMsg = { ok: true, text: 'Credentials saved — you can now authorize your Google account.' };
				googleClientId = '';
				googleClientSecret = '';
				await loadGoogleStatus();
			} else {
				googleCredsMsg = { ok: false, text: data.detail ?? 'Failed to save credentials.' };
			}
		} catch (e) {
			googleCredsMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			googleCredsSubmitting = false;
		}
	}

	async function startGoogleAuth() {
		googleLoading = true;
		googleMsg = null;
		googleAuthUrl = null;
		try {
			const res = await fetch('/admin/api/install/google-auth', { method: 'POST' });
			const data = await res.json();
			if (res.ok && data.ok) {
				googleAuthUrl = data.auth_url;
				googleFlowRunning = true;
				window.open(data.auth_url, '_blank', 'noopener,noreferrer');
				_startPolling();
			} else {
				googleMsg = { ok: false, text: data.detail ?? 'Failed to start OAuth flow' };
			}
		} catch (e) {
			googleMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			googleLoading = false;
		}
	}

	async function refreshGoogleToken() {
		googleLoading = true;
		googleMsg = null;
		try {
			const res = await fetch('/admin/api/install/google-auth/refresh', { method: 'POST' });
			const data = await res.json();
			if (res.ok && data.ok) {
				googleMsg = { ok: true, text: 'Token refreshed successfully.' };
				await loadGoogleStatus();
			} else {
				googleMsg = { ok: false, text: data.detail ?? 'Refresh failed' };
			}
		} catch (e) {
			googleMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			googleLoading = false;
		}
	}

	async function saveCalendar() {
		if (!googleSelectedCalendar) return;
		googleCalendarSaving = true;
		googleMsg = null;
		try {
			const res = await fetch('/admin/api/install/google-auth/calendar', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ name: googleSelectedCalendar }),
			});
			const data = await res.json();
			if (res.ok && data.ok) {
				googleConfiguredCalendar = googleSelectedCalendar;
				googleMsg = { ok: true, text: `Calendar set to "${googleSelectedCalendar}" and saved to .env.` };
			} else {
				googleMsg = { ok: false, text: data.detail ?? 'Failed to save calendar' };
			}
		} catch (e) {
			googleMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			googleCalendarSaving = false;
		}
	}

	async function revokeGoogleToken() {
		googleLoading = true;
		googleMsg = null;
		try {
			const res = await fetch('/admin/api/install/google-auth', { method: 'DELETE' });
			const data = await res.json();
			if (res.ok) {
				googleStatus = 'missing';
				googleExpiry = null;
				googleAuthUrl = null;
				googleCalendars = [];
				googleSelectedCalendar = '';
				calendarQuery = '';
				googleMsg = { ok: true, text: 'Disconnected — click Authorize to reestablish.' };
			} else {
				googleMsg = { ok: false, text: data.detail ?? 'Revoke failed' };
			}
		} catch (e) {
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
			googleMsg = { ok: false, text: 'Not yet — complete the authorization in the browser tab.' };
		} else {
			googleMsg = { ok: false, text: `Status: ${googleStatus}` };
		}
	}

	onMount(async () => {
		await loadSkills();
		await loadGoogleStatus();
		if (googleStatus === 'valid') await loadCalendars();
		await loadShoppingCategories();
	});

	// ── Shopping categories state ─────────────────────────────────────────────
	type CategoryEntry = { name: string; hint: string; builtin?: boolean };
	let builtinCategories = $state<CategoryEntry[]>([]);
	let dynamicCategories = $state<{ name: string }[]>([]);
	let catMsg = $state<{ ok: boolean; text: string } | null>(null);
	let catDeleting = $state<string | null>(null);

	async function loadShoppingCategories() {
		try {
			const res = await fetch('/admin/api/skills/shopping/categories');
			if (res.ok) {
				const data = await res.json();
				builtinCategories = data.builtin ?? [];
				dynamicCategories = data.dynamic ?? [];
			}
		} catch { /* non-fatal */ }
	}

	async function deleteShoppingCategory(name: string) {
		catMsg = null;
		catDeleting = name;
		try {
			const res = await fetch(`/admin/api/skills/shopping/categories/${encodeURIComponent(name)}`, { method: 'DELETE' });
			const data = await res.json();
			if (res.ok && data.ok) {
				dynamicCategories = data.dynamic ?? [];
				const n = data.items_moved ?? 0;
				if (n > 0) catMsg = { ok: true, text: `Category removed. ${n} item${n === 1 ? '' : 's'} re-categorised automatically.` };
			} else {
				catMsg = { ok: false, text: data.detail ?? 'Failed to delete category.' };
			}
		} catch (e) {
			catMsg = { ok: false, text: e instanceof Error ? e.message : 'Request failed' };
		} finally {
			catDeleting = null;
		}
	}
</script>

<div class="space-y-6">

	<!-- Page header -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center gap-4">
		<span class="text-3xl">🧩</span>
		<div class="flex-1">
			<h2 class="text-lg font-bold">Skills</h2>
			<p class="text-xs text-surface-400-600 mt-0.5">Enable or disable bot capabilities. Disabled skills won't respond to related messages.</p>
		</div>
		<button
			onclick={() => goto('/')}
			class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-surface-300-700
			text-surface-500-500 hover:bg-surface-100-900 transition-colors"
		>
			← Back
		</button>
	</div>

	<!-- ── Google Calendar skill ──────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">

		<!-- Skill header row -->
		<div
			role="button"
			tabindex="0"
			onclick={() => skillOpen.calendar = !skillOpen.calendar}
			onkeydown={(e) => e.key === 'Enter' && (skillOpen.calendar = !skillOpen.calendar)}
			class="w-full px-5 py-4 flex items-center gap-4 cursor-pointer hover:bg-surface-100-900/50 transition-colors select-none"
		>
			<span class="text-2xl shrink-0">📅</span>
			<div class="flex-1 min-w-0">
				<p class="font-semibold text-sm">Google Calendar</p>
				<p class="text-xs text-surface-400-600 mt-0.5">
					{#if skillEnabled.calendar && googleStatus === 'valid' && googleConfiguredCalendar}
						Connected · <span class="font-medium text-surface-900-50">{googleConfiguredCalendar}</span>
					{:else}
						{SKILL_META.calendar.description}
					{/if}
				</p>
			</div>
			<!-- Status badge -->
			{#if skillEnabled.calendar}
				{#if googleStatus === 'valid'}
					<span class="text-[10px] px-2 py-0.5 rounded-full bg-success-500/15 text-success-400 font-medium shrink-0">authorized</span>
				{:else if googleStatus === 'expired'}
					<span class="text-[10px] px-2 py-0.5 rounded-full bg-warning-500/10 text-warning-400 font-medium shrink-0">expired</span>
				{:else if googleStatus !== 'unknown'}
					<span class="text-[10px] px-2 py-0.5 rounded-full bg-error-500/10 text-error-400 font-medium shrink-0">not connected</span>
				{/if}
			{/if}
			<!-- Enable toggle -->
			<button
				onclick={(e) => { e.stopPropagation(); toggleSkill('calendar'); }}
				disabled={skillToggling.calendar}
				class="shrink-0 relative inline-flex h-6 w-11 items-center rounded-full transition-colors
				{skillEnabled.calendar ? 'bg-primary-500' : 'bg-surface-300-700'}
				disabled:opacity-40 disabled:cursor-not-allowed"
				aria-label="Toggle Google Calendar skill"
			>
				<span class="inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform
					{skillEnabled.calendar ? 'translate-x-6' : 'translate-x-1'}"></span>
			</button>
			<!-- Chevron -->
			<span class="text-surface-400-600 text-xs shrink-0 transition-transform {skillOpen.calendar ? 'rotate-180' : ''}">▼</span>
		</div>

		{#if skillMsg.calendar}
			<div class="px-5 pb-3">
				<p class="text-xs {skillMsg.calendar.ok ? 'text-success-500' : 'text-error-400'}">{skillMsg.calendar.text}</p>
			</div>
		{/if}

		<!-- Google Calendar configuration (shown when enabled AND expanded) -->
		{#if skillEnabled.calendar && skillOpen.calendar}
			<div class="border-t border-surface-200-800 p-5 space-y-4">

				<!-- Section title + refresh -->
				<div class="flex items-center justify-between">
					<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Google Account Configuration</p>
					<button
						onclick={loadGoogleStatus}
						class="text-xs px-2 py-1 rounded bg-surface-100-900 hover:bg-surface-200-800
						text-surface-500-500 transition-colors"
					>↻ Refresh</button>
				</div>

				<!-- No credentials file warning + paste form -->
				{#if !googleCredsExist}
					<div class="space-y-3">
						<div class="flex items-start gap-3 px-4 py-3 rounded-xl border border-error-500/40 bg-error-500/10">
							<span class="text-xl mt-0.5">⚠️</span>
							<div class="flex-1 min-w-0">
								<p class="font-semibold text-xs text-error-400">Google OAuth credentials file missing</p>
								<p class="text-xs text-surface-400-600 mt-1">
									HouseBot needs a Google Cloud project with the Calendar API enabled.
								</p>
								<p class="text-xs font-medium text-surface-400-600 mt-2">If you don't have a Google Cloud project yet:</p>
								<ol class="text-xs text-surface-400-600 mt-1 list-decimal list-inside space-y-0.5">
									<li>Go to <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">Create a new project ↗</a> — give it a meaningful name (e.g. <em>HouseBot</em>)</li>
									<li>Enable the <a href="https://console.cloud.google.com/apis/library/calendar-json.googleapis.com" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">Google Calendar API ↗</a></li>
									<li>Configure the <a href="https://console.cloud.google.com/apis/credentials/consent" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">OAuth consent screen ↗</a> (External, add your Google account as a test user)</li>
								</ol>
								<p class="text-xs font-medium text-surface-400-600 mt-2">Then create the OAuth credentials:</p>
								<ol class="text-xs text-surface-400-600 mt-1 list-decimal list-inside space-y-0.5">
									<li>Open <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">APIs &amp; Services → Credentials ↗</a></li>
									<li>Click <strong>+ CREATE CREDENTIALS</strong> → <strong>OAuth client ID</strong></li>
									<li>Choose application type <strong>Desktop app</strong>, click <strong>Create</strong></li>
									<li>Copy the <strong>Client ID</strong> and <strong>Client Secret</strong> and paste them below</li>
								</ol>
							</div>
						</div>

						<!-- Credentials form -->
						<div class="space-y-3">
							<div class="space-y-1">
								<p class="text-xs font-medium text-surface-400-600">Client ID</p>
								<input
									bind:value={googleClientId}
									type="text"
									spellcheck="false"
									placeholder="1234567890-abc….apps.googleusercontent.com"
									class="w-full font-mono text-xs rounded-lg border border-surface-300-700
									bg-surface-100-900 text-surface-900-50 placeholder:text-surface-400-600
									focus:outline-none focus:border-primary-500/60 px-3 py-2 transition-colors"
								/>
							</div>
							<div class="space-y-1">
								<p class="text-xs font-medium text-surface-400-600">Client Secret</p>
								<input
									bind:value={googleClientSecret}
									type="password"
									spellcheck="false"
									placeholder="GOCSPX-…"
									class="w-full font-mono text-xs rounded-lg border border-surface-300-700
									bg-surface-100-900 text-surface-900-50 placeholder:text-surface-400-600
									focus:outline-none focus:border-primary-500/60 px-3 py-2 transition-colors"
								/>
							</div>
							<div class="flex items-center gap-3">
								<button
									onclick={saveGoogleCredentials}
									disabled={googleCredsSubmitting || !googleClientId.trim() || !googleClientSecret.trim()}
									class="px-4 py-2 rounded-lg text-xs font-semibold bg-primary-500/20 text-primary-400
									hover:bg-primary-500/30 border border-primary-500/40 transition-colors
									disabled:opacity-40 disabled:cursor-not-allowed"
								>
									{googleCredsSubmitting ? '…' : '💾 Save Credentials'}
								</button>
								{#if googleCredsMsg}
									<span class="text-xs {googleCredsMsg.ok ? 'text-success-500' : 'text-error-400'}">
										{googleCredsMsg.text}
									</span>
								{/if}
							</div>
						</div>
					</div>
				{/if}

				<!-- Token status card -->
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
					{#if googleStatus === 'expired' && googleHasRefresh}
						<button
							onclick={refreshGoogleToken}
							disabled={googleLoading}
							class="shrink-0 text-xs px-2 py-1 rounded bg-warning-500/10 hover:bg-warning-500/20
							text-warning-400 transition-colors disabled:opacity-40"
						>🔄 Refresh Token</button>
					{/if}
				</div>

				<!-- OAuth flow pending banner -->
				{#if googleFlowRunning && googleAuthUrl}
					<div class="flex items-start gap-3 px-4 py-3 rounded-xl border border-primary-500/30 bg-primary-500/5">
						<span class="text-lg mt-0.5">🌐</span>
						<div class="flex-1 min-w-0">
							<p class="text-xs font-semibold text-primary-400">Waiting for authorization…</p>
							<p class="text-xs text-surface-400-600 mt-1">
								Complete the sign-in in the browser tab that opened. If it didn't open,
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
					<button
						onclick={startGoogleAuth}
						disabled={googleLoading || googleFlowRunning || !googleCredsExist}
						class="px-4 py-2 rounded-lg text-xs font-semibold bg-primary-500/20 text-primary-400
						hover:bg-primary-500/30 border border-primary-500/40 transition-colors
						disabled:opacity-40 disabled:cursor-not-allowed"
					>
						{googleLoading ? '…' : googleFlowRunning ? '⏳ Waiting…' : googleStatus === 'valid' ? '🔑 Re-authorize' : '🔑 Authorize'}
					</button>
				</div>

				{#if googleMsg}
					<div class="text-xs px-3 py-2 rounded-lg
						{googleMsg.ok ? 'bg-success-500/10 text-success-500' : 'bg-error-500/10 text-error-400'}">
						{googleMsg.text}
					</div>
				{/if}

				{#if googleStatus !== 'valid'}
					<div class="text-xs text-surface-400-600 space-y-1 pt-1 border-t border-surface-200-800">
						<p class="font-semibold text-surface-500-500">How it works</p>
						<ol class="list-decimal list-inside space-y-1">
							<li>Click <strong>Authorize</strong> — a Google sign-in tab opens.</li>
							<li>Sign in and grant calendar access.</li>
							<li>The tab closes automatically. Click <strong>Check again</strong> to confirm.</li>
						</ol>
					</div>
				{/if}

				<!-- Calendar picker + revoke — shown when token is valid -->
				{#if googleStatus === 'valid'}
					<div class="space-y-3 pt-1 border-t border-surface-200-800">
						<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Choose calendar</p>
						{#if googleCalendarsLoading}
							<p class="text-xs text-surface-400-600">Loading calendars…</p>
						{:else if googleCalendarsError}
							<p class="text-xs text-error-400">❌ {googleCalendarsError}</p>
						{:else if googleCalendars.length === 0}
							<p class="text-xs text-surface-400-600">No calendars found. <button onclick={loadCalendars} class="text-primary-400 hover:underline">Reload</button></p>
						{:else}
							<input
								type="text"
								bind:value={calendarQuery}
								placeholder="Search calendars…"
								class="w-full text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
								text-surface-900-50 placeholder:text-surface-400-600
								focus:outline-none focus:border-primary-500/60"
							/>
							{@const sorted = [
								...googleCalendars.filter(c => c.name === googleConfiguredCalendar),
								...googleCalendars.filter(c => c.name !== googleConfiguredCalendar),
							]}
							{@const filtered = sorted.filter(c => !calendarQuery.trim() || c.name.toLowerCase().includes(calendarQuery.toLowerCase()))}
							<div class="max-h-48 overflow-y-auto rounded-lg border border-surface-200-800 bg-surface-50-950">
								{#each filtered as cal}
									<button
										onclick={() => googleSelectedCalendar = cal.name}
										class="w-full text-left px-3 py-2.5 flex items-center gap-2 hover:bg-surface-100-900 transition-colors
										       {googleSelectedCalendar === cal.name ? 'bg-primary-500/10' : ''}"
									>
										<span class="text-xs flex-1">{cal.name}</span>
										{#if cal.primary}<span class="text-[10px] text-surface-400-600">primary</span>{/if}
										{#if googleConfiguredCalendar === cal.name}<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-success-500/20 text-success-400 font-medium">selected</span>{/if}
									</button>
								{/each}
								{#if filtered.length === 0}
									<p class="text-xs text-surface-400-600 px-3 py-2">No match</p>
								{/if}
							</div>
							<button
								onclick={saveCalendar}
								disabled={googleCalendarSaving || !googleSelectedCalendar || googleSelectedCalendar === googleConfiguredCalendar}
								class="px-4 py-2 rounded-lg text-xs font-semibold bg-primary-500/20 text-primary-400
								hover:bg-primary-500/30 border border-primary-500/40 transition-colors
								disabled:opacity-40 disabled:cursor-not-allowed"
							>
								{googleCalendarSaving ? '…' : '💾 Save Calendar'}
							</button>
						{/if}
					</div>

					<!-- Revoke / reestablish -->
					<div class="pt-2 border-t border-surface-200-800 flex items-center gap-3">
						<p class="text-xs text-surface-400-600 flex-1">Need to change account or reestablish the integration?</p>
						<button
							onclick={revokeGoogleToken}
							disabled={googleLoading}
							class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium bg-error-500/15 text-error-400
							hover:bg-error-500/25 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
						>
							{googleLoading ? '…' : '🔌 Disconnect'}
						</button>
					</div>
				{/if}

			</div>
		{/if}
	</div>

	<!-- ── Shopping List skill ────────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div
			role="button"
			tabindex="0"
			onclick={() => skillOpen.shopping = !skillOpen.shopping}
			onkeydown={(e) => e.key === 'Enter' && (skillOpen.shopping = !skillOpen.shopping)}
			class="w-full px-5 py-4 flex items-center gap-4 cursor-pointer hover:bg-surface-100-900/50 transition-colors select-none"
		>
			<span class="text-2xl shrink-0">🛒</span>
			<div class="flex-1 min-w-0">
				<p class="font-semibold text-sm">Shopping List</p>
				<p class="text-xs text-surface-400-600 mt-0.5">{SKILL_META.shopping.description}</p>
			</div>
			<!-- Enable toggle -->
			<button
				onclick={(e) => { e.stopPropagation(); toggleSkill('shopping'); }}
				disabled={skillToggling.shopping}
				class="shrink-0 relative inline-flex h-6 w-11 items-center rounded-full transition-colors
				{skillEnabled.shopping ? 'bg-primary-500' : 'bg-surface-300-700'}
				disabled:opacity-40 disabled:cursor-not-allowed"
				aria-label="Toggle Shopping List skill"
			>
				<span class="inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform
					{skillEnabled.shopping ? 'translate-x-6' : 'translate-x-1'}"></span>
			</button>
			<!-- Chevron -->
			<span class="text-surface-400-600 text-xs shrink-0 transition-transform {skillOpen.shopping ? 'rotate-180' : ''}">▼</span>
		</div>

		{#if skillMsg.shopping}
			<div class="px-5 pb-3">
				<p class="text-xs {skillMsg.shopping.ok ? 'text-success-500' : 'text-error-400'}">{skillMsg.shopping.text}</p>
			</div>
		{/if}

		{#if skillEnabled.shopping && skillOpen.shopping}
			<div class="border-t border-surface-200-800 p-5 space-y-5">

				<!-- Built-in categories (read-only) -->
				<div class="space-y-2">
					<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Built-in categories</p>
					<p class="text-[11px] text-surface-400-600">These are fixed and cannot be removed.</p>
					<div class="space-y-1.5">
						{#each builtinCategories as cat}
							<div class="flex items-start gap-3 px-3 py-2.5 rounded-lg border border-surface-200-800 bg-surface-100-900/50">
								<span class="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-surface-200-800 text-surface-500-500 shrink-0 mt-0.5">{cat.name}</span>
								<p class="text-[11px] text-surface-400-600 flex-1">{cat.hint}</p>
								<span class="text-[10px] text-surface-400-600 shrink-0 opacity-60">built-in</span>
							</div>
						{/each}
					</div>
				</div>

				<!-- Dynamic categories -->
				<div class="space-y-2 pt-3 border-t border-surface-200-800">
					<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">AI-generated categories</p>
					<p class="text-[11px] text-surface-400-600">
						Created automatically when items don't fit a built-in category. Remove one to have its items re-classified.
					</p>

					{#if dynamicCategories.length > 0}
						<div class="space-y-1.5">
							{#each dynamicCategories as cat}
								<div class="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-surface-200-800 bg-surface-50-950">
									<span class="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-primary-500/15 text-primary-400 shrink-0">{cat.name}</span>
									<p class="text-[11px] text-surface-400-600 flex-1 italic">AI-generated</p>
									<button
										onclick={() => deleteShoppingCategory(cat.name)}
										disabled={catDeleting === cat.name}
										class="shrink-0 text-[10px] px-2 py-0.5 rounded bg-error-500/10 text-error-400
										hover:bg-error-500/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
									>
										{catDeleting === cat.name ? '…' : '✕ remove'}
									</button>
								</div>
							{/each}
						</div>
					{:else}
						<p class="text-[11px] text-surface-400-600 italic">None yet — the bot will create them automatically as needed.</p>
					{/if}

					{#if catMsg}
						<p class="text-xs {catMsg.ok ? 'text-success-500' : 'text-error-400'}">{catMsg.text}</p>
					{/if}
				</div>

			</div>
		{/if}
	</div>

	<!-- ── Weather Forecast skill ─────────────────────────────────────────────── -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">
		<div
			role="button"
			tabindex="0"
			onclick={() => skillOpen.weather = !skillOpen.weather}
			onkeydown={(e) => e.key === 'Enter' && (skillOpen.weather = !skillOpen.weather)}
			class="w-full px-5 py-4 flex items-center gap-4 cursor-pointer hover:bg-surface-100-900/50 transition-colors select-none"
		>
			<span class="text-2xl shrink-0">⛅</span>
			<div class="flex-1 min-w-0">
				<p class="font-semibold text-sm">Weather Forecast</p>
				<p class="text-xs text-surface-400-600 mt-0.5">{SKILL_META.weather.description}</p>
			</div>
			<!-- Enable toggle -->
			<button
				onclick={(e) => { e.stopPropagation(); toggleSkill('weather'); }}
				disabled={skillToggling.weather}
				class="shrink-0 relative inline-flex h-6 w-11 items-center rounded-full transition-colors
				{skillEnabled.weather ? 'bg-primary-500' : 'bg-surface-300-700'}
				disabled:opacity-40 disabled:cursor-not-allowed"
				aria-label="Toggle Weather Forecast skill"
			>
				<span class="inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform
					{skillEnabled.weather ? 'translate-x-6' : 'translate-x-1'}"></span>
			</button>
			<!-- Chevron -->
			<span class="text-surface-400-600 text-xs shrink-0 transition-transform {skillOpen.weather ? 'rotate-180' : ''}">▼</span>
		</div>

		{#if skillMsg.weather}
			<div class="px-5 pb-3">
				<p class="text-xs {skillMsg.weather.ok ? 'text-success-500' : 'text-error-400'}">{skillMsg.weather.text}</p>
			</div>
		{/if}

		{#if skillEnabled.weather && skillOpen.weather}
			<div class="border-t border-surface-200-800 px-5 py-4">
				<div class="flex items-start gap-3 px-4 py-3 rounded-xl border border-surface-200-800 bg-surface-100-900/50">
					<span class="text-base mt-0.5">🌐</span>
					<div>
						<p class="text-xs font-semibold">Open-Meteo (free, no API key)</p>
						<p class="text-[11px] text-surface-400-600 mt-0.5">
							Weather data is fetched from <a href="https://open-meteo.com" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">Open-Meteo ↗</a>.
							Default city and coordinates are configured in the
							<a href="/config" class="text-primary-400 hover:underline">Configuration page</a>.
						</p>
						<p class="text-[11px] text-surface-400-600 mt-1.5">
							Additional configuration options coming soon.
						</p>
					</div>
				</div>
			</div>
		{/if}
	</div>

</div>
