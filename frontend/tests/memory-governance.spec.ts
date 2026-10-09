/**
 * 015 T052 (US6/FR-035..FR-043, SC-014/SC-015) — governance UI route-stubbing
 * spec.  Same pattern as tests/memory.spec.ts: the dev server serves the app and
 * every REST call is stubbed with page.route, so the assertions measure the UI
 * (the no-domain gate, the strong confirmation, the single-entry boundary) and
 * not a backend.
 *
 * The counters are the point: `counts` records every body-returning endpoint and
 * `posts` records every governance write.  A zero counter is a measured zero,
 * never an assumption.
 *
 * Hidden antd tab panes stay mounted, so every interaction and every text
 * assertion is scoped to `.ant-tabs-tabpane-active` (or to the modal dialog).
 */
import { test, expect } from '@playwright/test';
import type { Locator, Page, Route } from '@playwright/test';

const SID = '365392222222222229';
const MID = '365392222222222231';
const NEXT = '365392222222222233';
const SCOPE_NAME = 'Governance scope';
const CANDIDATE_VERSION = 'a'.repeat(64);

type Counters = Record<string, number>;

interface Harness {
  counts: Counters;
  posts: Counters;
  browseQueries: URL[];
  failRebuild: boolean;
}

interface MemoryRow {
  memory_id: string;
  knowledge_scope_id: string;
  kind: string;
  provenance: string;
  status: string;
  title: string;
  content_excerpt: string;
  superseded_by: string | null;
  session_id: string;
  valid_from: string;
  valid_to: string | null;
  evidence_refs: string[];
  injection_flags: Record<string, unknown>;
  projection_status: string;
}

function row(memory_id: string, status: string, superseded_by: string | null, excerpt: string): MemoryRow {
  return {
    memory_id, knowledge_scope_id: SID, kind: 'procedural', provenance: 'soft', status, title: `Entry ${memory_id}`,
    content_excerpt: excerpt, superseded_by, session_id: 'session-a', valid_from: '2026-10-05T01:00:00Z',
    valid_to: null, evidence_refs: ['101'], injection_flags: { risk_level: 'low' }, projection_status: 'complete',
  };
}

const CONSOLIDATION_RUN = {
  schema_version: 1,
  run_id: 'run-015',
  trigger: 'manual',
  execution_context: 'management',
  status: 'failed',
  observation_seq: 7,
  window: { from: '2026-10-01T00:00:00Z', to: '2026-10-02T00:00:00Z' },
  input_event_ids: ['1', '2', '3'],
  proposals: [{ proposal_id: 'proposal-1' }],
  adjudications: [{ decision: 'reject', reason: 'REJECTED_EVIDENCE_WEAK' }],
  output_memory_ids: [],
  output_event_ids: [],
  degradation_reasons: ['DEGRADED_MODEL_UNAVAILABLE'],
  counts: { input_events: 3, proposals: 1, adjudications: 1, outputs: 0 },
  created_at: '2026-10-02T00:00:00Z',
  ttl_expires_at: '2026-11-02T00:00:00Z',
};

