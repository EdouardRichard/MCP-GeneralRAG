import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Button, Modal, Form, Input, Space, message, Card } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { Project } from '../types';
import { listProjects, createProject, deleteProject } from '../api/projects';
import type { CreateProjectInput } from '../api/projects';
import { useLocale } from '../i18n';

export default function ProjectsPage() {
  const navigate = useNavigate();
  const { t } = useLocale();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<CreateProjectInput>();

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listProjects();
      setProjects(data);
    } catch (err) {
      // FR-029: only the frontend prefix is translated; err.message (backend)
      // is displayed verbatim.
      message.error(t('projects.loadFailed') + (err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      setCreating(true);
      await createProject(values);
      message.success(t('projects.createdMsg'));
      setModalOpen(false);
      form.resetFields();
      fetchProjects();
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return; // validation error
      message.error(t('projects.createFailed') + (err as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteProject(id);
      message.success(t('projects.deletedMsg'));
      fetchProjects();
    } catch (err) {
      message.error(t('projects.deleteFailed') + (err as Error).message);
    }
  };

  const columns: ColumnsType<Project> = [
    {
      title: t('common.name'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: Project) => (
        <a onClick={() => navigate(`/projects/${record.project_id}`)}>{text}</a>
      ),
    },
    {
      title: t('common.alias'),
      dataIndex: 'alias',
      key: 'alias',
    },
    {
      title: t('projects.repoPath'),
      dataIndex: 'repo_path',
      key: 'repo_path',
      ellipsis: true,
    },
    {
      title: t('common.domainKey'),
      dataIndex: 'domain_key',
      key: 'domain_key',
      render: (val: string | undefined) => val || 'se-project',
    },
    {
      title: t('common.slug'),
      dataIndex: 'slug',
      key: 'slug',
      ellipsis: true,
    },
    {
      title: t('common.created'),
      dataIndex: 'created_at',
      key: 'created_at',
      render: (val: string) => new Date(val).toLocaleString(),
    },
    {
      title: t('common.actions'),
      key: 'actions',
      render: (_: unknown, record: Project) => (
        <Space>
          <Button size="small" onClick={() => navigate(`/projects/${record.project_id}`)}>
            {t('common.view')}
          </Button>
          <Button size="small" danger onClick={() => handleDelete(record.project_id)}>
            {t('common.delete')}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={t('projects.title')}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          {t('projects.createProject')}
        </Button>
      }
    >
      <Table
        rowKey="project_id"
        columns={columns}
        dataSource={projects}
        loading={loading}
        pagination={{ pageSize: 10 }}
      />

      <Modal
        title={t('projects.createProject')}
        open={modalOpen}
        onOk={handleCreate}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        confirmLoading={creating}
        okText={t('projects.create')}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label={t('common.name')} rules={[{ required: true, message: t('projects.nameRequired') }]}>
            <Input placeholder={t('projects.namePlaceholder')} />
          </Form.Item>
          <Form.Item name="alias" label={t('common.alias')}>
            <Input placeholder={t('projects.aliasPlaceholder')} />
          </Form.Item>
          <Form.Item name="repo_path" label={t('projects.repoPathLabel')}>
            <Input placeholder={t('projects.repoPathPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}