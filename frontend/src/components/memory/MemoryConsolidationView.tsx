/**
 * 015 T048 (US6/FR-042; research R10) — consolidation report and domain policy.
 *
 * The run list and run detail carry run id / domain / window / input size /
 * proposals and adjudication / output / status / retention / **failure and
 * rejection reasons**.  The `memory_policy` editor fails closed: an illegal
 * value never reaches the API, and a failed save reports the error explicitly.
 */
import { Alert, Button, Descriptions, Empty, Input, List, Space, Spin, Tag, Typography } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchConsolidationRun, fetchConsolidationRuns, fetchMemoryPolicy, updateMemoryPolicy, type ConsolidationRun } from '../../api/memories';
import { useLocale } from '../../i18n';
import { wireNumericId } from './ConfirmActionModal';

interface Props { scope?: string; refreshToken: number }

const REASON_KEY = /reason|reject|error/i;

/** Failure and rejection reasons, taken from the run's own facts. */
function collectReasons(run: ConsolidationRun): string[] {
  const reasons: string[] = [...(run.degradation_reasons ?? [])];
  const push = (value: string) => { if (!reasons.includes(value)) reasons.push(value); };
  const walk = (value: unknown) => {
    if (Array.isArray(value)) { value.forEach(walk); return; }
    if (typeof value !== 'object' || value === null) return;
    for (const [key, child] of Object.entries(value)) {
      if (typeof child === 'string') {
        if (REASON_KEY.test(key) || (key === 'decision' && child !== 'accept')) push(child);
      } else {
        walk(child);
      }
    }
  };
  walk(run.adjudications);
  walk(run.proposals);
  return reasons;
}

const STATUS_COLOR: Record<string, string> = { complete: 'green', failed: 'red', degraded: 'orange', pending: 'default' };

