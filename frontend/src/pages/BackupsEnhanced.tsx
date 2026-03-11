import { useEffect, useState } from 'react';
import { Archive, Plus, Trash2, Play, Calendar, Download, Camera, FolderOpen } from 'lucide-react';
import api from '../api/client';
import {
  Button, DataTable, Input, Modal, Select, Badge,
  EmptyState, Tabs,
  type Column,
} from '@/components/ui';
import { useToast } from '@/components/ui/Toast';

// --- Types ---

interface ProxmoxBackup {
  volid: string;
  size: number;
  ctime: number;
  format: string;
  storage: string;
  notes: string;
  pbs: boolean;
  resource_id: string | null;
  resource_name: string | null;
  resource_type: string | null;
  vmid: number | null;
  node: string | null;
  [key: string]: unknown;
}

interface Snapshot {
  name: string;
  description: string;
  snaptime?: number;
  parent?: string;
  resource_id: string;
  resource_name: string;
  resource_type: string;
  [key: string]: unknown;
}

interface BackupPlan {
  id: string;
  name: string;
  resource_id: string;
  schedule_cron: string;
  backup_type: string;
  retention_count: number;
  retention_days: number;
  is_active: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  [key: string]: unknown;
}

interface ResourceItem {
  id: string;
  display_name?: string;
  name?: string;
  resource_type: string;
  status: string;
  proxmox_vmid?: number;
  proxmox_node?: string;
}

