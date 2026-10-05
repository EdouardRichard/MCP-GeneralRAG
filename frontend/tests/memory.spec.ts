import { test, expect } from '@playwright/test';

test('memory browser selects explicit scope and shows lifecycle and provenance on desktop and mobile', async ({ page }) => {
  const sid = '365392222222222223';
  await page.route('**/api/memories/scopes', route => route.fulfill({ json: { items: [{ scope_id: sid, name: 'Acceptance scope', slug: 'acceptance', domain_key: 'generic' }] } }));
  await page.route('**/api/memories?**', route => {
    expect(new URL(route.request().url()).searchParams.get('scope_ref')).toBe(sid);
    return route.fulfill({ json: { total: 1, memories: [{ memory_id: '365392222222222225', knowledge_scope_id: sid,
      kind: 'procedural', provenance: 'soft', status: 'active', title: 'Scoped procedure',
      content_excerpt: 'Keep the domain explicit.', valid_from: '2026-10-05T01:00:00Z', valid_to: null,
      evidence_refs: ['101'], injection_flags: { risk_level: 'low' }, projection_status: 'complete' }] } });
  });
  await page.goto('/memories');
  await expect(page.getByRole('heading', { name: 'Memories', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Knowledge scope' }).click();
  await page.getByText('Acceptance scope', { exact: true }).last().click();
  await expect(page.getByText('365392222222222225', { exact: true })).toBeVisible();
  await expect(page.getByText('Keep the domain explicit.')).toBeVisible();
  await expect(page.getByText('101', { exact: true })).toBeVisible();
  await expect(page.getByText('complete', { exact: true })).toBeVisible();
  await expect(page.getByText('low', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/memory-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'Memories', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/memory-mobile.png', fullPage: true });
});

test('empty and failed scopes remain visible and can be retried', async ({ page }) => {
  await page.route('**/api/memories/scopes', route => route.fulfill({ json: { items: [{ scope_id: '7', name: 'Empty scope' }] } }));
  let fail = false;
  await page.route('**/api/memories?**', route => fail ? route.fulfill({ status: 503, json: { detail: { code: 'MEMORY_WRITE_UNAVAILABLE' } } }) : route.fulfill({ json: { total: 0, memories: [] } }));
  await page.goto('/memories');
  await page.getByRole('combobox', { name: 'Knowledge scope' }).click();
  await page.getByText('Empty scope', { exact: true }).last().click();
  await expect(page.getByText('No memories in this scope.')).toBeVisible();
  fail = true;
  await page.getByRole('button', { name: 'Refresh memories' }).click();
  await expect(page.getByRole('alert')).toContainText('MEMORY_WRITE_UNAVAILABLE');
  fail = false;
  await page.getByRole('button', { name: 'Refresh memories' }).click();
  await expect(page.getByText('No memories in this scope.')).toBeVisible();
});
