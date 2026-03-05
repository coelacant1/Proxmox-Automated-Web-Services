import { useEffect, useState } from 'react';
import { Globe, Plus, Trash2, RefreshCw } from 'lucide-react';
import api from '../api/client';
import {
  Button, DataTable, Modal, Input, Badge, EmptyState, type Column,
} from '@/components/ui';

interface IPReservation {
  id: string;
  ip_address: string;
  vpc_id: string;
  subnet_id?: string;
  resource_id?: string;
  status: string;
  created_at: string;
  [key: string]: unknown;
}

export default function IPManagement() {
  const [ips, setIPs] = useState<IPReservation[]>([]);
  const [loading, setLoading] = useState(true);
  const [showReserve, setShowReserve] = useState(false);
  const [form, setForm] = useState({ vpc_id: '', ip_address: '' });

  const fetchIPs = () => {
    api.get('/api/networking/ips')
      .then((res) => setIPs(res.data))
      .catch(() => setIPs([]))
      .finally(() => setLoading(false));
  };

  useEffect(fetchIPs, []);

  const handleReserve = async () => {
    await api.post(`/api/networking/vpcs/${form.vpc_id}/ips`, { ip_address: form.ip_address || undefined });
    setShowReserve(false);
    setForm({ vpc_id: '', ip_address: '' });
    fetchIPs();
  };

  const handleRelease = async (ip: IPReservation) => {
    if (!confirm(`Release IP ${ip.ip_address}?`)) return;
    await api.delete(`/api/networking/vpcs/${ip.vpc_id}/ips/${ip.ip_address}`);
    fetchIPs();
  };

  const columns: Column<IPReservation>[] = [
    { key: 'ip_address', header: 'IP Address', render: (row) => <span className="font-mono text-sm text-paws-text">{row.ip_address}</span> },
    { key: 'vpc_id', header: 'VPC', render: (row) => <span className="text-xs font-mono text-paws-text-dim">{row.vpc_id.slice(0, 8)}</span> },
    { key: 'resource_id', header: 'Attached To', render: (row) => <span className="text-xs text-paws-text-dim">{row.resource_id || 'Unattached'}</span> },
    { key: 'status', header: 'Status', render: (row) => <Badge variant={row.status === 'reserved' ? 'info' : 'success'}>{row.status}</Badge> },
    {
      key: 'actions', header: '',
      render: (row) => (
        <Button variant="ghost" size="sm" onClick={() => handleRelease(row)}>
          <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">IP Addresses</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchIPs}><RefreshCw className="h-4 w-4" /></Button>
          <Button onClick={() => setShowReserve(true)}><Plus className="h-4 w-4 mr-1" /> Reserve IP</Button>
        </div>
      </div>

      {ips.length === 0 && !loading ? (
        <EmptyState icon={Globe} title="No reserved IPs" description="Reserve a static IP to assign to your instances." />
      ) : (
        <DataTable columns={columns} data={ips} loading={loading} />
      )}

      <Modal open={showReserve} onClose={() => setShowReserve(false)} title="Reserve IP Address">
        <div className="space-y-4">
          <Input label="VPC ID" value={form.vpc_id} onChange={(e) => setForm({ ...form, vpc_id: e.target.value })} />
          <Input label="IP Address (optional, auto-assign if empty)" placeholder="10.0.1.50" value={form.ip_address}
            onChange={(e) => setForm({ ...form, ip_address: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowReserve(false)}>Cancel</Button>
            <Button onClick={handleReserve} disabled={!form.vpc_id}>Reserve</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
