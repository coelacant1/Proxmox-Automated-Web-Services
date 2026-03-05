import { useEffect, useState } from 'react';
import { Globe, Plus, Trash2, RefreshCw } from 'lucide-react';
import api from '../api/client';
import {
  Button,
  DataTable, Input, Modal, Select, Badge, EmptyState, type Column,
} from '@/components/ui';

interface DNSRecord {
  id: string;
  name: string;
  type: string;
  value: string;
  ttl: number;
  proxied: boolean;
  [key: string]: unknown;
}

export default function DNSManagement() {
  const [records, setRecords] = useState<DNSRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', type: 'A', value: '', ttl: 3600 });

  const fetchRecords = () => {
    api.get('/api/dns/records')
      .then((res) => setRecords(res.data))
      .catch(() => setRecords([]))
      .finally(() => setLoading(false));
  };

  useEffect(fetchRecords, []);

  const handleCreate = async () => {
    await api.post('/api/dns/records', form);
    setShowCreate(false);
    setForm({ name: '', type: 'A', value: '', ttl: 3600 });
    fetchRecords();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this DNS record?')) return;
    await api.delete(`/api/dns/records/${id}`);
    fetchRecords();
  };

  const columns: Column<DNSRecord>[] = [
    { key: 'name', header: 'Name', render: (row) => <span className="font-mono text-sm text-paws-text">{row.name}</span> },
    { key: 'type', header: 'Type', render: (row) => <Badge variant="default">{row.type}</Badge> },
    { key: 'value', header: 'Value', render: (row) => <span className="font-mono text-sm text-paws-text-dim">{row.value}</span> },
    { key: 'ttl', header: 'TTL', render: (row) => <span className="text-xs text-paws-text-dim">{row.ttl}s</span> },
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
        <h1 className="text-2xl font-bold text-paws-text">DNS Records</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchRecords}>
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4 mr-1" /> Add Record
          </Button>
        </div>
      </div>

      {records.length === 0 && !loading ? (
        <EmptyState icon={Globe} title="No DNS records" description="DNS records are auto-created when you set up service endpoints." />
      ) : (
        <DataTable columns={columns} data={records} loading={loading} />
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Add DNS Record">
        <div className="space-y-4">
          <Input label="Name" placeholder="app.example.com" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Select label="Type" options={[
            { value: 'A', label: 'A (IPv4)' },
            { value: 'AAAA', label: 'AAAA (IPv6)' },
            { value: 'CNAME', label: 'CNAME' },
            { value: 'TXT', label: 'TXT' },
            { value: 'SRV', label: 'SRV' },
          ]} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} />
          <Input label="Value" placeholder="192.168.1.100" value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })} />
          <Input label="TTL (seconds)" type="number" value={form.ttl}
            onChange={(e) => setForm({ ...form, ttl: +e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name || !form.value}>Create</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
