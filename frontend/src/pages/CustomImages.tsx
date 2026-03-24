import { useEffect, useState } from 'react';
import { Image, Plus, Trash2 } from 'lucide-react';
import api from '../api/client';
import {
  Button, DataTable, Input, Modal, Select, Badge, EmptyState, useConfirm, useToast, type Column,
} from '@/components/ui';

interface CustomImage {
  id: string;
  name: string;
  os_type: string;
  size_gb: number;
  format: string;
  status: string;
  created_by: string;
  created_at: string;
  [key: string]: unknown;
}

export default function CustomImages() {
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const [images, setImages] = useState<CustomImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', os_type: 'linux', format: 'qcow2', source_url: '' });

  const fetchImages = () => {
    api.get('/api/admin/images')
      .then((res) => setImages(res.data))
      .catch(() => setImages([]))
      .finally(() => setLoading(false));
  };

  useEffect(fetchImages, []);

  const handleCreate = async () => {
    try {
      await api.post('/api/admin/images', form);
      toast('Image created successfully', 'success');
      setShowCreate(false);
      setForm({ name: '', os_type: 'linux', format: 'qcow2', source_url: '' });
      fetchImages();
    } catch {
      toast('Failed to create image', 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!await confirm({ title: 'Delete Image', message: 'Delete this custom image?' })) return;
    try {
      await api.delete(`/api/admin/images/${id}`);
      toast('Image deleted', 'success');
      fetchImages();
    } catch {
      toast('Failed to delete image', 'error');
    }
  };

  const columns: Column<CustomImage>[] = [
    {
      key: 'name', header: 'Name',
      render: (row) => (
        <div className="flex items-center gap-2">
          <Image className="h-4 w-4 text-paws-text-dim" />
          <span className="font-medium text-paws-text">{row.name}</span>
        </div>
      ),
    },
    { key: 'os_type', header: 'OS', render: (row) => <Badge variant="default">{row.os_type}</Badge> },
    { key: 'format', header: 'Format', render: (row) => <span className="text-xs font-mono text-paws-text-dim">{row.format}</span> },
    { key: 'size_gb', header: 'Size', render: (row) => <span className="text-sm">{row.size_gb} GB</span> },
    { key: 'status', header: 'Status', render: (row) => <Badge variant={row.status === 'ready' ? 'success' : 'warning'}>{row.status}</Badge> },
    {
      key: 'actions', header: '',
      render: (row) => (
        <Button variant="ghost" size="sm" onClick={() => handleDelete(row.id)}>
          <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Custom Images</h1>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> Add Image
        </Button>
      </div>

      {images.length === 0 && !loading ? (
        <EmptyState icon={Image} title="No custom images" description="Upload OS images for users to use as templates." />
      ) : (
        <DataTable columns={columns} data={images} loading={loading} />
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Add Custom Image" size="lg">
        <div className="space-y-4">
          <Input label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div className="grid grid-cols-2 gap-4">
            <Select label="OS Type" options={[
              { value: 'linux', label: 'Linux' },
              { value: 'windows', label: 'Windows' },
              { value: 'bsd', label: 'BSD' },
              { value: 'other', label: 'Other' },
            ]} value={form.os_type} onChange={(e) => setForm({ ...form, os_type: e.target.value })} />
            <Select label="Format" options={[
              { value: 'qcow2', label: 'QCOW2' },
              { value: 'raw', label: 'RAW' },
              { value: 'vmdk', label: 'VMDK' },
              { value: 'iso', label: 'ISO' },
            ]} value={form.format} onChange={(e) => setForm({ ...form, format: e.target.value })} />
          </div>
          <Input label="Source URL" placeholder="https://example.com/image.qcow2" value={form.source_url}
            onChange={(e) => setForm({ ...form, source_url: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name || !form.source_url}>Add Image</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
