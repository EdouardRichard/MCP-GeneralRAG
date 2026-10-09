import { Alert, Button, Select, Space, Tabs, Tooltip, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { fetchMemoryScopes, type MemoryScope } from '../api/memories';
import { useLocale } from '../i18n';
import MemoryBrowseView from '../components/memory/MemoryBrowseView';
import MemoryGovernanceView from '../components/memory/MemoryGovernanceView';
import MemoryRollbackView from '../components/memory/MemoryRollbackView';
import MemoryRebuildView from '../components/memory/MemoryRebuildView';
import MemoryPromotionView from '../components/memory/MemoryPromotionView';
import MemoryConsolidationView from '../components/memory/MemoryConsolidationView';
import MemoryStatsPanel from '../components/memory/MemoryStatsPanel';

/**
 * 015 T049 (US6/FR-035, FR-043; research R10, governance-ui-contract §1/§2).
 *
 * antd `Tabs` hosts the six governance views plus the statistics panel.  The
 * domain selection is a mandatory gate: with no domain selected every view
 * renders `Empty`/`memories.noScope` and issues no request that can return body
 * text (each view guards `if (!scope) return` and the page never widens the
 * scope on a tab change).  Switching views cannot reset or clear the selection
 * because the selection lives here, not inside a tab pane.  `App.tsx` keeps its
 * four flat routes unchanged.
 */
export default function MemoriesPage() {
  const { t } = useLocale();
  const [scopes, setScopes] = useState<MemoryScope[]>([]);
  const [scope, setScope] = useState<string>();
  const [scopeLoading, setScopeLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let active = true;
    fetchMemoryScopes().then(response => { if (active) setScopes(response.items); })
      .catch(cause => { if (active) setError(String(cause)); })
      .finally(() => { if (active) setScopeLoading(false); });
    return () => { active = false; };
  }, []);

  return <section style={{ maxWidth: 1120, margin: '0 auto', minWidth: 0 }}>
    {/* The tab bar must never introduce horizontal overflow on a 390px phone:
        the shipped nav list is `flex: none; white-space: nowrap`, so the seven
        labels are wrapped instead of scrolled (the existing memory.spec.ts
        overflow assertion is a hard constraint). */}
    <style>{`
.memories-tabs .ant-tabs-nav-wrap { overflow: visible; }
.memories-tabs .ant-tabs-nav-list { flex-wrap: wrap; width: 100%; transform: none; }
`}</style>
    <Typography.Title level={2} style={{ marginTop: 0, fontSize: 24 }}>{t('memories.title')}</Typography.Title>
    <Space wrap style={{ marginBottom: 20, width: '100%' }}>
      <Select aria-label={t('memories.scope')} placeholder={t('memories.scope')} value={scope}
        loading={scopeLoading} showSearch optionFilterProp="label" style={{ width: 272, maxWidth: '100%' }}
        options={scopes.map(item => ({ value: item.scope_id, label: item.name }))}
        onChange={value => setScope(value)} />
      <Tooltip title={t('memories.refresh')}><Button aria-label={t('memories.refresh')} icon={<ReloadOutlined />}
        disabled={!scope} onClick={() => setRefreshToken(token => token + 1)} /></Tooltip>
    </Space>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16, overflowWrap: 'anywhere' }} />}
    <Tabs className="memories-tabs" items={[
      { key: 'browse', label: t('memories.tabs.browse'), children: <MemoryBrowseView scope={scope} refreshToken={refreshToken} /> },
      { key: 'governance', label: t('memories.tabs.governance'), children: <MemoryGovernanceView scope={scope} /> },
      { key: 'rollback', label: t('memories.tabs.rollback'), children: <MemoryRollbackView scope={scope} /> },
      { key: 'rebuild', label: t('memories.tabs.rebuild'), children: <MemoryRebuildView scope={scope} /> },
      { key: 'promotion', label: t('memories.tabs.promotion'), children: <MemoryPromotionView scope={scope} refreshToken={refreshToken} /> },
      { key: 'consolidation', label: t('memories.tabs.consolidation'), children: <MemoryConsolidationView scope={scope} refreshToken={refreshToken} /> },
      { key: 'stats', label: t('memories.tabs.stats'), children: <MemoryStatsPanel scope={scope} refreshToken={refreshToken} /> },
    ]} />
  </section>;
}
