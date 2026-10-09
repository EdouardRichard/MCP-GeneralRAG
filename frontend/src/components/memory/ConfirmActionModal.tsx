/**
 * 015 T042 (US6/FR-037, FR-039; research R11, governance-ui-contract §3) —
 * strong confirmation.
 *
 * The submit button stays disabled until the operator types the exact
 * confirmation value.  That value always carries an **explicit domain
 * reference** plus the target identity (`<scope_ref>::<memory_id>` for
 * retire/purge, `<scope_ref>::<event_point|time_point>` for rollback), so the
 * server never has to infer the domain from a memory id alone.  A single-click
 * confirmation (`Popconfirm`, `Modal.confirm`) is deliberately not used.
 *
 * The dialog also renders the impact preview (affected entry count plus the
 * affected projections) and, after submit, the result with its audit pointer
 * (authority `event_id` + `request_id`).
 */
import { Alert, Button, Descriptions, Input, List, Modal, Space, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { useLocale } from '../../i18n';

export interface ConfirmImpact {
  /** Affected entry count; `null` = the REST surface cannot preview it. */
  affected: number | null;
  /** Affected projections with per-projection counts; `null` = not previewable. */
  projections: Record<string, number | null>;
  note?: string;
}

export interface ConfirmActionOutcome {
  ok: boolean;
  message: string;
  /** The raw governance response; the audit pointer is read from it. */
  detail?: unknown;
}

export interface ConfirmActionModalProps {
  open: boolean;
  title: string;
  /** Explicit domain reference — always part of the confirmation value. */
  scopeRef: string;
  /** Target identity: a memory id (retire/purge) or an event/time point. */
  target: string;
  impact?: ConfirmImpact | null;
  submitting?: boolean;
  outcome?: ConfirmActionOutcome;
  onSubmit: () => void;
  onClose: () => void;
}

/** The one and only way a confirmation value is composed for this feature. */
export function confirmationValue(scopeRef: string, target: string): string {
  return `${scopeRef}::${target}`;
}

/**
 * The delivered REST clients type `scope_id`/`memory_id` as `number`, but the
 * authority ids are 64-bit values that the API serializes as decimal strings.
 * `Number()` would silently round anything above 2^53 (365392222222222229 ->
 * 365392222222222208), so the exact decimal string is what goes on the wire:
 * the backend declares `int`, which parses a decimal string exactly.
 */
export function wireNumericId(id: string): number {
  const trimmed = id.trim();
  return (/^\d+$/.test(trimmed) ? trimmed : Number(trimmed)) as unknown as number;
}

function auditPointer(detail: unknown): { eventId?: string; requestId?: string } {
  if (typeof detail !== 'object' || detail === null) return {};
  const record = detail as Record<string, unknown>;
  const pick = (key: string): string | undefined => {
    const value = record[key];
    return value === undefined || value === null ? undefined : String(value);
  };
  return { eventId: pick('event_id'), requestId: pick('request_id') };
}

export default function ConfirmActionModal({
  open, title, scopeRef, target, impact, submitting, outcome, onSubmit, onClose,
}: ConfirmActionModalProps) {
  const { t } = useLocale();
  const [typed, setTyped] = useState('');
  const required = confirmationValue(scopeRef, target);
  const matches = typed === required;
  const projections = Object.entries(impact?.projections ?? {});
  const pointer = auditPointer(outcome?.detail);

  useEffect(() => { if (open) setTyped(''); }, [open]);

  return <Modal
    open={open}
    title={title}
    onCancel={onClose}
    footer={[
      <Button key="cancel" onClick={onClose}>{t('memories.confirm.cancel')}</Button>,
      <Button key="submit" type="primary" danger disabled={!matches || Boolean(submitting)}
        loading={submitting} onClick={onSubmit}>{t('memories.confirm.submit')}</Button>,
    ]}
  >
    <Space direction="vertical" size={12} style={{ width: '100%', minWidth: 0 }}>
      <Typography.Paragraph style={{ marginBottom: 0, overflowWrap: 'anywhere' }}>
        {t('memories.confirm.instruction')}
      </Typography.Paragraph>
      <Typography.Paragraph style={{ marginBottom: 0, overflowWrap: 'anywhere' }}>
        <Typography.Text type="secondary">{t('memories.confirm.valueLabel')}</Typography.Text>
        <br />
        <Typography.Text code data-testid="memory-confirm-required">{required}</Typography.Text>
      </Typography.Paragraph>
      <Input aria-label={t('memories.confirm.input')} placeholder={t('memories.confirm.input')}
        value={typed} onChange={event => setTyped(event.target.value)} />
      {typed.length > 0 && !matches &&
        <Alert type="warning" showIcon message={t('memories.confirm.mismatch')} />}
      <Typography.Text type="secondary">{t('memories.confirm.singleClick')}</Typography.Text>
      <section style={{ minWidth: 0 }}>
        <Typography.Text strong>{t('memories.confirm.impact')}</Typography.Text>
        <Descriptions size="small" column={1} items={[{
          key: 'affected', label: t('memories.confirm.affectedEntries'),
          children: impact?.affected ?? t('memories.confirm.unknown'),
        }]} />
        {projections.length > 0 && <List size="small" dataSource={projections}
          renderItem={([name, count]) => <List.Item key={name} style={{ padding: '4px 0' }}>
            <Space wrap size={[8, 4]}><Tag>{name}</Tag>
              <Typography.Text>{count ?? t('memories.confirm.unknown')}</Typography.Text></Space>
          </List.Item>} />}
        {impact?.note && <Typography.Paragraph type="secondary" style={{ marginBottom: 0, overflowWrap: 'anywhere' }}>
          {impact.note}
        </Typography.Paragraph>}
        {!impact && <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('memories.confirm.noImpact')}
        </Typography.Paragraph>}
      </section>
      {outcome && <section style={{ minWidth: 0 }}>
        <Alert type={outcome.ok ? 'success' : 'error'} showIcon message={outcome.message} style={{ overflowWrap: 'anywhere' }} />
        {(pointer.eventId || pointer.requestId) && <Descriptions size="small" column={1} style={{ marginTop: 8 }}
          styles={{ content: { overflowWrap: 'anywhere' } }} items={[
            { key: 'pointer', label: t('memories.confirm.auditPointer'), children: ' ' },
            { key: 'event', label: t('memories.confirm.eventId'), children: pointer.eventId ?? '-' },
            { key: 'request', label: t('memories.confirm.requestId'), children: pointer.requestId ?? '-' },
          ]} />}
      </section>}
    </Space>
  </Modal>;
}
