/**
 * 015 T043 (US6/FR-036, FR-038; research R10) — browse view.
 *
 * Six-dimensional narrowing (domain / kind / status / provenance / session /
 * salience) with server-side pagination (20 per page), the existing `List`
 * presentation and the 300-character excerpt.
 *
 * Filtering can only narrow: every request carries the current `scope_ref`, and
 * the domain control is a locked value — there is no "clear the domain to browse
 * across domains" path.  Superseded entries are never deleted from history: the
 * correction chain is derived from the loaded rows and navigable, and the
 * history itself is reachable through a narrowing `status=superseded` query that
 * still carries `scope_ref`.
 */
import { Alert, Button, Descriptions, Empty, Input, List, Pagination, Select, Space, Spin, Tag, Tooltip, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { fetchMemoryPage, type MemorySummary } from '../../api/memories';
import { useLocale } from '../../i18n';

interface Props { scope?: string; refreshToken: number }

/**
 * `public_entry` also publishes `superseded_by`/`session_id`; the shared client
 * type predates this view and lives outside this task's write scope, so the
 * chain reads them through a narrow structural extension rather than `any`.
 */
type ChainRow = MemorySummary & { superseded_by?: string | number | null; session_id?: string | null };

const PAGE_SIZE = 20;
const EXCERPT_LIMIT = 300;

const KIND_OPTIONS = ['episodic', 'semantic', 'procedural'].map(value => ({ value, label: value }));
const STATUS_OPTIONS = ['active', 'superseded', 'retired', 'quarantined'].map(value => ({ value, label: value }));
const PROVENANCE_OPTIONS = ['hard', 'soft', 'distilled'].map(value => ({ value, label: value }));
const SALIENCE_OPTIONS = [0, 0.25, 0.5, 0.75, 0.9].map(value => ({ value, label: String(value) }));

function excerpt(value?: string): string {
  const text = value ?? '';
  return text.length > EXCERPT_LIMIT ? text.slice(0, EXCERPT_LIMIT) : text;
}

function chainOf(id: string, rows: ChainRow[]): { predecessors: string[]; successors: string[] } {
  const byId = new Map(rows.map(item => [item.memory_id, item]));
  const seen = new Set<string>([id]);
  const successors: string[] = [];
  let cursor = byId.get(id);
  while (cursor?.superseded_by !== undefined && cursor.superseded_by !== null) {
    const next = String(cursor.superseded_by);
    if (seen.has(next)) break;
    seen.add(next);
    successors.push(next);
    cursor = byId.get(next);
  }
  const predecessors: string[] = [];
  let previous = id;
  for (;;) {
    const predecessor = rows.find(item => item.superseded_by !== undefined && item.superseded_by !== null
      && String(item.superseded_by) === previous);
    if (!predecessor || seen.has(predecessor.memory_id)) break;
    seen.add(predecessor.memory_id);
    predecessors.unshift(predecessor.memory_id);
    previous = predecessor.memory_id;
  }
  return { predecessors, successors };
}

export default function MemoryBrowseView({ scope, refreshToken }: Props) {
  const { t } = useLocale();
  const [items, setItems] = useState<ChainRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [kind, setKind] = useState<string>();
  const [status, setStatus] = useState<string>();
  const [provenance, setProvenance] = useState<string>();
  const [session, setSession] = useState('');
  const [minSalience, setMinSalience] = useState<number>();
  const [selected, setSelected] = useState<string>();
  const generation = useRef(0);

  useEffect(() => { setPage(1); }, [scope]);

  useEffect(() => {
    if (!scope) { setItems([]); setTotal(0); setError(undefined); setLoading(false); return; }
    let active = true;
    const revision = ++generation.current;
    setLoading(true);
    setError(undefined);
    fetchMemoryPage(scope, (page - 1) * PAGE_SIZE, PAGE_SIZE, {
      kind, status, provenance,
      session_id: session.trim() === '' ? undefined : session.trim(),
      min_salience: minSalience,
    }).then(response => {
      if (!active || revision !== generation.current) return;
      setItems(response.memories);
      setTotal(response.total);
    }).catch((cause: unknown) => {
      if (!active || revision !== generation.current) return;
      setItems([]);
      setTotal(0);
      setError(`${t('memories.browse.loadFailed')}${cause instanceof Error ? cause.message : String(cause)}`);
    }).finally(() => {
      if (active && revision === generation.current) setLoading(false);
    });
    return () => { active = false; };
  }, [scope, page, kind, status, provenance, session, minSalience, refreshToken, t]);

  if (!scope) return <section data-testid="memory-view-browse"><Empty description={t('memories.noScope')} /></section>;

  const reset = () => {
    setKind(undefined); setStatus(undefined); setProvenance(undefined);
    setSession(''); setMinSalience(undefined); setPage(1);
  };
  const narrowed = kind !== undefined || status !== undefined || provenance !== undefined
    || session.trim() !== '' || minSalience !== undefined;

  return <section data-testid="memory-view-browse" style={{ minWidth: 0 }}>
    <Space wrap size={[8, 8]} style={{ marginBottom: 12 }}>
      <Select aria-label={t('memories.filter.domain')} value={scope} disabled style={{ width: 190, maxWidth: '100%' }}
        options={[{ value: scope, label: scope }]} />
      <Select aria-label={t('memories.filter.kind')} allowClear placeholder={t('memories.filter.kind')}
        value={kind} onChange={value => { setKind(value); setPage(1); }} style={{ width: 140, maxWidth: '100%' }}
        options={KIND_OPTIONS} />
      <Select aria-label={t('memories.filter.status')} allowClear placeholder={t('memories.filter.status')}
        value={status} onChange={value => { setStatus(value); setPage(1); }} style={{ width: 140, maxWidth: '100%' }}
        options={STATUS_OPTIONS} />
      <Select aria-label={t('memories.filter.provenance')} allowClear placeholder={t('memories.filter.provenance')}
        value={provenance} onChange={value => { setProvenance(value); setPage(1); }} style={{ width: 140, maxWidth: '100%' }}
        options={PROVENANCE_OPTIONS} />
      <Input aria-label={t('memories.filter.session')} placeholder={t('memories.filter.session')} allowClear
        value={session} onChange={event => { setSession(event.target.value); setPage(1); }} style={{ width: 160, maxWidth: '100%' }} />
      <Select aria-label={t('memories.filter.salience')} allowClear placeholder={t('memories.filter.salience')}
        value={minSalience} onChange={value => { setMinSalience(value); setPage(1); }} style={{ width: 160, maxWidth: '100%' }}
        options={SALIENCE_OPTIONS} />
      <Button onClick={reset}>{t('memories.filter.reset')}</Button>
      <Tooltip title={t('memories.chain.history')}>
        <Button onClick={() => { setStatus('superseded'); setPage(1); }}>{t('memories.filter.showHistory')}</Button>
      </Tooltip>
    </Space>
    <Typography.Paragraph type="secondary" style={{ marginBottom: 12, overflowWrap: 'anywhere' }}>
      {t('memories.filter.domainLocked')}
    </Typography.Paragraph>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16, overflowWrap: 'anywhere' }} />}
    <Spin spinning={loading}>
      {!items.length && !error && !loading ?
        <Empty description={narrowed ? t('memories.browse.empty') : t('memories.empty')} /> :
        <List dataSource={items} renderItem={item => {
          const chain = chainOf(item.memory_id, items);
          return <List.Item key={item.memory_id} style={{ display: 'block', padding: '20px 0' }}>
            <Space wrap size={[8, 8]} style={{ marginBottom: 8 }}>
              <Typography.Text strong style={{ overflowWrap: 'anywhere' }}>{item.title || item.memory_id}</Typography.Text>
              <Tag>{item.kind}</Tag>
              <Tag color={item.provenance === 'hard' ? 'green' : 'cyan'}>{item.provenance}</Tag>
              <Tag color={item.status === 'quarantined' ? 'red' : item.status === 'active' ? 'green' : 'default'}>{item.status}</Tag>
            </Space>
            <Typography.Paragraph style={{ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
              {excerpt(item.content_excerpt)}
            </Typography.Paragraph>
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}
              styles={{ content: { overflowWrap: 'anywhere', minWidth: 0 } }} items={[
                { key: 'id', label: t('memories.id'), children: item.memory_id },
                { key: 'scope', label: t('memories.scope'), children: item.knowledge_scope_id },
                { key: 'projection', label: t('memories.projection'), children: <Tag color={item.projection_status === 'complete' ? 'green' : 'red'}>{item.projection_status || 'unknown'}</Tag> },
                { key: 'from', label: t('memories.validFrom'), children: item.valid_from || '-' },
                { key: 'to', label: t('memories.validTo'), children: item.valid_to || '-' },
                { key: 'injection', label: t('memories.injection'), children: String(item.injection_flags?.risk_level || 'none') },
                { key: 'evidence', label: t('memories.evidence'), span: 3, children: item.evidence_refs?.length ? item.evidence_refs.map(String).join(', ') : '-' },
              ]} />
            <Space wrap size={[8, 8]} style={{ marginTop: 8 }}>
              <Button size="small" aria-label={`${t('memories.chain.select')} ${item.memory_id}`}
                onClick={() => setSelected(selected === item.memory_id ? undefined : item.memory_id)}>
                {t('memories.chain.select')}
              </Button>
            </Space>
            {selected === item.memory_id && <section style={{ marginTop: 12, padding: 12, background: '#fafafa', minWidth: 0 }}>
              <Typography.Text strong>{t('memories.chain.title')}</Typography.Text>
              <Space wrap size={[8, 8]} style={{ marginTop: 8 }}>
                <Typography.Text type="secondary">{t('memories.chain.predecessor')}</Typography.Text>
                {chain.predecessors.length === 0 ? <Typography.Text type="secondary">-</Typography.Text> :
                  chain.predecessors.map(id => <ChainNode key={id} id={id} rows={items} label={t('memories.chain.outsidePage')} onSelect={setSelected} />)}
                <Typography.Text type="secondary">{t('memories.chain.current')}</Typography.Text>
                <Tag color="blue"><span data-testid="memory-chain-current">{item.memory_id}</span></Tag>
                <Typography.Text type="secondary">{t('memories.chain.successor')}</Typography.Text>
                {chain.successors.length === 0 ? <Typography.Text type="secondary">-</Typography.Text> :
                  chain.successors.map(id => <ChainNode key={id} id={id} rows={items} label={t('memories.chain.outsidePage')} onSelect={setSelected} />)}
              </Space>
              {chain.predecessors.length === 0 && chain.successors.length === 0 &&
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>{t('memories.chain.none')}</Typography.Paragraph>}
              <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0', overflowWrap: 'anywhere' }}>
                {t('memories.chain.history')}
              </Typography.Paragraph>
            </section>}
          </List.Item>;
        }} />}
    </Spin>
    {scope && total > PAGE_SIZE && <Pagination current={page} total={total} pageSize={PAGE_SIZE} showSizeChanger={false}
      onChange={setPage} style={{ marginTop: 16 }} />}
  </section>;
}

function ChainNode({ id, rows, label, onSelect }: { id: string; rows: ChainRow[]; label: string; onSelect: (id: string) => void }) {
  const loaded = rows.some(item => item.memory_id === id);
  return <Space size={4}>
    <Button size="small" aria-label={`Chain entry ${id}`} disabled={!loaded}
      onClick={() => onSelect(id)}>{id}</Button>
    {!loaded && <Tag>{label}</Tag>}
  </Space>;
}
