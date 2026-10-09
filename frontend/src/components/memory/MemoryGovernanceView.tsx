/**
 * 015 T044 (US6/FR-037; research R10/R11) — retire and explicit purge.
 *
 * Purge is the only deletion path.  The order is fixed: impact preview ->
 * strong confirmation (`ConfirmActionModal`) -> result plus audit pointer
 * (authority `event_id` + `request_id`).  The first phase is single-entry only:
 * no `rowSelection`, no `Checkbox`, no batch API call.
 *
 * The impact preview is honest about what the REST surface exposes: the entry
 * count is the verified single target (or `null` when the target is not in the
 * first 100 rows of the domain), and the affected projections are listed with
 * per-projection counts that are only measured after execution — never invented.
 */
import { Alert, Button, Descriptions, Empty, Input, Space, Spin, Tag, Typography } from 'antd';
import { useState } from 'react';
import { fetchMemoryPage, purgeMemory, retireMemory } from '../../api/memories';
import { useLocale } from '../../i18n';
import ConfirmActionModal, { wireNumericId, type ConfirmActionOutcome, type ConfirmImpact } from './ConfirmActionModal';

interface Props { scope?: string }

/** The projections a governance command must propagate to (015 six-projection set). */
const PROJECTIONS = ['relation', 'dense', 'links', 'summary', 'file', 'salience'];

export default function MemoryGovernanceView({ scope }: Props) {
  const { t } = useLocale();
  const [memoryId, setMemoryId] = useState('');
  const [reason, setReason] = useState('');
  const [impact, setImpact] = useState<ConfirmImpact | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string>();
  const [action, setAction] = useState<'retire' | 'purge' | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [outcome, setOutcome] = useState<ConfirmActionOutcome>();

  if (!scope) return <section data-testid="memory-view-governance"><Empty description={t('memories.noScope')} /></section>;

  const target = memoryId.trim();
  const ready = target !== '' && reason.trim() !== '';

  const preview = async () => {
    setPreviewing(true);
    setPreviewError(undefined);
    setImpact(null);
    try {
      const page = await fetchMemoryPage(scope, 0, 100, {});
      const found = page.memories.some(item => item.memory_id === target);
      setImpact({
        affected: found ? 1 : null,
        projections: Object.fromEntries(PROJECTIONS.map(name => [name, null])),
        note: found ? t('memories.governance.singleEntry') : t('memories.governance.notInPage'),
      });
    } catch (cause: unknown) {
      setPreviewError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPreviewing(false);
    }
  };

  const submit = async () => {
    if (!action) return;
    const command = { scope_id: wireNumericId(scope), memory_id: wireNumericId(target), reason: reason.trim() };
    setSubmitting(true);
    try {
      const result = action === 'retire' ? await retireMemory(command) : await purgeMemory(command);
      setOutcome({ ok: true, message: t('memories.confirm.succeeded'), detail: result });
    } catch (cause: unknown) {
      setOutcome({
        ok: false,
        message: `${t('memories.confirm.failed')}${cause instanceof Error ? cause.message : String(cause)}`,
      });
    } finally {
      setSubmitting(false);
      // Correctness comes from REST: re-read the domain after every governance action.
      void preview();
    }
  };

  return <section data-testid="memory-view-governance" style={{ minWidth: 0 }}>
    <Typography.Title level={4} style={{ marginTop: 0 }}>{t('memories.governance.title')}</Typography.Title>
    <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>{t('memories.governance.intro')}</Typography.Paragraph>
    <Typography.Paragraph type="secondary" style={{ overflowWrap: 'anywhere' }}>{t('memories.governance.singleEntry')}</Typography.Paragraph>
    <Space wrap size={[8, 8]} style={{ marginBottom: 12 }}>
      <Input aria-label={t('memories.governance.memoryId')} placeholder={t('memories.governance.memoryId')}
        value={memoryId} onChange={event => { setMemoryId(event.target.value); setImpact(null); setOutcome(undefined); }}
        style={{ width: 240, maxWidth: '100%' }} />
      <Input aria-label={t('memories.governance.reason')} placeholder={t('memories.governance.reason')}
        value={reason} onChange={event => setReason(event.target.value)} style={{ width: 280, maxWidth: '100%' }} />
      <Button loading={previewing} disabled={!ready} onClick={() => void preview()}>{t('memories.governance.preview')}</Button>
      <Button danger disabled={!impact || !ready} onClick={() => { setOutcome(undefined); setAction('retire'); }}>{t('memories.governance.retire')}</Button>
      <Button danger disabled={!impact || !ready} onClick={() => { setOutcome(undefined); setAction('purge'); }}>{t('memories.governance.purge')}</Button>
    </Space>
    {previewError && <Alert type="error" showIcon message={previewError} style={{ marginBottom: 12, overflowWrap: 'anywhere' }} />}
    {!impact && !previewError && <Typography.Paragraph type="secondary">{t('memories.governance.previewFirst')}</Typography.Paragraph>}
    <Spin spinning={previewing}>
      {impact && <section data-testid="memory-governance-impact">
        <Descriptions size="small" column={1} items={[
          { key: 'affected', label: t('memories.confirm.affectedEntries'), children: impact.affected ?? t('memories.confirm.unknown') },
          { key: 'target', label: t('memories.governance.memoryId'), children: target },
        ]} />
        <Space wrap size={[8, 8]}>
          <Typography.Text type="secondary">{t('memories.confirm.affectedProjections')}</Typography.Text>
          {Object.entries(impact.projections).map(([name, count]) => <Tag key={name}>{name}: {count ?? t('memories.confirm.unknown')}</Tag>)}
        </Space>
        {impact.note && <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, overflowWrap: 'anywhere' }}>{impact.note}</Typography.Paragraph>}
      </section>}
      {outcome && <Alert style={{ marginTop: 12, overflowWrap: 'anywhere' }} type={outcome.ok ? 'success' : 'error'} showIcon message={outcome.message} />}
    </Spin>
    <ConfirmActionModal
      open={action !== null}
      title={action === 'purge' ? t('memories.governance.purge') : t('memories.governance.retire')}
      scopeRef={scope}
      target={target}
      impact={impact}
      submitting={submitting}
      outcome={outcome}
      onSubmit={() => void submit()}
      onClose={() => { setAction(null); setOutcome(undefined); }}
    />
  </section>;
}