async function stub(page: Page): Promise<Harness> {
  const harness: Harness = { counts: {}, posts: {}, browseQueries: [], failRebuild: false };
  const count = (name: string) => { harness.counts[name] = (harness.counts[name] || 0) + 1; };
  const post = (name: string) => { harness.posts[name] = (harness.posts[name] || 0) + 1; };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

  await page.route('**/api/memories/scopes', route => {
    count('scopes');
    return json(route, { items: [{ scope_id: SID, name: SCOPE_NAME, slug: 'governance', domain_key: 'generic' }] });
  });
  await page.route('**/api/memories?**', route => {
    count('browse');
    harness.browseQueries.push(new URL(route.request().url()));
    return json(route, { scope_id: SID, total: 2, memories: [
      row(MID, 'active', NEXT, 'Governance excerpt body'),
      row(NEXT, 'superseded', null, 'Superseded excerpt body'),
    ] });
  });
  await page.route('**/api/memories/stats**', route => {
    count('stats');
    return json(route, { scope_id: SID, domain_key: 'generic', generated_at: '2026-10-09T12:00:00Z', total: 2,
      kind_distribution: { episodic: 0, semantic: 1, procedural: 1 },
      provenance_distribution: { hard: 0, soft: 1, distilled: 1 },
      status_distribution: { active: 1, superseded: 1, retired: 0, quarantined: 0 },
      salience_distribution: { p50: 0.5, p90: 0.9, p95: 0.95,
        buckets: [{ lower: 0, upper: 0.5, count: 1 }, { lower: 0.5, upper: null, count: 1 }] },
      consolidation_run_count: 1, rollback_count: 0 });
  });
  await page.route('**/api/memories/promotion-candidates**', route => {
    count('promotionCandidates');
    return json(route, { scope_id: SID, total: 1, items: [{ memory_id: MID, kind: 'semantic', provenance: 'soft',
      confidence: 0.8, promote_candidate_at: '2026-10-08T00:00:00Z', candidate_version: CANDIDATE_VERSION,
      evidence_attributions: [{ evidence_id: '101', source_version: 2 }], promotable: true, ineligibility_reasons: [],
      promotion_pointer: null }] });
  });
  await page.route('**/api/memories/consolidation**', route => {
    if (route.request().method() === 'POST') {
      post('consolidation');
      return json(route, { schema_version: 1, run_id: 'run-015', scope_id: SID, request_id: 'req-cons',
        trigger: 'manual', execution_context: 'management', status: 'accepted', window: null, report_url: '/x' }, 202);
    }
    if (new URL(route.request().url()).pathname.endsWith('/runs')) {
      count('consolidationRuns');
      return json(route, { schema_version: 1, scope_id: SID, total: 1, items: [CONSOLIDATION_RUN] });
    }
    count('consolidationRunDetail');
    return json(route, CONSOLIDATION_RUN);
  });
  await page.route('**/api/memories/rebuild**', route => {
    if (new URL(route.request().url()).pathname.endsWith('/audit')) {
      count('rebuildAudit');
      return json(route, { request_id: 'req-rebuild-1', operation: 'rebuild', actor: 'management',
        scope_id: Number(SID), reason: 'audit', source_event_id: 42, since_event_id: null, result: { status: 'complete' },
        created_at: '2026-10-09T12:00:00Z' });
    }
    post('rebuild');
    if (harness.failRebuild) return json(route, { detail: { code: 'MEMORY_WRITE_UNAVAILABLE' } }, 500);
    return json(route, { scope_id: Number(SID), request_id: 'req-rebuild-1', projections: {
      scope_id: Number(SID), scope_slug: 'governance', source_event_id: 42, file_count: 7, tree_fingerprint: 'fp-1',
      status: 'complete', guard_state: 'writable', unexpected_paths: [], missing_paths: [], mode_mismatch: [],
      content_mismatch_paths: [], reason_code: null, repaired: false } });
  });
  await page.route('**/api/memories/policy**', route => {
    if (route.request().method() === 'POST') { post('policy'); return json(route, { ok: true }); }
    count('policy');
    return json(route, { scope_id: SID, domain_key: 'generic', policy: { decay_rate: 0.01, consolidation: { enabled: false } } });
  });
  await page.route('**/api/memories/promote', route => {
    post('promote');
    return json(route, { schema_version: 1, scope_id: SID, memory_id: MID, candidate_version: CANDIDATE_VERSION,
      task_id: 4242, source_id: 'src-1', initial_processing_run_id: 'run-1', status: 'uploaded', version_id: null,
      request_id: 'req-promote-1', reused: false });
  });
  await page.route('**/api/memories/retire', route => {
    post('retire');
    return json(route, { scope_id: SID, event_id: 9001, request_id: 'req-retire-1',
      impact: { memory_ids: [MID], scope_ids: [SID] }, before_fingerprint: 'b', after_fingerprint: 'a' });
  });
  await page.route('**/api/memories/purge', route => {
    post('purge');
    return json(route, { scope_id: SID, event_id: 9002, request_id: 'req-purge-1',
      impact: { memory_ids: [MID], scope_ids: [SID] }, before_fingerprint: 'b', after_fingerprint: 'a' });
  });
  await page.route('**/api/memories/rollback', route => {
    post('rollback');
    return json(route, { scope_id: SID, event_id: 9003, request_id: 'req-rollback-1',
      impact: { memory_ids: [MID], scope_ids: [SID] }, before_fingerprint: 'b', after_fingerprint: 'a' });
  });
  await page.route('**/api/memories/usage', route => {
    post('usage');
    return json(route, { ok: true });
  });
  return harness;
}