export default function MemoryConsolidationView({ scope, refreshToken }: Props) {
  const { t } = useLocale();
  const [runs, setRuns] = useState<ConsolidationRun[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [detail, setDetail] = useState<ConsolidationRun | null>(null);
  const [detailError, setDetailError] = useState<string>();
  const [policyText, setPolicyText] = useState('');
  const [reason, setReason] = useState('');
  const [policyError, setPolicyError] = useState<string>();
  const [policyMessage, setPolicyMessage] = useState<string>();
  const [policySaving, setPolicySaving] = useState(false);
  const generation = useRef(0);

  const loadRuns = useCallback(async () => {
    if (!scope) return;
    const revision = ++generation.current;
    setLoading(true);
    setError(undefined);
    try {
      const page = await fetchConsolidationRuns(scope);
      if (revision === generation.current) { setRuns(page.items); setTotal(page.total); }
    } catch (cause: unknown) {
      if (revision === generation.current) setError(`${t('memories.consolidation.loadFailed')}${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      if (revision === generation.current) setLoading(false);
    }
  }, [scope, t]);

  const loadPolicy = useCallback(async () => {
    if (!scope) return;
    setPolicyError(undefined);
    try {
      const response = await fetchMemoryPolicy(scope);
      setPolicyText(JSON.stringify(response.policy ?? {}, null, 2));
    } catch (cause: unknown) {
      setPolicyError(`${t('memories.consolidation.policySaveFailed')}${cause instanceof Error ? cause.message : String(cause)}`);
    }
  }, [scope, t]);

  useEffect(() => {
    setDetail(null);
    void loadRuns();
    void loadPolicy();
    return () => { generation.current++; };
  }, [loadRuns, loadPolicy, refreshToken]);

  if (!scope) return <section data-testid="memory-view-consolidation"><Empty description={t('memories.noScope')} /></section>;

  const openRun = async (runId: string) => {
    setDetailError(undefined);
    try {
      setDetail(await fetchConsolidationRun(scope, runId));
    } catch (cause: unknown) {
      setDetail(null);
      setDetailError(`${t('memories.consolidation.loadFailed')}${cause instanceof Error ? cause.message : String(cause)}`);
    }
  };

  const savePolicy = async () => {
    setPolicyError(undefined);
    setPolicyMessage(undefined);
    let parsed: unknown;
    try {
      parsed = JSON.parse(policyText);
    } catch {
      setPolicyError(t('memories.consolidation.policyIllegal'));
      return;
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      setPolicyError(t('memories.consolidation.policyIllegal'));
      return;
    }
    setPolicySaving(true);
    try {
      await updateMemoryPolicy({
        scope_id: wireNumericId(scope),
        reason: reason.trim() === '' ? 'management policy update' : reason.trim(),
        policy: parsed,
      });
      setPolicyMessage(t('memories.consolidation.policySaved'));
      await loadPolicy();
    } catch (cause: unknown) {
      setPolicyError(`${t('memories.consolidation.policySaveFailed')}${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      setPolicySaving(false);
    }
  };

  const shown = detail ?? null;

  return <section data-testid="memory-view-consolidation" style={{ minWidth: 0 }}>
    <Typography.Title level={4} style={{ marginTop: 0 }}>{t('memories.consolidation.title')}</Typography.Title>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12, overflowWrap: 'anywhere' }} />}
    <Spin spinning={loading}>
      {!runs.length && !error && !loading ? <Empty description={t('memories.browse.empty')} /> :
        <List dataSource={runs} renderItem={run => <List.Item key={run.run_id ?? String(run.observation_seq)} style={{ display: 'block', padding: '16px 0' }}>
          <Space wrap size={[8, 8]} style={{ marginBottom: 8 }}>
            <Typography.Text strong style={{ overflowWrap: 'anywhere' }}>{run.run_id ?? '-'}</Typography.Text>
            <Tag color={STATUS_COLOR[run.status] ?? 'default'}>{run.status}</Tag>
            <Tag>{run.trigger}</Tag>
          </Space>
          <Descriptions size="small" column={{ xs: 1, sm: 2 }} styles={{ content: { overflowWrap: 'anywhere', minWidth: 0 } }} items={[
            { key: 'window', label: t('memories.consolidation.window'), children: run.window ? JSON.stringify(run.window) : '-' },
            { key: 'input', label: t('memories.consolidation.inputSize'), children: String(run.counts?.input_events ?? run.input_event_ids?.length ?? 0) },
            { key: 'proposals', label: t('memories.consolidation.proposals'), children: String(run.counts?.proposals ?? run.proposals?.length ?? 0) },
            { key: 'adjudications', label: t('memories.consolidation.adjudications'), children: String(run.counts?.adjudications ?? run.adjudications?.length ?? 0) },
            { key: 'output', label: t('memories.consolidation.output'), children: String(run.counts?.outputs ?? run.output_memory_ids?.length ?? 0) },
            { key: 'retention', label: t('memories.consolidation.retention'), children: run.ttl_expires_at },
            { key: 'reasons', label: t('memories.consolidation.failureReasons'), span: 2, children: collectReasons(run).length ? collectReasons(run).join(', ') : t('memories.consolidation.noReasons') },
          ]} />
          {run.run_id && <Space wrap size={[8, 8]} style={{ marginTop: 8 }}>
            <Button size="small" aria-label={`${t('memories.consolidation.select')} ${run.run_id}`}
              onClick={() => void openRun(run.run_id as string)}>{t('memories.consolidation.detail')}</Button>
          </Space>}
        </List.Item>} />}
    </Spin>
    {total > runs.length && <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>{total}</Typography.Paragraph>}
    {detailError && <Alert type="error" showIcon message={detailError} style={{ marginTop: 12, overflowWrap: 'anywhere' }} />}
    {shown && <section data-testid="memory-consolidation-detail" style={{ marginTop: 16 }}>
      <Typography.Title level={5}>{t('memories.consolidation.detail')}</Typography.Title>
      <Descriptions size="small" column={{ xs: 1, sm: 2 }} styles={{ content: { overflowWrap: 'anywhere', minWidth: 0 } }} items={[
        { key: 'run', label: t('memories.consolidation.runId'), children: shown.run_id ?? '-' },
        { key: 'status', label: t('memories.consolidation.status'), children: shown.status },
        { key: 'window', label: t('memories.consolidation.window'), children: shown.window ? JSON.stringify(shown.window) : '-' },
        { key: 'input', label: t('memories.consolidation.inputSize'), children: String(shown.counts?.input_events ?? shown.input_event_ids?.length ?? 0) },
        { key: 'proposals', label: t('memories.consolidation.proposals'), children: String(shown.counts?.proposals ?? shown.proposals?.length ?? 0) },
        { key: 'adjudications', label: t('memories.consolidation.adjudications'), children: String(shown.counts?.adjudications ?? shown.adjudications?.length ?? 0) },
        { key: 'output', label: t('memories.consolidation.output'), children: shown.output_memory_ids?.length ? shown.output_memory_ids.join(', ') : '-' },
        { key: 'retention', label: t('memories.consolidation.retention'), children: shown.ttl_expires_at },
        { key: 'proposalDetail', label: t('memories.consolidation.proposals'), span: 2, children: JSON.stringify(shown.proposals ?? []) },
        { key: 'adjudicationDetail', label: t('memories.consolidation.adjudications'), span: 2, children: JSON.stringify(shown.adjudications ?? []) },
      ]} />
      <Typography.Text strong>{t('memories.consolidation.failureReasons')}</Typography.Text>
      <List size="small" dataSource={collectReasons(shown)} locale={{ emptyText: t('memories.consolidation.noReasons') }}
        renderItem={entry => <List.Item key={entry} style={{ padding: '4px 0' }}>
          <Typography.Text style={{ overflowWrap: 'anywhere' }}>{entry}</Typography.Text>
        </List.Item>} />
    </section>}
    <section data-testid="memory-consolidation-policy" style={{ marginTop: 16 }}>
      <Typography.Title level={5}>{t('memories.consolidation.policy')}</Typography.Title>
      <Input.TextArea aria-label={t('memories.consolidation.policyValue')} value={policyText} autoSize={{ minRows: 4, maxRows: 12 }}
        onChange={event => setPolicyText(event.target.value)} />
      <Space wrap size={[8, 8]} style={{ marginTop: 8 }}>
        <Input aria-label={t('memories.consolidation.reason')} placeholder={t('memories.consolidation.reason')}
          value={reason} onChange={event => setReason(event.target.value)} style={{ width: 240, maxWidth: '100%' }} />
        <Button type="primary" loading={policySaving} onClick={() => void savePolicy()}>{t('memories.consolidation.savePolicy')}</Button>
      </Space>
      {policyError && <Alert style={{ marginTop: 8, overflowWrap: 'anywhere' }} type="error" showIcon message={policyError} />}
      {policyMessage && <Alert style={{ marginTop: 8, overflowWrap: 'anywhere' }} type="success" showIcon message={policyMessage} />}
    </section>
  </section>;
}
