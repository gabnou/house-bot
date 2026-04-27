<script lang="ts">
	import { onMount } from 'svelte';

	// ── Types ──────────────────────────────────────────────────────────────
	interface TestCase {
		id: string;
		section: string;
		message: string;
		expect_contains: string[];
		skip_in_test_mode: boolean;
		destructive: boolean;
		note: string;
	}

	type TestStatus = 'idle' | 'pass' | 'fail' | 'skip' | 'warn' | 'running';

	interface TestResult {
		id: string;
		status: TestStatus;
		section: string;
		message: string;
		reply: string;
		note: string;
		duration?: number;
	}

	// ── State ──────────────────────────────────────────────────────────────
	let cases = $state<TestCase[]>([]);
	let loadError = $state<string | null>(null);

	// Run state
	type RunPhase = 'idle' | 'running' | 'done' | 'error';
	let runPhase = $state<RunPhase>('idle');
	let runError = $state<string | null>(null);
	let results = $state<Map<string, TestResult>>(new Map());
	let summary = $state<{ passed: number; failed: number; skipped: number; warned: number } | null>(null);
	let currentRunId = $state<string | null>(null);
	let currentCaseStart = 0;
	let runAbort: AbortController | null = null;

	// Edit modal
	let editingCase = $state<TestCase | null>(null);
	let editDraft = $state<TestCase | null>(null);
	let editNameError = $state<string | null>(null);
	let savingCases = $state(false);

	// Add case modal
	let addingCase = $state(false);
	let addNameError = $state<string | null>(null);
	let addDraft = $state<TestCase>({
		id: '',
		section: 'Shopping',
		message: '',
		expect_contains: [],
		skip_in_test_mode: false,
		destructive: false,
		note: ''
	});

	const SECTIONS = ['Shopping', 'Weather', 'Calendar', 'Special'];

	// ── Status helpers ─────────────────────────────────────────────────────
	function statusColor(s: TestStatus) {
		switch (s) {
			case 'pass':    return 'text-green-600 dark:text-green-400';
			case 'fail':    return 'text-red-600 dark:text-red-400';
			case 'warn':    return 'text-yellow-600 dark:text-yellow-400';
			case 'skip':    return 'text-surface-400-600';
			case 'running': return 'text-blue-500 animate-pulse';
			default:        return 'text-surface-400-600';
		}
	}

	function statusBadge(s: TestStatus) {
		switch (s) {
			case 'pass':    return 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300';
			case 'fail':    return 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300';
			case 'warn':    return 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300';
			case 'skip':    return 'bg-surface-100-900 text-surface-400-600';
			case 'running': return 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300';
			default:        return 'bg-surface-100-900 text-surface-400-600';
		}
	}

	function statusIcon(s: TestStatus) {
		switch (s) {
			case 'pass':    return '✓';
			case 'fail':    return '✗';
			case 'warn':    return '⚠';
			case 'skip':    return '—';
			case 'running': return '…';
			default:        return '·';
		}
	}

	function sectionColor(section: string) {
		switch (section) {
			case 'Shopping': return 'text-emerald-600 dark:text-emerald-400';
			case 'Weather':  return 'text-sky-600 dark:text-sky-400';
			case 'Calendar': return 'text-violet-600 dark:text-violet-400';
			case 'Special':  return 'text-orange-600 dark:text-orange-400';
			default:         return 'text-surface-500';
		}
	}

	function formatDuration(ms: number): string {
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(1)}s`;
	}

	// ── API ─────────────────────────────────────────────────────────────────
	async function loadCases() {
		loadError = null;
		try {
			const res = await fetch('/admin/api/test/cases');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			cases = await res.json();
		} catch (e: unknown) {
			loadError = e instanceof Error ? e.message : 'Failed to load test cases';
		}
	}

	async function saveCases() {
		savingCases = true;
		try {
			const res = await fetch('/admin/api/test/cases', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ cases }),
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
		} catch (e: unknown) {
			alert('Failed to save: ' + (e instanceof Error ? e.message : String(e)));
		} finally {
			savingCases = false;
		}
	}

	async function runTests() {
		runPhase = 'running';
		runError = null;
		summary = null;
		// Reset all results to running
		const initial = new Map<string, TestResult>();
		for (const c of cases) {
			initial.set(c.id, {
				id: c.id,
				status: 'running',
				section: c.section,
				message: c.message,
				reply: '',
				note: c.note
			});
		}
		results = initial;
		currentRunId = cases[0]?.id ?? null;
		currentCaseStart = Date.now();
		runAbort = new AbortController();

		try {
			const res = await fetch('/admin/api/test/run', { method: 'POST', signal: runAbort.signal });
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(err.detail ?? `HTTP ${res.status}`);
			}
			const reader = res.body!.getReader();
			const decoder = new TextDecoder();
			let buf = '';

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				buf += decoder.decode(value, { stream: true });
				const lines = buf.split('\n');
				buf = lines.pop() ?? '';
				for (const line of lines) {
					if (!line.startsWith('data: ')) continue;
					const event = JSON.parse(line.slice(6));

					if (event.type === 'result') {
						const elapsed = Date.now() - currentCaseStart;
						results = new Map(results).set(event.id, {
							id: event.id,
							status: event.status,
							section: event.section,
							message: event.message,
							reply: event.reply,
							note: event.note,
							duration: elapsed,
						});
						const idx = cases.findIndex(c => c.id === event.id);
						currentRunId = idx >= 0 && idx + 1 < cases.length ? cases[idx + 1].id : null;
						currentCaseStart = Date.now();
					} else if (event.type === 'done') {
						summary = { passed: event.passed, failed: event.failed, skipped: event.skipped, warned: event.warned };
						currentRunId = null;
						runPhase = 'done';
					} else if (event.type === 'error') {
						runError = event.detail;
						currentRunId = null;
						runPhase = 'error';
					}
				}
			}
			if (runPhase === 'running') runPhase = 'done';
		} catch (e: unknown) {
			if (e instanceof DOMException && e.name === 'AbortError') {
				// user stopped the run — clear pending cards
				results = new Map([...results.entries()].map(([k, v]) =>
					[k, v.status === 'running' ? { ...v, status: 'skip' as TestStatus } : v]
				));
				runPhase = 'done';
			} else {
				runError = e instanceof Error ? e.message : String(e);
				runPhase = 'error';
			}
		} finally {
			currentRunId = null;
			runAbort = null;
		}
	}

	function stopTests() {
		runAbort?.abort();
	}

	// ── Case editing ───────────────────────────────────────────────────────
	function openEdit(c: TestCase) {
		editingCase = c;
		editDraft = { ...c, expect_contains: [...c.expect_contains] };
	}

	function saveEdit() {
		if (!editDraft) return;
		const name = editDraft.id.trim();
		if (!name) { editNameError = 'Name is required.'; return; }
		const duplicate = cases.some(c => c.id === name && c.id !== editingCase!.id);
		if (duplicate) { editNameError = `'${name}' is already used by another test case.`; return; }
		editDraft.id = name;
		cases = cases.map(c => c.id === editingCase!.id ? { ...editDraft! } : c);
		editingCase = null;
		editDraft = null;
		editNameError = null;
		saveCases();
	}

	function deleteCase(id: string) {
		cases = cases.filter(c => c.id !== id);
		saveCases();
	}

	function toggleSkip(id: string) {
		cases = cases.map(c => c.id === id ? { ...c, skip_in_test_mode: !c.skip_in_test_mode } : c);
		saveCases();
	}

	function openAdd() {
		addDraft = { id: '', section: 'Shopping', message: '', expect_contains: [], skip_in_test_mode: false, destructive: false, note: '' };
		addNameError = null;
		addingCase = true;
	}

	function confirmAdd() {
		const name = addDraft.id.trim();
		if (!name) { addNameError = 'Name is required.'; return; }
		if (cases.some(c => c.id === name)) { addNameError = `'${name}' is already used by another test case.`; return; }
		if (!addDraft.message.trim()) return;
		addDraft.id = name;
		cases = [...cases, { ...addDraft, expect_contains: [...addDraft.expect_contains] }];
		addingCase = false;
		addNameError = null;
		saveCases();
	}

	onMount(loadCases);
</script>

<!-- ── Page ─────────────────────────────────────────────────────────────── -->
<div class="max-w-4xl mx-auto space-y-6">

	<!-- Header -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-2xl font-bold">Testing</h1>
			<p class="text-sm text-surface-400-600 mt-0.5">Run test messages against the bot to verify its behaviour.</p>
			<p class="text-xs text-surface-400-600 mt-0.5">Shopping data is never touched. Calendar-modifying tests can be paused with the skip toggle.</p>
		</div>
		<div class="flex items-center gap-2">
			<button
				onclick={openAdd}
				class="px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 hover:bg-surface-100-900 transition-colors"
			>
				+ Add case
			</button>
			{#if runPhase === 'running'}
			<button
				onclick={stopTests}
				class="px-4 py-1.5 text-sm font-semibold rounded-lg bg-red-500 hover:bg-red-600 text-white transition-colors"
			>■ Stop</button>
			{:else}
			<button
				onclick={runTests}
				disabled={cases.length === 0}
				class="px-4 py-1.5 text-sm font-semibold rounded-lg bg-primary-500 hover:bg-primary-600 text-white
				disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
			>▶ Run All</button>
			{/if}
		</div>
	</div>

	<!-- Summary bar (shown after run) -->
	{#if summary}
	<div class="flex gap-4 p-3 rounded-xl border border-surface-200-800 bg-surface-50-950 text-sm font-medium">
		<span class="text-green-600 dark:text-green-400">✓ {summary.passed} passed</span>
		{#if summary.failed > 0}
		<span class="text-red-600 dark:text-red-400">✗ {summary.failed} failed</span>
		{/if}
		{#if summary.warned > 0}
		<span class="text-yellow-600 dark:text-yellow-400">⚠ {summary.warned} warnings</span>
		{/if}
		{#if summary.skipped > 0}
		<span class="text-surface-400-600">— {summary.skipped} skipped</span>
		{/if}
	</div>
	{/if}

	{#if runError}
	<div class="p-3 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
		Error: {runError}
	</div>
	{/if}

	{#if loadError}
	<div class="p-3 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
		{loadError}
	</div>
	{/if}

	<!-- Test case cards -->
	{#if cases.length === 0 && !loadError}
	<div class="text-center py-12 text-surface-400-600 text-sm">No test cases loaded.</div>
	{:else}
	<div class="flex flex-col divide-y divide-surface-200-800 rounded-xl border border-surface-200-800 overflow-hidden">
		{#each cases as c, i}
		{@const result = results.get(c.id)}
		{@const status = result?.status ?? 'idle'}
		{@const isActive = c.id === currentRunId}
		<div class="flex flex-col transition-colors
			{status === 'fail' ? 'bg-red-50/40 dark:bg-red-900/10' : isActive ? 'bg-blue-50/60 dark:bg-blue-900/20' : 'hover:bg-surface-50-950'}
			{status === 'running' && !isActive ? 'opacity-60' : ''}
			{c.skip_in_test_mode ? 'opacity-50' : ''}">

			<!-- progress bar -->
			<div class="h-0.5 w-full overflow-hidden">
				{#if isActive}
				<div class="h-full w-1/3 bg-surface-400-600 progress-bar"></div>
				{:else if status === 'pass'}
				<div class="h-full w-full bg-green-400"></div>
				{:else if status === 'fail'}
				<div class="h-full w-full bg-red-400"></div>
				{:else if status === 'warn'}
				<div class="h-full w-full bg-yellow-400"></div>
				{/if}
			</div>

			<div class="px-4 py-3 flex flex-col gap-1.5">

			<!-- Row 1: index · name · section · status · actions -->
			<div class="flex items-center gap-2 min-w-0">
				<span class="text-surface-400-600 font-mono text-xs shrink-0 w-5 text-right">{i + 1}</span>
				<span class="font-mono text-xs font-semibold text-surface-700-300 truncate" title={c.id}>{c.id}</span>
				<span class="text-xs font-medium {sectionColor(c.section)} shrink-0">{c.section}</span>
				<span class="inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold shrink-0 {statusBadge(status)}">
					{statusIcon(status)}
				</span>			{#if isActive}
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" class="w-3.5 h-3.5 shrink-0 text-surface-400-600 spin-icon" fill="currentColor" aria-label="Running" aria-hidden="false">
				<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1ZM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm8-3.5a.75.75 0 0 1 .75.75v3.19l2.28 1.32a.75.75 0 1 1-.75 1.3l-2.5-1.44A.75.75 0 0 1 7.25 10V5.25A.75.75 0 0 1 8 4.5Z"/>
			</svg>
			{:else if result?.duration != null && status !== 'idle' && status !== 'running'}
			<span class="text-[10px] font-mono text-surface-400-600 shrink-0">{formatDuration(result.duration)}</span>
			{/if}				<!-- actions pushed to the right -->
				<div class="ml-auto flex items-center gap-1 shrink-0">
					<button
						onclick={() => toggleSkip(c.id)}
						title={c.skip_in_test_mode ? 'Mark as active' : 'Skip this test'}
						class="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border transition-colors
							{c.skip_in_test_mode
								? 'border-amber-400 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20'
								: 'border-surface-300-700 text-surface-400-600 hover:border-amber-400 hover:text-amber-600 dark:hover:text-amber-400'}"
					>{c.skip_in_test_mode ? 'active' : 'skip'}</button>
					<button onclick={() => openEdit(c)} title="Edit" class="p-1 rounded text-surface-400-600 hover:text-primary-500 transition-colors">
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" class="w-3.5 h-3.5" fill="currentColor" aria-hidden="true"><path d="M11.013 1.427a1.75 1.75 0 0 1 2.474 0l1.086 1.086a1.75 1.75 0 0 1 0 2.474l-8.61 8.61c-.21.21-.47.364-.756.445l-3.251.93a.75.75 0 0 1-.927-.928l.929-3.25c.081-.286.235-.547.445-.758l8.61-8.61Z"/></svg>
					</button>
					<button onclick={() => deleteCase(c.id)} title="Delete" class="p-1 rounded text-surface-400-600 hover:text-red-500 transition-colors">
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" class="w-3.5 h-3.5" fill="currentColor" aria-hidden="true"><path d="M6.5 1.75a.25.25 0 0 1 .25-.25h2.5a.25.25 0 0 1 .25.25V3h-3Zm4.5 0V3h2.25a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75ZM4.496 6.675l.66 6.6a.25.25 0 0 0 .249.225h5.19a.25.25 0 0 0 .249-.225l.66-6.6a.75.75 0 0 1 1.492.149l-.66 6.6A1.748 1.748 0 0 1 10.595 15h-5.19a1.75 1.75 0 0 1-1.741-1.575l-.66-6.6a.75.75 0 1 1 1.492-.15Z"/></svg>
					</button>
				</div>
			</div>

			<!-- Row 2: note / reply -->
			{#if result?.reply || c.note}
			<div class="text-xs text-surface-400-600 italic pl-7">
				{result?.reply ?? c.note}
			</div>
			{/if}

			<!-- Row 3: message · expected -->
			<div class="flex gap-4 pl-7 text-xs font-mono">
				<span class="text-surface-500 truncate" title={c.message}>{c.message}</span>
				{#if c.expect_contains.length > 0}
				<span class="text-surface-400-600 shrink-0">→ {c.expect_contains.join(', ')}</span>
				{/if}
			</div>

			</div><!-- end inner px-4 -->
		</div>
		{/each}
	</div>
	{/if}

</div>

<!-- ── Edit modal ────────────────────────────────────────────────────────── -->
{#if editingCase && editDraft}
<div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
	<div class="bg-white dark:bg-gray-900 rounded-2xl shadow-xl w-full max-w-lg p-6 space-y-4">
		<h2 class="text-lg font-bold">Edit test case</h2>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Name</span>
			<input
				bind:value={editDraft.id}
				oninput={() => editNameError = null}
				class="w-full px-3 py-1.5 text-sm rounded-lg border {editNameError ? 'border-red-400' : 'border-surface-300-700'} bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
				placeholder="e.g. shopping_add_milk"
			/>
			{#if editNameError}<p class="text-xs text-red-500 mt-1">{editNameError}</p>{/if}
		</label>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Section</span>
			<select
				bind:value={editDraft.section}
				class="w-full px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
			>
				{#each SECTIONS as s}<option value={s}>{s}</option>{/each}
			</select>
		</label>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Message</span>
			<input
				bind:value={editDraft.message}
				class="w-full px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
				placeholder="Message to send to the bot"
			/>
		</label>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Expected contains (comma-separated)</span>
			<input
				value={editDraft.expect_contains.join(', ')}
				oninput={(e) => { if (editDraft) editDraft.expect_contains = (e.currentTarget as HTMLInputElement).value.split(',').map(s => s.trim()).filter(Boolean); }}
				class="w-full px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
				placeholder="milk, eggs (leave empty to only check non-empty reply)"
			/>
		</label>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Note</span>
			<input
				bind:value={editDraft.note}
				class="w-full px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
				placeholder="Human-readable description"
			/>
		</label>

		<div class="flex gap-4 text-sm">
			<label class="flex items-center gap-2 cursor-pointer">
				<input type="checkbox" bind:checked={editDraft.skip_in_test_mode} class="rounded" />
				<span>Skip in test mode</span>
			</label>
			<label class="flex items-center gap-2 cursor-pointer">
				<input type="checkbox" bind:checked={editDraft.destructive} class="rounded" />
				<span>Destructive</span>
			</label>
		</div>

		<div class="flex justify-end gap-2 pt-2">
			<button
				onclick={() => { editingCase = null; editDraft = null; editNameError = null; }}
				class="px-4 py-1.5 text-sm rounded-lg border border-surface-300-700 hover:bg-surface-100-900 transition-colors"
			>Cancel</button>
			<button
				onclick={saveEdit}
				class="px-4 py-1.5 text-sm font-semibold rounded-lg bg-primary-500 hover:bg-primary-600 text-white transition-colors"
			>Save</button>
		</div>
	</div>
</div>
{/if}

<!-- ── Add modal ─────────────────────────────────────────────────────────── -->
{#if addingCase}
<div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
	<div class="bg-white dark:bg-gray-900 rounded-2xl shadow-xl w-full max-w-lg p-6 space-y-4">
		<h2 class="text-lg font-bold">Add test case</h2>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Name</span>
			<input
				bind:value={addDraft.id}
				oninput={() => addNameError = null}
				class="w-full px-3 py-1.5 text-sm rounded-lg border {addNameError ? 'border-red-400' : 'border-surface-300-700'} bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
				placeholder="e.g. shopping_add_milk"
			/>
			{#if addNameError}<p class="text-xs text-red-500 mt-1">{addNameError}</p>{/if}
		</label>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Section</span>
			<select
				bind:value={addDraft.section}
				class="w-full px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
			>
				{#each SECTIONS as s}<option value={s}>{s}</option>{/each}
			</select>
		</label>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Message</span>
			<input
				bind:value={addDraft.message}
				class="w-full px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
				placeholder="Message to send to the bot"
			/>
		</label>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Expected contains (comma-separated, optional)</span>
			<input
				value={addDraft.expect_contains.join(', ')}
				oninput={(e) => { addDraft.expect_contains = (e.currentTarget as HTMLInputElement).value.split(',').map(s => s.trim()).filter(Boolean); }}
				class="w-full px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
				placeholder="milk, eggs"
			/>
		</label>

		<label class="block space-y-1">
			<span class="text-xs font-semibold text-surface-500 uppercase">Note (optional)</span>
			<input
				bind:value={addDraft.note}
				class="w-full px-3 py-1.5 text-sm rounded-lg border border-surface-300-700 bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
				placeholder="Description"
			/>
		</label>

		<div class="flex gap-4 text-sm">
			<label class="flex items-center gap-2 cursor-pointer">
				<input type="checkbox" bind:checked={addDraft.skip_in_test_mode} class="rounded" />
				<span>Skip in test mode</span>
			</label>
			<label class="flex items-center gap-2 cursor-pointer">
				<input type="checkbox" bind:checked={addDraft.destructive} class="rounded" />
				<span>Destructive</span>
			</label>
		</div>

		<div class="flex justify-end gap-2 pt-2">
			<button
				onclick={() => { addingCase = false; addNameError = null; }}
				class="px-4 py-1.5 text-sm rounded-lg border border-surface-300-700 hover:bg-surface-100-900 transition-colors"
			>Cancel</button>
			<button
				onclick={confirmAdd}
				disabled={!addDraft.message.trim() || !addDraft.id.trim()}
				class="px-4 py-1.5 text-sm font-semibold rounded-lg bg-primary-500 hover:bg-primary-600 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
			>Add</button>
		</div>
	</div>
</div>
{/if}

<style>
	@keyframes progress-slide {
		0%   { transform: translateX(-150%); }
		100% { transform: translateX(450%); }
	}
	.progress-bar {
		animation: progress-slide 1.4s ease-in-out infinite;
	}
	@keyframes spin {
		to { transform: rotate(360deg); }
	}
	.spin-icon {
		animation: spin 1.2s linear infinite;
	}
</style>