const TABS = ['Browse', 'Governance', 'Rollback', 'Projection rebuild', 'Promotion', 'Consolidation report', 'Statistics'];
const BODY_ENDPOINTS = ['browse', 'stats', 'promotionCandidates', 'consolidationRuns', 'rebuildAudit', 'policy', 'usage'];

const pane = (page: Page): Locator => page.locator('.ant-tabs-tabpane-active');
const dialog = (page: Page): Locator => page.getByRole('dialog');

async function selectScope(page: Page): Promise<void> {
  await page.getByRole('combobox', { name: 'Knowledge scope' }).click();
  await page.getByText(SCOPE_NAME, { exact: true }).last().click();
}

test('with no domain selected every view renders the empty state and no body-returning endpoint is called', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await expect(page.getByRole('heading', { name: 'Memories', exact: true })).toBeVisible();

  // The initial state is unselected-domain: the empty state is already there.
  await expect(pane(page).getByText('No scope selected')).toBeVisible();
  for (const tab of TABS) {
    await page.getByRole('tab', { name: tab }).click();
    await expect(pane(page).getByText('No scope selected')).toBeVisible();
  }
  await page.waitForTimeout(300);
  for (const endpoint of BODY_ENDPOINTS) expect(harness.counts[endpoint] || 0, endpoint).toBe(0);
  expect(await page.getByText('Governance excerpt body').count()).toBe(0);
  expect(await page.getByText('Superseded excerpt body').count()).toBe(0);
});

test('six-dimensional filtering narrows the browse list and the domain reference is always sent', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  await expect(pane(page).getByText('Governance excerpt body')).toBeVisible();

  // Six dimensions, one of which (the domain) is fixed by the gate: there is no
  // "clear the domain" path, only a locked value.
  await expect(pane(page).getByRole('combobox', { name: 'Domain' })).toBeDisabled();
  for (const name of ['Kind', 'Status', 'Provenance', 'Minimum salience']) {
    await expect(pane(page).getByRole('combobox', { name })).toBeEnabled();
  }
  await expect(pane(page).getByRole('textbox', { name: 'Session' })).toBeEnabled();

  const before = harness.browseQueries.length;
  await pane(page).getByRole('combobox', { name: 'Kind' }).click();
  await page.getByText('procedural', { exact: true }).last().click();
  await pane(page).getByRole('combobox', { name: 'Status' }).click();
  await page.getByText('active', { exact: true }).last().click();
  await pane(page).getByRole('combobox', { name: 'Provenance' }).click();
  await page.getByText('soft', { exact: true }).last().click();
  await pane(page).getByRole('textbox', { name: 'Session' }).fill('session-a');
  await pane(page).getByRole('combobox', { name: 'Minimum salience' }).click();
  await page.getByText('0.5', { exact: true }).last().click();
  await expect.poll(() => harness.browseQueries.length).toBeGreaterThan(before);
  const last = harness.browseQueries[harness.browseQueries.length - 1];
  expect(last.searchParams.get('scope_ref')).toBe(SID);
  expect(last.searchParams.get('kind')).toBe('procedural');
  expect(last.searchParams.get('status')).toBe('active');
  expect(last.searchParams.get('provenance')).toBe('soft');
  expect(last.searchParams.get('session_id')).toBe('session-a');
  expect(last.searchParams.get('min_salience')).toBe('0.5');

  // Every request ever issued carried the current scope_ref: filters only narrow.
  expect(harness.browseQueries.every(query => query.searchParams.get('scope_ref') === SID)).toBe(true);
});

