/**
 * 015 T046 (US6/FR-040; research R10) — projection rebuild.
 *
 * Trigger a rebuild for the selected domain, then show the rebuild result and
 * the per-projection consistency report.  `POST /api/memories/rebuild` and
 * `GET /api/memories/rebuild/audit` (the only audit read path) are the complete
 * surface used here.  A failure is presented explicitly and never swallowed.
 *
 * The delivered `RebuildCommand` carries `scope_id`/`reason`/`since_event_id`
 * only, so the projection selector narrows the *report*, which is stated in the
 * UI instead of pretending a per-projection trigger exists.
 */
import { Alert, Button, Descriptions, Empty, Input, List, Select, Space, Spin, Tag, Typography } from 'antd';
import { useState } from 'react';
import { fetchRebuildAudit, rebuildMemoryProjections, type RebuildAudit, type RebuildResult } from '../../api/memories';
import { useLocale } from '../../i18n';
import { wireNumericId } from './ConfirmActionModal';

interface Props { scope?: string }

const PROJECTIONS = ['relation', 'dense', 'links', 'summary', 'file', 'salience'];
const PROJECTION_OPTIONS = PROJECTIONS.map(value => ({ value, label: value }));
const MISMATCH_KEYS = ['unexpected_paths', 'missing_paths', 'mode_mismatch', 'content_mismatch_paths'];

function failureLines(result: RebuildResult): string[] {
  const report = (result.projections ?? {}) as Record<string, unknown>;
  const lines: string[] = [];
  if (typeof report.status === 'string' && report.status !== 'complete') lines.push(`status=${report.status}`);
  if (report.reason_code !== undefined && report.reason_code !== null) lines.push(`reason_code=${String(report.reason_code)}`);
  for (const key of MISMATCH_KEYS) {
    const value = report[key];
    if (Array.isArray(value) && value.length > 0) lines.push(`${key}=${value.map(String).join(', ')}`);
  }
  for (const [name, value] of Object.entries(report)) {
    if (typeof value === 'object' && value !== null && (value as Record<string, unknown>).matches_replay === false) {
      lines.push(`${name}: matches_replay=false`);
    }
  }
  return lines;
}

