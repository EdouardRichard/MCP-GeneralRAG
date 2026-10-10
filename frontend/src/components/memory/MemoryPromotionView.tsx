/**
 * 015 T047 (US6/FR-041; research R10) — promotion candidates.
 *
 * Candidate queue browsing plus an explicit **manual** promote action.  The view
 * shows the candidate basis, the promotion destination and the relationship to
 * the retained original memory.  There is no automatic (machine-triggered)
 * promotion entry: nothing is promoted until a human supplies a reason and
 * clicks the button, and no switch/auto control exists on this surface.
 *
 * T083: the promotion response exposes the authority `event_id` next to
 * `request_id`, and the pointer is dereferenced through the management audit read
 * path, so the displayed event is the stored authority row rather than a client
 * echo.
 */
import { Alert, Button, Descriptions, Empty, Input, List, Space, Spin, Tag, Typography } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchMemoryAudit, fetchPromotionCandidates, promoteCandidate, type MemoryAuditRecord, type PromotionCandidate, type PromotionTask } from '../../api/memories';
import { useLocale } from '../../i18n';
import { wireNumericId } from './ConfirmActionModal';

interface Props { scope?: string; refreshToken: number }

/** The resolved authority event, rendered from the stored row only. */
export function auditResolution(record: MemoryAuditRecord): string {
  return `${record.event_type} · ${record.knowledge_scope_id} · ${record.occurred_at}`;
}

