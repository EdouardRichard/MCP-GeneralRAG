import { Alert, Empty, List, Space, Spin, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { fetchMemories, type MemorySummary } from '../api/memories';

export default function MemoriesPage() {
  const [items, setItems] = useState<MemorySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  useEffect(() => {
    fetchMemories().then(setItems).catch((e) => setError(e instanceof Error ? e.message : 'Unable to load memories')).finally(() => setLoading(false));
  }, []);
  if (loading) return <Spin />;
  if (error) return <Alert type="error" message={error} />;
  if (!items.length) return <Empty description="No memories" />;
  return <List dataSource={items} renderItem={(item) => (
    <List.Item>
      <Space direction="vertical" size={4}>
        <Space><Typography.Text strong>#{item.memory_id}</Typography.Text><Tag>{item.kind}</Tag><Tag>{item.provenance}</Tag><Tag>{item.status}</Tag></Space>
        <Typography.Paragraph ellipsis={{ rows: 2 }}>{item.content_excerpt}</Typography.Paragraph>
        <Typography.Text type="secondary">Scope {item.knowledge_scope_id} · Projection {item.projection_status ?? 'unknown'}</Typography.Text>
      </Space>
    </List.Item>
  )} />;
}