export default function MemoryRebuildView({ scope }: Props) {
  const { t } = useLocale();
  const [projection, setProjection] = useState<string>();
  const [sinceEventId, setSinceEventId] = useState('');
  const [reason, setReason] = useState('');
  const [result, setResult] = useState<RebuildResult | null>(null);
  const [audit, setAudit] = useState<RebuildAudit | null>(null);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string>();

  if (!scope) return <section data-testid="memory-view-rebuild"><Empty description={t('memories.noScope')} /></section>;

  const trigger = async () => {
    setLoading(true);
    setError(undefined);
    setAudit(null);
    setAuditError(undefined);
    try {
      const since = sinceEventId.trim();
      setResult(await rebuildMemoryProjections({
        scope_id: wireNumericId(scope),
        reason: reason.trim() === '' ? 'management rebuild' : reason.trim(),
        since_event_id: since === '' ? undefined : wireNumericId(since),
      }));
    } catch (cause: unknown) {
      setResult(null);
      setError(`${t('memories.rebuild.failed')}${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      setLoading(false);
    }
  };

  const loadAudit = async () => {
    if (!result) return;
    setAuditLoading(true);
    setAuditError(undefined);
    try {
      setAudit(await fetchRebuildAudit(result.request_id));
    } catch (cause: unknown) {
      setAudit(null);
      setAuditError(`${t('memories.rebuild.failed')}${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      setAuditLoading(false);
    }
  };

  const report = (result?.projections ?? {}) as Record<string, unknown>;
  const reportRows = Object.entries(report).filter(([key]) => projection === undefined || PROJECTIONS.includes(key));
  const projectionRows = PROJECTIONS
    .filter(name => projection === undefined || projection === name)
    .map(name => {
      const value = report[name];
      const record = typeof value === 'object' && value !== null ? value as Record<string, unknown> : undefined;
      return {
        name,
        reported: record !== undefined,
        count: typeof record?.count === 'number' ? record.count : undefined,
        matchesReplay: typeof record?.matches_replay === 'boolean' ? record.matches_replay : undefined,
      };
    });
  const failures = result ? failureLines(result) : [];

  return <section data-testid="memory-view-rebuild" style={{ minWidth: 0 }}>
    <Typography.Title level={4} style={{ marginTop: 0 }}>{t('memories.rebuild.title')}</Typography.Title>
    <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>{t('memories.rebuild.intro')}</Typography.Paragraph>
    <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>{t('memories.rebuild.projectionScope')}</Typography.Paragraph>
    <Space wrap size={[8, 8]} style={{ marginBottom: 12 }}>
      <Select aria-label={t('memories.rebuild.projection')} allowClear placeholder={t('memories.rebuild.projection')}
        value={projection} onChange={setProjection} style={{ width: 200, maxWidth: '100%' }} options={PROJECTION_OPTIONS} />
      <Input aria-label={t('memories.rebuild.sinceEventId')} placeholder={t('memories.rebuild.sinceEventId')}
        value={sinceEventId} onChange={event => setSinceEventId(event.target.value)} style={{ width: 200, maxWidth: '100%' }} />
      <Input aria-label={t('memories.rebuild.reason')} placeholder={t('memories.rebuild.reason')}
        value={reason} onChange={event => setReason(event.target.value)} style={{ width: 240, maxWidth: '100%' }} />
      <Button type="primary" loading={loading} onClick={() => void trigger()}>{t('memories.rebuild.trigger')}</Button>
    </Space>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12, overflowWrap: 'anywhere' }} />}
    {!error && failures.length > 0 && <Alert type="warning" showIcon style={{ marginBottom: 12, overflowWrap: 'anywhere' }}
      message={t('memories.rebuild.notComplete')} description={failures.join('; ')} />}
    <Spin spinning={loading}>
      {result && <section data-testid="memory-rebuild-result">
        <Typography.Title level={5}>{t('memories.rebuild.result')}</Typography.Title>
        <Descriptions size="small" column={{ xs: 1, sm: 2 }} styles={{ content: { overflowWrap: 'anywhere', minWidth: 0 } }} items={[
          { key: 'request', label: t('memories.rebuild.requestId'), children: result.request_id },
          { key: 'scope', label: t('memories.filter.domain'), children: String(result.scope_id) },
        ]} />
        <Typography.Title level={5}>{t('memories.rebuild.report')}</Typography.Title>
        <List size="small" dataSource={projectionRows} renderItem={item => <List.Item key={item.name} style={{ padding: '6px 0' }}>
          <Space wrap size={[8, 4]}>
            <Tag>{item.name}</Tag>
            <Typography.Text>{t('memories.confirm.count')}: {item.count ?? t('memories.rebuild.notReported')}</Typography.Text>
            <Typography.Text>{t('memories.rebuild.matchesReplay')}: {item.matchesReplay === undefined ? t('memories.rebuild.notReported') : String(item.matchesReplay)}</Typography.Text>
          </Space>
        </List.Item>} />
        {reportRows.length > 0 && <Descriptions size="small" column={1} style={{ marginTop: 8 }}
          styles={{ content: { overflowWrap: 'anywhere' } }}
          items={reportRows.map(([key, value]) => ({
            key, label: key,
            children: typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value),
          }))} />}
        <Space wrap size={[8, 8]} style={{ marginTop: 12 }}>
          <Button loading={auditLoading} onClick={() => void loadAudit()}>{t('memories.rebuild.audit')}</Button>
        </Space>
      </section>}
    </Spin>
    {auditError && <Alert type="error" showIcon message={auditError} style={{ marginTop: 12, overflowWrap: 'anywhere' }} />}
    {audit && <section data-testid="memory-rebuild-audit" style={{ marginTop: 12 }}>
      <Typography.Title level={5}>{t('memories.rebuild.auditTitle')}</Typography.Title>
      <Descriptions size="small" column={{ xs: 1, sm: 2 }} styles={{ content: { overflowWrap: 'anywhere', minWidth: 0 } }} items={[
        { key: 'request', label: t('memories.rebuild.requestId'), children: audit.request_id },
        { key: 'operation', label: t('common.actions'), children: audit.operation },
        { key: 'actor', label: t('memories.promotion.retained'), children: audit.actor },
        { key: 'scope', label: t('memories.filter.domain'), children: String(audit.scope_id) },
        { key: 'reason', label: t('memories.rebuild.reason'), children: audit.reason },
        { key: 'source', label: t('memories.confirm.eventId'), children: audit.source_event_id === null ? '-' : String(audit.source_event_id) },
        { key: 'created', label: t('memories.stats.generatedAt'), children: audit.created_at },
        { key: 'result', label: t('memories.confirm.result'), span: 2, children: JSON.stringify(audit.result) },
      ]} />
    </section>}
  </section>;
}
