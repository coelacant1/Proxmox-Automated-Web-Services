import { useState, useEffect } from 'react';
import api from '../api/client';
import { useAuth } from '../context/AuthContext';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { DataTable } from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import { MetricCard } from '@/components/ui/MetricCard';

// --- Types ---------------------------------------------------------------

interface UserData {
  id: string; email: string; username: string; full_name: string | null;
  role: string; is_active: boolean; auth_provider: string; created_at: string;
}
interface Template {
  id: string; proxmox_vmid: number; name: string; description: string | null;
  os_type: string | null; category: string; min_cpu: number; min_ram_mb: number;
  min_disk_gb: number; icon_url: string | null; is_active: boolean;
  tags: string[] | null; created_at: string;
}
interface QuotaRequest {
  id: string; user_id: string; request_type: string; current_value: number;
  requested_value: number; reason: string; status: string;
  admin_notes: string | null; reviewed_by: string | null;
  created_at: string; reviewed_at: string | null;
}
interface Setting {
  key: string; value: string; description: string | null; updated_at: string;
}
interface AuditEntry {
  id: string; user_id: string; action: string; resource_type: string | null;
  resource_id: string | null; details: string | null; created_at: string | null;
}
interface ClusterStatus {
  api_reachable: boolean; cluster_name: string | null; node_count: number;
  nodes_online: number; nodes: { name: string; status: string; uptime_seconds: number }[];
  quorate: boolean;
}
interface AdminOverview {
  total_users: number; active_users: number; total_resources: Record<string, number>;
  active_resources: number; pending_quota_requests: number;
  recent_users: { username: string; email: string; created_at: string }[];
}
interface ProjectData {
  id: string; name: string; slug: string; description: string | null;
  owner_id: string; is_personal: boolean; created_at: string;
}
interface ProjectMemberData {
  id: string; project_id: string; user_id: string; role: string; created_at: string;
}
export interface ApiKeyData {
  id: string; name: string; prefix: string; created_at: string;
  expires_at: string | null; is_active: boolean; user_id: string;
}

const TABS = ['Overview', 'Users', 'Templates', 'Quota Requests', 'Storage', 'Settings', 'Audit Log', 'Projects', 'API Keys', 'Cluster'] as const;
type Tab = typeof TABS[number];

// Helper type to satisfy DataTable's Record<string, unknown> constraint
type TableRow<T> = T & Record<string, unknown>;

// --- Main Component -----------------------------------------------------

