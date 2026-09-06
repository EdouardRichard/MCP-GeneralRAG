import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Modal, Form, Input, Tag, Space, message, Card, Popconfirm } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { DomainProfile, DomainProfileInput } from '../api/domainProfiles';
import { listDomainProfiles, createDomainProfile, updateDomainProfile, deleteDomainProfile } from '../api/domainProfiles';

export default function DomainProfilesPage() {
  const [profiles, setProfiles] = useState<DomainProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<DomainProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<DomainProfileInput>();

  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    try {
      setProfiles(await listDomainProfiles());
    } catch (err) {
      message.error('Failed to load domain profiles: ' + (err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchProfiles(); }, [fetchProfiles]);

  const openCreate = () => { setEditing(null); form.resetFields(); setModalOpen(true); };
  const openEdit = (p: DomainProfile) => { setEditing(p); form.setFieldsValue(p as unknown as Record<string, unknown>); setModalOpen(true); };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editing) {
        await updateDomainProfile(editing.domain_key, values);
        message.success('Domain profile updated');
      } else {
        await createDomainProfile(values);
        message.success('Domain profile created');
      }
      setModalOpen(false);
      form.resetFields();
      fetchProfiles();
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return;
      message.error('Save failed: ' + (err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (key: string) => {
    try {
      await deleteDomainProfile(key);
      message.success('Domain profile deleted');
      fetchProfiles();
    } catch (err) {
      message.error('Delete failed: ' + (err as Error).message);
    }
  };

  const columns: ColumnsType<DomainProfile> = [
    { title: 'Domain Key', dataIndex: 'domain_key', key: 'domain_key' },
    { title: 'Name', dataIndex: 'name', key: 'name' },
    {
      title: 'Formats', dataIndex: 'supported_formats', key: 'supported_formats',
      render: (f: string[]) => f.map((x) => <Tag key={x}>{x}</Tag>),
    },
    {
      title: 'Graph', dataIndex: 'graph_relations', key: 'graph_relations',
      render: (g: Record<string, unknown>) => (g && Object.keys(g).length > 0) ? 'Yes' : 'No',
    },
    {
      title: 'Builtin', dataIndex: 'is_builtin', key: 'is_builtin',
      render: (b: boolean) => (b ? <Tag color="gold">builtin</Tag> : <Tag color="blue">custom</Tag>),
    },
    {
      title: 'Actions', key: 'actions',
      render: (_: unknown, record: DomainProfile) => (
        <Space>
          <Button size="small" disabled={record.is_builtin} onClick={() => openEdit(record)}>Edit</Button>
          <Popconfirm
            title="Delete this profile?"
            disabled={record.is_builtin}
            onConfirm={() => handleDelete(record.domain_key)}
            okText="Yes" cancelText="No"
          >
            <Button size="small" danger disabled={record.is_builtin}>Delete</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card title="Domain Profiles" extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>Create Profile</Button>}>
      <Table rowKey="domain_key" columns={columns} dataSource={profiles} loading={loading} pagination={{ pageSize: 10 }} />
      <Modal
        title={editing ? 'Edit Domain Profile' : 'Create Domain Profile'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        confirmLoading={saving}
        okText="Save"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="domain_key" label="Domain Key" rules={[{ required: true, message: 'Domain key is required' }]}>
            <Input disabled={!!editing} placeholder="e.g. legal" />
          </Form.Item>
          <Form.Item name="name" label="Name" rules={[{ required: true, message: 'Name is required' }]}>
            <Input placeholder="Display name" />
          </Form.Item>
          <Form.Item name="supported_formats" label="Supported Formats (comma-separated)" rules={[{ required: true, message: 'At least one format is required' }]}>
            <Input placeholder="markdown, java, pdf" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
