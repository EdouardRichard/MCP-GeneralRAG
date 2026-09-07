import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Descriptions,
  Table,
  Tag,
  Button,
  Upload,
  Space,
  message,
  Popconfirm,
  Spin,
  Typography,
} from 'antd';
import { InboxOutlined, ReloadOutlined, DeleteOutlined, ArrowLeftOutlined, ClearOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { KnowledgeSource } from '../types';
import { getProject } from '../api/projects';
import { listKnowledgeSources, uploadKnowledgeSource, reprocessSource, deleteSource, clearScope } from '../api/knowledgeSources';
import { useSSE } from '../hooks/useSSE';
import type { Project } from '../types';
import { useLocale } from '../i18n';

const { Dragger } = Upload;
const { Text } = Typography;

const STATUS_COLORS: Record<string, string> = {
  published: 'green',
  processing: 'blue',
  uploaded: 'orange',
  failed: 'red',
  deleted: 'default',
};

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useLocale();
  const [project, setProject] = useState<Project | null>(null);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  const fetchProject = useCallback(async () => {
    if (!id) return;
    try {
      const data = await getProject(id);
      setProject(data);
    } catch (err) {
      message.error(t('projectDetail.loadFailed') + (err as Error).message);
    }
  }, [id, t]);

  const fetchSources = useCallback(async () => {
    if (!project?.knowledge_scope_id) return;
    try {
      const data = await listKnowledgeSources(project.knowledge_scope_id);
      setSources(data);
    } catch (err) {
      message.error(t('projectDetail.loadSourcesFailed') + (err as Error).message);
    }
  }, [project?.knowledge_scope_id, t]);

  useEffect(() => {
    setLoading(true);
    fetchProject().finally(() => setLoading(false));
  }, [fetchProject]);

  useEffect(() => {
    if (project) fetchSources();
  }, [project, fetchSources]);

  // SSE for real-time status updates
  const topics = project ? [`scope:${project.knowledge_scope_id}`] : [];
  const { lastEvent, connected } = useSSE(topics);

  // React to SSE events by refreshing sources
  useEffect(() => {
    if (lastEvent) {
      fetchSources();
      if (lastEvent.event === 'error') {
        // SSE data.message is backend content — displayed verbatim (FR-029).
        message.error(lastEvent.data.message || t('projectDetail.processingError'));
      }
    }
  }, [lastEvent, fetchSources, t]);

  const handleUpload = async (file: File) => {
    if (!project) return false;
    setUploading(true);
    try {
      await uploadKnowledgeSource(project.knowledge_scope_id, file);
      // filename is domain data (verbatim); only the suffix is translated.
      message.success(`${file.name} ${t('projectDetail.uploadedSuccess')}`);
      fetchSources();
    } catch (err) {
      message.error(t('projectDetail.uploadFailed') + (err as Error).message);
    } finally {
      setUploading(false);
    }
    return false; // prevent default upload behavior
  };

  const handleReprocess = async (sourceId: string) => {
    try {
      await reprocessSource(sourceId);
      message.success(t('projectDetail.reprocessingStarted'));
      fetchSources();
    } catch (err) {
      message.error(t('projectDetail.reprocessFailed') + (err as Error).message);
    }
  };

  const handleDeleteSource = async (sourceId: string) => {
    try {
      await deleteSource(sourceId);
      message.success(t('projectDetail.sourceDeleted'));
      fetchSources();
    } catch (err) {
      message.error(t('projectDetail.deleteFailed') + (err as Error).message);
    }
  };

  const handleClearScope = async () => {
    if (!project) return;
    try {
      await clearScope(project.knowledge_scope_id);
      message.success(t('projectDetail.scopeCleared'));
      fetchSources();
    } catch (err) {
      message.error(t('projectDetail.clearScopeFailed') + (err as Error).message);
    }
  };

  const columns: ColumnsType<KnowledgeSource> = [
    {
      title: t('projectDetail.filename'),
      dataIndex: 'filename',
      key: 'filename',
    },
    {
      title: t('projectDetail.format'),
      dataIndex: 'format',
      key: 'format',
      width: 100,
    },
    {
      title: t('projectDetail.size'),
      dataIndex: 'size_bytes',
      key: 'size_bytes',
      width: 120,
      render: (bytes: number) => `${(bytes / 1024).toFixed(1)} KB`,
    },
    {
      title: t('projectDetail.status'),
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => (
        // status is domain data (backend status code) — verbatim (FR-029).
        <Tag color={STATUS_COLORS[status] || 'default'}>{status.toUpperCase()}</Tag>
      ),
    },
    {
      title: t('projectDetail.error'),
      dataIndex: 'processing_error',
      key: 'processing_error',
      ellipsis: true,
      render: (err: string | undefined) =>
        err ? <Text type="danger">{err}</Text> : '-',
    },
    {
      title: t('common.updated'),
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (val: string) => new Date(val).toLocaleString(),
    },
    {
      title: t('common.actions'),
      key: 'actions',
      width: 160,
      render: (_: unknown, record: KnowledgeSource) => (
        <Space>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            disabled={record.status === 'processing'}
            onClick={() => handleReprocess(record.source_id)}
          >
            {t('projectDetail.reprocess')}
          </Button>
          <Popconfirm
            title={t('projectDetail.deleteSourceTitle')}
            description={t('projectDetail.deleteSourceDesc')}
            onConfirm={() => handleDeleteSource(record.source_id)}
            okText={t('common.yes')}
            cancelText={t('common.no')}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              {t('common.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!project) {
    return <div>{t('projectDetail.notFound')}</div>;
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
        {t('projectDetail.backToProjects')}
      </Button>

      <Card title={t('projectDetail.projectDetails')}>
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label={t('projectDetail.projectId')}>{project.project_id}</Descriptions.Item>
          <Descriptions.Item label={t('common.name')}>{project.name}</Descriptions.Item>
          <Descriptions.Item label={t('common.alias')}>{project.alias || '-'}</Descriptions.Item>
          <Descriptions.Item label={t('projects.repoPathLabel')}>{project.repo_path || '-'}</Descriptions.Item>
          <Descriptions.Item label={t('projectDetail.knowledgeScopeId')}>
            {project.knowledge_scope_id}
          </Descriptions.Item>
          <Descriptions.Item label={t('projectDetail.scopeType')}>{project.scope_type || 'project'}</Descriptions.Item>
          <Descriptions.Item label={t('common.domainKey')}>{project.domain_key || 'se-project'}</Descriptions.Item>
          <Descriptions.Item label={t('common.slug')}>{project.slug || '-'}</Descriptions.Item>
          <Descriptions.Item label={t('common.created')}>
            {new Date(project.created_at).toLocaleString()}
          </Descriptions.Item>
          <Descriptions.Item label={t('common.updated')}>
            {new Date(project.updated_at).toLocaleString()}
          </Descriptions.Item>
          <Descriptions.Item label={t('projectDetail.sseConnection')}>
            <Tag color={connected ? 'green' : 'red'}>
              {connected ? t('projectDetail.connected') : t('projectDetail.disconnected')}
            </Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title={t('projectDetail.knowledgeSources')}
        extra={
          <Popconfirm
            title={t('projectDetail.clearScopeTitle')}
            description={t('projectDetail.clearScopeDesc')}
            onConfirm={handleClearScope}
            okText={t('common.yes')}
            cancelText={t('common.no')}
          >
            <Button size="small" danger icon={<ClearOutlined />}>
              {t('projectDetail.clearScope')}
            </Button>
          </Popconfirm>
        }
      >
        <Table
          rowKey="source_id"
          columns={columns}
          dataSource={sources}
          pagination={{ pageSize: 10 }}
          size="small"
        />
      </Card>

      <Card title={t('projectDetail.uploadTitle')}>
        <Dragger
          accept=".md,.markdown,.java,.json,.yaml,.yml,.sql,.go,.py,.docx,.pdf,.html,.htm,.txt,.csv,.xml,.xlsx,.pptx,.eml"
          multiple={false}
          showUploadList={false}
          disabled={uploading}
          beforeUpload={(file) => {
            handleUpload(file);
            return false;
          }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">{t('projectDetail.uploadText')}</p>
          <p className="ant-upload-hint">
            {t('projectDetail.uploadHint')}
          </p>
        </Dragger>
      </Card>
    </Space>
  );
}