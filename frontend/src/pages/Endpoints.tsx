import { useEffect, useState } from 'react';
import { Globe, Plus, Trash2, Copy, Check, Power } from 'lucide-react';
import api from '../api/client';
import {
  Button, DataTable, Input, Modal,
  Select, Badge, StatusBadge, EmptyState, type Column,
} from '@/components/ui';

interface Endpoint {
  id: string;
  name: string;
  protocol: string;
  subdomain: string;
  fqdn: string;
  internal_port: number;
  is_active: boolean;
  tls_enabled: boolean;
  auth_required: boolean;
  resource_id: string;
  created_at: string;
  [key: string]: unknown;
}

interface QuotaInfo {
  max_endpoints: number;
  used: number;
  remaining: number;
}

export default function Endpoints() {
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [quota, setQuota] = useState<QuotaInfo | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [form, setForm] = useState({
    resource_id: '', name: '', protocol: 'http', internal_port: 8080, subdomain: '',
    tls_enabled: true, auth_required: false,
  });

  const fetchData = () => {
    api.get('/api/endpoints/').then((res) => setEndpoints(res.data)).catch(() => {}).finally(() => setLoading(false));
    api.get('/api/endpoints/quota').then((res) => setQuota(res.data)).catch(() => {});
  };

  useEffect(fetchData, []);

  const handleCreate = async () => {
    await api.post('/api/endpoints/', form);
    setShowCreate(false);
    setForm({ resource_id: '', name: '', protocol: 'http', internal_port: 8080, subdomain: '', tls_enabled: true, auth_required: false });
    fetchData();
  };

  const handleToggle = async (id: string, active: boolean) => {
    await api.patch(`/api/endpoints/${id}`, { is_active: !active });
    fetchData();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this endpoint?')) return;
    await api.delete(`/api/endpoints/${id}`);
    fetchData();
  };

  const copyUrl = (fqdn: string) => {
    navigator.clipboard.writeText(`https://${fqdn}`);
    setCopied(fqdn);
    setTimeout(() => setCopied(null), 2000);
  };

  const columns: Column<Endpoint>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (row) => (
        <div>
          <p className="font-medium text-paws-text">{row.name}</p>
          <p className="text-xs text-paws-text-dim">{row.fqdn}</p>
        </div>
      ),
    },
    {
      key: 'protocol',
      header: 'Protocol',
      render: (row) => <Badge variant="default">{row.protocol.toUpperCase()}</Badge>,
    },
    { key: 'internal_port', header: 'Port', render: (row) => <span className="font-mono text-sm">{row.internal_port}</span> },
    {
      key: 'is_active',
      header: 'Status',
      render: (row) => <StatusBadge status={row.is_active ? 'active' : 'stopped'} />,
    },
    {
      key: 'tls',
      header: 'TLS',
      render: (row) => row.tls_enabled ? <Badge variant="success">TLS</Badge> : <Badge variant="default">None</Badge>,
    },
    {
      key: 'actions',
      header: '',
      render: (row) => (
        <div className="flex gap-1">
          <button onClick={() => copyUrl(row.fqdn)} className="p-1.5 rounded hover:bg-paws-surface-hover text-paws-text-dim">
            {copied === row.fqdn ? <Check className="h-3.5 w-3.5 text-paws-success" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
          <button onClick={() => handleToggle(row.id, row.is_active)} className="p-1.5 rounded hover:bg-paws-surface-hover text-paws-text-dim">
            <Power className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => handleDelete(row.id)} className="p-1.5 rounded hover:bg-paws-surface-hover text-paws-danger">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-paws-text">Service Endpoints</h1>
          {quota && (
            <p className="text-sm text-paws-text-muted mt-1">
              {quota.used} / {quota.max_endpoints} endpoints used
            </p>
          )}
        </div>
        <Button onClick={() => setShowCreate(true)} disabled={quota ? quota.remaining <= 0 : false}>
          <Plus className="h-4 w-4 mr-1" /> Create Endpoint
        </Button>
      </div>

      {endpoints.length === 0 && !loading ? (
        <EmptyState
          icon={Globe}
          title="No endpoints"
          description="Create a service endpoint to expose your instances via HTTP, TCP, RDP, or SSH."
          action={{ label: 'Create Endpoint', onClick: () => setShowCreate(true) }}
        />
      ) : (
        <DataTable columns={columns} data={endpoints} loading={loading} />
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Service Endpoint" size="lg">
        <div className="space-y-4">
          <Input label="Resource ID" placeholder="VM or container UUID" value={form.resource_id}
            onChange={(e) => setForm({ ...form, resource_id: e.target.value })} />
          <Input label="Name" placeholder="my-web-app" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div className="grid grid-cols-2 gap-4">
            <Select label="Protocol" options={[
              { value: 'http', label: 'HTTP' },
              { value: 'https', label: 'HTTPS' },
              { value: 'tcp', label: 'TCP' },
              { value: 'rdp', label: 'RDP' },
              { value: 'ssh', label: 'SSH' },
            ]} value={form.protocol} onChange={(e) => setForm({ ...form, protocol: e.target.value })} />
            <Input label="Internal Port" type="number" value={form.internal_port}
              onChange={(e) => setForm({ ...form, internal_port: +e.target.value })} />
          </div>
          <Input label="Subdomain" placeholder="my-app" value={form.subdomain}
            onChange={(e) => setForm({ ...form, subdomain: e.target.value })} />
          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm text-paws-text cursor-pointer">
              <input type="checkbox" checked={form.tls_enabled}
                onChange={(e) => setForm({ ...form, tls_enabled: e.target.checked })} className="rounded border-paws-border" />
              Enable TLS
            </label>
            <label className="flex items-center gap-2 text-sm text-paws-text cursor-pointer">
              <input type="checkbox" checked={form.auth_required}
                onChange={(e) => setForm({ ...form, auth_required: e.target.checked })} className="rounded border-paws-border" />
              Require Auth
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name || !form.subdomain || !form.resource_id}>Create</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
