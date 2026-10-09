/**
 * 015 T045 (US6/FR-039; research R10/R11) — rollback.
 *
 * Target selection (time point / event point) -> impact preview -> strong
 * confirmation -> result plus audit pointer.  Reachable only on the management
 * surface: the MCP surface exposes no rollback entry or capability.  One target
 * per action: no batch and no multi-target rollback.
 *
 * The preview counts the entries the domain currently publishes (the stats
 * endpoint, body-free) and names the projections a rollback must re-derive;
 * per-projection counts are only measured by the rollback response itself, so
 * they are shown as unknown before execution and never invented.
 */
import { Alert, Button, Descriptions, Empty, Input, Radio, Space, Tag, Typography } from 'antd';
import { useState } from 'react';
import { fetchMemoryStats, rollbackMemories } from '../../api/memories';
import { useLocale } from '../../i18n';
import ConfirmActionModal, { wireNumericId, type ConfirmActionOutcome, type ConfirmImpact } from './ConfirmActionModal';

interface Props { scope?: string }

const PROJECTIONS = ['relation', 'dense', 'links', 'summary', 'file', 'salience'];

export default function MemoryRollbackView({ scope }: Props) {
  const { t } = useLocale();
  const [targetKind, setTargetKind] = useState<'event_point' | 'time_point'>('event_point');
  const [eventPoint, setEventPoint] = useState('');
  const [timePoint, setTimePoint] = useState('');
  const [reason, setReason] = useState('');
  const [impact, setImpact] = useState<ConfirmImpact | null>(null);
  const [target, setTarget] = useState('');
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string>();
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [outcome, setOutcome] = useState<ConfirmActionOutcome>();

  if (!scope) return <section data-testid="memory-view-rollback"><Empty description={t('memories.noScope')} /></section>;

  const preview = async () => {
    const value = (targetKind === 'event_point' ? eventPoint : timePoint).trim();
    setError(undefined);
    setImpact(null);
    if (value === '' || (targetKind === 'event_point' ? !/^\d+$/.test(value) : Number.isNaN(Date.parse(value)))) {
      setError(t('memories.rollback.invalidTarget'));
      return;
    }
    setPreviewing(true);
    try {
      const stats = await fetchMemoryStats(scope);
      setImpact({
        affected: stats.total,
        projections: Object.fromEntries(PROJECTIONS.map(name => [name, null])),
        note: t('memories.rollback.singleTarget'),
      });
      setTarget(value);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPreviewing(false);
    }
  };

  const submit = async () => {
    setSubmitting(true);
    try {
      const base = { scope_id: wireNumericId(scope), reason: reason.trim() };
      const result = targetKind === 'event_point'
        ? await rollbackMemories({ ...base, event_point: wireNumericId(target) })
        : await rollbackMemories({ ...base, time_point: target });
      setOutcome({ ok: true, message: t('memories.confirm.succeeded'), detail: result });
    } catch (cause: unknown) {
      setOutcome({
        ok: false,
        message: `${t('memories.confirm.failed')}${cause instanceof Error ? cause.message : String(cause)}`,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return <section data-testid="memory-view-rollback" style={{ minWidth: 0 }}>
    <Typography.Title level={4} style={{ marginTop: 0 }}>{t('memories.rollback.title')}</Typography.Title>
    <Alert type="info" showIcon message={t('memories.rollback.managementOnly')} style={{ marginBottom: 12, overflowWrap: 'anywhere' }} />
    <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>{t('memories.rollback.singleTarget')}</Typography.Paragraph>
    <Space wrap size={[8, 8]} style={{ marginBottom: 12 }}>
      <Radio.Group aria-label={t('memories.rollback.targetKind')} value={targetKind}
        onChange={event => { setTargetKind(event.target.value as 'event_point' | 'time_point'); setImpact(null); setTarget(''); }}
        options={[
          { value: 'event_point', label: t('memories.rollback.eventPoint') },
          { value: 'time_point', label: t('memories.rollback.timePoint') },
        ]} />
      {targetKind === 'event_point'
        ? <Input aria-label={t('memories.rollback.eventPointValue')} placeholder={t('memories.rollback.eventPointValue')}
          value={eventPoint} onChange={event => { setEventPoint(event.target.value); setImpact(null); }} style={{ width: 200, maxWidth: '100%' }} />
        : <Input aria-label={t('memories.rollback.timePointValue')} placeholder={t('memories.rollback.timePointValue')}
          value={timePoint} onChange={event => { setTimePoint(event.target.value); setImpact(null); }} style={{ width: 240, maxWidth: '100%' }} />}
      <Input aria-label={t('memories.rollback.reason')} placeholder={t('memories.rollback.reason')}
        value={reason} onChange={event => setReason(event.target.value)} style={{ width: 240, maxWidth: '100%' }} />
      <Button loading={previewing} onClick={() => void preview()}>{t('memories.rollback.preview')}</Button>
      <Button danger disabled={!impact || !target || reason.trim() === ''}
        onClick={() => { setOutcome(undefined); setOpen(true); }}>{t('memories.rollback.execute')}</Button>
    </Space>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12, overflowWrap: 'anywhere' }} />}
    {impact && <section data-testid="memory-rollback-impact">
      <Descriptions size="small" column={1} items={[
        { key: 'affected', label: t('memories.confirm.affectedEntries'), children: impact.affected ?? t('memories.confirm.unknown') },
        { key: 'target', label: t('memories.rollback.eventPoint'), children: target },
      ]} />
      <Space wrap size={[8, 8]}>
        <Typography.Text type="secondary">{t('memories.confirm.affectedProjections')}</Typography.Text>
        {Object.entries(impact.projections).map(([name, count]) => <Tag key={name}>{name}: {count ?? t('memories.confirm.unknown')}</Tag>)}
      </Space>
      {impact.note && <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, overflowWrap: 'anywhere' }}>{impact.note}</Typography.Paragraph>}
    </section>}
    {outcome && <Alert style={{ marginTop: 12, overflowWrap: 'anywhere' }} type={outcome.ok ? 'success' : 'error'} showIcon message={outcome.message} />}
    <ConfirmActionModal
      open={open}
      title={t('memories.rollback.execute')}
      scopeRef={scope}
      target={target}
      impact={impact}
      submitting={submitting}
      outcome={outcome}
      onSubmit={() => void submit()}
      onClose={() => { setOpen(false); setOutcome(undefined); }}
    />
  </section>;
}
