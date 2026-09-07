import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Modal, Form, Input, Tag, Space, message, Card, Popconfirm } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { DomainProfile, DomainProfileInput } from '../api/domainProfiles';
import { listDomainProfiles, createDomainProfile, updateDomainProfile, deleteDomainProfile } from '../api/domainProfiles';
import { useLocale } from '../i18n';

export default function DomainProfilesPage() {
  const { t } = useLocale();
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
      message.error(t('domainProfiles.loadFailed') + (err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { fetchProfiles(); }, [fetchProfiles]);

  const openCreate = () => { setEditing(null); form.resetFields(); setModalOpen(true); };
  const openEdit = (p: DomainProfile) => { setEditing(p); form.setFieldsValue(p as unknown as Record<string, unknown>); setModalOpen(true); };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editing) {
        await updateDomainProfile(editing.domain_key, values);
        message.success(t('domainProfiles.updatedMsg'));
      } else {
        await createDomainProfile(values);
        message.success(t('domainProfiles.createdMsg'));
      }
      setModalOpen(false);
      form.resetFields();
      fetchProfiles();
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return;
      message.error(t('domainProfiles.saveFailed') + (err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (key: string) => {
    try {
      await deleteDomainProfile(key);
      message.success(t('domainProfiles.deletedMsg'));
      fetchProfiles();
    } catch (err) {
      message.error(t('domainProfiles.deleteFailed') + (err as Error).message);
    }
  };

  const columns: ColumnsType<DomainProfile> = [
    { title: t('common.domainKey'), dataIndex: 'domain_key', key: 'domain_key' },
    { title: t('common.name'), dataIndex: 'name', key: 'name' },
    {
      title: t('domainProfiles.formats'), dataIndex: 'supported_formats', key: 'supported_formats',
      // format names are domain data (backend vocabulary) — verbatim (FR-029).
      render: (f: string[]) => f.map((x) => <Tag key={x}>{x}</Tag>),
    },
    {
      title: t('domainProfiles.graph'), dataIndex: 'graph_relations', key: 'graph_relations',
      render: (g: Record<string, unknown>) => (g && Object.keys(g).length > 0) ? t('common.yes') : t('common.no'),
    },
    {
      title: t('domainProfiles.builtin'), dataIndex: 'is_builtin', key: 'is_builtin',
      render: (b: boolean) => (b ? <Tag color="gold">{t('domainProfiles.builtin')}</Tag> : <Tag color="blue">{t('domainProfiles.custom')}</Tag>),
    },
    {
      title: t('common.actions'), key: 'actions',
      render: (_: unknown, record: DomainProfile) => (
        <Space>
          <Button size="small" disabled={record.is_builtin} onClick={() => openEdit(record)}>{t('common.edit')}</Button>
          <Popconfirm
            title={t('domainProfiles.deleteProfileTitle')}
            disabled={record.is_builtin}
            onConfirm={() => handleDelete(record.domain_key)}
            okText={t('common.yes')} cancelText={t('common.no')}
          >
            <Button size="small" danger disabled={record.is_builtin}>{t('common.delete')}</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card title={t('domainProfiles.title')} extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>{t('domainProfiles.createProfile')}</Button>}>
      <Table rowKey="domain_key" columns={columns} dataSource={profiles} loading={loading} pagination={{ pageSize: 10 }} />
      <Modal
        title={editing ? t('domainProfiles.editTitle') : t('domainProfiles.createTitle')}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        confirmLoading={saving}
        okText={t('domainProfiles.save')}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="domain_key" label={t('common.domainKey')} rules={[{ required: true, message: t('domainProfiles.domainKeyRequired') }]}>
            <Input disabled={!!editing} placeholder={t('domainProfiles.domainKeyPlaceholder')} />
          </Form.Item>
          <Form.Item name="name" label={t('common.name')} rules={[{ required: true, message: t('domainProfiles.nameRequired') }]}>
            <Input placeholder={t('domainProfiles.namePlaceholder')} />
          </Form.Item>
          <Form.Item name="supported_formats" label={t('domainProfiles.formatsLabel')} rules={[{ required: true, message: t('domainProfiles.formatsRequired') }]}>
            <Input placeholder={t('domainProfiles.formatsPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}