export default function MemoryPromotionView({ scope, refreshToken }: Props) {
  const { t } = useLocale();
  const [items, setItems] = useState<PromotionCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [reason, setReason] = useState('');
  const [actionError, setActionError] = useState<string>();
  const [task, setTask] = useState<PromotionTask | null>(null);
  const [audit, setAudit] = useState<MemoryAuditRecord | null>(null);
  const [auditError, setAuditError] = useState<string>();
  const [submitting, setSubmitting] = useState<string>();
  const generation = useRef(0);

  const load = useCallback(async () => {
    if (!scope) return;
    const revision = ++generation.current;
    setLoading(true);
    setError(undefined);
    try {
      const page = await fetchPromotionCandidates(scope);
      if (revision === generation.current) { setItems(page.items); setTotal(page.total); }
    } catch (cause: unknown) {
      if (revision === generation.current) setError(`${t('memories.promotion.loadFailed')}${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      if (revision === generation.current) setLoading(false);
    }
  }, [scope, t]);

  useEffect(() => { void load(); return () => { generation.current++; }; }, [load, refreshToken]);

  if (!scope) return <section data-testid="memory-view-promotion"><Empty description={t('memories.noScope')} /></section>;

  const resolve = async (requestId: string) => {
    setAudit(null);
    setAuditError(undefined);
    try {
      setAudit(await fetchMemoryAudit(requestId, wireNumericId(scope)));
    } catch (cause: unknown) {
      setAuditError(`${t('memories.audit.unavailable')}${cause instanceof Error ? cause.message : String(cause)}`);
    }
  };

  const promote = async (candidate: PromotionCandidate) => {
    if (reason.trim() === '') { setActionError(t('memories.promotion.reasonRequired')); return; }
    setActionError(undefined);
    setAudit(null);
    setAuditError(undefined);
    setSubmitting(candidate.memory_id);
    try {
      const result = await promoteCandidate({
        scope_id: wireNumericId(scope),
        memory_id: wireNumericId(candidate.memory_id),
        candidate_version: candidate.candidate_version ?? '',
        reason: reason.trim(),
      });
      setTask(result);
      await resolve(result.request_id);
      await load();
    } catch (cause: unknown) {
      setTask(null);
      setActionError(`${t('memories.promotion.promoteFailed')}${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      setSubmitting(undefined);
    }
  };

  return <section data-testid="memory-view-promotion" style={{ minWidth: 0 }}>
    <Typography.Title level={4} style={{ marginTop: 0 }}>{t('memories.promotion.title')}</Typography.Title>
    <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>{t('memories.promotion.intro')}</Typography.Paragraph>
    <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>{t('memories.promotion.destination')}: {t('memories.promotion.destinationValue')}</Typography.Paragraph>
    <Space wrap size={[8, 8]} style={{ marginBottom: 12 }}>
      <Input aria-label={t('memories.promotion.reason')} placeholder={t('memories.promotion.reason')}
        value={reason} onChange={event => setReason(event.target.value)} style={{ width: 280, maxWidth: '100%' }} />
    </Space>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12, overflowWrap: 'anywhere' }} />}
    {actionError && <Alert type="error" showIcon message={actionError} style={{ marginBottom: 12, overflowWrap: 'anywhere' }} />}
    <Spin spinning={loading}>
      {!items.length && !error && !loading ? <Empty description={t('memories.browse.empty')} /> :
        <List dataSource={items} renderItem={candidate => <List.Item key={candidate.memory_id} style={{ display: 'block', padding: '16px 0' }}>
          <Space wrap size={[8, 8]} style={{ marginBottom: 8 }}>
            <Typography.Text strong style={{ overflowWrap: 'anywhere' }}>{candidate.memory_id}</Typography.Text>
            <Tag color={candidate.promotable ? 'green' : 'default'}>{candidate.promotable ? t('memories.promotion.promotable') : t('memories.promotion.ineligible')}</Tag>
            {typeof candidate.confidence === 'number' && <Tag>{t('memories.promotion.confidence')}: {candidate.confidence}</Tag>}
          </Space>
          <Descriptions size="small" column={{ xs: 1, sm: 2 }} styles={{ content: { overflowWrap: 'anywhere', minWidth: 0 } }} items={[
            { key: 'basis', label: t('memories.promotion.basis'), children: `${t('memories.promotion.confidence')}: ${candidate.confidence ?? '-'}; observed: ${candidate.promote_candidate_at ?? '-'}; evidence: ${candidate.evidence_attributions?.length ?? 0}` },
            { key: 'version', label: t('memories.promotion.version'), children: candidate.candidate_version ?? '-' },
            { key: 'destination', label: t('memories.promotion.destination'), children: t('memories.promotion.destinationValue') },
            { key: 'retained', label: t('memories.promotion.retained'), children: `${candidate.memory_id} (${t('memories.promotion.task')}: ${String(candidate.promotion_pointer ?? '-')})` },
            { key: 'ineligible', label: t('memories.promotion.ineligible'), children: candidate.ineligibility_reasons?.length ? candidate.ineligibility_reasons.join(', ') : '-' },
          ]} />
          <Space wrap size={[8, 8]} style={{ marginTop: 8 }}>
            <Button type="primary" aria-label={`${t('memories.promotion.promote')} ${candidate.memory_id}`}
              disabled={!candidate.promotable || !candidate.candidate_version}
              loading={submitting === candidate.memory_id}
              onClick={() => void promote(candidate)}>{t('memories.promotion.promote')}</Button>
          </Space>
        </List.Item>} />}
    </Spin>
    {total > items.length && <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>{total}</Typography.Paragraph>}
    {task && <section data-testid="memory-promotion-task" style={{ marginTop: 12 }}>
      <Typography.Title level={5}>{t('memories.promotion.task')}</Typography.Title>
      <Descriptions size="small" column={{ xs: 1, sm: 2 }} styles={{ content: { overflowWrap: 'anywhere', minWidth: 0 } }} items={[
        { key: 'task', label: t('memories.promotion.task'), children: String(task.task_id) },
        { key: 'status', label: t('memories.promotion.status'), children: task.status },
        { key: 'source', label: t('memories.promotion.destination'), children: task.source_id },
        { key: 'retained', label: t('memories.promotion.retained'), children: task.memory_id },
      ]} />
      <section data-testid="memory-promotion-audit" style={{ marginTop: 8, minWidth: 0 }}>
        <Typography.Text strong>{t('memories.audit.pointer')}</Typography.Text>
        <Descriptions size="small" column={1} styles={{ content: { overflowWrap: 'anywhere' } }} items={[
          { key: 'event', label: t('memories.confirm.eventId'), children: String(task.event_id ?? '-') },
          { key: 'request', label: t('memories.confirm.requestId'), children: task.request_id },
          { key: 'resolved', label: t('memories.audit.resolved'), children: audit ? auditResolution(audit) : '-' },
        ]} />
        {auditError && <Alert type="warning" showIcon message={auditError} style={{ overflowWrap: 'anywhere' }} />}
      </section>
    </section>}
  </section>;
}
