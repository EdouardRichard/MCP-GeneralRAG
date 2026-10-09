/**
 * 015 T049 (US6/FR-044, SC-016; research R10) — domain statistics panel.
 *
 * Counts and distributions only, consumed from `GET /api/memories/stats`.  The
 * panel never renders body text: every value is a count, a closed-vocabulary
 * label or a quantile, so the privacy guard of the statistics endpoint holds all
 * the way to the DOM.
 */
import { Alert, Descriptions, Empty, List, Space, Spin, Tag, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { fetchMemoryStats, type MemoryStats } from '../../api/memories';
import { useLocale } from '../../i18n';

interface Props { scope?: string; refreshToken: number }

function bucketLabel(lower: number, upper: number | null, unbounded: string): string {
  return upper === null ? `${lower} – ${unbounded}` : `${lower} – ${upper}`;
}

export default function MemoryStatsPanel({ scope, refreshToken }: Props) {
  const { t } = useLocale();
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const generation = useRef(0);

  useEffect(() => {
    if (!scope) { setStats(null); setError(undefined); setLoading(false); return; }
    let active = true;
    const revision = ++generation.current;
    setLoading(true);
    setError(undefined);
    fetchMemoryStats(scope).then(response => {
      if (active && revision === generation.current) setStats(response);
    }).catch((cause: unknown) => {
      if (!active || revision !== generation.current) return;
      setStats(null);
      setError(`${t('memories.stats.loadFailed')}${cause instanceof Error ? cause.message : String(cause)}`);
    }).finally(() => {
      if (active && revision === generation.current) setLoading(false);
    });
    return () => { active = false; };
  }, [scope, refreshToken, t]);

  if (!scope) return <section data-testid="memory-stats-panel"><Empty description={t('memories.noScope')} /></section>;

  const quantile = (value: number | null): string => value === null ? t('memories.stats.notMeasured') : String(value);

  return <section data-testid="memory-stats-panel" style={{ minWidth: 0 }}>
    <Typography.Title level={4} style={{ marginTop: 0 }}>{t('memories.stats.title')}</Typography.Title>
    <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>{t('memories.stats.intro')}</Typography.Paragraph>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12, overflowWrap: 'anywhere' }} />}
    <Spin spinning={loading}>
      {stats && <>
        <Descriptions size="small" column={{ xs: 1, sm: 2 }} styles={{ content: { overflowWrap: 'anywhere', minWidth: 0 } }} items={[
          { key: 'total', label: t('memories.stats.total'), children: stats.total },
          { key: 'generated', label: t('memories.stats.generatedAt'), children: stats.generated_at },
          { key: 'domain', label: t('memories.filter.domain'), children: stats.domain_key },
          { key: 'runs', label: t('memories.stats.consolidationRuns'), children: stats.consolidation_run_count },
          { key: 'rollbacks', label: t('memories.stats.rollbacks'), children: stats.rollback_count },
          { key: 'p50', label: t('memories.stats.p50'), children: quantile(stats.salience_distribution?.p50 ?? null) },
          { key: 'p90', label: t('memories.stats.p90'), children: quantile(stats.salience_distribution?.p90 ?? null) },
          { key: 'p95', label: t('memories.stats.p95'), children: quantile(stats.salience_distribution?.p95 ?? null) },
        ]} />
        <Space direction="vertical" size={12} style={{ width: '100%', marginTop: 12, minWidth: 0 }}>
          <Distribution title={t('memories.stats.kind')} values={stats.kind_distribution} />
          <Distribution title={t('memories.stats.provenance')} values={stats.provenance_distribution} />
          <Distribution title={t('memories.stats.status')} values={stats.status_distribution} />
          <section>
            <Typography.Text strong>{t('memories.stats.salience')}</Typography.Text>
            <List size="small" dataSource={stats.salience_distribution?.buckets ?? []}
              locale={{ emptyText: t('memories.stats.notMeasured') }}
              renderItem={bucket => <List.Item key={`${bucket.lower}-${bucket.upper}`} style={{ padding: '4px 0' }}>
                <Space wrap size={[8, 4]}>
                  <Tag>{t('memories.stats.bucket')}</Tag>
                  <Typography.Text>{bucketLabel(bucket.lower, bucket.upper, '+')}</Typography.Text>
                  <Typography.Text>{t('memories.stats.count')}: {bucket.count}</Typography.Text>
                </Space>
              </List.Item>} />
          </section>
        </Space>
      </>}
    </Spin>
  </section>;
}

function Distribution({ title, values }: { title: string; values: Record<string, number> }) {
  const entries = Object.entries(values ?? {});
  return <section>
    <Typography.Text strong>{title}</Typography.Text>
    <Space wrap size={[8, 8]} style={{ marginTop: 4 }}>
      {entries.length === 0 ? <Typography.Text type="secondary">-</Typography.Text> :
        entries.map(([key, count]) => <Tag key={key}>{key}: {count}</Tag>)}
    </Space>
  </section>;
}
