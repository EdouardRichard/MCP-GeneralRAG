import { Alert, Button, Descriptions, Empty, List, Pagination, Select, Space, Spin, Tag, Tooltip, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchMemories, fetchMemoryScopes, type MemoryScope, type MemorySummary } from '../api/memories';
import { useLocale } from '../i18n';

export default function MemoriesPage() {
  const { t } = useLocale();
  const [items, setItems] = useState<MemorySummary[]>([]);
  const [scopes, setScopes] = useState<MemoryScope[]>([]);
  const [scope, setScope] = useState<string>();
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [scopeLoading, setScopeLoading] = useState(true);
  const [error, setError] = useState<string>();
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    fetchMemoryScopes().then(response => { if (active) setScopes(response.items); })
      .catch(e => { if (active) setError(String(e)); })
      .finally(() => { if (active) setScopeLoading(false); });
    return () => { active = false; };
  }, []);
  const load = useCallback(async () => {
    if (!scope) return;
    const revision = ++generation.current;
    setLoading(true); setError(undefined); setItems([]);
    try {
      const response = await fetchMemories(scope, (page - 1) * 20);
      if (revision === generation.current) { setItems(response.memories); setTotal(response.total); }
    } catch (e) {
      if (revision === generation.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (revision === generation.current) setLoading(false);
    }
  }, [scope, page]);
  useEffect(() => { void load(); return () => { generation.current++; }; }, [load]);

  return <section style={{ maxWidth: 1120, margin: '0 auto', minWidth: 0 }}>
    <Typography.Title level={2} style={{ marginTop: 0, fontSize: 24 }}>{t('memories.title')}</Typography.Title>
    <Space wrap style={{ marginBottom: 20, width: '100%' }}>
      <Select aria-label={t('memories.scope')} placeholder={t('memories.scope')} value={scope}
        loading={scopeLoading} showSearch optionFilterProp="label" style={{ width: 272, maxWidth: '100%' }}
        options={scopes.map(item => ({ value: item.scope_id, label: item.name }))}
        onChange={value => { setScope(value); setPage(1); }} />
      <Tooltip title={t('memories.refresh')}><Button aria-label={t('memories.refresh')} icon={<ReloadOutlined />}
        disabled={!scope || loading} onClick={() => void load()} /></Tooltip>
    </Space>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16, overflowWrap: 'anywhere' }} />}
    <Spin spinning={loading}>
      {!scope ? <Empty description={t('memories.noScope')} /> : !items.length && !error && !loading ?
        <Empty description={t('memories.empty')} /> :
        <List dataSource={items} renderItem={item => <List.Item key={item.memory_id} style={{ display: 'block', padding: '20px 0' }}>
          <Space wrap size={[8, 8]} style={{ marginBottom: 8 }}>
            <Typography.Text strong style={{ overflowWrap: 'anywhere' }}>{item.title || item.memory_id}</Typography.Text>
            <Tag>{item.kind}</Tag><Tag color={item.provenance === 'hard' ? 'green' : 'cyan'}>{item.provenance}</Tag>
            <Tag color={item.status === 'quarantined' ? 'red' : item.status === 'active' ? 'green' : 'default'}>{item.status}</Tag>
          </Space>
          <Typography.Paragraph style={{ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{item.content_excerpt}</Typography.Paragraph>
          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} styles={{ content: { overflowWrap: 'anywhere', minWidth: 0 } }} items={[
            { key: 'id', label: t('memories.id'), children: item.memory_id },
            { key: 'scope', label: t('memories.scope'), children: item.knowledge_scope_id },
            { key: 'projection', label: t('memories.projection'), children: <Tag color={item.projection_status === 'complete' ? 'green' : 'red'}>{item.projection_status || 'unknown'}</Tag> },
            { key: 'from', label: t('memories.validFrom'), children: item.valid_from || '-' },
            { key: 'to', label: t('memories.validTo'), children: item.valid_to || '-' },
            { key: 'injection', label: t('memories.injection'), children: String(item.injection_flags?.risk_level || 'none') },
            { key: 'evidence', label: t('memories.evidence'), span: 3, children: item.evidence_refs?.length ? item.evidence_refs.map(String).join(', ') : '-' },
          ]} />
        </List.Item>} />}
    </Spin>
    {scope && total > 20 && <Pagination current={page} total={total} pageSize={20} showSizeChanger={false}
      onChange={setPage} style={{ marginTop: 16 }} />}
  </section>;
}
