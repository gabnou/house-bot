<script lang="ts">
	import { goto } from '$app/navigation';

	// ── Types ────────────────────────────────────────────────────────────────
	type InstalledModelDetail = { name: string; size_gb: number; family: string; params: string; tested: boolean; incompatible: boolean };
	type CatalogModel = { id: string; family: string; description: string; ram: string };

	// ── Language constants ────────────────────────────────────────────────────
	const PINNED_LANGUAGES = ['English', 'Italian', 'Spanish', 'French'];

	const ALL_LANGUAGES = [
		'Afrikaans', 'Albanian', 'Amharic', 'Arabic', 'Armenian', 'Azerbaijani',
		'Basque', 'Belarusian', 'Bengali', 'Bosnian', 'Breton', 'Bulgarian', 'Burmese',
		'Catalan', 'Chinese', 'Croatian', 'Czech',
		'Danish', 'Dutch',
		'English', 'Estonian',
		'Faroese', 'Filipino', 'Finnish', 'French',
		'Galician', 'Georgian', 'German', 'Greek', 'Gujarati',
		'Hausa', 'Hebrew', 'Hindi', 'Hungarian',
		'Icelandic', 'Igbo', 'Indonesian', 'Irish', 'Italian',
		'Japanese',
		'Kazakh', 'Khmer', 'Korean', 'Kyrgyz',
		'Lao', 'Latvian', 'Lithuanian', 'Luxembourgish',
		'Macedonian', 'Malagasy', 'Malay', 'Malayalam', 'Maltese', 'Marathi', 'Mongolian',
		'Nepali', 'Norwegian',
		'Occitan', 'Odia',
		'Pashto', 'Persian', 'Polish', 'Portuguese', 'Punjabi',
		'Romanian', 'Russian',
		'Serbian', 'Sinhalese', 'Slovak', 'Slovenian', 'Somali', 'Spanish', 'Swahili', 'Swedish',
		'Tagalog', 'Tajik', 'Tamil', 'Telugu', 'Thai', 'Tibetan', 'Turkish', 'Turkmen',
		'Ukrainian', 'Urdu', 'Uzbek',
		'Vietnamese',
		'Welsh',
		'Xhosa',
		'Yoruba',
		'Zulu',
	];

	// country name (from Open-Meteo) → official language
	const COUNTRY_LANGUAGE_MAP: Record<string, string> = {
		'Afghanistan': 'Pashto', 'Albania': 'Albanian', 'Algeria': 'Arabic',
		'Argentina': 'Spanish', 'Armenia': 'Armenian', 'Australia': 'English',
		'Austria': 'German', 'Azerbaijan': 'Azerbaijani',
		'Bangladesh': 'Bengali', 'Belarus': 'Belarusian', 'Belgium': 'Dutch',
		'Bolivia': 'Spanish', 'Bosnia and Herzegovina': 'Bosnian', 'Brazil': 'Portuguese',
		'Bulgaria': 'Bulgarian',
		'Cambodia': 'Khmer', 'Canada': 'English', 'Chile': 'Spanish', 'China': 'Chinese',
		'Colombia': 'Spanish', 'Costa Rica': 'Spanish', 'Croatia': 'Croatian',
		'Cuba': 'Spanish', 'Czech Republic': 'Czech', 'Czechia': 'Czech',
		'Denmark': 'Danish',
		'Ecuador': 'Spanish', 'Egypt': 'Arabic', 'Estonia': 'Estonian', 'Ethiopia': 'Amharic',
		'Finland': 'Finnish', 'France': 'French',
		'Georgia': 'Georgian', 'Germany': 'German', 'Ghana': 'English', 'Greece': 'Greek',
		'Guatemala': 'Spanish',
		'Hungary': 'Hungarian',
		'Iceland': 'Icelandic', 'India': 'Hindi', 'Indonesia': 'Indonesian',
		'Iran': 'Persian', 'Iraq': 'Arabic', 'Ireland': 'Irish', 'Israel': 'Hebrew',
		'Italy': 'Italian',
		'Japan': 'Japanese', 'Jordan': 'Arabic',
		'Kazakhstan': 'Kazakh', 'Kenya': 'Swahili', 'Korea': 'Korean',
		'South Korea': 'Korean', 'Kuwait': 'Arabic', 'Kyrgyzstan': 'Kyrgyz',
		'Laos': 'Lao', 'Latvia': 'Latvian', 'Lebanon': 'Arabic', 'Lithuania': 'Lithuanian',
		'Luxembourg': 'Luxembourgish',
		'Malaysia': 'Malay', 'Malta': 'Maltese', 'Mexico': 'Spanish',
		'Mongolia': 'Mongolian', 'Morocco': 'Arabic', 'Myanmar': 'Burmese',
		'Nepal': 'Nepali', 'Netherlands': 'Dutch', 'New Zealand': 'English',
		'Nigeria': 'English', 'North Macedonia': 'Macedonian', 'Norway': 'Norwegian',
		'Pakistan': 'Urdu', 'Peru': 'Spanish', 'Philippines': 'Filipino',
		'Poland': 'Polish', 'Portugal': 'Portuguese',
		'Romania': 'Romanian', 'Russia': 'Russian',
		'Saudi Arabia': 'Arabic', 'Serbia': 'Serbian', 'Singapore': 'English',
		'Slovakia': 'Slovak', 'Slovenia': 'Slovenian', 'Somalia': 'Somali',
		'South Africa': 'Afrikaans', 'Spain': 'Spanish', 'Sri Lanka': 'Sinhalese',
		'Sweden': 'Swedish', 'Switzerland': 'German', 'Syria': 'Arabic',
		'Taiwan': 'Chinese', 'Tajikistan': 'Tajik', 'Tanzania': 'Swahili',
		'Thailand': 'Thai', 'Tunisia': 'Arabic', 'Turkey': 'Turkish',
		'Turkmenistan': 'Turkmen',
		'Ukraine': 'Ukrainian', 'United Arab Emirates': 'Arabic',
		'United Kingdom': 'English', 'United States': 'English', 'Uruguay': 'Spanish',
		'Uzbekistan': 'Uzbek',
		'Venezuela': 'Spanish', 'Vietnam': 'Vietnamese',
		'Yemen': 'Arabic',
		'Zimbabwe': 'Shona',
	};

	// ── Step 1 state ────────────────────────────────────────────────────────────
	let step1Open = $state(false);
	let installedModels = $state<string[]>([]);
	let installedModelDetails = $state<InstalledModelDetail[]>([]);
	let configuredModel = $state('');
	let modelsLoading = $state(false);
	let modelsChecked = $state(false);
	let pullingModel = $state<string | null>(null);
	let pullStatus = $state('');
	let pullProgress = $state<{ completed: number; total: number } | null>(null);
	let pullDone = $state(false);
	let pullError = $state<string | null>(null);

	// Model catalog (combobox)
	let catalog = $state<CatalogModel[]>([]);
	let catalogLoading = $state(false);
	let catalogQuery = $state('');
	let catalogOpen = $state(false);
	let selectedCatalogModel = $state<CatalogModel | null>(null);
	let comboboxEl = $state<HTMLDivElement | null>(null);

	// Model pull cancel
	let pullAbortController = $state<AbortController | null>(null);
	let pullCancelling = $state(false);

	// Model deletion
	let deletingModel = $state<string | null>(null);
	let pendingDeleteModel = $state<string | null>(null);
	let deleteError = $state<string | null>(null);

	// Model loading (switch active)
	let loadingModel = $state<string | null>(null);
	let loadModelError = $state<string | null>(null);

	let chatModel = $state('');
	let chatMessage = $state('');
	let chatResponse = $state('');
	let chatLoading = $state(false);
	let chatError = $state<string | null>(null);
	let chatVerdict = $state<'verified' | 'rejected' | null>(null);
	let chatVerdictLoading = $state(false);
	let chatVerdictError = $state<string | null>(null);

	const step1Done = $derived(installedModels.length > 0);

	// Classify models by role: embedding models (nomic-embed-text, etc.) vs. language models
	const isEmbedModel = (name: string) => /embed/i.test(name);
	const llmModels    = $derived(installedModelDetails.filter(m => !isEmbedModel(m.name)));
	const embedModels  = $derived(installedModelDetails.filter(m =>  isEmbedModel(m.name)));
	const llmModelNames = $derived(installedModels.filter(n => !isEmbedModel(n)));

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

	// Reset verdict when the user selects a different model or sends a new message
	$effect(() => {
		chatModel; // track
		chatVerdict = null;
		chatVerdictError = null;
		chatResponse = '';
		chatError = null;
	});

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
		if (step1Open && catalog.length === 0 && !catalogLoading) {
			await loadCatalog();
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
				const raw = (data.models ?? []) as InstalledModelDetail[];
				installedModelDetails = raw;
				installedModels = raw.map(m => m.name);
				configuredModel = data.configured ?? '';
				const firstLlm = raw.find(m => !isEmbedModel(m.name))?.name ?? '';
				if (!chatModel && firstLlm) chatModel = firstLlm;
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
		pullCancelling = false;
		const controller = new AbortController();
		pullAbortController = controller;
		try {
			const res = await fetch('/admin/api/install/ollama/pull', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: modelId }),
				signal: controller.signal,
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
			if (!pullCancelling && !pullError) {
				pullDone = true;
				await loadInstalledModels();
				await loadCatalog();
				chatModel = modelId;
				selectedCatalogModel = null;
				catalogQuery = '';
			}
		} catch (e) {
			if (!pullCancelling) pullError = e instanceof Error ? e.message : String(e);
		} finally {
			pullingModel = null;
			pullAbortController = null;
		}
	}

	async function cancelPull() {
		if (!pullingModel) return;
		const modelToCancel = pullingModel;
		pullCancelling = true;
		pullStatus = 'Cancelling…';
		pullAbortController?.abort();
		pullAbortController = null;
		// Ask the server to delete any partial blobs from Ollama's cache
		try {
			await fetch('/admin/api/install/ollama/pull/cancel', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: modelToCancel }),
			});
		} catch { /* non-fatal */ }
		pullingModel = null;
		pullProgress = null;
		pullStatus = '';
		await loadCatalog();
		setTimeout(() => { pullCancelling = false; }, 100);
	}

	// ── Catalog helpers ───────────────────────────────────────────────────────
	async function loadCatalog() {
		catalogLoading = true;
		try {
			const res = await fetch('/admin/api/ollama/catalog');
			if (res.ok) catalog = (await res.json()).catalog ?? [];
		} catch { /* non-fatal */ } finally {
			catalogLoading = false;
		}
	}

	const filteredCatalog = $derived(
		catalog
			.filter(m => {
				if (!catalogQuery.trim()) return true;
				const q = catalogQuery.toLowerCase();
				return m.id.toLowerCase().includes(q) || m.family.toLowerCase().includes(q) || m.description.toLowerCase().includes(q);
			})
			.slice(0, 25)
	);

	function onCatalogInput() {
		if (selectedCatalogModel && selectedCatalogModel.id !== catalogQuery) selectedCatalogModel = null;
		catalogOpen = true;
	}

	function onCatalogFocus() { catalogOpen = true; }

	function selectCatalogModel(item: CatalogModel) {
		selectedCatalogModel = item;
		catalogQuery = item.id;
		catalogOpen = false;
	}

	function clearCatalogSelection() {
		selectedCatalogModel = null;
		catalogQuery = '';
		catalogOpen = false;
	}

	$effect(() => {
		function handleClickOutside(e: MouseEvent) {
			if (comboboxEl && !comboboxEl.contains(e.target as Node)) catalogOpen = false;
			if (locLangComboEl && !locLangComboEl.contains(e.target as Node)) locLangOpen = false;
			if (calendarComboEl && !calendarComboEl.contains(e.target as Node)) calendarDropdownOpen = false;
		}
		document.addEventListener('mousedown', handleClickOutside);
		return () => document.removeEventListener('mousedown', handleClickOutside);
	});

	// ── Model deletion ────────────────────────────────────────────────────────
	async function deleteModel(name: string) {
		deletingModel = name;
		pendingDeleteModel = null;
		deleteError = null;
		const wasConfigured = configuredModel === name;
		try {
			const res = await fetch('/admin/api/ollama/models', {
				method: 'DELETE',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: name }),
			});
			if (res.ok) {
				await loadInstalledModels();
				await loadCatalog();
				if (chatModel === name) chatModel = installedModels[0] ?? '';
				// If we deleted the active model and other models are available, auto-switch
				if (wasConfigured && installedModels.length > 0) {
					const fallback = installedModels[0];
					try {
						const sw = await fetch('/admin/api/ollama/switch', {
							method: 'POST',
							headers: { 'Content-Type': 'application/json' },
							body: JSON.stringify({ model: fallback }),
						});
						if (sw.ok) configuredModel = fallback;
					} catch { /* non-fatal */ }
				}
			} else {
				const err = await res.json().catch(() => ({}));
				deleteError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			deleteError = e instanceof Error ? e.message : String(e);
		} finally {
			deletingModel = null;
		}
	}

	async function sendChat() {
		if (!chatMessage.trim() || !chatModel) return;
		chatLoading = true;
		chatResponse = '';
		chatError = null;
		chatVerdict = null;
		chatVerdictError = null;
		const msg = chatMessage;
		try {
			// Load model temporarily without writing to .env
			const switchRes = await fetch('/admin/api/ollama/switch', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: chatModel, persist: false }),
			});
			if (!switchRes.ok) {
				const err = await switchRes.json().catch(() => ({}));
				throw new Error(err.detail ?? `Load failed: HTTP ${switchRes.status}`);
			}

			// Send through the real HouseBot pipeline
			const msgRes = await fetch('/message', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ sender: '__admin_test__', text: msg }),
			});
			if (!msgRes.ok) {
				const err = await msgRes.json().catch(() => ({}));
				throw new Error(err.detail ?? `HTTP ${msgRes.status}`);
			}
			const data = await msgRes.json();
			const reply = data.reply ?? null;

			if (!reply) {
				chatError = 'No reply received — the model may be incompatible with HouseBot.';
			} else {
				chatResponse = reply;
			}
		} catch (e) {
			chatError = e instanceof Error ? e.message : String(e);
		} finally {
			chatLoading = false;
		}
	}

	async function loadModel(name: string) {
		loadingModel = name;
		loadModelError = null;
		try {
			const res = await fetch('/admin/api/ollama/switch', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: name, persist: true }),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
			}
			configuredModel = name;
			await loadInstalledModels();
		} catch (e) {
			loadModelError = e instanceof Error ? e.message : String(e);
		} finally {
			loadingModel = null;
		}
	}

	async function markVerified() {
		chatVerdictLoading = true;
		chatVerdictError = null;
		try {
			await fetch('/admin/api/ollama/tested', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: chatModel }),
			});
			chatVerdict = 'verified';
			await loadInstalledModels();
		} catch (e) {
			chatVerdictError = e instanceof Error ? e.message : String(e);
		} finally {
			chatVerdictLoading = false;
		}
	}

	async function markIncompatible() {
		chatVerdictLoading = true;
		chatVerdictError = null;
		try {
			await fetch('/admin/api/ollama/incompatible', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ model: chatModel }),
			});
			// Restore the originally configured model in-memory
			if (configuredModel && configuredModel !== chatModel) {
				await fetch('/admin/api/ollama/switch', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ model: configuredModel, persist: false }),
				});
			}
			chatVerdict = 'rejected';
			await loadInstalledModels();
		} catch (e) {
			chatVerdictError = e instanceof Error ? e.message : String(e);
		} finally {
			chatVerdictLoading = false;
		}
	}

	// ── Step 2: Google Calendar Setup ────────────────────────────────────────────
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

	// Credentials paste-and-upload state
	let googleClientId = $state('');
	let googleClientSecret = $state('');
	let googleCredsSubmitting = $state(false);
	let googleCredsMsg = $state<{ ok: boolean; text: string } | null>(null);

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

	const step2Done = $derived(googleStatus === 'valid');

	// Calendar picker state
	let googleCalendars = $state<{ id: string; name: string; primary: boolean }[]>([]);
	let googleCalendarsLoading = $state(false);
	let googleCalendarsError = $state<string | null>(null);
	let googleConfiguredCalendar = $state('');
	let googleSelectedCalendar = $state('');
	let calendarQuery = $state('');
	let calendarDropdownOpen = $state(false);
	let calendarComboEl = $state<HTMLDivElement | null>(null);
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
				googleMsg = { ok: true, text: `Calendar set to “${googleSelectedCalendar}” and saved to .env.` };
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

	async function toggleStep2() {
		step2Open = !step2Open;
		if (step2Open) {
			await loadGoogleStatus();
			if (googleStatus === 'valid') await loadCalendars();
		}
	}

	// ── Eager status load on every page visit ────────────────────────────────────
	// All badge states are populated here so every card shows its status without
	// needing to open the accordion first.
	$effect(() => {
		// Bot display name (unnumbered card)
		loadWaAppName();
		// Step 1 — Ollama models
		loadInstalledModels();
		loadCatalog();
		// Step 2 — Google Calendar (load calendars only when already authorised)
		(async () => {
			await loadGoogleStatus();
			if (googleStatus === 'valid') await loadCalendars();
		})();
		// Step 3 — WhatsApp pairing
		loadWaQr();
		// Step 4 — Sender restrictions
		loadAuthorizedSenders();
		// Step 5 — Location & Briefing
		loadLocationSettings();
		// Step 6 — Speech recognition model
		loadWhisperModel();
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

	let waShowQr = $state(false);

	function startReconnect() {
		waShowQr = true;
		startWaPoll();
	}

	async function toggleStep3() {
		step3Open = !step3Open;
		if (step3Open) {
			waShowQr = false;
			await loadWaQr();
		} else {
			_stopWaPoll();
		}
	}

	// ── Step 3: WA app name ──────────────────────────────────────────────────────
	let waAppName        = $state('');
	let waAppNameSaving  = $state(false);
	let waAppNameSaved   = $state(false);
	let waAppNameError   = $state<string | null>(null);
	let waNameOpen       = $state(false);

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

	// ── Step 3: WA disconnect ─────────────────────────────────────────────────
	let waDisconnecting  = $state(false);
	let waDisconnectError = $state<string | null>(null);

	async function disconnectWa() {
		waDisconnecting   = true;
		waDisconnectError = null;
		try {
			const res = await fetch('/admin/api/install/whatsapp/disconnect', { method: 'POST' });
			if (res.ok) {
				waState = 'idle';
				waQr    = null;
				startWaPoll();
			} else {
				const err = await res.json().catch(() => ({}));
				waDisconnectError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			waDisconnectError = e instanceof Error ? e.message : 'Request failed';
		} finally {
			waDisconnecting = false;
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
	let removingJid      = $state<string | null>(null);
	let removeError      = $state<string | null>(null);

	async function removeSender(jid: string) {
		removingJid = jid;
		removeError = null;
		try {
			const res = await fetch('/admin/api/install/sender-restrictions', {
				method: 'DELETE',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ jid }),
			});
			if (res.ok) {
				const data = await res.json();
				authorizedPartners = data.partners ?? [];
			} else {
				const err = await res.json().catch(() => ({}));
				removeError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			removeError = e instanceof Error ? e.message : 'Request failed';
		} finally {
			removingJid = null;
		}
	}

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
	let locDetectedLang      = $state('');          // auto-detected from picked country
	let locLangQuery         = $state('');          // combobox input
	let locLangOpen          = $state(false);
	let locLangComboEl       = $state<HTMLDivElement | null>(null);

	const filteredLangOptions = $derived(
		ALL_LANGUAGES.filter(l => {
			if (!locLangQuery.trim()) return true;
			return l.toLowerCase().includes(locLangQuery.toLowerCase());
		})
	);

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
				locLangQuery = locLang;
				locTimezones = data.timezones ?? [];
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

	function pickCity(r: { name: string; lat: number; lon: number; tz: string; country: string }) {
		locCity     = r.name.split(',')[0].trim();
		locLat      = String(r.lat);
		locLon      = String(r.lon);
		if (r.tz) locTimezone = r.tz;
		locSearchResults = [];
		locSearchQuery   = '';
		// Auto-detect official language for the chosen country
		const detected = COUNTRY_LANGUAGE_MAP[r.country] ?? '';
		locDetectedLang = detected && !PINNED_LANGUAGES.includes(detected) ? detected : '';
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

	// ── Step 6: Whisper Model ────────────────────────────────────────────────────
	const WHISPER_MODELS = ['tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3'];

	let step6Open = $state(false);
	let whisperModel = $state('');
	let whisperSaving = $state(false);
	let whisperSaved = $state(false);
	let whisperError = $state<string | null>(null);

	const step6Done = $derived(!!whisperModel);

	async function loadWhisperModel() {
		try {
			const res = await fetch('/admin/api/install/whisper/model');
			if (res.ok) whisperModel = (await res.json()).value || 'small';
		} catch { /* non-fatal */ }
	}

	async function saveWhisperModel(value: string) {
		whisperSaving = true;
		whisperSaved = false;
		whisperError = null;
		try {
			const res = await fetch('/admin/api/install/whisper/model', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ value }),
			});
			if (res.ok) {
				whisperModel = value;
				whisperSaved = true;
				setTimeout(() => whisperSaved = false, 2500);
			} else {
				const err = await res.json().catch(() => ({}));
				whisperError = err.detail ?? `HTTP ${res.status}`;
			}
		} catch (e) {
			whisperError = e instanceof Error ? e.message : 'Request failed';
		} finally {
			whisperSaving = false;
		}
	}

	async function toggleStep6() {
		step6Open = !step6Open;
		if (step6Open && !whisperModel) await loadWhisperModel();
	}

	// ── Back / incomplete-warning logic ─────────────────────────────────────────
	const STEPS = [
		{ label: 'Ollama — AI Models',       done: () => step1Done },
		{ label: 'Google Calendar Setup',    done: () => step2Done },
		{ label: 'WhatsApp Pairing',         done: () => step3Done },
		{ label: 'Sender Restrictions',      done: () => step4Done },
		{ label: 'Location & Briefing',      done: () => step5Done },
		{ label: 'Speech recognition model', done: () => step6Done },
	];

	let showBackWarning = $state(false);
	const missingSteps = $derived(STEPS.filter(s => !s.done()).map(s => s.label));

	function goBack() {
		if (missingSteps.length === 0) {
			goto('/');
		} else {
			showBackWarning = true;
		}
	}

	function confirmGoBack() { goto('/'); }
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl p-5 flex items-center gap-4">
		<span class="text-3xl">⚙️</span>
		<div class="flex-1">
			<h2 class="text-lg font-bold">Configuration</h2>
			<p class="text-xs text-surface-400-600 mt-0.5">
				Configure your housebot
			</p>
		</div>
		<button
			onclick={goBack}
			class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-surface-300-700
			text-surface-500-500 hover:bg-surface-100-900 transition-colors"
		>
			← Back
		</button>
	</div>

	<!-- Incomplete-steps warning banner -->
	{#if showBackWarning}
		<div class="flex items-start gap-3 px-4 py-4 rounded-xl border border-error-500/40 bg-error-500/10">
			<span class="text-xl mt-0.5">⚠️</span>
			<div class="flex-1">
				<p class="font-semibold text-sm text-error-400">Setup not completed</p>
				<p class="text-xs text-surface-400-600 mt-1 mb-2">
					The following steps are still pending — the bot may be partially or fully non-functional until they are completed:
				</p>
				<ul class="list-disc list-inside space-y-0.5">
					{#each missingSteps as step}
						<li class="text-xs text-error-400">{step}</li>
					{/each}
				</ul>
			</div>
			<div class="flex flex-col gap-2 shrink-0">
				<button
					onclick={confirmGoBack}
					class="px-3 py-1.5 rounded-lg text-xs font-medium bg-error-500/20 text-error-400
					hover:bg-error-500/30 transition-colors"
				>
					Go back anyway
				</button>
				<button
					onclick={() => showBackWarning = false}
					class="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-200-800 text-surface-500-500
					hover:bg-surface-300-700 transition-colors"
				>
					Stay here
				</button>
			</div>
		</div>
	{/if}

	<!-- Steps -->
	<div class="space-y-3">

		<!-- ── Bot display name ──────────────────────────────────────────────────── -->
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">

			<!-- Accordion header -->
			<button
				onclick={() => waNameOpen = !waNameOpen}
				class="w-full p-4 flex items-center gap-4 text-left hover:bg-surface-100-900/50 transition-colors"
			>
				<div class="w-9 h-9 rounded-full bg-surface-100-900 border border-surface-200-800 flex items-center justify-center text-lg shrink-0">
					🤖
				</div>
				<div class="flex-1 min-w-0">
					<p class="font-semibold text-sm">Bot display name</p>
					<p class="text-xs text-surface-400-600 mt-0.5">
						{waAppName ? waAppName : 'Not set'} · Name shown in WhatsApp's linked devices list.
					</p>
				</div>
				<span class="text-surface-400-600 text-xs shrink-0">{waNameOpen ? '▲' : '▼'}</span>
			</button>

			<!-- Expanded panel -->
			{#if waNameOpen}
				<div class="border-t border-surface-200-800 p-4 space-y-3">
					<p class="text-xs text-surface-400-600">Edit the bot name and save. A WhatsApp Bridge restart is required — do it from the <a href="/admin" class="text-primary-400 hover:underline">Admin</a> page.</p>
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
						<p class="text-xs text-success-400">✓ Saved — restart the bridge to apply.</p>
					{/if}
					{#if waAppNameError}
						<p class="text-xs text-error-400">❌ {waAppNameError}</p>
					{/if}
				</div>
			{/if}
		</div>

		<!-- ── Step 1: Ollama — AI Models (interactive) ──────────────────────────── -->
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl">

			<!-- Accordion header -->
			<button
				onclick={toggleStep1}
				class="w-full p-4 flex items-center gap-4 text-left hover:bg-surface-100-900/50 transition-colors rounded-xl"
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

					<!-- ── Installed models ─────────────────────────────────────────── -->
				<div class="space-y-4">

					{#if modelsLoading}
						<p class="text-xs text-surface-400-600">Checking installed models…</p>
					{:else if installedModelDetails.length === 0 && modelsChecked}
						<p class="text-xs text-surface-400-600">No models installed yet. Pull one below.</p>
					{/if}

					<!-- Language models -->
					{#if llmModels.length > 0 || (!modelsLoading && modelsChecked)}
						<div class="space-y-2">
							<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Language Models</p>
							{#if llmModels.length === 0}
								<p class="text-xs text-surface-400-600/60">No language model installed yet.</p>
							{/if}
							{#each llmModels as model}
								{@const isLoaded = configuredModel === model.name}
								{@const isDeleting = deletingModel === model.name}
								{@const isPendingDelete = pendingDeleteModel === model.name}
								<div class="flex items-center gap-3 p-3 rounded-lg border border-surface-200-800 bg-surface-100-900/40">
									<div class="flex-1 min-w-0">
										<div class="flex items-center gap-2 flex-wrap">
											<span class="text-xs font-mono font-semibold">{model.name}</span>
											{#if isLoaded}
												<span class="px-1.5 py-0.5 rounded text-xs bg-primary-500/15 text-primary-400">loaded</span>
											{/if}
										</div>
										<p class="text-xs text-surface-400-600 mt-0.5">
											{model.params || model.family || ''}
											{#if model.size_gb > 0} · {model.size_gb} GB on disk{/if}
										</p>
										{#if model.tested}
											<p class="text-[10px] mt-0.5 font-medium text-success-400">✓ tested</p>
										{:else if model.incompatible}
											<p class="text-[10px] mt-0.5 font-medium text-error-400">✖ rejected</p>
										{:else}
											<p class="text-[10px] mt-0.5 text-surface-400-600/60">untested</p>
										{/if}
									</div>
									<!-- Delete controls -->
									{#if isPendingDelete}
										{@const noFallback = isLoaded && llmModels.length === 1}
										<div class="flex flex-col items-end gap-1.5 shrink-0">
											{#if noFallback}
												<span class="text-[10px] text-warning-500 text-right max-w-[200px] leading-tight">
													⚠️ No other model available — the bot will stop working.
												</span>
											{:else if isLoaded}
												<span class="text-[10px] text-surface-400-600 text-right max-w-[200px] leading-tight">
													Active model — will switch to {llmModels.find(m => m.name !== model.name)?.name ?? 'next available'}.
												</span>
											{/if}
											<div class="flex items-center gap-2">
												<span class="text-xs text-error-400">Delete?</span>
												<button
													onclick={() => deleteModel(model.name)}
													disabled={isDeleting}
													class="px-2 py-1 rounded text-xs font-medium bg-error-500/20 text-error-400
													hover:bg-error-500/30 border border-error-500/40 transition-colors disabled:opacity-40"
												>Yes</button>
												<button
													onclick={() => pendingDeleteModel = null}
													class="px-2 py-1 rounded text-xs font-medium border border-surface-300-700
													text-surface-500-500 hover:bg-surface-100-900 transition-colors"
												>No</button>
											</div>
										</div>
									{:else}
										<div class="flex items-center gap-1 shrink-0">
											{#if !isLoaded}
												<button
													onclick={() => loadModel(model.name)}
													disabled={!!loadingModel || !!deletingModel}
													title="Load this model as active"
													class="flex flex-col items-center px-2 py-1 rounded-lg border border-surface-300-700
													text-surface-500-500 hover:border-primary-500/40 hover:text-primary-400 hover:bg-primary-500/5
													transition-colors disabled:opacity-40"
												>
													<span class="text-xs leading-none">{loadingModel === model.name ? '…' : '▶'}</span>
													<span class="text-[9px] leading-none mt-0.5">load</span>
												</button>
											{/if}
											<button
												onclick={() => pendingDeleteModel = model.name}
												disabled={isDeleting || !!deletingModel || !!loadingModel}
												title="Remove model from local disk"
												class="flex flex-col items-center px-2 py-1 rounded-lg border border-surface-300-700
												text-surface-500-500 hover:border-error-500/40 hover:text-error-400 hover:bg-error-500/5
												transition-colors disabled:opacity-40"
											>
												<span class="text-xs leading-none">{isDeleting ? '…' : '🗑'}</span>
												<span class="text-[9px] leading-none mt-0.5">delete</span>
											</button>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}

					<!-- Embedding models -->
					{#if embedModels.length > 0}
						<div class="space-y-2">
							<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Embedding Models</p>
							{#each embedModels as model}
								{@const isDeleting = deletingModel === model.name}
								{@const isPendingDelete = pendingDeleteModel === model.name}
								<div class="flex items-center gap-3 p-3 rounded-lg border border-surface-200-800 bg-surface-100-900/40">
									<div class="flex-1 min-w-0">
										<div class="flex items-center gap-2 flex-wrap">
											<span class="text-xs font-mono font-semibold">{model.name}</span>
											<span class="px-1.5 py-0.5 rounded text-xs bg-tertiary-500/15 text-tertiary-400">embed</span>
										</div>
										<p class="text-xs text-surface-400-600 mt-0.5">
											{model.params || model.family || ''}
											{#if model.size_gb > 0} · {model.size_gb} GB on disk{/if}
										</p>
										<p class="text-[10px] mt-0.5 text-surface-400-600/60">used for multilingual intent classification</p>
									</div>
									<!-- Delete controls -->
									{#if isPendingDelete}
										<div class="flex flex-col items-end gap-1.5 shrink-0">
											<div class="flex items-center gap-2">
												<span class="text-xs text-error-400">Delete?</span>
												<button
													onclick={() => deleteModel(model.name)}
													disabled={isDeleting}
													class="px-2 py-1 rounded text-xs font-medium bg-error-500/20 text-error-400
													hover:bg-error-500/30 border border-error-500/40 transition-colors disabled:opacity-40"
												>Yes</button>
												<button
													onclick={() => pendingDeleteModel = null}
													class="px-2 py-1 rounded text-xs font-medium border border-surface-300-700
													text-surface-500-500 hover:bg-surface-100-900 transition-colors"
												>No</button>
											</div>
										</div>
									{:else}
										<div class="flex items-center gap-1 shrink-0">
											<button
												onclick={() => pendingDeleteModel = model.name}
												disabled={isDeleting || !!deletingModel || !!loadingModel}
												title="Remove model from local disk"
												class="flex flex-col items-center px-2 py-1 rounded-lg border border-surface-300-700
												text-surface-500-500 hover:border-error-500/40 hover:text-error-400 hover:bg-error-500/5
												transition-colors disabled:opacity-40"
											>
												<span class="text-xs leading-none">{isDeleting ? '…' : '🗑'}</span>
												<span class="text-[9px] leading-none mt-0.5">delete</span>
											</button>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
						{#if deleteError}
							<p class="text-xs text-error-400">❌ {deleteError}</p>
						{/if}
						{#if loadModelError}
							<p class="text-xs text-error-400">❌ {loadModelError}</p>
						{/if}
					</div>

					{#if llmModelNames.length > 0}
						<div class="space-y-3 pt-3 border-t border-surface-200-800">
							<div>
								<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Load and Test the Model with HouseBot</p>
								<p class="text-xs text-surface-400-600 mt-1">Send a real command (e.g. <em>weather today</em>, <em>add milk</em>) and check the reply makes sense.<br/>Then mark the model as tested or rejected. Use "▶ load" in the list above to load a tested model.</p>
							</div>

							<!-- Model selector -->
							<div class="flex items-center gap-2">
								<label for="chat-model" class="text-xs text-surface-400-600 shrink-0">Model:</label>
								<select
									id="chat-model"
									bind:value={chatModel}
									class="flex-1 text-xs rounded-lg px-2 py-1.5 bg-surface-100-900 border border-surface-200-800
									       text-surface-900-50 focus:outline-none focus:border-primary-500/60"
								>
									{#each llmModelNames as m}
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
									<p class="text-xs text-surface-400-600 whitespace-pre-wrap break-words">{chatResponse}</p>
								</div>
								<!-- Verdict buttons -->
								{#if chatVerdict === null && !chatVerdictLoading}
									<div class="flex gap-2 pt-1">
										<button
											onclick={markVerified}
											disabled={chatVerdictLoading}
											class="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold border border-success-500 bg-success-500/40 text-black hover:bg-success-500/60 transition-colors disabled:opacity-40"
										>
											✓ Mark as Tested
										</button>
										<button
											onclick={markIncompatible}
											disabled={chatVerdictLoading}
											class="flex-1 px-3 py-1.5 rounded-lg text-xs font-semibold border border-error-500 bg-error-500/40 text-black hover:bg-error-500/60 transition-colors disabled:opacity-40"
										>
											✖ Mark as Rejected
										</button>
									</div>
								{:else if chatVerdict === "verified"}
									<div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-success-500/10 border border-success-500/30">
										<span class="text-success-400 text-xs">✓ Model marked as tested. Use ▶ on the card above to set it as active.</span>
									</div>
								{:else if chatVerdict === "rejected"}
									<div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-error-500/10 border border-error-500/30">
										<span class="text-error-400 text-xs">✖ Model marked as rejected.</span>
									</div>
								{:else if chatVerdictLoading}
									<p class="text-xs text-surface-400-600"><span class="animate-pulse">…</span></p>
								{/if}
								{#if chatVerdictError}
									<p class="text-xs text-error-400">{chatVerdictError}</p>
								{/if}
							{:else if chatLoading}
								<div class="px-3 py-2 rounded-lg bg-surface-100-900 border border-surface-200-800">
									<p class="text-xs text-surface-400-600">Loading model and processing<span class="animate-pulse">…</span> <span class="text-surface-400-600/60">(first request only after the keep-alive expires, takes {chatLoadEstimate}{ramGb ? ` on your ${ramGb} GB machine` : ''})</span></p>
								</div>
							{/if}
							{#if chatError}
								<p class="text-xs text-error-400">{chatError}</p>
							{/if}
						</div>
					{/if}

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

					<!-- ── Install new model ─────────────────────────────────────────── -->
					<div class="space-y-3 pt-3 border-t border-surface-200-800">
						<p class="text-xs font-semibold text-surface-400-600 uppercase tracking-wide">Install a new model</p>
						<p class="text-xs text-surface-400-600">HouseBot handles simple, structured commands — intent classification, not reasoning. Small models (4b–8b parameters) are sufficient and will give faster response times.</p>

						<div class="relative" bind:this={comboboxEl}>
							<div class="flex gap-2">
								<div class="relative flex-1">
									<input
										type="text"
										bind:value={catalogQuery}
										oninput={onCatalogInput}
										onfocus={onCatalogFocus}
										placeholder={catalogLoading ? 'Loading catalog…' : 'Search models (e.g. llama, gemma, phi)…'}
										disabled={!!pullingModel}
										class="w-full text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
										text-surface-900-50 placeholder:text-surface-400-600
										focus:outline-none focus:border-primary-500/60 disabled:opacity-60"
									/>
									{#if catalogQuery}
										<button
											onclick={clearCatalogSelection}
											class="absolute right-2 top-1/2 -translate-y-1/2 text-surface-400-600
											hover:text-surface-900-50 text-xs leading-none"
											aria-label="Clear"
										>✕</button>
									{/if}
								</div>
								<button
									onclick={() => selectedCatalogModel && pullModel(selectedCatalogModel.id)}
									disabled={!selectedCatalogModel || !!pullingModel}
									class="shrink-0 px-4 py-2 rounded-lg text-xs font-semibold border transition-colors disabled:opacity-40
									border-primary-500/40 text-primary-400 hover:bg-primary-500/10 disabled:cursor-not-allowed"
								>
									{pullingModel && selectedCatalogModel?.id === pullingModel ? 'Pulling…' : 'Pull'}
								</button>
							</div>

							<!-- Dropdown -->
							{#if catalogOpen && filteredCatalog.length > 0}
								<div class="absolute z-50 top-full left-0 right-0 mt-1 max-h-64 overflow-y-auto
								bg-surface-50-950 border border-surface-200-800 rounded-lg shadow-2xl">
									{#each filteredCatalog as item}
										<button
											onclick={() => selectCatalogModel(item)}
											class="w-full text-left px-3 py-2 hover:bg-surface-100-900 transition-colors
											{selectedCatalogModel?.id === item.id ? 'bg-primary-500/10' : ''}"
										>
											<div class="flex items-center gap-2">
												<span class="text-xs font-mono font-semibold">{item.id}</span>
												<span class="text-xs text-surface-400-600">{item.ram}</span>
												<span class="text-xs text-surface-400-600 ml-auto">{item.family}</span>
											</div>
											<p class="text-[10px] text-surface-400-600 mt-0.5">{item.description}</p>
										</button>
									{/each}
								</div>
							{:else if catalogOpen && catalogQuery.trim() && filteredCatalog.length === 0}
								<div class="absolute z-50 top-full left-0 right-0 mt-1 px-3 py-2
								bg-surface-50-950 border border-surface-200-800 rounded-lg shadow-2xl">
									<p class="text-xs text-surface-400-600">No matches — try a different name or
										<a href="https://ollama.com/library" target="_blank" rel="noopener noreferrer"
											class="text-primary-400 hover:underline">browse the full library →</a>
									</p>
								</div>
							{/if}
						</div>

						<!-- Pull-in-progress for catalog selection -->
						{#if pullingModel && selectedCatalogModel?.id === pullingModel}
							<div class="space-y-2">
								<div class="flex items-center justify-between gap-3">
									<p class="text-xs text-primary-400">{pullStatus}</p>
									{#if !pullCancelling}
										<button
											onclick={cancelPull}
											class="shrink-0 px-2.5 py-1 rounded-lg text-xs font-medium border border-error-500/40
											text-error-400 hover:bg-error-500/10 transition-colors"
										>Cancel</button>
									{:else}
										<span class="text-xs text-warning-400">Cleaning up…</span>
									{/if}
								</div>
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

						<!-- Result banners -->
						{#if pullDone && !pullingModel}
							<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-success-500/10 border border-success-500/30">
								<span>✅</span>
								<p class="text-xs text-success-400">Model pulled successfully — you can test it above.</p>
							</div>
						{/if}
						{#if pullError && !pullingModel}
							<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-error-500/10 border border-error-500/30">
								<span>❌</span>
								<p class="text-xs text-error-400">{pullError}</p>
							</div>
						{/if}

						<p class="text-xs text-surface-400-600">
							Not finding what you need?
							<a href="https://ollama.com/library" target="_blank" rel="noopener noreferrer"
								class="text-primary-400 hover:underline">Browse the full Ollama library →</a>
						</p>
					</div>
				</div>
			{/if}
		</div>

		<!-- ── Step 2: Google Calendar Setup (interactive) ─────────────────────────────────── -->
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
						Google Calendar Setup
					</p>
					<p class="text-xs text-surface-400-600 mt-0.5">
						{#if googleStatus === 'valid' && googleConfiguredCalendar}
							Connected · <span class="font-medium">{googleConfiguredCalendar}</span>
						{:else}
							Connect your Google account and choose the calendar for the bot.
						{/if}
					</p>
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

					<!-- No credentials file warning + paste form -->
					{#if !googleCredsExist}
						<div class="space-y-3">
							<!-- Warning banner -->
							<div class="flex items-start gap-3 px-4 py-3 rounded-xl border border-error-500/40 bg-error-500/10">
								<span class="text-xl mt-0.5">⚠️</span>
								<div class="flex-1 min-w-0">
									<p class="font-semibold text-xs text-error-400">Google OAuth credentials file missing</p>
									<p class="text-xs text-surface-400-600 mt-1">
										HouseBot needs a Google Cloud project with the Calendar API enabled to access your calendar.
										The project name is what Google shows on the consent screen when you authorize the app.
									</p>
									<p class="text-xs font-medium text-surface-400-600 mt-2">If you don't have a Google Cloud project yet:</p>
									<ol class="text-xs text-surface-400-600 mt-1 list-decimal list-inside space-y-0.5">
										<li>Go to <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">Create a new project ↗</a> — give it a meaningful name (e.g. <em>HouseBot</em>)</li>
										<li>Enable the <a href="https://console.cloud.google.com/apis/library/calendar-json.googleapis.com" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">Google Calendar API ↗</a> on that project</li>
										<li>Configure the <a href="https://console.cloud.google.com/apis/credentials/consent" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">OAuth consent screen ↗</a> (External, add your Google account as a test user)</li>
									</ol>
									<p class="text-xs font-medium text-surface-400-600 mt-2">Then create the OAuth credentials:</p>
									<ol class="text-xs text-surface-400-600 mt-1 list-decimal list-inside space-y-0.5">
										<li>Open <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:underline">APIs &amp; Services → Credentials ↗</a></li>
										<li>Click <strong>+ CREATE CREDENTIALS</strong> → <strong>OAuth client ID</strong></li>
										<li>Choose application type <strong>Desktop app</strong>, click <strong>Create</strong></li>
										<li>Copy the <strong>Client ID</strong> and <strong>Client Secret</strong> from the confirmation dialog and enter them below</li>
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
								{googleStatus === 'unknown' ? 'Checking…' : googleStatus}
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
								<!-- Search + always-visible list -->
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
								{googleLoading ? '…' : '� Disconnect'}
							</button>
						</div>
					{/if}

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

					{#if waState === 'loading' && !waShowQr}
						<!-- Checking status -->
						<div class="flex items-center gap-2 px-3 py-3 rounded-lg bg-surface-100-900 border border-surface-200-800">
							<span class="animate-spin text-base">⏳</span>
							<p class="text-xs text-surface-400-600">Checking bridge status…</p>
						</div>

					{:else if waState === 'connected'}
						<!-- Connected -->
						<div class="flex items-center gap-3 px-4 py-4 rounded-xl border border-success-500/40 bg-success-500/5">
							<span class="text-2xl">✅</span>
							<div class="flex-1">
								<p class="font-semibold text-sm text-success-400">Already connected</p>
								<p class="text-xs text-surface-400-600 mt-0.5">The WhatsApp bridge is paired and ready.</p>
							</div>
							<button
								onclick={disconnectWa}
								disabled={waDisconnecting}
								class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-error-500/40
								       text-error-400 hover:bg-error-500/10 transition-colors disabled:opacity-40"
							>
								{waDisconnecting ? '⏳ Re-configuring…' : '🔌 Re-configure'}
							</button>
						</div>
						{#if waDisconnectError}
							<p class="text-xs text-error-400">❌ {waDisconnectError}</p>
						{/if}

					{:else if !waShowQr}
						<!-- Not connected, user hasn't asked for QR yet -->
						<div class="flex items-center gap-3 px-4 py-4 rounded-xl border border-surface-200-800 bg-surface-100-900/50">
							<span class="text-2xl">📵</span>
							<div class="flex-1">
								<p class="font-semibold text-sm">Not paired</p>
								<p class="text-xs text-surface-400-600 mt-0.5">No active WhatsApp session found.</p>
							</div>
							<button
								onclick={startReconnect}
								class="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium bg-primary-500/20 text-primary-400
								       hover:bg-primary-500/30 border border-primary-500/40 transition-colors"
							>
								🔗 Connect
							</button>
						</div>

					{:else if waState === 'qr' && waQr}
						<!-- QR code -->
						<div class="flex flex-col items-center gap-3">
							<p class="text-xs text-surface-400-600 text-center">
								Open WhatsApp on the <strong>bot number's phone</strong> → Linked Devices → Link a device, then scan:
							</p>
							<div class="p-3 rounded-xl bg-white shadow-md inline-block">
								<img src={waQr} alt="WhatsApp QR code" width="264" height="264" class="block rounded-lg" />
							</div>
							<p class="text-xs text-surface-400-600 text-center">
								QR refreshes automatically every 5 s. After scanning, this panel updates to “Connected”.
							</p>
						</div>

					{:else if waState === 'loading'}
						<!-- Waiting for QR -->
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

					<!-- Instructions: only when actively trying to connect -->
					{#if waShowQr && waState !== 'connected'}
					<div class="text-xs text-surface-400-600 space-y-1 pt-1 border-t border-surface-200-800">
						<p class="font-semibold text-surface-500-500">Not seeing a QR?</p>
						<ol class="list-decimal list-inside space-y-1">
							<li>Make sure the bridge is running (<span class="font-mono">housebot.sh start</span>).</li>
							<li>Wait ~5 s for the bridge to generate the first QR, then click <strong>Connect</strong> again.</li>
						</ol>
					</div>
					{/if}

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
								<button
									onclick={() => removeSender(partner.jid)}
									disabled={removingJid === partner.jid}
									title="Remove sender"
									class="shrink-0 px-2 py-1 rounded text-xs font-medium text-error-400/70
									hover:text-error-400 hover:bg-error-500/10 transition-colors
									disabled:opacity-40 disabled:cursor-not-allowed"
								>{removingJid === partner.jid ? '…' : '✕'}</button>
							</div>
						{/each}
						{#if removeError}
							<p class="text-xs text-error-400">❌ {removeError}</p>
						{/if}
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
								<p class="text-[10px] text-surface-400-600">
									Authorize the <span class="font-mono text-primary-400">@lid</span> entry — that is the Linked Device ID used by multi-device WhatsApp for direct messages.
								</p>
								{#each scannedSenders as sender}
									<div class="flex items-center gap-3 p-3 rounded-lg border border-surface-200-800 bg-surface-100-900/40">
										<div class="flex-1 min-w-0">
											<div class="flex items-center gap-2">
												<p class="text-xs font-semibold">{sender.name || '(no display name)'}</p>
												<span class="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium
													{sender.type === 'lid' ? 'bg-primary-500/15 text-primary-400' : 'bg-surface-300-700/40 text-surface-400-600'}">
													@{sender.type}
												</span>
											</div>
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
						<div class="space-y-2">
							<label class="text-[10px] text-surface-400-600 font-medium uppercase tracking-wide" for="loc-lang-input">Morning briefing language</label>
							<p class="text-[10px] text-surface-400-600">The language used for the daily morning briefing sent to all partners.</p>

							<!-- Quick-pick chips: pinned + detected country language -->
							<div class="flex flex-wrap gap-2 pt-1">
								{#each PINNED_LANGUAGES as lang}
									<button
										onclick={() => { locLang = lang; locLangQuery = lang; locLangOpen = false; }}
										class="px-3 py-1 rounded-lg text-xs font-medium border transition-colors
											{locLang === lang
												? 'border-primary-500/60 bg-primary-500/15 text-primary-400'
												: 'border-surface-300-700 text-surface-500-500 hover:bg-surface-100-900'}"
									>{lang}</button>
								{/each}
								{#if locDetectedLang}
									<button
										onclick={() => { locLang = locDetectedLang; locLangQuery = locDetectedLang; locLangOpen = false; }}
										class="px-3 py-1 rounded-lg text-xs font-medium border transition-colors
											{locLang === locDetectedLang
												? 'border-primary-500/60 bg-primary-500/15 text-primary-400'
												: 'border-surface-300-700 text-surface-500-500 hover:bg-surface-100-900'}"
									>{locDetectedLang} <span class="text-[10px] text-surface-400-600 ml-1">detected</span></button>
								{/if}
							</div>

							<!-- Searchable combobox for all languages -->
							<div class="relative" bind:this={locLangComboEl}>
								<input
									id="loc-lang-input"
									type="text"
									bind:value={locLangQuery}
									oninput={() => { locLangOpen = true; locLang = locLangQuery.trim(); }}
									onfocus={() => locLangOpen = true}
									placeholder="Search or type a language…"
									class="w-full text-xs rounded-lg px-3 py-2 bg-surface-100-900 border border-surface-200-800
									       text-surface-900-50 placeholder:text-surface-400-600
									       focus:outline-none focus:border-primary-500/60"
								/>
								{#if locLangOpen && filteredLangOptions.length > 0}
									<div class="absolute z-50 top-full left-0 right-0 mt-1 max-h-48 overflow-y-auto
									bg-surface-50-950 border border-surface-200-800 rounded-lg shadow-2xl">
										{#each filteredLangOptions as lang}
											<button
												onclick={() => { locLang = lang; locLangQuery = lang; locLangOpen = false; }}
												class="w-full text-left px-3 py-2 text-xs hover:bg-surface-100-900 transition-colors
												{locLang === lang ? 'bg-primary-500/10 text-primary-400' : 'text-surface-900-50'}"
											>{lang}</button>
										{/each}
									</div>
								{/if}
							</div>
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

		<!-- ── Step 6: Whisper Model (interactive) ──────────────────────────────── -->
		<div class="card bg-surface-50-950 border border-surface-200-800 rounded-xl overflow-hidden">

			<!-- Accordion header -->
			<button
				onclick={toggleStep6}
				class="w-full p-4 flex items-center gap-4 text-left hover:bg-surface-100-900/50 transition-colors"
			>
				<div class="w-9 h-9 rounded-full bg-surface-100-900 border border-surface-200-800 flex items-center justify-center text-lg shrink-0">
					🎙️
				</div>
				<div class="flex-1 min-w-0">
					<p class="font-semibold text-sm">
						<span class="text-surface-400-600 font-mono text-xs mr-2">6.</span>
						Speech recognition model
					</p>
					<p class="text-xs text-surface-400-600 mt-0.5">Choose the faster-whisper model size — larger models are more accurate but require more RAM.</p>
				</div>
				{#if step6Done}
					<span class="text-xs text-success-400 shrink-0 mr-1">{whisperModel}</span>
				{:else}
					<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-error-500/10 text-error-400/70 shrink-0 mr-1">pending</span>
				{/if}
				<span class="text-surface-400-600 text-xs shrink-0">{step6Open ? '▲' : '▼'}</span>
			</button>

			<!-- Expanded panel -->
			{#if step6Open}
				<div class="border-t border-surface-200-800 p-4 space-y-3">
					<div class="flex flex-wrap gap-2">
						{#each WHISPER_MODELS as model}
							{@const isActive = whisperModel === model}
							<button
								onclick={() => saveWhisperModel(model)}
								disabled={whisperSaving}
								class="px-3 py-1 rounded-lg text-xs font-medium border transition-colors disabled:opacity-40
									{isActive
										? 'border-primary-500/60 bg-primary-500/15 text-primary-400'
										: 'border-surface-300-700 text-surface-500-500 hover:bg-surface-100-900'}"
							>{model}</button>
						{/each}
					</div>
					<p class="text-[10px] text-surface-400-600">
						Recommended: <strong>small</strong> for low-RAM machines, <strong>medium</strong> for best accuracy/speed balance.
					</p>
					{#if whisperSaved}
						<p class="text-xs text-success-400">✓ Saved to .env — restart HouseBot to apply.</p>
					{/if}
					{#if whisperError}
						<p class="text-xs text-error-400">❌ {whisperError}</p>
					{/if}
				</div>
			{/if}
		</div>

	</div>
</div>