function formatSize(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

function rName(r: ResourceItem): string {
  return r.display_name || r.name || r.id;
}

export default function BackupsEnhanced() {
  const { toast } = useToast();
  const [proxmoxBackups, setProxmoxBackups] = useState<ProxmoxBackup[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [plans, setPlans] = useState<BackupPlan[]>([]);
  const [resources, setResources] = useState<ResourceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [backupsLoading, setBackupsLoading] = useState(true);
  const [tab, setTab] = useState('backups');

  // Modals
  const [showCreate, setShowCreate] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);
  const [showPlan, setShowPlan] = useState(false);
  const [showRestore, setShowRestore] = useState<ProxmoxBackup | null>(null);
  const [showDelete, setShowDelete] = useState<ProxmoxBackup | null>(null);

  // File browser state (reuses InstanceDetail pattern)
  const [browsingBackup, setBrowsingBackup] = useState<ProxmoxBackup | null>(null);
  const [backupFiles, setBackupFiles] = useState<any[]>([]);
  const [backupFilePath, setBackupFilePath] = useState('');
  const [backupFileLoading, setBackupFileLoading] = useState(false);

  // Forms
  const [backupForm, setBackupForm] = useState({ resource_id: '', storage: '', mode: 'snapshot', compress: 'zstd', notes: '' });
  const [snapForm, setSnapForm] = useState({ resource_id: '', name: '', description: '' });
  const [planForm, setPlanForm] = useState({
    resource_id: '', name: '', schedule_cron: '0 2 * * *', backup_type: 'snapshot',
    retention_count: 7, retention_days: 30,
  });
  const [storageNames, setStorageNames] = useState<string[]>([]);

  const fetchData = async () => {
    setLoading(true);
    // Fast calls first - resources and storages
    const [resRes, storageRes, planRes] = await Promise.all([
      api.get('/api/resources').catch(() => ({ data: { items: [] } })),
      api.get('/api/compute/backup-storages').catch(() => ({ data: [] })),
      api.get('/api/backups/plans').catch(() => ({ data: [] })),
    ]);
    const allRes = resRes.data.items ?? resRes.data ?? [];
    const computeRes = allRes.filter((r: ResourceItem) => r.resource_type === 'vm' || r.resource_type === 'lxc' || r.resource_type === 'container');
    setResources(computeRes);
    setPlans(Array.isArray(planRes.data) ? planRes.data : []);

    // Extract storage names from objects
    const rawStorages = Array.isArray(storageRes.data) ? storageRes.data : [];
    const names = rawStorages.map((s: any) => typeof s === 'string' ? s : s.storage || s.name || '').filter(Boolean);
    setStorageNames(names);

    setLoading(false);

    // Slower calls - Proxmox backups (don't block render)
    setBackupsLoading(true);
    api.get('/api/backups/proxmox/all')
      .then((r) => setProxmoxBackups(r.data.backups || []))
      .catch(() => {})
      .finally(() => setBackupsLoading(false));

    // Fetch snapshots for all resources (parallel)
    const snapPromises = computeRes.map((r: ResourceItem) =>
      api.get(`/api/backups/${r.id}/snapshots`)
        .then((snapRes) => {
          const snaps = (snapRes.data || []).filter((s: Snapshot) => s.name !== 'current');
          return snaps.map((s: Snapshot) => ({
            ...s,
            resource_id: r.id,
            resource_name: rName(r),
            resource_type: r.resource_type,
          }));
        })
        .catch(() => [] as Snapshot[])
    );
    const allSnapResults = await Promise.all(snapPromises);
    setSnapshots(allSnapResults.flat());
  };

  useEffect(() => { fetchData(); }, []);

  // --- Actions ---

  const handleCreateBackup = async () => {
    try {
      await api.post(`/api/compute/vms/${backupForm.resource_id}/backups`, {
        storage: backupForm.storage || storageNames[0] || 'local',
        mode: backupForm.mode,
        compress: backupForm.compress,
        notes: backupForm.notes || undefined,
      });
      toast('Backup job started', 'success');
      setShowCreate(false);
      setBackupForm({ resource_id: '', storage: '', mode: 'snapshot', compress: 'zstd', notes: '' });
      setTimeout(fetchData, 2000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to create backup';
      toast(msg, 'error');
    }
  };

  const handleCreateSnapshot = async () => {
    try {
      await api.post(`/api/backups/${snapForm.resource_id}/snapshots`, {
        name: snapForm.name,
        description: snapForm.description,
      });
      toast('Snapshot created', 'success');
      setShowSnapshot(false);
      setSnapForm({ resource_id: '', name: '', description: '' });
      fetchData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to create snapshot';
      toast(msg, 'error');
    }
  };

  const handleDeleteSnapshot = async (resourceId: string, snapName: string) => {
    try {
      await api.delete(`/api/backups/${resourceId}/snapshots/${snapName}`);
      toast('Snapshot deleted', 'success');
      fetchData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed';
      toast(msg, 'error');
    }
  };

  const handleRollbackSnapshot = async (resourceId: string, snapName: string) => {
    try {
      await api.post(`/api/backups/${resourceId}/snapshots/rollback`, { name: snapName });
      toast('Rollback started', 'success');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed';
      toast(msg, 'error');
    }
  };

  const handleRestoreBackup = async () => {
    if (!showRestore?.resource_id) return;
    try {
      await api.post(`/api/compute/vms/${showRestore.resource_id}/backups/restore`, {
        volid: showRestore.volid,
        storage: showRestore.storage,
        pbs: showRestore.pbs,
      });
      toast('Restore started', 'success');
      setShowRestore(null);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast(err.response?.data?.detail || 'Restore failed', 'error');
    }
  };

  const handleDeleteBackup = async () => {
    if (!showDelete?.resource_id) return;
    try {
      await api.delete(`/api/compute/vms/${showDelete.resource_id}/backups`, {
        data: { volid: showDelete.volid, storage: showDelete.storage, pbs: showDelete.pbs },
      });
      toast('Backup deleted', 'success');
      setShowDelete(null);
      fetchData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed';
      toast(msg, 'error');
    }
  };

  const handleBrowseBackup = async (backup: ProxmoxBackup) => {
    if (!backup.resource_id) { toast('No linked resource', 'error'); return; }
    setBrowsingBackup(backup);
    setBackupFilePath('');
    setBackupFileLoading(true);
    try {
      const r = await api.post(`/api/compute/vms/${backup.resource_id}/backups/files`, {
        volid: backup.volid, storage: backup.storage,
      });
      setBackupFiles(r.data?.files || []);
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to browse backup', 'error');
      setBackupFiles([]);
    } finally {
      setBackupFileLoading(false);
    }
  };

  const handleBrowsePath = async (filepath: string) => {
    if (!browsingBackup?.resource_id) return;
    setBackupFilePath(filepath);
    setBackupFileLoading(true);
    try {
      const r = await api.post(`/api/compute/vms/${browsingBackup.resource_id}/backups/files`, {
        volid: browsingBackup.volid, storage: browsingBackup.storage, filepath,
      });
      setBackupFiles(r.data?.files || []);
    } catch {
      setBackupFiles([]);
    } finally {
      setBackupFileLoading(false);
    }
  };

  const handleDownloadFile = (filepath: string) => {
    if (!browsingBackup?.resource_id) return;
    if (!filepath || filepath.endsWith('.didx') || filepath.endsWith('.fidx')) {
      toast('Cannot download the entire archive. Browse into it and download individual files or folders.', 'warning', 6000);
      return;
    }
    const baseName = filepath.split('/').pop() || 'download';
    toast(`Preparing download: ${baseName}...`, 'info', 8000);
    api.post(`/api/compute/vms/${browsingBackup.resource_id}/backups/download`, {
      volid: browsingBackup.volid, storage: browsingBackup.storage, filepath,
    }, { responseType: 'blob' }).then((r) => {
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement('a');
      a.href = url;
      const contentType = r.headers?.['content-type'] || '';
      const isZip = contentType.includes('zip') || (!baseName.includes('.') && r.data.size > 0);
      a.download = isZip && !baseName.endsWith('.zip') ? `${baseName}.zip` : baseName;
      a.click();
      window.URL.revokeObjectURL(url);
      toast(`Download ready: ${a.download}`, 'success');
    }).catch((e: any) => {
      toast(e?.response?.data?.detail || 'Download failed', 'error');
    });
  };

  const handleCreatePlan = async () => {
    try {
      await api.post('/api/backups/plans', planForm);
      toast('Backup plan created', 'success');
      setShowPlan(false);
      setPlanForm({ resource_id: '', name: '', schedule_cron: '0 2 * * *', backup_type: 'snapshot', retention_count: 7, retention_days: 30 });
      fetchData();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed';
      toast(msg, 'error');
    }
  };

  const handleDeletePlan = async (planId: string) => {
    try {
      await api.delete(`/api/backups/plans/${planId}`);
      toast('Plan deleted', 'success');
      fetchData();
    } catch {
      toast('Failed to delete plan', 'error');
    }
  };

  const handleTogglePlan = async (plan: BackupPlan) => {
    try {
      await api.patch(`/api/backups/plans/${plan.id}`, { is_active: !plan.is_active });
      fetchData();
    } catch {
      toast('Failed to update plan', 'error');
    }
  };

  // --- Tab config ---

  const tabs = [
    { id: 'backups', label: 'Backups', count: proxmoxBackups.length },
    { id: 'snapshots', label: 'Snapshots', count: snapshots.length },
    { id: 'plans', label: 'Backup Plans', count: plans.length },
  ];

  // --- Column definitions ---

  const backupColumns: Column<ProxmoxBackup>[] = [
    {
      key: 'resource_name', header: 'Resource',
      render: (row) => (
        <div>
          <p className="font-medium text-paws-text">{row.resource_name || 'Unknown'}</p>
          <p className="text-xs text-paws-text-dim">VMID {row.vmid} · {row.resource_type || '?'}</p>
        </div>
      ),
    },
    {
      key: 'volid', header: 'Volume',
      render: (row) => <span className="text-xs font-mono text-paws-text-dim truncate max-w-[200px] block">{row.volid}</span>,
    },
    {
      key: 'format', header: 'Format',
      render: (row) => <Badge variant={row.pbs ? 'info' : 'default'}>{row.pbs ? 'PBS' : row.format || 'vzdump'}</Badge>,
    },
    {
      key: 'size', header: 'Size',
      render: (row) => <span className="text-sm">{formatSize(row.size)}</span>,
    },
    {
      key: 'ctime', header: 'Created',
      render: (row) => <span className="text-xs text-paws-text-dim">{row.ctime ? new Date(row.ctime * 1000).toLocaleString() : '-'}</span>,
    },
    { key: 'storage', header: 'Storage', render: (row) => <Badge variant="default">{row.storage}</Badge> },
    {
      key: 'actions', header: '',
      render: (row) => (
        <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
          <Button variant="outline" size="sm" onClick={() => setShowRestore(row)} title="Restore">
            <Play className="h-3 w-3" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => handleBrowseBackup(row)} title="Browse files">
            <FolderOpen className="h-3 w-3" />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setShowDelete(row)} title="Delete">
            <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
          </Button>
        </div>
      ),
    },
  ];

  const snapshotColumns: Column<Snapshot>[] = [
    {
      key: 'resource_name', header: 'Resource',
      render: (row) => (
        <div>
          <p className="font-medium text-paws-text">{row.resource_name}</p>
          <p className="text-xs text-paws-text-dim">{row.resource_type}</p>
        </div>
      ),
    },
    { key: 'name', header: 'Snapshot', render: (row) => <span className="font-mono text-sm">{row.name}</span> },
    {
      key: 'description', header: 'Description',
      render: (row) => <span className="text-xs text-paws-text-dim">{row.description || '-'}</span>,
    },
    {
      key: 'snaptime', header: 'Created',
      render: (row) => <span className="text-xs text-paws-text-dim">{row.snaptime ? new Date(row.snaptime * 1000).toLocaleString() : '-'}</span>,
    },
    {
      key: 'actions', header: '',
      render: (row) => (
        <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
          <Button variant="outline" size="sm" onClick={() => handleRollbackSnapshot(row.resource_id, row.name)} title="Rollback">
            <Play className="h-3 w-3" />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => handleDeleteSnapshot(row.resource_id, row.name)} title="Delete">
            <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
          </Button>
        </div>
      ),
    },
  ];

  const planColumns: Column<BackupPlan>[] = [
    { key: 'name', header: 'Plan', render: (row) => <span className="font-medium text-paws-text">{row.name}</span> },
    {
      key: 'schedule_cron', header: 'Schedule',
      render: (row) => <span className="text-xs font-mono text-paws-text-dim">{row.schedule_cron}</span>,
    },
    { key: 'backup_type', header: 'Type', render: (row) => <Badge variant="default">{row.backup_type}</Badge> },
    { key: 'retention_count', header: 'Keep', render: (row) => <span>{row.retention_count} copies</span> },
    { key: 'retention_days', header: 'Retention', render: (row) => <span>{row.retention_days}d</span> },
    {
      key: 'is_active', header: 'Status',
      render: (row) => (
        <button onClick={(e) => { e.stopPropagation(); handleTogglePlan(row); }}>
          <Badge variant={row.is_active ? 'success' : 'default'}>{row.is_active ? 'Active' : 'Paused'}</Badge>
        </button>
      ),
    },
    {
      key: 'last_run_at', header: 'Last Run',
      render: (row) => <span className="text-xs text-paws-text-dim">{row.last_run_at ? new Date(row.last_run_at).toLocaleString() : 'Never'}</span>,
    },
    {
      key: 'actions', header: '',
      render: (row) => (
        <div onClick={(e) => e.stopPropagation()}>
          <Button variant="ghost" size="sm" onClick={() => handleDeletePlan(row.id)}>
            <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
          </Button>
        </div>
      ),
    },
  ];

  const resourceOptions = resources.map((r) => ({
    value: r.id,
    label: `${rName(r)} (${r.resource_type})`,
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Backups & Snapshots</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setShowSnapshot(true)}>
            <Camera className="h-4 w-4 mr-1" /> New Snapshot
          </Button>
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4 mr-1" /> Create Backup
          </Button>
        </div>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} className="mb-4" />

      {/* Backups Tab */}
      {tab === 'backups' && (
        proxmoxBackups.length === 0 && !backupsLoading ? (
          <EmptyState
            icon={Archive}
            title="No backups"
            description="Create a backup to protect your instances and data."
            action={{ label: 'Create Backup', onClick: () => setShowCreate(true) }}
          />
        ) : (
          <DataTable columns={backupColumns} data={proxmoxBackups} loading={backupsLoading} />
        )
      )}

      {/* Snapshots Tab */}
      {tab === 'snapshots' && (
        snapshots.length === 0 && !loading ? (
          <EmptyState
            icon={Camera}
            title="No snapshots"
            description="Create a snapshot to save the current state of an instance."
            action={{ label: 'New Snapshot', onClick: () => setShowSnapshot(true) }}
          />
        ) : (
          <DataTable columns={snapshotColumns} data={snapshots} loading={loading} />
        )
      )}

      {/* Plans Tab */}
      {tab === 'plans' && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={() => setShowPlan(true)}>
              <Plus className="h-4 w-4 mr-1" /> Create Plan
            </Button>
          </div>
          {plans.length === 0 && !loading ? (
            <EmptyState
              icon={Calendar}
              title="No backup plans"
              description="Create a backup plan to automate scheduled backups."
              action={{ label: 'Create Plan', onClick: () => setShowPlan(true) }}
            />
          ) : (
            <DataTable columns={planColumns} data={plans} loading={loading} />
          )}
        </div>
      )}


      {/* Create Backup Modal */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Backup">
        <div className="space-y-4">
          <Select label="Resource" placeholder="Select a resource" options={resourceOptions} value={backupForm.resource_id}
            onChange={(e) => setBackupForm({ ...backupForm, resource_id: e.target.value })} />
          <Select label="Storage" placeholder="Select storage" options={storageNames.map(s => ({ value: s, label: s }))} value={backupForm.storage}
            onChange={(e) => setBackupForm({ ...backupForm, storage: e.target.value })} />
          <Select label="Mode" options={[
            { value: 'snapshot', label: 'Snapshot (live)' },
            { value: 'suspend', label: 'Suspend' },
            { value: 'stop', label: 'Stop' },
          ]} value={backupForm.mode} onChange={(e) => setBackupForm({ ...backupForm, mode: e.target.value })} />
          <Select label="Compression" options={[
            { value: 'zstd', label: 'ZSTD (recommended)' },
            { value: 'lzo', label: 'LZO' },
            { value: 'gzip', label: 'GZIP' },
            { value: 'none', label: 'None' },
          ]} value={backupForm.compress} onChange={(e) => setBackupForm({ ...backupForm, compress: e.target.value })} />
          <Input label="Notes (optional)" value={backupForm.notes}
            onChange={(e) => setBackupForm({ ...backupForm, notes: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreateBackup} disabled={!backupForm.resource_id}>Create Backup</Button>
          </div>
        </div>
      </Modal>

      {/* Create Snapshot Modal */}
      <Modal open={showSnapshot} onClose={() => setShowSnapshot(false)} title="Create Snapshot">
        <div className="space-y-4">
          <Select label="Resource" placeholder="Select a resource" options={resourceOptions} value={snapForm.resource_id}
            onChange={(e) => setSnapForm({ ...snapForm, resource_id: e.target.value })} />
          <Input label="Snapshot Name" value={snapForm.name}
            onChange={(e) => setSnapForm({ ...snapForm, name: e.target.value })} />
          <Input label="Description (optional)" value={snapForm.description}
            onChange={(e) => setSnapForm({ ...snapForm, description: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowSnapshot(false)}>Cancel</Button>
            <Button onClick={handleCreateSnapshot} disabled={!snapForm.resource_id || !snapForm.name}>Create Snapshot</Button>
          </div>
        </div>
      </Modal>

      {/* Create Plan Modal */}
      <Modal open={showPlan} onClose={() => setShowPlan(false)} title="Create Backup Plan" size="lg">
        <div className="space-y-4">
          <Input label="Plan Name" value={planForm.name}
            onChange={(e) => setPlanForm({ ...planForm, name: e.target.value })} />
          <Select label="Resource" placeholder="Select a resource" options={resourceOptions} value={planForm.resource_id}
            onChange={(e) => setPlanForm({ ...planForm, resource_id: e.target.value })} />
          <Input label="Cron Schedule" placeholder="0 2 * * *" value={planForm.schedule_cron}
            onChange={(e) => setPlanForm({ ...planForm, schedule_cron: e.target.value })} />
          <Select label="Backup Type" options={[
            { value: 'snapshot', label: 'Snapshot' },
            { value: 'full', label: 'Full' },
          ]} value={planForm.backup_type} onChange={(e) => setPlanForm({ ...planForm, backup_type: e.target.value })} />
          <div className="grid grid-cols-2 gap-4">
            <Input label="Keep Count" type="number" value={planForm.retention_count}
              onChange={(e) => setPlanForm({ ...planForm, retention_count: +e.target.value })} />
            <Input label="Retention Days" type="number" value={planForm.retention_days}
              onChange={(e) => setPlanForm({ ...planForm, retention_days: +e.target.value })} />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowPlan(false)}>Cancel</Button>
            <Button onClick={handleCreatePlan} disabled={!planForm.name || !planForm.resource_id}>Create Plan</Button>
          </div>
        </div>
      </Modal>

      {/* Restore Confirmation */}
      <Modal open={!!showRestore} onClose={() => setShowRestore(null)} title="Restore Backup">
        <div className="space-y-4">
          <p className="text-sm text-paws-text">
            Restore backup to <strong>{showRestore?.resource_name || 'resource'}</strong>?
          </p>
          <p className="text-xs text-paws-text-dim font-mono">{showRestore?.volid}</p>
          <p className="text-xs text-paws-text-dim">
            This will replace the current state of the resource. The instance must be stopped first.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowRestore(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleRestoreBackup}>Restore</Button>
          </div>
        </div>
      </Modal>

      {/* Delete Confirmation */}
      <Modal open={!!showDelete} onClose={() => setShowDelete(null)} title="Delete Backup">
        <div className="space-y-4">
          <p className="text-sm text-paws-text">
            Permanently delete this backup?
          </p>
          <p className="text-xs text-paws-text-dim font-mono">{showDelete?.volid}</p>
          <p className="text-xs text-paws-danger">This action cannot be undone.</p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowDelete(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDeleteBackup}>Delete</Button>
          </div>
        </div>
      </Modal>

      {/* Browse Backup Files (reuses InstanceDetail pattern) */}
      <Modal open={!!browsingBackup} onClose={() => { setBrowsingBackup(null); setBackupFiles([]); setBackupFilePath(''); }}
        title={`Browse Backup - ${browsingBackup?.resource_name || ''} @ ${browsingBackup ? new Date(browsingBackup.ctime * 1000).toLocaleString() : ''}`} size="lg">
        <div className="space-y-3">
          {backupFilePath && (
            <div className="flex items-center gap-2 text-sm">
              <Button variant="ghost" size="sm" onClick={() => {
                const parent = backupFilePath.split('/').slice(0, -1).join('/');
                if (parent) handleBrowsePath(parent);
                else handleBrowseBackup(browsingBackup!);
              }}>
                &larr; Back
              </Button>
              <span className="text-paws-text-dim font-mono text-xs">{backupFilePath}</span>
            </div>
          )}
          {backupFileLoading ? (
            <p className="text-sm text-paws-text-dim py-4 text-center">Loading...</p>
          ) : backupFiles.length === 0 ? (
            <p className="text-sm text-paws-text-dim py-4 text-center">No files found.</p>
          ) : (
            <div className="max-h-96 overflow-y-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-paws-text-dim border-b border-paws-border-subtle">
                    <th className="text-left py-1">Name</th>
                    <th className="text-left py-1">Type</th>
                    <th className="text-left py-1">Size</th>
                    <th className="text-right py-1">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {backupFiles.map((f: any, i: number) => {
                    const name = f.filename || f.text || f.name || `item-${i}`;
                    const isDir = f.type === 'd' || f.type === 'directory' || f.leaf === false || f.leaf === 0;
                    const isSymlink = f.type === 'l';
                    const isBrowsable = isDir || isSymlink;
                    const typeLabel = isSymlink ? 'symlink' : isDir ? 'dir' : 'file';
                    const fullPath = backupFilePath ? `${backupFilePath}/${name}` : name;
                    return (
                      <tr key={i} className="border-b border-paws-border-subtle last:border-0">
                        <td className="py-1 text-paws-text font-mono text-xs">
                          {isBrowsable ? (
                            <button className="text-paws-accent hover:underline" onClick={() => handleBrowsePath(fullPath)}>
                              {name}/
                            </button>
                          ) : name}
                        </td>
                        <td className="py-1 text-paws-text-dim text-xs">{typeLabel}</td>
                        <td className="py-1 text-paws-text text-xs">{f.size ? formatSize(f.size) : '-'}</td>
                        <td className="py-1 text-right">
                          <Button variant="ghost" size="sm" onClick={() => handleDownloadFile(fullPath)}>
                            <Download className="h-3 w-3 mr-1" />
                            {isBrowsable ? '.zip' : 'Download'}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