export default function Admin() {
  const [activeTab, setActiveTab] = useState<Tab>('Overview');
  const { user } = useAuth();

  if (user?.role !== 'admin') {
    return <p className="text-paws-danger">Access denied. Admin only.</p>;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-paws-text">Administration</h1>
      <div className="flex gap-1 flex-wrap">
        {TABS.map((tab) => (
          <Button
            key={tab}
            variant={activeTab === tab ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </Button>
        ))}
      </div>
      {activeTab === 'Overview' && <OverviewTab />}
      {activeTab === 'Users' && <UsersTab />}
      {activeTab === 'Templates' && <TemplatesTab />}
      {activeTab === 'Quota Requests' && <QuotaRequestsTab />}
      {activeTab === 'Storage' && <StoragePoolsTab />}
      {activeTab === 'Settings' && <SettingsTab />}
      {activeTab === 'Audit Log' && <AuditLogTab />}
      {activeTab === 'Projects' && <ProjectsTab />}
      {activeTab === 'API Keys' && <ApiKeysTab onSwitchTab={setActiveTab} />}
      {activeTab === 'Cluster' && <ClusterTab />}
    </div>
  );
}

// --- Overview Tab --------------------------------------------------------

function OverviewTab() {
  const [data, setData] = useState<AdminOverview | null>(null);
  useEffect(() => { api.get('/api/dashboard/admin/overview').then(r => setData(r.data)).catch(() => {}); }, []);
  if (!data) return <p className="text-paws-text-muted">Loading...</p>;

  const stats: { label: string; value: number; variant: 'default' | 'success' | 'warning' | 'danger' }[] = [
    { label: 'Total Users', value: data.total_users, variant: 'default' },
    { label: 'Active Users', value: data.active_users, variant: 'success' },
    { label: 'Active Resources', value: data.active_resources, variant: 'default' },
    { label: 'Pending Quota Requests', value: data.pending_quota_requests, variant: 'warning' },
  ];

  return (
    <div className="space-y-6">
      <div className="flex gap-4 flex-wrap mb-8">
        {stats.map(s => (
          <MetricCard key={s.label} label={s.label} value={s.value} variant={s.variant} className="flex-1 min-w-[180px]" />
        ))}
      </div>

      <h3 className="mb-2 text-paws-text">Resources by Type</h3>
      <Card className="mb-4">
        <CardContent>
          {Object.entries(data.total_resources).length === 0
            ? <p className="text-paws-text-dim">No resources</p>
            : Object.entries(data.total_resources).map(([type, count]) => (
                <div key={type} className="flex justify-between py-2 border-b border-paws-border-subtle">
                  <span className="text-paws-text">{type}</span>
                  <span className="text-paws-text-muted">{count}</span>
                </div>
              ))}
        </CardContent>
      </Card>

      <h3 className="mb-2 text-paws-text">Recent Users</h3>
      <Card>
        <CardContent>
          {data.recent_users.map(u => (
            <div key={u.username} className="flex justify-between py-2 border-b border-paws-border-subtle">
              <span className="text-paws-text">
                {u.username} <span className="text-paws-text-dim">({u.email})</span>
              </span>
              <span className="text-paws-text-muted text-xs">{new Date(u.created_at).toLocaleDateString()}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// --- Users Tab -----------------------------------------------------------

function UsersTab() {
  const [users, setUsers] = useState<UserData[]>([]);
  const fetchUsers = () => api.get('/api/admin/users/').then(r => setUsers(r.data.items ?? r.data)).catch(() => {});
  useEffect(() => { fetchUsers(); }, []);

  const toggleActive = async (id: string, active: boolean) => {
    await api.patch(`/api/admin/users/${id}/active?is_active=${active}`);
    fetchUsers();
  };
  const changeRole = async (id: string, role: string) => {
    await api.patch(`/api/admin/users/${id}/role?role=${role}`);
    fetchUsers();
  };
  const deleteUser = async (id: string) => {
    if (!confirm('Delete this user and all their resources?')) return;
    await api.delete(`/api/admin/users/${id}`);
    fetchUsers();
  };

  const columns: Column<TableRow<UserData>>[] = [
    { key: 'username', header: 'Username' },
    { key: 'email', header: 'Email' },
    {
      key: 'role', header: 'Role',
      render: (u) => (
        <select
          value={u.role}
          onChange={e => changeRole(u.id, e.target.value)}
          className="rounded border border-paws-border bg-paws-bg text-paws-text text-sm px-2 py-1"
        >
          <option value="admin">admin</option>
          <option value="operator">operator</option>
          <option value="member">member</option>
          <option value="viewer">viewer</option>
        </select>
      ),
    },
    {
      key: 'is_active', header: 'Status',
      render: (u) => <StatusBadge status={u.is_active ? 'active' : 'offline'} />,
    },
    { key: 'auth_provider', header: 'Provider' },
    {
      key: 'actions', header: 'Actions',
      render: (u) => (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => toggleActive(u.id, !u.is_active)}>
            {u.is_active ? 'Disable' : 'Enable'}
          </Button>
          <Button variant="danger" size="sm" onClick={() => deleteUser(u.id)}>Delete</Button>
        </div>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      data={users as TableRow<UserData>[]}
      emptyMessage="No users found."
    />
  );
}

// --- Templates Tab -------------------------------------------------------

function TemplatesTab() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [available, setAvailable] = useState<any[]>([]);
  const [showPicker, setShowPicker] = useState(false);
  const [selected, setSelected] = useState<any | null>(null);
  const [form, setForm] = useState({ name: '', description: '', min_cpu: 1, min_ram_mb: 512, min_disk_gb: 10 });

  const fetchTemplates = () => api.get('/api/admin/templates/?include_inactive=true').then(r => setTemplates(r.data)).catch(() => {});
  const fetchAvailable = () => api.get('/api/admin/templates/proxmox-available').then(r => setAvailable(r.data)).catch(() => {});
  useEffect(() => { fetchTemplates(); }, []);

  const openPicker = () => {
    fetchAvailable();
    setShowPicker(true);
    setSelected(null);
  };

  const selectTemplate = (t: any) => {
    setSelected(t);
    setForm({
      name: t.name,
      description: '',
      min_cpu: t.cpu || 1,
      min_ram_mb: t.ram_mb || 512,
      min_disk_gb: t.disk_gb || 10,
    });
  };

  const createTemplate = async () => {
    if (!selected) return;
    await api.post('/api/admin/templates/', {
      proxmox_vmid: selected.vmid,
      name: form.name,
      description: form.description || null,
      os_type: selected.os_type,
      category: selected.category,
      min_cpu: form.min_cpu,
      min_ram_mb: form.min_ram_mb,
      min_disk_gb: form.min_disk_gb,
      tags: selected.tags?.length ? selected.tags : null,
    });
    setShowPicker(false);
    setSelected(null);
    fetchTemplates();
  };

  const toggleActive = async (id: string, active: boolean) => {
    await api.patch(`/api/admin/templates/${id}`, { is_active: active });
    fetchTemplates();
  };
  const deleteTemplate = async (id: string) => {
    if (!confirm('Remove this template from catalog?')) return;
    await api.delete(`/api/admin/templates/${id}`);
    fetchTemplates();
  };

  const osLabel = (os: string) => {
    const icons: Record<string, string> = { linux: '🐧', windows: '🪟', bsd: '😈', other: '💻' };
    return `${icons[os] || '💻'} ${os}`;
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-paws-text">Template Catalog</h3>
        <Button variant="primary" size="sm" onClick={() => showPicker ? setShowPicker(false) : openPicker()}>
          {showPicker ? 'Cancel' : '+ Add from Proxmox'}
        </Button>
      </div>

      {/* Template Picker */}
      {showPicker && !selected && (
        <Card className="mb-4">
          <CardContent>
            <p className="text-paws-text-muted text-sm mb-3">
              Select a Proxmox template to add to the user catalog:
            </p>
            {available.length === 0 ? (
              <p className="text-paws-text-dim">No available templates (all already in catalog or none found).</p>
            ) : (
              <div className="flex flex-col gap-2">
                {available.map((t: any) => (
                  <div
                    key={t.vmid}
                    onClick={() => selectTemplate(t)}
                    className="flex justify-between items-center px-4 py-3 rounded-md cursor-pointer border border-paws-border bg-paws-bg hover:bg-paws-surface-hover"
                  >
                    <div>
                      <span className="font-bold text-paws-text">{t.name}</span>
                      <span className="text-paws-text-dim text-xs ml-3">
                        VMID {t.vmid} · {t.node}
                      </span>
                    </div>
                    <div className="flex gap-3 items-center text-paws-text-muted text-xs">
                      <span>{osLabel(t.os_type)}</span>
                      <Badge variant={t.category === 'vm' ? 'info' : 'primary'}>{t.category.toUpperCase()}</Badge>
                      <span>{t.cpu} vCPU · {t.ram_mb} MB · {t.disk_gb} GB</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Configure Selected Template */}
      {showPicker && selected && (
        <Card className="mb-4">
          <CardContent>
            <div className="flex justify-between items-center mb-3">
              <div className="flex items-center gap-2">
                <span className="font-bold text-paws-text">Configuring: </span>
                <span className="text-paws-text">{osLabel(selected.os_type)} </span>
                <Badge variant={selected.category === 'vm' ? 'info' : 'primary'}>{selected.category.toUpperCase()}</Badge>
                <span className="text-paws-text-dim text-sm"> · VMID {selected.vmid}</span>
              </div>
              <Button variant="outline" size="sm" onClick={() => setSelected(null)}>← Back</Button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Input label="Display Name" value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })} />
              <Input label="Min vCPUs" type="number" value={form.min_cpu}
                onChange={e => setForm({ ...form, min_cpu: parseInt(e.target.value) || 1 })} />
              <Input label="Min RAM (MB)" type="number" value={form.min_ram_mb}
                onChange={e => setForm({ ...form, min_ram_mb: parseInt(e.target.value) || 512 })} />
              <Input label="Min Disk (GB)" type="number" value={form.min_disk_gb}
                onChange={e => setForm({ ...form, min_disk_gb: parseInt(e.target.value) || 10 })} />
              <div className="col-span-2">
                <label className="block text-xs text-paws-text-muted mb-1">Description (optional)</label>
                <textarea
                  className="w-full rounded border border-paws-border bg-paws-bg text-paws-text text-sm px-2 py-1 min-h-[60px]"
                  value={form.description}
                  onChange={e => setForm({ ...form, description: e.target.value })}
                />
              </div>
              <div className="col-span-2">
                <Button variant="primary" className="w-full" onClick={createTemplate}>
                  Add to Catalog
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Catalog List */}
      <div className="flex flex-col gap-3">
        {templates.map(t => (
          <Card key={t.id}>
            <CardContent className="flex items-center justify-between">
              <div>
                <p className="font-bold text-paws-text">{t.name}</p>
                <p className="text-sm text-paws-text-dim">
                  VMID {t.proxmox_vmid} · {t.min_cpu} vCPU · {t.min_ram_mb} MB · {t.min_disk_gb} GB
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Badge variant={t.category === 'vm' ? 'info' : 'primary'}>{t.category.toUpperCase()}</Badge>
                <span className="text-sm text-paws-text-muted">{t.os_type ? osLabel(t.os_type) : '-'}</span>
                <StatusBadge status={t.is_active ? 'active' : 'stopped'} />
                <Button variant="outline" size="sm" onClick={() => toggleActive(t.id, !t.is_active)}>
                  {t.is_active ? 'Disable' : 'Enable'}
                </Button>
                <Button variant="danger" size="sm" onClick={() => deleteTemplate(t.id)}>Delete</Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

// --- Quota Requests Tab --------------------------------------------------

function QuotaRequestsTab() {
  const [requests, setRequests] = useState<QuotaRequest[]>([]);
  const [filter, setFilter] = useState('pending');
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});

  const fetchRequests = () => api.get(`/api/admin/quota-requests/?status_filter=${filter}`).then(r => setRequests(r.data.items ?? r.data)).catch(() => {});
  useEffect(() => { fetchRequests(); }, [filter]);

  const review = async (id: string, status: string) => {
    await api.patch(`/api/admin/quota-requests/${id}`, { status, admin_notes: reviewNotes[id] || null });
    fetchRequests();
  };

  return (
    <div className="space-y-6">
      <div className="flex gap-2 mb-4">
        {['pending', 'approved', 'denied'].map(s => (
          <Button
            key={s}
            variant={filter === s ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setFilter(s)}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </Button>
        ))}
      </div>
      {requests.length === 0 ? <p className="text-paws-text-dim">No {filter} requests.</p> : (
        <div className="flex flex-col gap-3">
          {requests.map(qr => (
            <Card key={qr.id}>
              <CardContent>
                <div className="flex justify-between mb-2">
                  <span className="text-paws-text"><strong>{qr.request_type}</strong>: {qr.current_value} → {qr.requested_value}</span>
                  <StatusBadge status={qr.status} />
                </div>
                <p className="text-sm text-paws-text-muted">{qr.reason}</p>
                <p className="text-xs text-paws-text-dim mt-1">
                  Submitted {new Date(qr.created_at).toLocaleString()}
                </p>
                {qr.status === 'pending' && (
                  <div className="mt-3 flex gap-2 items-center">
                    <Input
                      placeholder="Admin notes (optional)"
                      className="flex-1"
                      value={reviewNotes[qr.id] || ''}
                      onChange={e => setReviewNotes({ ...reviewNotes, [qr.id]: e.target.value })}
                    />
                    <Button variant="success" size="sm" onClick={() => review(qr.id, 'approved')}>Approve</Button>
                    <Button variant="danger" size="sm" onClick={() => review(qr.id, 'denied')}>Deny</Button>
                  </div>
                )}
                {qr.admin_notes && (
                  <p className="text-xs text-paws-text-muted mt-2 italic">
                    Admin: {qr.admin_notes}
                  </p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Storage Pools Tab --------------------------------------------------

function StoragePoolsTab() {
  const [pools, setPools] = useState<string[]>([]);
  const [defaultPool, setDefaultPool] = useState('');
  const [newPool, setNewPool] = useState('');
  const [saving, setSaving] = useState(false);

  const fetchPools = () => {
    api.get('/api/storage-pools/').then((r) => {
      setPools(r.data.pools || []);
      setDefaultPool(r.data.default || '');
    }).catch(() => {});
  };
  useEffect(() => { fetchPools(); }, []);

  const savePools = async (updatedPools: string[], updatedDefault?: string) => {
    setSaving(true);
    try {
      await api.patch('/api/admin/settings/storage_pools', { value: JSON.stringify(updatedPools) });
      if (updatedDefault !== undefined) {
        await api.patch('/api/admin/settings/default_storage_pool', { value: updatedDefault });
      }
      fetchPools();
    } finally {
      setSaving(false);
    }
  };

  const addPool = async () => {
    const name = newPool.trim();
    if (!name || pools.includes(name)) return;
    const updated = [...pools, name];
    await savePools(updated);
    setNewPool('');
  };

  const removePool = async (pool: string) => {
    const updated = pools.filter((p) => p !== pool);
    const newDefault = pool === defaultPool ? (updated[0] || '') : defaultPool;
    await savePools(updated, newDefault);
  };

  const setAsDefault = async (pool: string) => {
    await savePools(pools, pool);
  };

  return (
    <div className="space-y-6">
      <p className="text-sm text-paws-text-dim">
        Configure shared storage pools available to users when creating instances and volumes.
      </p>

      <div className="flex gap-2 items-end">
        <Input
          label="Add Storage Pool"
          placeholder="e.g. ceph-pool, shared-nfs"
          value={newPool}
          onChange={(e) => setNewPool(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addPool()}
        />
        <Button variant="primary" size="sm" onClick={addPool} disabled={!newPool.trim() || saving}>
          Add
        </Button>
      </div>

      <div className="flex flex-col gap-2">
        {pools.map((pool) => (
          <Card key={pool}>
            <CardContent className="flex items-center gap-4 py-3">
              <span className="font-medium text-paws-text flex-1">{pool}</span>
              {pool === defaultPool ? (
                <Badge variant="default">Default</Badge>
              ) : (
                <Button variant="ghost" size="sm" onClick={() => setAsDefault(pool)} disabled={saving}>
                  Set Default
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => removePool(pool)}
                disabled={saving || pools.length <= 1}
                className="text-paws-danger hover:text-red-400"
              >
                Remove
              </Button>
            </CardContent>
          </Card>
        ))}
        {pools.length === 0 && (
          <p className="text-center text-paws-text-dim py-4">No storage pools configured.</p>
        )}
      </div>
    </div>
  );
}

// --- Settings Tab --------------------------------------------------------

function SettingsTab() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [editValues, setEditValues] = useState<Record<string, string>>({});

  const fetchSettings = () => api.get('/api/admin/settings/').then(r => {
    setSettings(r.data);
    const vals: Record<string, string> = {};
    r.data.forEach((s: Setting) => { vals[s.key] = s.value; });
    setEditValues(vals);
  }).catch(() => {});
  useEffect(() => { fetchSettings(); }, []);

  const save = async (key: string) => {
    await api.patch(`/api/admin/settings/${key}`, { value: editValues[key] });
    fetchSettings();
  };

  return (
    <div className="flex flex-col gap-4">
      {settings.map(s => (
        <Card key={s.key}>
          <CardContent className="flex gap-4 items-center">
            <div className="flex-1">
              <p className="font-bold text-sm text-paws-text">{s.key}</p>
              <p className="text-xs text-paws-text-dim">{s.description}</p>
            </div>
            <Input
              className="w-[200px]"
              value={editValues[s.key] || ''}
              onChange={e => setEditValues({ ...editValues, [s.key]: e.target.value })}
            />
            <Button
              variant="primary"
              size="sm"
              onClick={() => save(s.key)}
              disabled={editValues[s.key] === s.value}
            >
              Save
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// --- Audit Log Tab -------------------------------------------------------

function AuditLogTab() {
  const [logs, setLogs] = useState<AuditEntry[]>([]);
  const [actionFilter, setActionFilter] = useState('');

  const fetchLogs = () => {
    const params = actionFilter ? `?action=${actionFilter}` : '';
    api.get(`/api/admin/audit-logs/${params}`).then(r => setLogs(r.data.items ?? r.data)).catch(() => {});
  };
  useEffect(() => { fetchLogs(); }, [actionFilter]);

  const columns: Column<TableRow<AuditEntry>>[] = [
    {
      key: 'created_at', header: 'Time',
      render: (l) => <span>{l.created_at ? new Date(l.created_at).toLocaleString() : '-'}</span>,
    },
    { key: 'action', header: 'Action' },
    {
      key: 'resource_type', header: 'Resource Type',
      render: (l) => <span>{l.resource_type || '-'}</span>,
    },
    {
      key: 'details', header: 'Details',
      className: 'max-w-xs truncate',
      render: (l) => <span className="block max-w-xs truncate">{l.details || '-'}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="mb-4 max-w-xs">
        <Input
          placeholder="Filter by action..."
          value={actionFilter}
          onChange={e => setActionFilter(e.target.value)}
        />
      </div>
      <DataTable
        columns={columns}
        data={logs as TableRow<AuditEntry>[]}
        emptyMessage="No audit logs found."
      />
    </div>
  );
}

// --- Projects Tab --------------------------------------------------------

function ProjectsTab() {
  const [projects, setProjects] = useState<ProjectData[]>([]);
  const [selectedProject, setSelectedProject] = useState<ProjectData | null>(null);
  const [members, setMembers] = useState<ProjectMemberData[]>([]);

  useEffect(() => {
    api.get('/api/projects/').then(r => setProjects(r.data.items || [])).catch(() => {});
  }, []);

  const viewMembers = (project: ProjectData) => {
    setSelectedProject(project);
    api.get(`/api/projects/${project.id}/members`).then(r => setMembers(r.data.items || [])).catch(() => setMembers([]));
  };

  const columns: Column<TableRow<ProjectData>>[] = [
    { key: 'name', header: 'Name' },
    { key: 'slug', header: 'Slug' },
    { key: 'owner_id', header: 'Owner' },
    {
      key: 'is_personal', header: 'Personal',
      render: (p) => <Badge variant={p.is_personal ? 'default' : 'info'}>{p.is_personal ? 'Personal' : 'Team'}</Badge>,
    },
    {
      key: 'created_at', header: 'Created',
      render: (p) => <span>{new Date(p.created_at).toLocaleDateString()}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <DataTable
        columns={columns}
        data={projects as TableRow<ProjectData>[]}
        emptyMessage="No projects found."
        onRowClick={(p) => viewMembers(p)}
      />
      {selectedProject && (
        <Card className="mt-4">
          <CardContent>
            <div className="flex justify-between items-center mb-3">
              <h4 className="text-paws-text font-bold">Members of "{selectedProject.name}"</h4>
              <Button variant="ghost" size="sm" onClick={() => setSelectedProject(null)}>Close</Button>
            </div>
            {members.length === 0 ? (
              <p className="text-paws-text-dim">No members found.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {members.map(m => (
                  <div key={m.id} className="flex justify-between py-2 border-b border-paws-border-subtle">
                    <span className="text-paws-text text-sm">{m.user_id}</span>
                    <Badge variant="default">{m.role}</Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// --- API Keys Tab --------------------------------------------------------

function ApiKeysTab({ onSwitchTab }: { onSwitchTab: (tab: Tab) => void }) {
  return (
    <Card>
      <CardContent>
        <h4 className="text-paws-text font-bold mb-2">API Key Management</h4>
        <p className="text-paws-text-muted text-sm">
          API keys are managed by individual users via their profile or the <code className="text-paws-text">/api/api-keys</code> endpoints.
          Admins can view user activity through the Audit Log tab.
        </p>
        <div className="mt-4">
          <Button variant="outline" size="sm" onClick={() => onSwitchTab('Audit Log')}>
            View Audit Log
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// --- Cluster Tab ---------------------------------------------------------

function ClusterTab() {
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  useEffect(() => { api.get('/api/cluster/status').then(r => setStatus(r.data)).catch(() => {}); }, []);
  if (!status) return <p className="text-paws-text-muted">Loading...</p>;

  return (
    <div className="space-y-6">
      <div className="flex gap-4 mb-6 flex-wrap">
        <MetricCard
          label="API Status"
          value={status.api_reachable ? 'Connected' : 'Unreachable'}
          variant={status.api_reachable ? 'success' : 'danger'}
          className="flex-1 min-w-[180px]"
        />
        <MetricCard
          label="Cluster"
          value={status.cluster_name || 'N/A'}
          className="flex-1 min-w-[180px]"
        />
        <MetricCard
          label="Nodes Online"
          value={`${status.nodes_online} / ${status.node_count}`}
          className="flex-1 min-w-[180px]"
        />
        <MetricCard
          label="Quorum"
          value={status.quorate ? 'OK' : 'Lost'}
          variant={status.quorate ? 'success' : 'danger'}
          className="flex-1 min-w-[180px]"
        />
      </div>

      <h3 className="mb-2 text-paws-text">Nodes</h3>
      <div className="flex gap-3 flex-wrap">
        {status.nodes.map(n => (
          <Card key={n.name} className="flex-1 min-w-[200px]">
            <CardContent>
              <div className="flex items-center gap-2 mb-2">
                <StatusBadge status={n.status} />
                <span className="font-bold text-paws-text">{n.name}</span>
              </div>
              <p className="text-xs text-paws-text-muted">
                Uptime: {n.uptime_seconds >= 86400 ? `${Math.floor(n.uptime_seconds / 86400)}d ` : ''}{Math.floor((n.uptime_seconds % 86400) / 3600)}h {Math.floor((n.uptime_seconds % 3600) / 60)}m
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
