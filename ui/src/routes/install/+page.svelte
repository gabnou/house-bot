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
	let configuredModel = $state('');
	let modelsLoading = $state(false);
	let modelsChecked = $state(false);
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
				configuredModel = data.configured ?? '';
				if (!chatModel && installedModels.length > 0) chatModel = installedModels[0];
			}
		} catch {
			// non-fatal
		} finally {
			modelsLoading = false;
			modelsChecked = true;
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
			// If the test succeeded, persist this model as the configured one
			if (receivedTokens && !chatError) {
				fetch('/admin/api/ollama/switch', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ model: chatModel }),
				}).then(r => { if (r.ok) configuredModel = chatModel; }).catch(() => {});
			}
		} catch (e) {
			chatError = e instanceof Error ? e.message : String(e);
		} finally {
			chatLoading = false;
		}
	}

	// ── Step 2: Google OAuth ─────────────────────────────────────────────────────
	let step2Open = $state(false);

	type GoogleStatus = 'unknown' | 'valid' | 'missing' | 'expired' | 'invalid';
	let googleStatus = $state<GoogleStatus>('unknown');
	let googleExpiry = $state<string | null>(null);
	let googleHasRefresh = $state(false);
	let googleCredsExist = $state(false);
	let googleFlowRunning = $state(false);
	let googleAuthUrl = $state<string | null>(null);
	let googleLoading = $state(false);
	let googleMsg = $state<{ ok: boolean; text: string } | null>(null);

	const step2Done = $derived(googleStatus === 'valid');

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
			const res = await fetch('/admin/api/install/google-auth/status');
			if (res.ok) {
				const data = await res.json();
				googleStatus = data.status ?? 'unknown';
				googleExpiry = data.expiry ?? null;
				googleHasRefresh = data.has_refresh ?? false;
				googleCredsExist = data.credentials_exist ?? false;
				googleFlowRunning = data.flow_running ?? false;
			}
		} catch { /* non-fatal */ }
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

	async function toggleStep2() {
		step2Open = !step2Open;
		if (step2Open) await loadGoogleStatus();
	}

	// ── Eager status load on mount ───────────────────────────────────────────────
	$effect(() => {
		loadInstalledModels();
		loadGoogleStatus();
		// Silently check bridge so Step 3 header badge shows correct status without opening the panel
		loadWaQr();
		// Silently load authorized senders so Step 4 header badge is correct without opening
		loadAuthorizedSenders();
		// Silently load location settings so Step 5 header badge is correct without opening
		loadLocationSettings();
	});

	// ── Step 3: WhatsApp Pairing ────────────────────────────────────────────────
	let step3Open = $state(false);
	type WaState = 'idle' | 'loading' | 'connected' | 'qr' | 'error';
	let waState = $state<WaState>('idle');
	let waQr = $state<string | null>(null);
	let waError = $state<string | null>(null);
	let _waPollTimer: ReturnType<typeof setInterval> | null = null;

	const step3Done = $derived(waState === 'connected');

	function _stopWaPoll() {
		if (_waPollTimer) { clearInterval(_waPollTimer); _waPollTimer = null; }
	}

	async function loadWaQr() {
		waState = 'loading';
		waError = null;
		try {
			const res = await fetch('/admin/api/install/whatsapp/qr');
			if (!res.ok) {
				const d = await res.json().catch(() => ({}));
				waError = d.detail ?? `HTTP ${res.status}`;
				waState = 'error';
				return;
			}
			const data = await res.json();
			if (data.connected) {
				waState = 'connected';
				waQr = null;
				_stopWaPoll();
			} else if (data.qr) {
				waState = 'qr';
				waQr = data.qr;
			} else {
				waError = data.error ?? 'QR not yet available — bridge may be starting up';
				waState = 'error';
			}
		} catch (e) {
			waError = e instanceof Error ? e.message : 'Request failed';
			waState = 'error';
		}
	}

	function startWaPoll() {
		_stopWaPoll();
		loadWaQr();
		_waPollTimer = setInterval(async () => {
			if (waState === 'connected') { _stopWaPoll(); return; }
			await loadWaQr();
		}, 5000);
	}

	async function toggleStep3() {
		step3Open = !step3Open;
		if (step3Open && waState === 'idle') startWaPoll();
		if (step3Open) await loadWaAppName();
		if (!step3Open) _stopWaPoll();
	}

	// ── Step 3: WA app name ──────────────────────────────────────────────────────
	let waAppName        = $state('');
	let waAppNameSaving  = $state(false);
	let waAppNameSaved   = $state(false);
	let waAppNameError   = $state<string | null>(null);

	async function loadWaAppName() {
		try {
			const res = await fetch('/admin/api/install/wa-app-name');
			if (res.ok) waAppName = (await res.json()).value ?? 'HouseBot';
		} catch { /* non-fatal */ }
	}

	async function saveWaAppName() {
		waAppNameSaving = true;
		waAppNameSaved  = false;
		waAppNameError  = null;
		try {
			const res = await fetch('/admin/api/install/wa-app-name', {
				method:  'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ value: waAppName.trim() || 'HouseBot' }),
			});
			if (res.ok) {
				waAppNameSaved = true;
				setTimeout(() => waAppNameSaved = false, 2500);
			} else {
				const err = await res.json().catch(() => ({}));
				waAppNameError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			waAppNameError = e instanceof Error ? e.message : 'Request failed';
		} finally {
			waAppNameSaving = false;
		}
	}

	// ── Step 4: Sender Restrictions ─────────────────────────────────────────────
	let step4Open = $state(false);

	type AuthorizedPartner = { jid: string; name: string };
	type SenderInfo = { jid: string; type: string; name: string; already_authorized: boolean };
	let authorizedPartners = $state<AuthorizedPartner[]>([]);
	let scannedSenders   = $state<SenderInfo[]>([]);
	let scanLoading      = $state(false);
	let scanError        = $state<string | null>(null);
	let scanDone         = $state(false);
	let authorizingJid   = $state<string | null>(null);
	let authorizeError   = $state<string | null>(null);

	const step4Done = $derived(authorizedPartners.length > 0);

	async function loadAuthorizedSenders() {
		try {
			const res = await fetch('/admin/api/install/sender-restrictions');
			if (res.ok) {
				const data = await res.json();
				authorizedPartners = data.partners ?? [];
			}
		} catch { /* non-fatal */ }
	}

	async function scanSenders() {
		scanLoading = true;
		scanError   = null;
		scannedSenders = [];
		scanDone    = false;
		try {
			const res = await fetch('/admin/api/install/sender-restrictions/scan', { method: 'POST' });
			if (res.ok) {
				const data = await res.json();
				scannedSenders = data.senders ?? [];
				scanDone = true;
			} else {
				const err = await res.json().catch(() => ({}));
				scanError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			scanError = e instanceof Error ? e.message : 'Request failed';
		} finally {
			scanLoading = false;
		}
	}

	async function authorizeSender(jid: string, name: string) {
		authorizingJid  = jid;
		authorizeError  = null;
		try {
			const res = await fetch('/admin/api/install/sender-restrictions/authorize', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ jid, name }),
			});
			if (res.ok) {
				const data = await res.json();
				authorizedPartners = data.partners ?? [];
				scannedSenders = [];
				scanDone = false;
			} else {
				const err = await res.json().catch(() => ({}));
				authorizeError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			authorizeError = e instanceof Error ? e.message : 'Request failed';
		} finally {
			authorizingJid = null;
		}
	}

	async function toggleStep4() {
		step4Open = !step4Open;
		if (step4Open) await loadAuthorizedSenders();
	}

	// ── Static placeholder steps 5 ──────────────────────────────────────────────
	const steps: { n: number; icon: string; label: string; desc: string }[] = [];

	// ── Step 5: Location & Briefing ──────────────────────────────────────────────
	let step5Open = $state(false);

	let locCity              = $state('');
	let locLat               = $state('');
	let locLon               = $state('');
	let locTimezone          = $state('');
	let locLang              = $state('English');
	let locTimezones         = $state<string[]>([]);
	let locLanguages         = $state<string[]>([]);

	let locSearchQuery       = $state('');
	let locSearching         = $state(false);
	let locSearchError       = $state<string | null>(null);
	let locSearchResults     = $state<{ name: string; lat: number; lon: number; tz: string; country: string }[]>([]);

	let locSaving            = $state(false);
	let locSaved             = $state(false);
	let locSaveError         = $state<string | null>(null);

	// Derived: show OSM embed only when we have valid coords
	const locMapUrl = $derived(
		locLat && locLon
			? (() => {
					const lat = parseFloat(locLat);
					const lon = parseFloat(locLon);
					if (isNaN(lat) || isNaN(lon)) return null;
					const d = 0.3;
					return `https://www.openstreetmap.org/export/embed.html?bbox=${lon-d},${lat-d},${lon+d},${lat+d}&layer=mapnik&marker=${lat},${lon}`;
				})()
			: null
	);

	const step5Done = $derived(!!(locCity && locLat && locLon));

	async function loadLocationSettings() {
		try {
			const res = await fetch('/admin/api/install/location');
			if (res.ok) {
				const data = await res.json();
				locCity      = data.city      ?? '';
				locLat       = data.latitude  ?? '';
				locLon       = data.longitude ?? '';
				locTimezone  = data.timezone  ?? '';
				locLang      = data.briefing_language ?? 'English';
				locTimezones = data.timezones ?? [];
				locLanguages = data.briefing_languages ?? [];
			}
		} catch { /* non-fatal */ }
	}

	async function searchCity() {
		const q = locSearchQuery.trim();
		if (!q) return;
		locSearching = true;
		locSearchError = null;
		locSearchResults = [];
		try {
			const res = await fetch(
				`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=5&language=en&format=json`
			);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			locSearchResults = (data.results ?? []).map((r: Record<string, unknown>) => ({
				name:    `${r.name}${r.admin1 ? ', ' + r.admin1 : ''}`,
				lat:     r.latitude as number,
				lon:     r.longitude as number,
				tz:      (r.timezone as string) ?? '',
				country: (r.country as string)  ?? '',
			}));
			if (locSearchResults.length === 0) locSearchError = 'No results — try a different spelling.';
		} catch (e) {
			locSearchError = e instanceof Error ? e.message : 'Geocoding failed';
		} finally {
			locSearching = false;
		}
	}

	function pickCity(r: { name: string; lat: number; lon: number; tz: string }) {
		locCity     = r.name.split(',')[0].trim();
		locLat      = String(r.lat);
		locLon      = String(r.lon);
		if (r.tz) locTimezone = r.tz;
		locSearchResults = [];
		locSearchQuery   = '';
	}

	async function saveLocationSettings() {
		locSaving    = true;
		locSaved     = false;
		locSaveError = null;
		try {
			const res = await fetch('/admin/api/install/location', {
				method:  'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					city:              locCity.trim(),
					latitude:          parseFloat(locLat),
					longitude:         parseFloat(locLon),
					timezone:          locTimezone.trim(),
					briefing_language: locLang,
				}),
			});
			if (res.ok) {
				locSaved = true;
				setTimeout(() => locSaved = false, 2500);
			} else {
				const err = await res.json().catch(() => ({}));
				locSaveError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			locSaveError = e instanceof Error ? e.message : 'Request failed';
		} finally {
			locSaving = false;
		}
	}

	async function toggleStep5() {
		step5Open = !step5Open;
		if (step5Open) await loadLocationSettings();
	}

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
				{:else if modelsChecked && !modelsLoading}
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
							{@const isConfigured = configuredModel === model.id}
							{@const isPulling = pullingModel === model.id}
							<div class="flex items-center gap-3 p-3 rounded-lg border border-surface-200-800 bg-surface-100-900/40">
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2 flex-wrap">
										<span class="text-xs font-semibold">{model.name}</span>
										<span class="text-xs text-surface-400-600 font-mono">{model.id}</span>
										{#if isConfigured && isInstalled}
											<span class="px-1.5 py-0.5 rounded text-xs bg-primary-500/15 text-primary-400">loaded</span>
										{:else if isInstalled}
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

		<!-- ── Step 2: Google OAuth (interactive) ───────────────────────────────────── -->
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">

			<!-- Accordion header -->
			<button
				onclick={toggleStep2}
				class="w-full p-4 flex items-center gap-4 text-left hover:bg-surface-100-900/50 transition-colors"
			>
				<div class="w-9 h-9 rounded-full bg-surface-100-900 border border-surface-200-800 flex items-center justify-center text-lg shrink-0">
					🔑
				</div>
				<div class="flex-1 min-w-0">
					<p class="font-semibold text-sm">
						<span class="text-surface-400-600 font-mono text-xs mr-2">2.</span>
						Google OAuth
					</p>
					<p class="text-xs text-surface-400-600 mt-0.5">Authorize Google Calendar access and store the OAuth token.</p>
				</div>
				{#if step2Done}
					<span class="text-xs text-success-400 shrink-0 mr-1">authorized</span>
				{:else if googleStatus === 'expired'}
					<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-warning-500/10 text-warning-400/80 shrink-0 mr-1">expired</span>
				{:else if googleStatus !== 'unknown'}
					<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-error-500/10 text-error-400/70 shrink-0 mr-1">pending</span>
				{/if}
				<span class="text-surface-400-600 text-xs shrink-0">{step2Open ? '▲' : '▼'}</span>
			</button>

			<!-- Expanded panel -->
			{#if step2Open}
				<div class="border-t border-surface-200-800 p-4 space-y-4">

					<!-- No credentials file warning -->
					{#if !googleCredsExist}
						<div class="flex items-start gap-3 px-4 py-3 rounded-xl border border-error-500/40 bg-error-500/10">
							<span class="text-xl mt-0.5">⚠️</span>
							<div>
								<p class="font-semibold text-xs text-error-400">Credentials file missing</p>
								<p class="text-xs text-surface-400-600 mt-1">
									Place your Google OAuth credentials at <span class="font-mono">creds/client_google_api_calendar.json</span>.
									Download it from the <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">Google Cloud Console</a>.
								</p>
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
								{googleStatus === 'unknown' ? 'Checking…' : googleStatus}
							</p>
							{#if googleExpiry}
								<p class="text-[10px] text-surface-400-600 mt-0.5">Expiry: {googleExpiry}</p>
							{/if}
						</div>
						<button
							onclick={loadGoogleStatus}
							class="text-xs px-2 py-1 rounded bg-surface-100-900 hover:bg-surface-200-800
							text-surface-500-500 transition-colors"
						>↻ Refresh</button>
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
						{#if googleStatus !== 'valid'}
							<button
								onclick={startGoogleAuth}
								disabled={googleLoading || googleFlowRunning || !googleCredsExist}
								class="px-4 py-2 rounded-lg text-xs font-semibold bg-primary-500/20 text-primary-400
								hover:bg-primary-500/30 border border-primary-500/40 transition-colors
								disabled:opacity-40 disabled:cursor-not-allowed"
							>
								{googleLoading ? '…' : googleFlowRunning ? '⏳ Waiting…' : '🔑 Authorize'}
							</button>
						{/if}
						{#if googleStatus === 'expired' && googleHasRefresh}
							<button
								onclick={refreshGoogleToken}
								disabled={googleLoading}
								class="px-4 py-2 rounded-lg text-xs font-semibold bg-success-500/15 text-success-500
								hover:bg-success-500/25 border border-success-500/30 transition-colors
								disabled:opacity-40 disabled:cursor-not-allowed"
							>
								{googleLoading ? '…' : '🔄 Refresh Token'}
							</button>
						{/if}
					</div>

					{#if googleMsg}
						<div class="text-xs px-3 py-2 rounded-lg
							{googleMsg.ok ? 'bg-success-500/10 text-success-500' : 'bg-error-500/10 text-error-400'}">
							{googleMsg.text}
						</div>
					{/if}

					<!-- Instructions -->
					<div class="text-xs text-surface-400-600 space-y-1 pt-1 border-t border-surface-200-800">
						<p class="font-semibold text-surface-500-500">How it works</p>
						<ol class="list-decimal list-inside space-y-1">
							<li>Click <strong>Authorize</strong> — a Google sign-in tab opens.</li>
							<li>Sign in and grant calendar access.</li>
							<li>The tab closes automatically. Click <strong>Check again</strong> to confirm.</li>
						</ol>
					</div>

				</div>
			{/if}
		</div>

		<!-- ── Step 3: WhatsApp Pairing (interactive) ─────────────────────────────── -->
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">

			<!-- Accordion header -->
			<button
				onclick={toggleStep3}
				class="w-full p-4 flex items-center gap-4 text-left hover:bg-surface-100-900/50 transition-colors"
			>
				<div class="w-9 h-9 rounded-full bg-surface-100-900 border border-surface-200-800 flex items-center justify-center text-lg shrink-0">
					📱
				</div>
				<div class="flex-1 min-w-0">
					<p class="font-semibold text-sm">
						<span class="text-surface-400-600 font-mono text-xs mr-2">3.</span>
						WhatsApp Pairing
					</p>
					<p class="text-xs text-surface-400-600 mt-0.5">Scan the QR code to link the WhatsApp number to the bot.</p>
				</div>
				{#if step3Done}
					<span class="text-xs text-success-400 shrink-0 mr-1">connected</span>
				{:else if waState !== 'idle'}
					<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-error-500/10 text-error-400/70 shrink-0 mr-1">pending</span>
				{/if}
				<span class="text-surface-400-600 text-xs shrink-0">{step3Open ? '▲' : '▼'}</span>
			</button>

			<!-- Expanded panel -->
			{#if step3Open}
				<div class="border-t border-surface-200-800 p-4 space-y-4">

					{#if waState === 'connected'}
						<!-- Already connected -->
						<div class="flex items-center gap-3 px-4 py-4 rounded-xl border border-success-500/40 bg-success-500/5">
							<span class="text-2xl">✅</span>
							<div>
								<p class="font-semibold text-sm text-success-400">Already connected</p>
								<p class="text-xs text-surface-400-600 mt-0.5">The WhatsApp bridge is paired and ready.</p>
							</div>
						</div>

					{:else if waState === 'qr' && waQr}
						<!-- QR code -->
						<div class="flex flex-col items-center gap-3">
							<p class="text-xs text-surface-400-600 text-center">
								Open WhatsApp on the <strong>dedicated number's phone</strong> → Linked Devices → Link a device, then scan:
							</p>
							<div class="p-3 rounded-xl bg-white shadow-md inline-block">
								<img src={waQr} alt="WhatsApp QR code" width="264" height="264" class="block rounded-lg" />
							</div>
							<p class="text-xs text-surface-400-600 text-center">
								QR refreshes automatically every 5 s. After scanning, this panel updates to "Connected".
							</p>
						</div>

					{:else if waState === 'loading'}
						<div class="flex items-center gap-2 px-3 py-3 rounded-lg bg-surface-100-900 border border-surface-200-800">
							<span class="animate-spin text-base">⏳</span>
							<p class="text-xs text-surface-400-600">Fetching QR from bridge…</p>
						</div>

					{:else if waState === 'error'}
						<div class="flex items-start gap-3 px-4 py-3 rounded-xl border border-error-500/40 bg-error-500/10">
							<span class="text-xl mt-0.5">⚠️</span>
							<div class="flex-1">
								<p class="font-semibold text-xs text-error-400">Bridge unavailable</p>
								<p class="text-xs text-surface-400-600 mt-1">{waError}</p>
							</div>
						</div>
					{/if}

					<!-- Refresh button -->
					<div class="flex items-center gap-3 pt-1">
						<button
							onclick={startWaPoll}
							disabled={waState === 'loading'}
							class="px-4 py-2 rounded-lg text-xs font-semibold border transition-colors disabled:opacity-40
							       border-primary-500/40 text-primary-400 hover:bg-primary-500/10"
						>
							{waState === 'loading' ? '…' : '↻ Refresh'}
						</button>
						{#if waState === 'qr'}
							<p class="text-xs text-surface-400-600">Auto-refreshes every 5 s</p>
						{/if}
					</div>

					<!-- Instructions -->
					<div class="text-xs text-surface-400-600 space-y-1 pt-1 border-t border-surface-200-800">
						<p class="font-semibold text-surface-500-500">Not seeing a QR?</p>
						<ol class="list-decimal list-inside space-y-1">
							<li>Make sure the bridge is running (<span class="font-mono">housebot.sh start</span>).</li>
							<li>Wait ~5 s for the bridge to generate the first QR, then click <strong>Refresh</strong>.</li>
							<li>If it was already paired on a previous session, the status shows "Connected".</li>
						</ol>
					</div>

					<!-- App name -->
					<div class="space-y-2 pt-1 border-t border-surface-200-800">
						<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Linked-device display name</p>
						<p class="text-xs text-surface-400-600">
							Name shown in WhatsApp's <em>Linked Devices</em> list. Change it before pairing — takes effect on the next bridge restart.
						</p>
						<div class="flex gap-2 items-center">
							<input
								type="text"
								bind:value={waAppName}
								placeholder="HouseBot"
								maxlength={20}
								class="flex-1 text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
								       text-surface-900-50 placeholder:text-surface-400-600 focus:outline-none focus:border-primary-500/60"
							/>
							<button
								onclick={saveWaAppName}
								disabled={waAppNameSaving || !waAppName.trim()}
								class="shrink-0 px-3 py-2 rounded-lg text-xs font-medium bg-primary-500/20 text-primary-400
								       hover:bg-primary-500/30 transition-colors disabled:opacity-40"
							>
								{waAppNameSaving ? '…' : '💾 Save'}
							</button>
						</div>
						{#if waAppNameSaved}
							<p class="text-xs text-success-400">✓ Saved to .env — restart the bridge to apply.</p>
						{/if}
						{#if waAppNameError}
							<p class="text-xs text-error-400">❌ {waAppNameError}</p>
						{/if}
					</div>

				</div>
			{/if}
		</div>

		<!-- ── Step 4: Sender Restrictions (interactive) ─────────────────────────── -->
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">

			<!-- Accordion header -->
			<button
				onclick={toggleStep4}
				class="w-full p-4 flex items-center gap-4 text-left hover:bg-surface-100-900/50 transition-colors"
			>
				<div class="w-9 h-9 rounded-full bg-surface-100-900 border border-surface-200-800 flex items-center justify-center text-lg shrink-0">
					🛡️
				</div>
				<div class="flex-1 min-w-0">
					<p class="font-semibold text-sm">
						<span class="text-surface-400-600 font-mono text-xs mr-2">4.</span>
						Sender Restrictions
					</p>
					<p class="text-xs text-surface-400-600 mt-0.5">Identify and authorize the WhatsApp JIDs allowed to interact with the bot.</p>
				</div>
				{#if step4Done}
					<span class="text-xs text-success-400 shrink-0 mr-1">{authorizedPartners.length} authorized</span>
				{:else}
					<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-error-500/10 text-error-400/70 shrink-0 mr-1">pending</span>
				{/if}
				<span class="text-surface-400-600 text-xs shrink-0">{step4Open ? '▲' : '▼'}</span>
			</button>

			<!-- Expanded panel -->
			{#if step4Open}
				<div class="border-t border-surface-200-800 p-4 space-y-4">

					<!-- Currently authorized senders -->
				{#if authorizedPartners.length > 0}
					<div class="space-y-2">
						<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Currently authorized</p>
						{#each authorizedPartners as partner}
							<div class="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-success-500/30 bg-success-500/5">
								<span class="text-success-400 text-sm">✅</span>
								<div class="flex-1 min-w-0">
									<p class="text-xs font-semibold">{partner.name || '—'}</p>
									<p class="text-[10px] text-surface-400-600 font-mono">{partner.jid}</p>
								</div>
								<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-success-500/15 text-success-400 shrink-0">authorized</span>
							</div>
						{/each}
					</div>
				{/if}

					<!-- Instruction card -->
					<div class="flex items-start gap-3 px-4 py-3 rounded-xl border border-primary-500/20 bg-primary-500/5">
						<span class="text-lg mt-0.5">📲</span>
						<div>
							<p class="text-xs font-semibold text-primary-400">Add a sender</p>
							<p class="text-xs text-surface-400-600 mt-1">
								Send <strong>any WhatsApp message</strong> from the phone you want to authorize to the
								bot's number, then click the button below to detect it.
							</p>
						</div>
					</div>

					<!-- Scan button -->
					<button
						onclick={scanSenders}
						disabled={scanLoading}
						class="px-4 py-2 rounded-lg text-xs font-semibold bg-primary-500/20 text-primary-400
						hover:bg-primary-500/30 border border-primary-500/40 transition-colors disabled:opacity-40"
					>
						{scanLoading ? '⏳ Scanning logs…' : '🔍 I\'ve sent a message — detect sender'}
					</button>

					{#if scanError}
						<p class="text-xs text-error-400">❌ {scanError}</p>
					{/if}

					<!-- Scan results -->
					{#if scanDone}
						{#if scannedSenders.length === 0}
							<div class="flex items-start gap-3 px-4 py-3 rounded-xl border border-warning-500/30 bg-warning-500/5">
								<span class="text-lg">⚠️</span>
								<div>
									<p class="text-xs font-semibold text-warning-400">No new messages detected</p>
									<p class="text-xs text-surface-400-600 mt-1">
										Make sure the bridge is running and you sent a message from the phone to
										authorize, then try scanning again.
									</p>
								</div>
							</div>
						{:else}
							<div class="space-y-2">
								<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Detected senders</p>
								{#each scannedSenders as sender}
									<div class="flex items-center gap-3 p-3 rounded-lg border border-surface-200-800 bg-surface-100-900/40">
										<div class="flex-1 min-w-0">
											<p class="text-xs font-semibold">{sender.name || '(no display name)'}</p>
											<p class="text-[10px] text-surface-400-600 font-mono">{sender.jid}</p>
										</div>
										{#if sender.already_authorized}
											<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-success-500/15 text-success-400 shrink-0">authorized</span>
										{:else}
											<button
												onclick={() => authorizeSender(sender.jid, sender.name)}
												disabled={authorizingJid === sender.jid}
												class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors
												       border-primary-500/40 text-primary-400 hover:bg-primary-500/10 disabled:opacity-40"
											>
												{authorizingJid === sender.jid ? '…' : 'Authorize'}
											</button>
										{/if}
									</div>
								{/each}
							</div>
						{/if}
					{/if}

					{#if authorizeError}
						<p class="text-xs text-error-400">❌ {authorizeError}</p>
					{/if}

					<!-- How it works -->
					<div class="text-xs text-surface-400-600 space-y-1 pt-1 border-t border-surface-200-800">
						<p class="font-semibold text-surface-500-500">How it works</p>
						<ol class="list-decimal list-inside space-y-1">
							<li>Send any message from the phone you want to authorize.</li>
							<li>Click <strong>Detect sender</strong> — the bridge log is scanned for the JID.</li>
							<li>Click <strong>Authorize</strong> — the JID is saved to <span class="font-mono">PARTNER_LID</span> in <span class="font-mono">.env</span>.</li>
							<li>Repeat for additional phones. Restart the bridge afterwards to apply.</li>
						</ol>
					</div>

				</div>
			{/if}
		</div>

		<!-- ── Steps 5 (static placeholders) ───────────────────────────────────────── -->
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

		<!-- ── Step 5: Location & Briefing (interactive) ─────────────────────────── -->
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">

			<!-- Accordion header -->
			<button
				onclick={toggleStep5}
				class="w-full p-4 flex items-center gap-4 text-left hover:bg-surface-100-900/50 transition-colors"
			>
				<div class="w-9 h-9 rounded-full bg-surface-100-900 border border-surface-200-800 flex items-center justify-center text-lg shrink-0">
					🌍
				</div>
				<div class="flex-1 min-w-0">
					<p class="font-semibold text-sm">
						<span class="text-surface-400-600 font-mono text-xs mr-2">5.</span>
						Location &amp; Briefing
					</p>
					<p class="text-xs text-surface-400-600 mt-0.5">Set your home city, timezone, and morning briefing language.</p>
				</div>
				{#if step5Done}
					<span class="text-xs text-success-400 shrink-0 mr-1">{locCity}</span>
				{:else}
					<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-error-500/10 text-error-400/70 shrink-0 mr-1">pending</span>
				{/if}
				<span class="text-surface-400-600 text-xs shrink-0">{step5Open ? '▲' : '▼'}</span>
			</button>

			<!-- Expanded panel -->
			{#if step5Open}
				<div class="border-t border-surface-200-800 p-4 space-y-5">

					<!-- City search -->
					<div class="space-y-2">
						<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Search city</p>
						<p class="text-xs text-surface-400-600">
							Type your city name and click <strong>Look up</strong> — coordinates and timezone are filled in automatically.
						</p>
						<div class="flex gap-2">
							<input
								type="text"
								bind:value={locSearchQuery}
								placeholder="e.g. Barcelona, Tokyo, New York…"
								onkeydown={(e) => { if (e.key === 'Enter') searchCity(); }}
								class="flex-1 text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
								       text-surface-900-50 placeholder:text-surface-400-600
								       focus:outline-none focus:border-primary-500/60"
							/>
							<button
								onclick={searchCity}
								disabled={locSearching || !locSearchQuery.trim()}
								class="shrink-0 px-3 py-2 rounded-lg text-xs font-medium bg-primary-500/20 text-primary-400
								       hover:bg-primary-500/30 transition-colors disabled:opacity-40"
							>
								{locSearching ? '…' : '🔍 Look up'}
							</button>
						</div>

						{#if locSearchError}
							<p class="text-xs text-error-400">{locSearchError}</p>
						{/if}

						<!-- Search results -->
						{#if locSearchResults.length > 0}
							<div class="space-y-1 border border-surface-200-800 rounded-lg overflow-hidden">
								{#each locSearchResults as r}
									<button
										onclick={() => pickCity(r)}
										class="w-full px-3 py-2.5 text-left flex items-center gap-3 hover:bg-surface-100-900 transition-colors border-b border-surface-200-800 last:border-0"
									>
										<span class="text-base">📍</span>
										<div class="flex-1 min-w-0">
											<p class="text-xs font-semibold truncate">{r.name}</p>
											<p class="text-[10px] text-surface-400-600">{r.country} · {r.lat.toFixed(4)}, {r.lon.toFixed(4)} · {r.tz}</p>
										</div>
										<span class="text-xs text-primary-400 shrink-0">Select →</span>
									</button>
								{/each}
							</div>
						{/if}
					</div>

					<!-- Map preview -->
					{#if locMapUrl}
						<div class="space-y-2">
							<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Map preview</p>
							<div class="rounded-xl overflow-hidden border border-surface-200-800" style="height: 200px;">
								<iframe
									title="City map preview"
									src={locMapUrl}
									width="100%"
									height="200"
									style="border: none; display: block;"
									loading="lazy"
									sandbox="allow-scripts allow-same-origin"
								></iframe>
							</div>
							<p class="text-[10px] text-surface-400-600">
								Map data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer" class="hover:underline">OpenStreetMap</a> contributors.
							</p>
						</div>
					{/if}

					<!-- Manual fields -->
					<div class="space-y-3">
						<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Settings</p>

						<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
							<!-- City -->
							<div class="space-y-1">
								<label class="text-[10px] text-surface-400-600 font-medium uppercase tracking-wide" for="loc-city">City name</label>
								<input
									id="loc-city"
									type="text"
									bind:value={locCity}
									placeholder="Barcelona"
									class="w-full text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
									       text-surface-900-50 placeholder:text-surface-400-600 focus:outline-none focus:border-primary-500/60"
								/>
							</div>

							<!-- Timezone -->
							<div class="space-y-1">
								<label class="text-[10px] text-surface-400-600 font-medium uppercase tracking-wide" for="loc-tz">Timezone</label>
								{#if locTimezones.length > 0}
									<select
										id="loc-tz"
										bind:value={locTimezone}
										class="w-full text-xs rounded-lg px-2 py-2 bg-surface-100-900 border border-surface-200-800
										       text-surface-900-50 focus:outline-none focus:border-primary-500/60"
									>
										{#each locTimezones as tz}
											<option value={tz}>{tz}</option>
										{/each}
									</select>
								{:else}
									<input
										id="loc-tz"
										type="text"
										bind:value={locTimezone}
										placeholder="Europe/Madrid"
										class="w-full text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
										       text-surface-900-50 placeholder:text-surface-400-600 focus:outline-none focus:border-primary-500/60"
									/>
								{/if}
							</div>

							<!-- Latitude -->
							<div class="space-y-1">
								<label class="text-[10px] text-surface-400-600 font-medium uppercase tracking-wide" for="loc-lat">Latitude</label>
								<input
									id="loc-lat"
									type="number"
									step="0.0001"
									min="-90"
									max="90"
									bind:value={locLat}
									placeholder="41.3874"
									class="w-full text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
									       text-surface-900-50 placeholder:text-surface-400-600 focus:outline-none focus:border-primary-500/60"
								/>
							</div>

							<!-- Longitude -->
							<div class="space-y-1">
								<label class="text-[10px] text-surface-400-600 font-medium uppercase tracking-wide" for="loc-lon">Longitude</label>
								<input
									id="loc-lon"
									type="number"
									step="0.0001"
									min="-180"
									max="180"
									bind:value={locLon}
									placeholder="2.1686"
									class="w-full text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
									       text-surface-900-50 placeholder:text-surface-400-600 focus:outline-none focus:border-primary-500/60"
								/>
							</div>
						</div>

						<!-- Briefing language -->
						<div class="space-y-1">
							<label class="text-[10px] text-surface-400-600 font-medium uppercase tracking-wide" for="loc-lang">Morning briefing language</label>
							<p class="text-[10px] text-surface-400-600">The language used for the daily morning briefing sent to all partners.</p>
							{#if locLanguages.length > 0}
								<div class="flex flex-wrap gap-2 pt-1">
									{#each locLanguages as lang}
										<button
											onclick={() => locLang = lang}
											class="px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors
												{locLang === lang
													? 'border-primary-500/60 bg-primary-500/15 text-primary-400'
													: 'border-surface-300-700 text-surface-500-500 hover:bg-surface-100-900'}"
										>
											{lang}
										</button>
									{/each}
								</div>
							{:else}
								<input
									id="loc-lang"
									type="text"
									bind:value={locLang}
									placeholder="English"
									class="w-full text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
									       text-surface-900-50 placeholder:text-surface-400-600 focus:outline-none focus:border-primary-500/60"
								/>
							{/if}
						</div>
					</div>

					<!-- Save button -->
					<div class="flex items-center gap-3 pt-1">
						<button
							onclick={saveLocationSettings}
							disabled={locSaving || !locCity.trim() || !locLat || !locLon}
							class="px-4 py-2 rounded-lg text-xs font-semibold bg-primary-500/20 text-primary-400
							       hover:bg-primary-500/30 border border-primary-500/40 transition-colors disabled:opacity-40"
						>
							{locSaving ? '…' : '💾 Save to .env'}
						</button>
						{#if locSaved}
							<span class="text-xs text-success-400">✓ Saved</span>
						{/if}
						{#if locSaveError}
							<span class="text-xs text-error-400">❌ {locSaveError}</span>
						{/if}
					</div>

				</div>
			{/if}
		</div>

	</div>
</div>