test('the correction chain is reachable and superseded history is never dropped', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  await expect(pane(page).getByText('Governance excerpt body')).toBeVisible();
  const before = harness.browseQueries.length;
  await pane(page).getByRole('button', { name: `Show correction chain ${MID}` }).click();
  await expect(pane(page).getByText('Correction chain', { exact: true })).toBeVisible();
  const successor = pane(page).getByRole('button', { name: `Chain entry ${NEXT}` });
  await expect(successor).toBeVisible();
  await successor.click();
  await expect(pane(page).getByTestId('memory-chain-current')).toHaveText(NEXT);

  // History remains reachable by a narrowing query that still carries scope_ref.
  await pane(page).getByRole('button', { name: 'Show superseded history' }).click();
  await expect.poll(() => harness.browseQueries.length).toBeGreaterThan(before);
  const last = harness.browseQueries[harness.browseQueries.length - 1];
  expect(last.searchParams.get('scope_ref')).toBe(SID);
  expect(last.searchParams.get('status')).toBe('superseded');
});

test('switching views never resets or clears the selected domain', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  await expect(pane(page).getByText('Governance excerpt body')).toBeVisible();
  for (const tab of TABS) {
    await page.getByRole('tab', { name: tab }).click();
    await expect(pane(page)).toBeVisible();
  }
  await page.getByRole('tab', { name: 'Browse' }).click();
  await expect(pane(page).getByText('Governance excerpt body')).toBeVisible();
  const before = harness.browseQueries.length;
  await page.getByRole('button', { name: 'Refresh memories' }).click();
  await expect.poll(() => harness.browseQueries.length).toBeGreaterThan(before);
  const scoped = harness.browseQueries.filter(query => query.searchParams.get('scope_ref'));
  expect(scoped.length).toBeGreaterThan(0);
  expect(scoped.every(query => query.searchParams.get('scope_ref') === SID)).toBe(true);
});

test('retire cannot be submitted without the strong confirmation value', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  await page.getByRole('tab', { name: 'Governance' }).click();

  // Single-entry only: no batch affordance anywhere on the surface.
  await expect(page.locator('.ant-checkbox')).toHaveCount(0);
  await expect(page.locator('.ant-table-row-selection')).toHaveCount(0);

  await pane(page).getByRole('textbox', { name: 'Memory ID' }).fill(MID);
  await pane(page).getByRole('textbox', { name: 'Reason' }).fill('015 governance verification');
  await pane(page).getByRole('button', { name: 'Preview impact' }).click();
  await expect(pane(page).getByText('Affected entries')).toBeVisible();

  await pane(page).getByRole('button', { name: 'Retire entry' }).click();
  await expect(dialog(page).getByText('Impact preview')).toBeVisible();
  const submit = dialog(page).getByRole('button', { name: 'Submit', exact: true });
  await expect(submit).toBeDisabled();
  expect(harness.posts.retire || 0).toBe(0);
  expect(harness.posts.purge || 0).toBe(0);
  await dialog(page).getByRole('textbox', { name: 'Type the confirmation value' }).fill('not-the-confirmation-value');
  await expect(submit).toBeDisabled();
  await expect(dialog(page).getByText('The typed value does not match the required confirmation value.')).toBeVisible();
  expect(harness.posts.retire || 0).toBe(0);

  await dialog(page).getByRole('textbox', { name: 'Type the confirmation value' }).fill(`${SID}::${MID}`);
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect.poll(() => harness.posts.retire || 0).toBe(1);
  await expect(dialog(page).getByText('Audit pointer')).toBeVisible();
  await expect(dialog(page).getByText('req-retire-1')).toBeVisible();
  await expect(dialog(page).getByText('9001')).toBeVisible();
});

