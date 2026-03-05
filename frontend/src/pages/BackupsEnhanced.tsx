import { useEffect, useState } from 'react';
import { Archive, Plus, Trash2, Play, Calendar } from 'lucide-react';
import api from '../api/client';
import {
  Button, DataTable, Input, Modal, Select, Badge, StatusBadge,
  EmptyState, Tabs, type Column,
} from '@/components/ui';

interface Backup {
  id: string;
  resource_id: string;
  resource_name: string;
  type: string;
  status: string;
  size_mb: number;
  created_at: string;
  retention_days: number;
  [key: string]: unknown;
}

interface BackupPlan {
  id: string;
  name: string;
  schedule_cron: string;
  resource_ids: string[];
  retention_days: number;
  enabled: boolean;
  last_run: string | null;
  [key: string]: unknown;
}

export default function BackupsEnhanced() {
  const [backups, setBackups] = useState<Backup[]>([]);
  const [plans, setPlans] = useState<BackupPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('backups');
  const [showCreate, setShowCreate] = useState(false);
  const [showPlan, setShowPlan] = useState(false);
  const [showRestore, setShowRestore] = useState<Backup | null>(null);
  const [form, setForm] = useState({ resource_id: '', type: 'snapshot' });
  const [planForm, setPlanForm] = useState({
    name: '', schedule_cron: '0 2 * * *', resource_ids: '', retention_days: 30, enabled: true,
  });

  const fetchData = () => {
    Promise.all([
      api.get('/api/backups/').catch(() => ({ data: [] })),
      api.get('/api/backups/plans').catch(() => ({ data: [] })),
    ]).then(([backupRes, planRes]) => {
      setBackups(backupRes.data);
      setPlans(planRes.data);
      setLoading(false);
    });
  };

  useEffect(fetchData, []);

  const handleCreateBackup = async () => {
    await api.post('/api/backups/', form);
    setShowCreate(false);
    setForm({ resource_id: '', type: 'snapshot' });
    fetchData();
  };

  const handleCreatePlan = async () => {
    await api.post('/api/backups/plans', {
      ...planForm,
      resource_ids: planForm.resource_ids.split(',').map((s) => s.trim()).filter(Boolean),
    });
    setShowPlan(false);
    setPlanForm({ name: '', schedule_cron: '0 2 * * *', resource_ids: '', retention_days: 30, enabled: true });
    fetchData();
  };

  const handleRestore = async () => {
    if (!showRestore) return;
    await api.post(`/api/backups/${showRestore.id}/restore`);
    setShowRestore(null);
    fetchData();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this backup?')) return;
    await api.delete(`/api/backups/${id}`);
    fetchData();
  };

  const tabs = [
    { id: 'backups', label: 'Backups', count: backups.length },
    { id: 'plans', label: 'Backup Plans', count: plans.length },
  ];

  const backupColumns: Column<Backup>[] = [
    {
      key: 'resource_name',
      header: 'Resource',
      render: (row) => (
        <div>
          <p className="font-medium text-paws-text">{row.resource_name || row.resource_id}</p>
          <p className="text-xs text-paws-text-dim font-mono">{row.id.slice(0, 8)}</p>
        </div>
      ),
    },
    { key: 'type', header: 'Type', render: (row) => <Badge variant="default">{row.type}</Badge> },
    { key: 'status', header: 'Status', render: (row) => <StatusBadge status={row.status} /> },
    { key: 'size_mb', header: 'Size', render: (row) => <span className="text-sm">{row.size_mb} MB</span> },
    {
      key: 'created_at',
      header: 'Created',
      render: (row) => <span className="text-xs text-paws-text-dim">{new Date(row.created_at).toLocaleString()}</span>,
    },
    {
      key: 'actions',
      header: '',
      render: (row) => (
        <div className="flex gap-1">
          <Button variant="outline" size="sm" onClick={() => setShowRestore(row)}>
            <Play className="h-3 w-3 mr-1" /> Restore
          </Button>
          <Button variant="ghost" size="sm" onClick={() => handleDelete(row.id)}>
            <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
          </Button>
        </div>
      ),
    },
  ];

  const planColumns: Column<BackupPlan>[] = [
    { key: 'name', header: 'Plan', render: (row) => <span className="font-medium text-paws-text">{row.name}</span> },
    {
      key: 'schedule_cron',
      header: 'Schedule',
      render: (row) => <span className="text-xs font-mono text-paws-text-dim">{row.schedule_cron}</span>,
    },
    {
      key: 'resources',
      header: 'Resources',
      render: (row) => <Badge variant="default">{row.resource_ids?.length || 0}</Badge>,
    },
    { key: 'retention_days', header: 'Retention', render: (row) => <span>{row.retention_days}d</span> },
    {
      key: 'enabled',
      header: 'Status',
      render: (row) => <Badge variant={row.enabled ? 'success' : 'default'}>{row.enabled ? 'Active' : 'Paused'}</Badge>,
    },
    {
      key: 'last_run',
      header: 'Last Run',
      render: (row) => (
        <span className="text-xs text-paws-text-dim">{row.last_run ? new Date(row.last_run).toLocaleString() : 'Never'}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Backups</h1>
        <div className="flex gap-2">
          {tab === 'backups' ? (
            <Button onClick={() => setShowCreate(true)}>
              <Plus className="h-4 w-4 mr-1" /> Create Backup
            </Button>
          ) : (
            <Button onClick={() => setShowPlan(true)}>
              <Plus className="h-4 w-4 mr-1" /> Create Plan
            </Button>
          )}
        </div>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} className="mb-4" />

      {tab === 'backups' && (
        backups.length === 0 && !loading ? (
          <EmptyState
            icon={Archive}
            title="No backups"
            description="Create a backup to protect your instances and data."
            action={{ label: 'Create Backup', onClick: () => setShowCreate(true) }}
          />
        ) : (
          <DataTable columns={backupColumns} data={backups} loading={loading} />
        )
      )}

      {tab === 'plans' && (
        plans.length === 0 && !loading ? (
          <EmptyState
            icon={Calendar}
            title="No backup plans"
            description="Create a backup plan to automate scheduled backups."
            action={{ label: 'Create Plan', onClick: () => setShowPlan(true) }}
          />
        ) : (
          <DataTable columns={planColumns} data={plans} loading={loading} />
        )
      )}

      {/* Create Backup Modal */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Backup">
        <div className="space-y-4">
          <Input label="Resource ID" value={form.resource_id}
            onChange={(e) => setForm({ ...form, resource_id: e.target.value })} />
          <Select label="Type" options={[
            { value: 'snapshot', label: 'Snapshot' },
            { value: 'full', label: 'Full Backup' },
          ]} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreateBackup} disabled={!form.resource_id}>Create</Button>
          </div>
        </div>
      </Modal>

      {/* Create Plan Modal */}
      <Modal open={showPlan} onClose={() => setShowPlan(false)} title="Create Backup Plan" size="lg">
        <div className="space-y-4">
          <Input label="Plan Name" value={planForm.name}
            onChange={(e) => setPlanForm({ ...planForm, name: e.target.value })} />
          <Input label="Cron Schedule" placeholder="0 2 * * *" value={planForm.schedule_cron}
            onChange={(e) => setPlanForm({ ...planForm, schedule_cron: e.target.value })} />
          <Input label="Resource IDs (comma-separated)" value={planForm.resource_ids}
            onChange={(e) => setPlanForm({ ...planForm, resource_ids: e.target.value })} />
          <Input label="Retention (days)" type="number" value={planForm.retention_days}
            onChange={(e) => setPlanForm({ ...planForm, retention_days: +e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowPlan(false)}>Cancel</Button>
            <Button onClick={handleCreatePlan} disabled={!planForm.name}>Create Plan</Button>
          </div>
        </div>
      </Modal>

      {/* Restore Modal */}
      <Modal open={!!showRestore} onClose={() => setShowRestore(null)} title="Restore Backup">
        <div className="space-y-4">
          <p className="text-sm text-paws-text">
            Restore backup <strong>{showRestore?.id?.slice(0, 8)}</strong> for resource <strong>{showRestore?.resource_name || showRestore?.resource_id}</strong>?
          </p>
          <p className="text-xs text-paws-text-dim">
            This will replace the current state of the resource. Existing data may be lost.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowRestore(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleRestore}>Restore</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
