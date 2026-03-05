import { useEffect, useState } from 'react';
import { HardDrive, Plus, Trash2 } from 'lucide-react';
import api from '../api/client';
import {
  Button, DataTable, Input, Modal,
  StatusBadge, EmptyState, type Column,
} from '@/components/ui';

interface Volume {
  id: string;
  name: string;
  size_gb: number;
  storage_pool: string;
  status: string;
  attached_to: string | null;
  created_at: string;
  [key: string]: unknown;
}

export default function Volumes() {
  const [volumes, setVolumes] = useState<Volume[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', size_gb: 10, storage_pool: 'local-lvm' });

  const fetchVolumes = () => {
    api.get('/api/volumes/').then((res) => setVolumes(res.data)).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(fetchVolumes, []);

  const handleCreate = async () => {
    await api.post('/api/volumes/', form);
    setShowCreate(false);
    setForm({ name: '', size_gb: 10, storage_pool: 'local-lvm' });
    fetchVolumes();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this volume? Data will be lost.')) return;
    await api.delete(`/api/volumes/${id}`);
    fetchVolumes();
  };

  const columns: Column<Volume>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (row) => (
        <div className="flex items-center gap-2">
          <HardDrive className="h-4 w-4 text-paws-text-dim" />
          <span className="font-medium">{row.name}</span>
        </div>
      ),
    },
    { key: 'size_gb', header: 'Size', render: (row) => <span>{row.size_gb} GB</span> },
    { key: 'storage_pool', header: 'Pool' },
    { key: 'status', header: 'Status', render: (row) => <StatusBadge status={row.status} /> },
    {
      key: 'attached_to',
      header: 'Attached To',
      render: (row) => <span className="text-paws-text-dim">{row.attached_to || 'Unattached'}</span>,
    },
    {
      key: 'actions',
      header: '',
      render: (row) => (
        <Button variant="ghost" size="sm" onClick={() => handleDelete(row.id)}>
          <Trash2 className="h-4 w-4 text-paws-danger" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Volumes</h1>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> Create Volume
        </Button>
      </div>

      {volumes.length === 0 && !loading ? (
        <EmptyState
          icon={HardDrive}
          title="No volumes"
          description="Create a volume to attach persistent storage to your instances."
          action={{ label: 'Create Volume', onClick: () => setShowCreate(true) }}
        />
      ) : (
        <DataTable columns={columns} data={volumes} loading={loading} />
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Volume">
        <div className="space-y-4">
          <Input label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input label="Size (GB)" type="number" min={1} value={form.size_gb}
            onChange={(e) => setForm({ ...form, size_gb: +e.target.value })} />
          <Input label="Storage Pool" value={form.storage_pool}
            onChange={(e) => setForm({ ...form, storage_pool: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name}>Create</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