test('purge is the only deletion path and needs the same strong confirmation', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  await page.getByRole('tab', { name: 'Governance' }).click();
  await pane(page).getByRole('textbox', { name: 'Memory ID' }).fill(MID);
  await pane(page).getByRole('textbox', { name: 'Reason' }).fill('purge verification');
  await pane(page).getByRole('button', { name: 'Preview impact' }).click();
  await expect(pane(page).getByText('Affected entries')).toBeVisible();
  await pane(page).getByRole('button', { name: 'Purge entry' }).click();
  const submit = dialog(page).getByRole('button', { name: 'Submit', exact: true });
  await expect(submit).toBeDisabled();
  expect(harness.posts.purge || 0).toBe(0);
  await dialog(page).getByRole('textbox', { name: 'Type the confirmation value' }).fill(`${SID}::${MID}`);
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect.poll(() => harness.posts.purge || 0).toBe(1);
});

test('rollback is management-surface only and needs the strong confirmation value', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  await expect(page.getByRole('tab', { name: 'Rollback' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Projection rebuild' })).toBeVisible();
  await page.getByRole('tab', { name: 'Rollback' }).click();

  await pane(page).getByRole('textbox', { name: 'Event point value' }).fill('77');
  await pane(page).getByRole('textbox', { name: 'Reason' }).fill('rollback verification');
  await pane(page).getByRole('button', { name: 'Preview impact' }).click();
  await expect(pane(page).getByText('Affected entries')).toBeVisible();
  await pane(page).getByRole('button', { name: 'Roll back' }).click();
  await expect(dialog(page).getByText('Impact preview')).toBeVisible();
  const submit = dialog(page).getByRole('button', { name: 'Submit', exact: true });
  await expect(submit).toBeDisabled();
  expect(harness.posts.rollback || 0).toBe(0);
  await dialog(page).getByRole('textbox', { name: 'Type the confirmation value' }).fill(`${SID}::77`);
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect.poll(() => harness.posts.rollback || 0).toBe(1);
});

test('a rebuild failure is presented explicitly and the audit read path stays reachable', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  harness.failRebuild = true;
  await page.getByRole('tab', { name: 'Projection rebuild' }).click();
  await pane(page).getByRole('textbox', { name: 'Reason' }).fill('rebuild verification');
  await pane(page).getByRole('button', { name: 'Trigger rebuild' }).click();
  await expect(pane(page).getByRole('alert')).toContainText('Rebuild failed');
  await expect(pane(page).getByRole('alert')).toContainText('MEMORY_WRITE_UNAVAILABLE');

  harness.failRebuild = false;
  await pane(page).getByRole('button', { name: 'Trigger rebuild' }).click();
  await expect.poll(() => harness.posts.rebuild || 0).toBe(2);
  await expect(pane(page).getByText('req-rebuild-1')).toBeVisible();
  await expect(pane(page).getByText('Per-projection consistency report')).toBeVisible();
  await pane(page).getByRole('button', { name: 'Load audit record' }).click();
  await expect.poll(() => harness.counts.rebuildAudit || 0).toBeGreaterThanOrEqual(1);
  await expect(pane(page).getByText('Rebuild audit (the only audit read path)')).toBeVisible();
});

test('promotion is an explicit manual action with no automatic entry', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  await page.getByRole('tab', { name: 'Promotion' }).click();
  // React StrictMode double-invokes mount effects in dev: at least one fetch, never zero.
  await expect.poll(() => harness.counts.promotionCandidates || 0).toBeGreaterThanOrEqual(1);
  await expect(pane(page).getByText('Candidate basis')).toBeVisible();
  await expect(pane(page).getByText('Promotion destination', { exact: true })).toBeVisible();
  await expect(pane(page).getByText('Retained original memory', { exact: true })).toBeVisible();
  // No machine-triggered entry: nothing is promoted until a human clicks, and no
  // toggle/switch exists that could promote on its own.
  expect(harness.posts.promote || 0).toBe(0);
  await expect(pane(page).getByRole('switch')).toHaveCount(0);
  await expect(pane(page).getByRole('button', { name: /automatic/i })).toHaveCount(0);
  await pane(page).getByRole('textbox', { name: 'Reason' }).fill('manual promotion verification');
  await pane(page).getByRole('button', { name: 'Promote manually' }).click();
  await expect.poll(() => harness.posts.promote || 0).toBe(1);
  await expect(pane(page).getByText('req-promote-1')).toBeVisible();
});

