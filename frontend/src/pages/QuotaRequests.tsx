import { useEffect, useState } from 'react';
import { Monitor, Box, Cpu, MemoryStick, HardDrive, Camera, Archive, Database, ArrowUpRight } from 'lucide-react';
import api from '../api/client';
import { Button, Card, CardHeader, CardTitle, CardContent, Input, QuotaBar, StatusBadge, Tabs } from '@/components/ui';

interface QuotaRequest {
  id: string; request_type: string; current_value: number; requested_value: number;
  reason: string; status: string; admin_notes: string | null;
  created_at: string; reviewed_at: string | null;
}

interface DashboardSummary {
  resources: {
    vms: number; containers: number; networks: number; storage_buckets: number;
    vcpus_used: number; ram_mb_used: number; disk_gb_used: number; snapshots: number;
  };
  quota: {
    max_vms: number; max_containers: number; max_vcpus: number;
    max_ram_mb: number; max_disk_gb: number; max_snapshots: number;
    max_backups: number; max_backup_size_gb: number;
  };
}

interface BackupQuota {
  max_snapshots: number;
  max_backups: number;
  max_backup_size_gb: number;
  snapshot_count: number;
  proxmox_backup_count: number;
  total_backup_size: number;
}

const QUOTA_LABELS: Record<string, string> = {
  max_vms: 'Max VMs', max_containers: 'Max Containers', max_vcpus: 'Max vCPUs',
  max_ram_mb: 'Max RAM (MB)', max_disk_gb: 'Max Disk (GB)', max_snapshots: 'Max Snapshots',
  max_backups: 'Max Backups', max_backup_size_gb: 'Max Backup Storage (GB)',
};

