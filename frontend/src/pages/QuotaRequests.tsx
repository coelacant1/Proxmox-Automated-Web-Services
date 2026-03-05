import { useEffect, useState } from 'react';
import api from '../api/client';
import { Button, Card, CardHeader, CardTitle, CardContent, Input, MetricCard, StatusBadge } from '@/components/ui';

interface QuotaRequest {
  id: string; request_type: string; current_value: number; requested_value: number;
  reason: string; status: string; admin_notes: string | null;
  created_at: string; reviewed_at: string | null;
}

interface Quota {
  max_vms: number; max_containers: number; max_vcpus: number;
  max_ram_mb: number; max_disk_gb: number; max_snapshots: number;
}

const QUOTA_LABELS: Record<string, string> = {
  max_vms: 'Max VMs', max_containers: 'Max Containers', max_vcpus: 'Max vCPUs',
  max_ram_mb: 'Max RAM (MB)', max_disk_gb: 'Max Disk (GB)', max_snapshots: 'Max Snapshots',
};

export default function QuotaRequests() {
  const [requests, setRequests] = useState<QuotaRequest[]>([]);
  const [quota, setQuota] = useState<Quota | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ request_type: 'max_vms', requested_value: 0, reason: '' });
  const [error, setError] = useState('');

  const fetchData = () => {
    api.get('/api/quota-requests/').then(r => setRequests(r.data.items ?? r.data)).catch(() => {});
    api.get('/api/dashboard/summary').then(r => setQuota(r.data.quota)).catch(() => {});
  };
  useEffect(fetchData, []);

  const submit = async () => {
    setError('');
    try {
      await api.post('/api/quota-requests/', form);
      setShowForm(false);
      setForm({ request_type: 'max_vms', requested_value: 0, reason: '' });
      fetchData();
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to submit request');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-paws-text">Quota Requests</h1>
          <p className="text-sm text-paws-text-muted mt-1">
            Request quota increases - similar to AWS service limit increases
          </p>
        </div>
        <Button variant={showForm ? 'outline' : 'primary'} onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ Request Increase'}
        </Button>
      </div>

      {/* Current Quotas */}
      {quota && (
        <div className="mb-8">
          <h3 className="mb-3 text-lg font-semibold text-paws-text">Current Quotas</h3>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3">
            {Object.entries(QUOTA_LABELS).map(([key, label]) => (
              <MetricCard key={key} label={label} value={(quota as any)[key]} />
            ))}
          </div>
        </div>
      )}

      {/* New Request Form */}
      {showForm && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>New Quota Request</CardTitle>
          </CardHeader>
          <CardContent>
            {error && <p className="text-sm text-paws-danger mb-2">{error}</p>}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="block text-sm font-medium text-paws-text-muted">Quota Type</label>
                <select
                  className="w-full rounded-md border border-paws-border bg-paws-surface px-3 py-2 text-sm text-paws-text focus:outline-none focus:ring-2 focus:ring-paws-primary/50 focus:border-paws-primary"
                  value={form.request_type}
                  onChange={e => setForm({ ...form, request_type: e.target.value })}
                >
                  {Object.entries(QUOTA_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              <Input
                label="Desired Value"
                type="number"
                value={form.requested_value}
                onChange={e => setForm({ ...form, requested_value: parseInt(e.target.value) || 0 })}
              />
              <div className="col-span-full space-y-1.5">
                <label className="block text-sm font-medium text-paws-text-muted">Reason / Justification</label>
                <textarea
                  className="w-full min-h-[80px] rounded-md border border-paws-border bg-paws-surface px-3 py-2 text-sm text-paws-text placeholder:text-paws-text-dim focus:outline-none focus:ring-2 focus:ring-paws-primary/50 focus:border-paws-primary"
                  value={form.reason}
                  onChange={e => setForm({ ...form, reason: e.target.value })}
                  placeholder="Explain why you need a quota increase..."
                />
              </div>
              <Button className="col-span-full" onClick={submit}>Submit Request</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Request History */}
      <h3 className="mb-3 text-lg font-semibold text-paws-text">Request History</h3>
      {requests.length === 0 ? (
        <p className="text-paws-text-dim">No quota requests yet.</p>
      ) : (
        requests.map(qr => (
          <Card key={qr.id} className="mb-3">
            <div className="flex items-center justify-between mb-2">
              <span>
                <strong>{QUOTA_LABELS[qr.request_type] || qr.request_type}</strong>: {qr.current_value} → {qr.requested_value}
              </span>
              <StatusBadge status={qr.status} />
            </div>
            <p className="text-sm text-paws-text-muted">{qr.reason}</p>
            <p className="text-xs text-paws-text-dim mt-1">
              Submitted {new Date(qr.created_at).toLocaleString()}
              {qr.reviewed_at && ` · Reviewed ${new Date(qr.reviewed_at).toLocaleString()}`}
            </p>
            {qr.admin_notes && (
              <p className="text-xs text-paws-text-muted italic mt-2 p-2 rounded bg-paws-bg">
                Admin: {qr.admin_notes}
              </p>
            )}
          </Card>
        ))
      )}
    </div>
  );
}