test('the consolidation report shows failure and rejection reasons and the policy editor fails closed', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  await page.getByRole('tab', { name: 'Consolidation report' }).click();
  await expect.poll(() => harness.counts.consolidationRuns || 0).toBeGreaterThanOrEqual(1);
  await expect(pane(page).getByText('failed', { exact: true }).first()).toBeVisible();
  await pane(page).getByRole('button', { name: 'Open run detail run-015' }).click();
  await expect.poll(() => harness.counts.consolidationRunDetail || 0).toBeGreaterThanOrEqual(1);
  const detail = pane(page).getByTestId('memory-consolidation-detail');
  await expect(detail.getByText('Failure and rejection reasons')).toBeVisible();
  await expect(detail.getByText('DEGRADED_MODEL_UNAVAILABLE', { exact: true })).toBeVisible();
  await expect(detail.getByText('REJECTED_EVIDENCE_WEAK', { exact: true })).toBeVisible();
  await expect(detail.getByText('2026-11-02T00:00:00Z')).toBeVisible();

  await pane(page).getByRole('textbox', { name: 'memory_policy (JSON)' }).fill('{ not json');
  await pane(page).getByRole('button', { name: 'Save policy' }).click();
  await expect(pane(page).getByRole('alert')).toContainText('not legal JSON');
  expect(harness.posts.policy || 0).toBe(0);
  await pane(page).getByRole('textbox', { name: 'memory_policy (JSON)' }).fill('{"decay_rate": 0.02}');
  await pane(page).getByRole('textbox', { name: 'Reason' }).fill('policy verification');
  await pane(page).getByRole('button', { name: 'Save policy' }).click();
  await expect.poll(() => harness.posts.policy || 0).toBe(1);
});

test('the statistics panel renders counts and distributions and no body text', async ({ page }) => {
  const harness = await stub(page);
  await page.goto('/memories');
  await selectScope(page);
  await page.getByRole('tab', { name: 'Statistics' }).click();
  await expect.poll(() => harness.counts.stats || 0).toBeGreaterThanOrEqual(1);
  const panel = page.getByTestId('memory-stats-panel');
  await expect(panel.getByText('Total entries')).toBeVisible();
  await expect(panel.getByText('Salience p50')).toBeVisible();
  await expect(panel.getByText('Governance excerpt body')).toHaveCount(0);
  await expect(panel.getByText('Superseded excerpt body')).toHaveCount(0);
  expect(harness.counts.browse || 0).toBeGreaterThan(0);
});

test('the seven-tab surface has no horizontal overflow at mobile width', async ({ page }) => {
  await stub(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/memories');
  await selectScope(page);
  await expect(page.getByRole('heading', { name: 'Memories', exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const overflow = await page.locator('body *').evaluateAll(elements => elements
    .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
    .map(element => ({ tag: element.tagName, class: element.className })));
  expect(overflow).toEqual([]);
});