function formatSize(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export default function QuotaRequests() {
  const [tab, setTab] = useState('usage');
  const [requests, setRequests] = useState<QuotaRequest[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [backupQuota, setBackupQuota] = useState<BackupQuota | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ request_type: 'max_vms', requested_value: 0, reason: '' });
  const [error, setError] = useState('');

  const fetchData = () => {
    api.get('/api/quota-requests/').then(r => setRequests(r.data.items ?? r.data)).catch(() => {});
    api.get('/api/dashboard/summary').then(r => setSummary(r.data)).catch(() => {});
    api.get('/api/backups/quota-summary').then(r => setBackupQuota(r.data)).catch(() => {});
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

  const pendingCount = requests.filter(r => r.status === 'pending').length;

  const tabs = [
    { id: 'usage', label: 'Usage' },
    { id: 'requests', label: 'Requests', count: pendingCount || undefined },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-paws-text">Quotas</h1>
          <p className="text-sm text-paws-text-muted mt-1">
            Monitor resource usage and request quota increases
          </p>
        </div>
        <Button onClick={() => { setTab('requests'); setShowForm(true); }}>
          <ArrowUpRight className="h-4 w-4 mr-1" /> Request Increase
        </Button>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} />

      {/* Usage Tab */}
      {tab === 'usage' && summary && (
        <div className="space-y-6">
          {/* Compute Quotas */}
          <Card>
            <CardHeader><CardTitle>Compute</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
                <div className="flex items-center gap-3">
                  <Monitor className="h-5 w-5 text-paws-primary shrink-0" />
                  <div className="flex-1"><QuotaBar label="Virtual Machines" used={summary.resources.vms} limit={summary.quota.max_vms} /></div>
                </div>
                <div className="flex items-center gap-3">
                  <Box className="h-5 w-5 text-paws-info shrink-0" />
                  <div className="flex-1"><QuotaBar label="Containers" used={summary.resources.containers} limit={summary.quota.max_containers} /></div>
                </div>
                <div className="flex items-center gap-3">
                  <Cpu className="h-5 w-5 text-paws-warning shrink-0" />
                  <div className="flex-1"><QuotaBar label="vCPUs" used={summary.resources.vcpus_used} limit={summary.quota.max_vcpus} /></div>
                </div>
                <div className="flex items-center gap-3">
                  <MemoryStick className="h-5 w-5 text-paws-success shrink-0" />
                  <div className="flex-1"><QuotaBar label="RAM" used={summary.resources.ram_mb_used} limit={summary.quota.max_ram_mb} unit=" MB" /></div>
                </div>
                <div className="flex items-center gap-3">
                  <HardDrive className="h-5 w-5 text-paws-text-muted shrink-0" />
                  <div className="flex-1"><QuotaBar label="Disk" used={summary.resources.disk_gb_used} limit={summary.quota.max_disk_gb} unit=" GB" /></div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Backup & Snapshot Quotas */}
          <Card>
            <CardHeader><CardTitle>Backups & Snapshots</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              {backupQuota ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
                  <div className="flex items-center gap-3">
                    <Archive className="h-5 w-5 text-paws-primary shrink-0" />
                    <div className="flex-1"><QuotaBar label="Backups" used={backupQuota.proxmox_backup_count} limit={backupQuota.max_backups} /></div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Camera className="h-5 w-5 text-paws-info shrink-0" />
                    <div className="flex-1"><QuotaBar label="Snapshots" used={backupQuota.snapshot_count} limit={backupQuota.max_snapshots} /></div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Database className="h-5 w-5 text-paws-warning shrink-0" />
                    <div className="flex-1">
                      <QuotaBar
                        label={`Backup Storage (${formatSize(backupQuota.total_backup_size)})`}
                        used={Math.round(backupQuota.total_backup_size / (1024 * 1024 * 1024))}
                        limit={backupQuota.max_backup_size_gb}
                        unit=" GB"
                      />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-paws-text-dim animate-pulse">Loading backup quota data...</div>
              )}
            </CardContent>
          </Card>

          {/* Storage Quotas */}
          <Card>
            <CardHeader><CardTitle>Object Storage</CardTitle></CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
                <div className="flex items-center gap-3">
                  <Database className="h-5 w-5 text-paws-success shrink-0" />
                  <div className="flex-1"><QuotaBar label="Buckets" used={summary.resources.storage_buckets} limit={summary.quota.max_vms > 0 ? 5 : 0} /></div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Quota Limits Summary Table */}
          <Card>
            <CardHeader><CardTitle>All Quota Limits</CardTitle></CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-paws-border">
                      <th className="text-left py-2 pr-4 text-paws-text-muted font-medium">Resource</th>
                      <th className="text-right py-2 px-4 text-paws-text-muted font-medium">Used</th>
                      <th className="text-right py-2 px-4 text-paws-text-muted font-medium">Limit</th>
                      <th className="text-right py-2 pl-4 text-paws-text-muted font-medium">Available</th>
                    </tr>
                  </thead>
                  <tbody className="text-paws-text">
                    {[
                      { label: 'Virtual Machines', used: summary.resources.vms, limit: summary.quota.max_vms },
                      { label: 'Containers', used: summary.resources.containers, limit: summary.quota.max_containers },
                      { label: 'vCPUs', used: summary.resources.vcpus_used, limit: summary.quota.max_vcpus },
                      { label: 'RAM (MB)', used: summary.resources.ram_mb_used, limit: summary.quota.max_ram_mb },
                      { label: 'Disk (GB)', used: summary.resources.disk_gb_used, limit: summary.quota.max_disk_gb },
                      { label: 'Snapshots', used: backupQuota?.snapshot_count ?? summary.resources.snapshots, limit: summary.quota.max_snapshots },
                      { label: 'Backups', used: backupQuota?.proxmox_backup_count ?? 0, limit: summary.quota.max_backups },
                      { label: 'Backup Storage (GB)', used: backupQuota ? Math.round(backupQuota.total_backup_size / (1024 * 1024 * 1024)) : 0, limit: summary.quota.max_backup_size_gb },
                    ].map((row) => {
                      const avail = Math.max(0, row.limit - row.used);
                      const ratio = row.limit > 0 ? row.used / row.limit : 0;
                      return (
                        <tr key={row.label} className="border-b border-paws-border/50">
                          <td className="py-2 pr-4">{row.label}</td>
                          <td className={`text-right py-2 px-4 font-medium ${ratio >= 0.9 ? 'text-paws-danger' : ratio >= 0.7 ? 'text-paws-warning' : ''}`}>{row.used}</td>
                          <td className="text-right py-2 px-4">{row.limit}</td>
                          <td className={`text-right py-2 pl-4 font-medium ${avail === 0 ? 'text-paws-danger' : ''}`}>{avail}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Requests Tab */}
      {tab === 'requests' && (
        <div className="space-y-6">
          {/* New Request Form */}
          {showForm ? (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>New Quota Request</CardTitle>
                  <Button variant="outline" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
                </div>
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
                  {summary && (
                    <div className="col-span-full text-sm text-paws-text-muted">
                      Current limit: <strong className="text-paws-text">{(summary.quota as any)[form.request_type] ?? 'N/A'}</strong>
                    </div>
                  )}
                  <div className="col-span-full space-y-1.5">
                    <label className="block text-sm font-medium text-paws-text-muted">Reason / Justification</label>
                    <textarea
                      className="w-full min-h-[80px] rounded-md border border-paws-border bg-paws-surface px-3 py-2 text-sm text-paws-text placeholder:text-paws-text-dim focus:outline-none focus:ring-2 focus:ring-paws-primary/50 focus:border-paws-primary"
                      value={form.reason}
                      onChange={e => setForm({ ...form, reason: e.target.value })}
                      placeholder="Explain why you need a quota increase..."
                    />
                  </div>
                  <Button className="col-span-full" onClick={submit} disabled={!form.requested_value || !form.reason.trim()}>
                    Submit Request
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="flex justify-end">
              <Button onClick={() => setShowForm(true)}>
                <ArrowUpRight className="h-4 w-4 mr-1" /> New Request
              </Button>
            </div>
          )}

          {/* Request History */}
          <div>
            <h3 className="mb-3 text-lg font-semibold text-paws-text">Request History</h3>
            {requests.length === 0 ? (
              <Card>
                <CardContent className="py-8 text-center text-paws-text-dim">
                  No quota requests yet. Submit a request to increase your resource limits.
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-3">
                {requests.map(qr => (
                  <Card key={qr.id}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-paws-text">
                        <strong>{QUOTA_LABELS[qr.request_type] || qr.request_type}</strong>: {qr.current_value} &rarr; {qr.requested_value}
                      </span>
                      <StatusBadge status={qr.status} />
                    </div>
                    <p className="text-sm text-paws-text-muted">{qr.reason}</p>
                    <p className="text-xs text-paws-text-dim mt-1">
                      Submitted {new Date(qr.created_at).toLocaleString()}
                      {qr.reviewed_at && ` \u00b7 Reviewed ${new Date(qr.reviewed_at).toLocaleString()}`}
                    </p>
                    {qr.admin_notes && (
                      <p className="text-xs text-paws-text-muted italic mt-2 p-2 rounded bg-paws-bg">
                        Admin: {qr.admin_notes}
                      </p>
                    )}
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
