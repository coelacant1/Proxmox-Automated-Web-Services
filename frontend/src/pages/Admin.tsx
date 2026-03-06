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
import { Textarea, Modal, Select, useToast } from '@/components/ui';
import { Bug, Paperclip, Download, Users, Activity, LogIn, Globe, RefreshCw, Filter, Shield, Plus, Trash2, Pencil } from 'lucide-react';
import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Area, AreaChart, Bar, BarChart,
} from 'recharts';

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
interface PveTask {
  upid: string; node: string; vmid: number | null; type: string; type_label: string;
  status: string; pve_user: string; starttime: number; endtime: number | null;
  duration_seconds: number | null; start_iso: string | null; end_iso: string | null;
  paws: {
    resource_id: string; display_name: string; resource_type: string;
    owner_username: string | null; owner_email: string | null;
  } | null;
}
interface PveTaskDetail extends PveTask {
  exitstatus: string;
  log: string;
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
interface TierData {
  id: string; name: string; description: string | null;
  capabilities: string[]; is_default: boolean; created_at: string | null;
}
interface SystemRuleData {
  id: string; category: string; title: string; description: string;
  severity: string; sort_order: number; is_active: boolean;
  created_at: string | null; updated_at: string | null;
}
interface TemplateRequestData {
  id: string; user_id: string; username: string | null;
  resource_id: string; resource_name: string | null; resource_vmid: number | null;
  name: string; description: string | null; category: string; os_type: string | null;
  min_cpu: number; min_ram_mb: number; min_disk_gb: number;
  tags: string[]; icon_url: string | null; status: string;
  admin_notes: string | null; reviewer_name: string | null;
  reviewed_at: string | null; created_at: string | null;
}

const TABS = ['Overview', 'Analytics', 'Users', 'Tiers', 'Templates', 'Quota Requests', 'Bug Reports', 'Storage', 'Rules', 'Settings', 'Audit Log', 'Projects', 'API Keys', 'Cluster'] as const;
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
      {activeTab === 'Analytics' && <AnalyticsTab />}
      {activeTab === 'Users' && <UsersTab />}
      {activeTab === 'Tiers' && <TiersTab />}
      {activeTab === 'Templates' && <TemplatesTab />}
      {activeTab === 'Quota Requests' && <QuotaRequestsTab />}
      {activeTab === 'Bug Reports' && <BugReportsTab />}
      {activeTab === 'Storage' && <StoragePoolsTab />}
      {activeTab === 'Rules' && <RulesTab />}
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

// --- Analytics Tab -------------------------------------------------------

interface AnalyticsData {
  active_users: { username: string; email: string; role: string; last_seen: string }[];
  active_user_count: number;
  request_history: { time: string; requests: number }[];
  total_requests_today: number;
  top_endpoints: { endpoint: string; count: number }[];
  logins_by_day: { date: string; logins: number }[];
  recent_logins: { username: string; email: string; action: string; created_at: string | null }[];
}

function AnalyticsTab() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchData = () => {
    api.get('/api/dashboard/admin/analytics').then(r => setData(r.data)).catch(() => {});
  };

  useEffect(() => { fetchData(); }, []);
  useEffect(() => {
    if (!autoRefresh) return;
    const iv = setInterval(fetchData, 30000);
    return () => clearInterval(iv);
  }, [autoRefresh]);

  if (!data) return <p className="text-paws-text-muted">Loading analytics...</p>;

  const formatHour = (t: string) => {
    const d = new Date(t);
    return `${d.getHours().toString().padStart(2, '0')}:00`;
  };

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="flex gap-4 flex-wrap">
        <MetricCard label="Active Now" value={data.active_user_count} icon={Users} variant="success" className="flex-1 min-w-[160px]" />
        <MetricCard label="Requests Today" value={data.total_requests_today} icon={Activity} className="flex-1 min-w-[160px]" />
        <MetricCard label="Logins (7d)" value={data.logins_by_day.reduce((s, d) => s + d.logins, 0)} icon={LogIn} className="flex-1 min-w-[160px]" />
        <MetricCard label="Top Endpoints" value={data.top_endpoints.length} icon={Globe} className="flex-1 min-w-[160px]" />
      </div>

      <div className="flex items-center justify-between">
        <h3 className="text-paws-text font-medium">Real-Time Analytics</h3>
        <div className="flex items-center gap-2">
          <label className="text-xs text-paws-text-muted flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)}
              className="rounded border-paws-border" />
            Auto-refresh (30s)
          </label>
          <Button variant="outline" size="sm" onClick={fetchData}>Refresh</Button>
        </div>
      </div>

      {/* Request volume chart */}
      <Card>
        <CardContent>
          <h4 className="text-sm font-medium text-paws-text mb-3">Requests per Hour (Last 24h)</h4>
          <div style={{ width: '100%', height: 192, minWidth: 0 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data.request_history}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="time" tickFormatter={formatHour} tick={{ fill: '#888', fontSize: 11 }} />
                <YAxis tick={{ fill: '#888', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1a1a2e', border: '1px solid #333', borderRadius: 8 }}
                  labelStyle={{ color: '#aaa' }}
                  labelFormatter={(v) => formatHour(String(v))}
                />
                <Area type="monotone" dataKey="requests" stroke="#6366f1" fill="#6366f1" fillOpacity={0.15} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Logins per day chart */}
      {data.logins_by_day.length > 0 && (
        <Card>
          <CardContent>
            <h4 className="text-sm font-medium text-paws-text mb-3">Logins per Day (Last 7 Days)</h4>
            <div style={{ width: '100%', height: 160, minWidth: 0 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.logins_by_day}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="date" tick={{ fill: '#888', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#888', fontSize: 11 }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1a1a2e', border: '1px solid #333', borderRadius: 8 }}
                    labelStyle={{ color: '#aaa' }}
                  />
                  <Bar dataKey="logins" fill="#22c55e" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Active users */}
        <Card>
          <CardContent>
            <h4 className="text-sm font-medium text-paws-text mb-3">
              Currently Active Users
              <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-green-500/20 text-green-400">{data.active_user_count}</span>
            </h4>
            {data.active_users.length === 0 ? (
              <p className="text-sm text-paws-text-dim">No active users in the last 15 minutes</p>
            ) : (
              <div className="space-y-1.5 max-h-60 overflow-y-auto">
                {data.active_users.map((u, i) => (
                  <div key={i} className="flex items-center justify-between py-1.5 border-b border-paws-border/50">
                    <div>
                      <span className="text-sm text-paws-text">{u.username}</span>
                      <span className="text-xs text-paws-text-dim ml-2">{u.email}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="default">{u.role}</Badge>
                      <span className="text-xs text-paws-text-dim">
                        {new Date(u.last_seen).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Top endpoints */}
        <Card>
          <CardContent>
            <h4 className="text-sm font-medium text-paws-text mb-3">Top Endpoints (This Hour)</h4>
            {data.top_endpoints.length === 0 ? (
              <p className="text-sm text-paws-text-dim">No data yet</p>
            ) : (
              <div className="space-y-1 max-h-60 overflow-y-auto">
                {data.top_endpoints.map((ep, i) => (
                  <div key={i} className="flex items-center justify-between py-1 text-xs">
                    <span className="text-paws-text-muted font-mono truncate mr-2">{ep.endpoint}</span>
                    <span className="text-paws-text shrink-0">{ep.count}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent logins */}
      <Card>
        <CardContent>
          <h4 className="text-sm font-medium text-paws-text mb-3">Recent Logins</h4>
          {data.recent_logins.length === 0 ? (
            <p className="text-sm text-paws-text-dim">No recent logins</p>
          ) : (
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
              {data.recent_logins.map((l, i) => (
                <div key={i} className="flex items-center justify-between py-1.5 border-b border-paws-border/50">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-paws-text">{l.username}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      l.action.includes('oauth') ? 'bg-blue-500/20 text-blue-400' : 'bg-paws-surface text-paws-text-dim'
                    }`}>
                      {l.action.includes('oauth') ? 'OAuth' : 'Local'}
                    </span>
                  </div>
                  <span className="text-xs text-paws-text-dim">
                    {l.created_at ? new Date(l.created_at).toLocaleString() : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// --- Users Tab -----------------------------------------------------------

function UsersTab() {
  const [users, setUsers] = useState<UserData[]>([]);
  const [tiers, setTiers] = useState<TierData[]>([]);
  const fetchUsers = () => api.get('/api/admin/users/').then(r => setUsers(r.data.items ?? r.data)).catch(() => {});
  const fetchTiers = () => api.get('/api/admin/tiers/').then(r => setTiers(r.data)).catch(() => {});
  useEffect(() => { fetchUsers(); fetchTiers(); }, []);

  const toggleActive = async (id: string, active: boolean) => {
    await api.patch(`/api/admin/users/${id}/active?is_active=${active}`);
    fetchUsers();
  };
  const changeRole = async (id: string, role: string) => {
    await api.patch(`/api/admin/users/${id}/role?role=${role}`);
    fetchUsers();
  };
  const changeTier = async (userId: string, tierId: string) => {
    await api.patch(`/api/admin/tiers/users/${userId}/tier${tierId ? `?tier_id=${tierId}` : ''}`);
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
      key: 'tier_id', header: 'Tier',
      render: (u) => (
        <select
          value={(u as any).tier_id || ''}
          onChange={e => changeTier(u.id, e.target.value)}
          className="rounded border border-paws-border bg-paws-bg text-paws-text text-sm px-2 py-1"
        >
          <option value="">None</option>
          {tiers.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
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

      {/* Template Requests from users */}
      <TemplateRequestsSection />
    </div>
  );
}

function TemplateRequestsSection() {
  const [requests, setRequests] = useState<TemplateRequestData[]>([]);
  const [selected, setSelected] = useState<TemplateRequestData | null>(null);
  const [notes, setNotes] = useState('');
  const toast = useToast();

  const fetchReqs = () => api.get('/api/templates/requests').then(r => setRequests(r.data)).catch(() => {});
  useEffect(() => { fetchReqs(); }, []);

  const review = async (id: string, status: string) => {
    try {
      await api.patch(`/api/templates/requests/${id}`, { status, admin_notes: notes || null });
      toast.toast(`Request ${status}`, 'success');
      setSelected(null);
      setNotes('');
      fetchReqs();
    } catch (e: any) {
      const _d = e.response?.data?.detail; toast.toast(typeof _d === 'string' ? _d : Array.isArray(_d) ? _d.map((v: any) => v.msg).join(', ') : 'Failed', 'error');
    }
  };

  const pending = requests.filter(r => r.status === 'pending');
  const others = requests.filter(r => r.status !== 'pending');

  return (
    <div className="space-y-3">
      <h3 className="text-paws-text font-semibold">Template Requests</h3>
      {pending.length === 0 && others.length === 0 ? (
        <p className="text-paws-text-muted text-sm">No template requests yet.</p>
      ) : (
        <>
          {pending.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm text-yellow-400 font-medium">Pending ({pending.length})</h4>
              {pending.map(r => (
                <Card key={r.id}>
                  <CardContent>
                    <div className="flex justify-between items-start">
                      <div>
                        <span className="text-paws-text font-medium">{r.name}</span>
                        <span className="text-paws-text-muted text-sm ml-2">by {r.username}</span>
                        <span className="text-paws-text-muted text-xs ml-2">VMID {r.resource_vmid}</span>
                        <p className="text-xs text-paws-text-muted">{r.description || 'No description'}</p>
                        <p className="text-xs text-paws-text-muted mt-1">{r.min_cpu} vCPU, {r.min_ram_mb}MB RAM, {r.min_disk_gb}GB disk</p>
                      </div>
                      <Button size="sm" onClick={() => { setSelected(r); setNotes(''); }}>Review</Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
          {others.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm text-paws-text-muted font-medium">History</h4>
              {others.slice(0, 10).map(r => (
                <div key={r.id} className="flex items-center gap-2 text-sm py-1 border-b border-paws-border/30">
                  <Badge variant={r.status === 'completed' ? 'success' : r.status === 'rejected' ? 'danger' : 'default'}>{r.status}</Badge>
                  <span className="text-paws-text">{r.name}</span>
                  <span className="text-paws-text-muted">by {r.username}</span>
                  {r.reviewed_at && <span className="text-xs text-paws-text-muted ml-auto">{new Date(r.reviewed_at).toLocaleDateString()}</span>}
                </div>
              ))}
            </div>
          )}
        </>
      )}
      <Modal open={selected !== null} onClose={() => setSelected(null)} title="Review Template Request" size="lg">
        {selected && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div><span className="text-paws-text-muted">Name</span><p className="text-paws-text">{selected.name}</p></div>
              <div><span className="text-paws-text-muted">Requested by</span><p className="text-paws-text">{selected.username}</p></div>
              <div><span className="text-paws-text-muted">VMID</span><p className="text-paws-text font-mono">{selected.resource_vmid}</p></div>
              <div><span className="text-paws-text-muted">Category</span><p className="text-paws-text">{selected.category}</p></div>
              <div><span className="text-paws-text-muted">Specs</span><p className="text-paws-text">{selected.min_cpu} vCPU, {selected.min_ram_mb}MB, {selected.min_disk_gb}GB</p></div>
              <div><span className="text-paws-text-muted">OS Type</span><p className="text-paws-text">{selected.os_type || '-'}</p></div>
            </div>
            {selected.description && <p className="text-sm text-paws-text-muted">{selected.description}</p>}
            <Textarea placeholder="Admin notes (optional)" rows={2} value={notes} onChange={e => setNotes(e.target.value)} />
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setSelected(null)}>Cancel</Button>
              <Button variant="danger" onClick={() => review(selected.id, 'rejected')}>Reject</Button>
              <Button onClick={() => review(selected.id, 'approved')}>Approve & Convert</Button>
            </div>
          </div>
        )}
      </Modal>
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

// --- Bug Reports Tab ----------------------------------------------------

interface AdminBugReport {
  id: string; user_id: string; username: string | null; email: string | null;
  title: string; description: string; severity: string; status: string;
  admin_notes: string | null; has_attachment: boolean; attachment_filename: string | null;
  created_at: string | null; updated_at: string | null;
}

function BugReportsTab() {
  const { toast } = useToast();
  const [reports, setReports] = useState<AdminBugReport[]>([]);
  const [stats, setStats] = useState<{ total: number; open: number; in_progress: number; resolved: number } | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [selected, setSelected] = useState<AdminBugReport | null>(null);
  const [adminNotes, setAdminNotes] = useState('');
  const [newStatus, setNewStatus] = useState('');
  const [saving, setSaving] = useState(false);

  const fetchReports = () => {
    const params = statusFilter ? `?status_filter=${statusFilter}` : '';
    api.get(`/api/bug-reports/${params}`).then(r => setReports(r.data)).catch(() => {});
  };
  const fetchStats = () => {
    api.get('/api/bug-reports/stats').then(r => setStats(r.data)).catch(() => {});
  };

  useEffect(() => { fetchReports(); fetchStats(); }, [statusFilter]);

  const openReport = (r: AdminBugReport) => {
    setSelected(r);
    setAdminNotes(r.admin_notes || '');
    setNewStatus(r.status);
  };

  const handleUpdate = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const formData = new FormData();
      if (newStatus !== selected.status) formData.append('status', newStatus);
      if (adminNotes !== (selected.admin_notes || '')) formData.append('admin_notes', adminNotes);
      const res = await api.patch(`/api/bug-reports/${selected.id}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      toast('Bug report updated', 'success');
      setSelected(res.data);
      fetchReports();
      fetchStats();
    } catch {
      toast('Failed to update report', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/api/bug-reports/${id}`);
      toast('Report deleted', 'success');
      setSelected(null);
      fetchReports();
      fetchStats();
    } catch {
      toast('Failed to delete', 'error');
    }
  };

  const downloadAttachment = async (id: string, filename: string | null) => {
    try {
      const res = await api.get(`/api/bug-reports/${id}/attachment`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || 'attachment';
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      toast('Failed to download attachment', 'error');
    }
  };

  const severityColor = (s: string) => {
    switch (s) {
      case 'critical': return 'bg-red-500/20 text-red-400';
      case 'high': return 'bg-orange-500/20 text-orange-400';
      case 'medium': return 'bg-yellow-500/20 text-yellow-400';
      case 'low': return 'bg-blue-500/20 text-blue-400';
      default: return 'bg-paws-surface text-paws-text-muted';
    }
  };
  const statusColor = (s: string) => {
    switch (s) {
      case 'open': return 'bg-blue-500/20 text-blue-400';
      case 'in_progress': return 'bg-yellow-500/20 text-yellow-400';
      case 'resolved': return 'bg-green-500/20 text-green-400';
      case 'closed': return 'bg-paws-surface text-paws-text-dim';
      case 'wont_fix': return 'bg-paws-surface text-paws-text-dim';
      default: return 'bg-paws-surface text-paws-text-muted';
    }
  };

  const STATUS_OPTIONS = [
    { value: 'open', label: 'Open' }, { value: 'in_progress', label: 'In Progress' },
    { value: 'resolved', label: 'Resolved' }, { value: 'closed', label: 'Closed' },
    { value: 'wont_fix', label: "Won't Fix" },
  ];

  return (
    <div className="space-y-4">
      {stats && (
        <div className="grid grid-cols-4 gap-3">
          <MetricCard label="Total" value={stats.total} icon={Bug} />
          <MetricCard label="Open" value={stats.open} icon={Bug} />
          <MetricCard label="In Progress" value={stats.in_progress} icon={Bug} />
          <MetricCard label="Resolved" value={stats.resolved} icon={Bug} />
        </div>
      )}

      <div className="flex items-center gap-2">
        <span className="text-sm text-paws-text-muted">Filter:</span>
        {['', 'open', 'in_progress', 'resolved', 'closed'].map(s => (
          <Button key={s} size="sm" variant={statusFilter === s ? 'primary' : 'ghost'}
            onClick={() => setStatusFilter(s)}>
            {s ? s.replace('_', ' ') : 'All'}
          </Button>
        ))}
      </div>

      {reports.length === 0 ? (
        <Card><CardContent className="py-8 text-center text-paws-text-dim">No bug reports found</CardContent></Card>
      ) : (
        <div className="space-y-2">
          {reports.map(r => (
            <div key={r.id} onClick={() => openReport(r)}
              className="cursor-pointer rounded-lg border border-paws-border bg-paws-surface p-6 hover:border-paws-primary/30 transition-colors">
              <CardContent className="py-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium shrink-0 ${severityColor(r.severity)}`}>
                      {r.severity}
                    </span>
                    <span className="text-sm font-medium text-paws-text truncate">{r.title}</span>
                    {r.has_attachment && <Paperclip className="h-3.5 w-3.5 text-paws-text-dim shrink-0" />}
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-xs text-paws-text-dim">{r.username || r.email}</span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor(r.status)}`}>
                      {r.status.replace('_', ' ')}
                    </span>
                    <span className="text-xs text-paws-text-dim">
                      {r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}
                    </span>
                  </div>
                </div>
              </CardContent>
            </div>
          ))}
        </div>
      )}

      {/* Detail / respond modal */}
      <Modal open={!!selected} onClose={() => setSelected(null)}
        title={selected?.title || 'Bug Report'}>
        {selected && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${severityColor(selected.severity)}`}>
                {selected.severity}
              </span>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor(selected.status)}`}>
                {selected.status.replace('_', ' ')}
              </span>
              <span className="text-xs text-paws-text-dim">
                by {selected.username || selected.email} &middot; {selected.created_at ? new Date(selected.created_at).toLocaleString() : ''}
              </span>
            </div>

            <div className="bg-paws-surface rounded-md p-3">
              <p className="text-sm text-paws-text whitespace-pre-wrap">{selected.description}</p>
            </div>

            {selected.has_attachment && (
              <Button variant="outline" size="sm"
                onClick={() => downloadAttachment(selected.id, selected.attachment_filename)}>
                <Download className="h-4 w-4 mr-1" /> {selected.attachment_filename || 'Download Attachment'}
              </Button>
            )}

            <div className="border-t border-paws-border pt-4 space-y-3">
              <p className="text-sm font-medium text-paws-text">Admin Response</p>
              <Select label="Status" options={STATUS_OPTIONS} value={newStatus}
                onChange={e => setNewStatus(e.target.value)} />
              <Textarea label="Admin Notes" value={adminNotes} onChange={e => setAdminNotes(e.target.value)}
                placeholder="Response to the user..." rows={3} />
              <div className="flex justify-between">
                <Button variant="danger" size="sm" onClick={() => handleDelete(selected.id)}>Delete</Button>
                <Button onClick={handleUpdate} disabled={saving}>
                  {saving ? 'Saving...' : 'Update'}
                </Button>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

// --- Storage Pools Tab --------------------------------------------------

function StoragePoolsTab() {
  const [pools, setPools] = useState<string[]>([]);
  const [defaultPool, setDefaultPool] = useState('');
  const [saving, setSaving] = useState(false);
  const [availablePools, setAvailablePools] = useState<{ storage: string; type: string; shared: boolean; content: string }[]>([]);

  // Backup storages state
  const [backupStorages, setBackupStorages] = useState<string[]>([]);
  const [availableBackupStorages, setAvailableBackupStorages] = useState<{ storage: string; type: string; shared: boolean }[]>([]);
  const [savingBackup, setSavingBackup] = useState(false);

  const fetchPools = () => {
    api.get('/api/storage-pools/').then((r) => {
      setPools(r.data.pools || []);
      setDefaultPool(r.data.default || '');
    }).catch(() => {});
    api.get('/api/storage-pools/available').then((r) => {
      setAvailablePools(r.data);
    }).catch(() => {});
  };

  const fetchBackupStorages = () => {
    api.get('/api/admin/settings/backup_storages').then((r) => {
      try { setBackupStorages(JSON.parse(r.data.value)); } catch { setBackupStorages([]); }
    }).catch(() => setBackupStorages([]));
    api.get('/api/compute/backup-storages/available').then((r) => {
      setAvailableBackupStorages(r.data);
    }).catch(() => {});
  };

  useEffect(() => { fetchPools(); fetchBackupStorages(); }, []);

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

  const saveBackupStorages = async (updated: string[]) => {
    setSavingBackup(true);
    try {
      await api.patch('/api/admin/settings/backup_storages', { value: JSON.stringify(updated) });
      setBackupStorages(updated);
    } finally {
      setSavingBackup(false);
    }
  };

  const addPool = async (name: string) => {
    if (pools.includes(name)) return;
    await savePools([...pools, name]);
  };

  const removePool = async (pool: string) => {
    const updated = pools.filter((p) => p !== pool);
    const newDefault = pool === defaultPool ? (updated[0] || '') : defaultPool;
    await savePools(updated, newDefault);
  };

  const setAsDefault = async (pool: string) => {
    await savePools(pools, pool);
  };

  const addBackupStorage = async (name: string) => {
    if (backupStorages.includes(name)) return;
    await saveBackupStorages([...backupStorages, name]);
  };

  const removeBackupStorage = async (name: string) => {
    await saveBackupStorages(backupStorages.filter((s) => s !== name));
  };

  // PVE storages not yet added
  const unaddedPools = availablePools.filter((s) => !pools.includes(s.storage));
  const unaddedBackup = availableBackupStorages.filter((s) => !backupStorages.includes(s.storage));

  return (
    <div className="space-y-8">
      {/* Instance Storage Pools */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-paws-text">Instance Storage Pools</h3>
        <p className="text-sm text-paws-text-dim">
          Enable Proxmox storages for users when creating instances and volumes. Only storages that support VM/container disks are shown.
        </p>

        {unaddedPools.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {unaddedPools.map((s) => (
              <Button
                key={s.storage}
                variant="outline"
                size="sm"
                onClick={() => addPool(s.storage)}
                disabled={saving}
              >
                + {s.storage} ({s.type}{s.shared ? ', shared' : ''})
              </Button>
            ))}
          </div>
        )}

        <div className="flex flex-col gap-2">
          {pools.map((pool) => {
            const info = availablePools.find((s) => s.storage === pool);
            return (
              <Card key={pool}>
                <CardContent className="flex items-center gap-4 py-3">
                  <span className="font-medium text-paws-text flex-1">
                    {pool}
                    {info && <span className="text-paws-text-dim text-sm ml-2">({info.type}{info.shared ? ', shared' : ''})</span>}
                  </span>
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
            );
          })}
          {pools.length === 0 && (
            <p className="text-center text-paws-text-dim py-4">No storage pools configured.</p>
          )}
        </div>
      </div>

      {/* Backup Storages */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-paws-text">Backup Storages</h3>
        <p className="text-sm text-paws-text-dim">
          Enable Proxmox storages for user backups. Only storages listed here will be available to users.
        </p>

        {unaddedBackup.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {unaddedBackup.map((s) => (
              <Button
                key={s.storage}
                variant="outline"
                size="sm"
                onClick={() => addBackupStorage(s.storage)}
                disabled={savingBackup}
              >
                + {s.storage} ({s.type}{s.shared ? ', shared' : ''})
              </Button>
            ))}
          </div>
        )}

        <div className="flex flex-col gap-2">
          {backupStorages.map((name) => {
            const info = availableBackupStorages.find((s) => s.storage === name);
            return (
              <Card key={name}>
                <CardContent className="flex items-center gap-4 py-3">
                  <span className="font-medium text-paws-text flex-1">
                    {name}
                    {info && <span className="text-paws-text-dim text-sm ml-2">({info.type}{info.shared ? ', shared' : ''})</span>}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => removeBackupStorage(name)}
                    disabled={savingBackup}
                    className="text-paws-danger hover:text-red-400"
                  >
                    Remove
                  </Button>
                </CardContent>
              </Card>
            );
          })}
          {backupStorages.length === 0 && (
            <p className="text-center text-paws-text-dim py-4">No backup storages enabled. Users cannot create backups until at least one is added.</p>
          )}
        </div>
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

// --- Tiers Tab -----------------------------------------------------------

const ALL_CAPABILITIES = [
  'template.request', 'ha.manage', 'group.create', 'group.manage',
  'volume.share', 'vpc.share', 'resource.share', 'bucket.share',
];

function TiersTab() {
  const [tiers, setTiers] = useState<TierData[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<TierData | null>(null);
  const [form, setForm] = useState({ name: '', description: '', capabilities: [] as string[], is_default: false });
  const toast = useToast();

  const fetch = () => { api.get('/api/admin/tiers/').then(r => setTiers(r.data)).catch(() => {}); };
  useEffect(() => { fetch(); }, []);

  const openCreate = () => { setEditing(null); setForm({ name: '', description: '', capabilities: [], is_default: false }); setShowModal(true); };
  const openEdit = (t: TierData) => { setEditing(t); setForm({ name: t.name, description: t.description || '', capabilities: [...t.capabilities], is_default: t.is_default }); setShowModal(true); };

  const toggleCap = (cap: string) => {
    setForm(f => ({ ...f, capabilities: f.capabilities.includes(cap) ? f.capabilities.filter(c => c !== cap) : [...f.capabilities, cap] }));
  };

  const save = async () => {
    try {
      if (editing) {
        await api.patch(`/api/admin/tiers/${editing.id}`, form);
        toast.toast('Tier updated', 'success');
      } else {
        await api.post('/api/admin/tiers/', form);
        toast.toast('Tier created', 'success');
      }
      setShowModal(false);
      fetch();
    } catch (e: any) {
      const _d = e.response?.data?.detail; toast.toast(typeof _d === 'string' ? _d : Array.isArray(_d) ? _d.map((v: any) => v.msg).join(', ') : 'Failed', 'error');
    }
  };

  const remove = async (id: string) => {
    if (!confirm('Delete this tier? Users on it will be unassigned.')) return;
    await api.delete(`/api/admin/tiers/${id}`);
    toast.toast('Tier deleted', 'success');
    fetch();
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-paws-text font-semibold">User Tiers</h3>
        <Button size="sm" onClick={openCreate}>Create Tier</Button>
      </div>
      {tiers.length === 0 ? <p className="text-paws-text-muted">No tiers configured. Create one to assign capabilities to users.</p> : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {tiers.map(t => (
            <Card key={t.id}>
              <CardContent>
                <div className="flex justify-between items-start mb-2">
                  <div>
                    <span className="font-bold text-paws-text">{t.name}</span>
                    {t.is_default && <Badge variant="success" className="ml-2">Default</Badge>}
                  </div>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="sm" onClick={() => openEdit(t)}>Edit</Button>
                    <Button variant="danger" size="sm" onClick={() => remove(t.id)}>Del</Button>
                  </div>
                </div>
                {t.description && <p className="text-xs text-paws-text-muted mb-2">{t.description}</p>}
                <div className="flex flex-wrap gap-1">
                  {t.capabilities.map(c => <Badge key={c} variant="default">{c}</Badge>)}
                  {t.capabilities.length === 0 && <span className="text-xs text-paws-text-muted">No capabilities</span>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      <Modal open={showModal} onClose={() => setShowModal(false)} title={editing ? 'Edit Tier' : 'Create Tier'}>
        <div className="space-y-3">
          <Input placeholder="Tier name" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          <Textarea placeholder="Description" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <label className="flex items-center gap-2 text-sm text-paws-text">
            <input type="checkbox" checked={form.is_default} onChange={e => setForm(f => ({ ...f, is_default: e.target.checked }))} />
            Default tier for new users
          </label>
          <div>
            <span className="text-sm text-paws-text-muted">Capabilities</span>
            <div className="grid grid-cols-2 gap-2 mt-1">
              {ALL_CAPABILITIES.map(cap => (
                <label key={cap} className="flex items-center gap-2 text-sm text-paws-text cursor-pointer">
                  <input type="checkbox" checked={form.capabilities.includes(cap)} onChange={() => toggleCap(cap)} />
                  {cap}
                </label>
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowModal(false)}>Cancel</Button>
            <Button onClick={save}>{editing ? 'Save' : 'Create'}</Button>
          </div>
        </div>
      </Modal>
      <TierRequestsSection />
    </div>
  );
}

function TierRequestsSection() {
  const [requests, setRequests] = useState<any[]>([]);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState('');
  const toast = useToast();

  const fetchReqs = () => { api.get('/api/admin/tiers/requests').then(r => setRequests(r.data || [])).catch(() => {}); };
  useEffect(() => { fetchReqs(); }, []);

  const review = async (id: string, status: string) => {
    try {
      await api.patch(`/api/admin/tiers/requests/${id}`, { status, admin_notes: reviewNotes || null });
      toast.toast(`Request ${status}`, 'success');
      setReviewId(null);
      setReviewNotes('');
      fetchReqs();
    } catch (e: any) {
      const d = e.response?.data?.detail;
      toast.toast(typeof d === 'string' ? d : 'Failed', 'error');
    }
  };

  const pending = requests.filter((r: any) => r.status === 'pending');
  const past = requests.filter((r: any) => r.status !== 'pending');

  return (
    <div className="space-y-3 mt-6">
      <h3 className="text-paws-text font-semibold">Tier Requests</h3>
      {pending.length === 0 && past.length === 0 && <p className="text-paws-text-muted text-sm">No tier requests.</p>}
      {pending.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-paws-text-muted">{pending.length} pending request{pending.length > 1 ? 's' : ''}</p>
          {pending.map((r: any) => (
            <Card key={r.id}>
              <CardContent>
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-paws-text font-medium">{r.username || r.email}</span>
                    <span className="text-paws-text-muted mx-2">&rarr;</span>
                    <span className="text-paws-text font-medium">{r.tier_name}</span>
                    {r.reason && <p className="text-xs text-paws-text-muted mt-0.5">Reason: {r.reason}</p>}
                  </div>
                  <div className="flex gap-1">
                    {reviewId === r.id ? (
                      <div className="flex items-center gap-2">
                        <input className="bg-paws-bg border border-paws-border rounded px-2 py-1 text-sm text-paws-text w-40" placeholder="Notes (optional)" value={reviewNotes} onChange={e => setReviewNotes(e.target.value)} />
                        <Button size="sm" onClick={() => review(r.id, 'approved')}>Approve</Button>
                        <Button size="sm" variant="danger" onClick={() => review(r.id, 'rejected')}>Reject</Button>
                        <Button size="sm" variant="ghost" onClick={() => setReviewId(null)}>Cancel</Button>
                      </div>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => { setReviewId(r.id); setReviewNotes(''); }}>Review</Button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {past.length > 0 && (
        <details className="text-sm">
          <summary className="text-paws-text-muted cursor-pointer">Past requests ({past.length})</summary>
          <div className="space-y-1 mt-2">
            {past.map((r: any) => (
              <div key={r.id} className="flex items-center gap-3 text-xs py-1">
                <span className="text-paws-text">{r.username}</span>
                <span className="text-paws-text-muted">&rarr;</span>
                <span className="text-paws-text">{r.tier_name}</span>
                <Badge variant={r.status === 'approved' ? 'success' : 'danger'}>{r.status}</Badge>
                {r.reviewed_by && <span className="text-paws-text-muted">by {r.reviewed_by}</span>}
                {r.created_at && <span className="text-paws-text-muted">{new Date(r.created_at).toLocaleDateString()}</span>}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

// --- Rules Tab -----------------------------------------------------------

const RULE_CATEGORIES = ['General', 'Compute', 'Storage', 'Network', 'Security', 'Other'];
const RULE_SEVERITIES = ['info', 'warning', 'restriction'];

function RulesTab() {
  const [rules, setRules] = useState<SystemRuleData[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<SystemRuleData | null>(null);
  const [form, setForm] = useState({ category: 'General', title: '', description: '', severity: 'info', sort_order: 0, is_active: true });
  const toast = useToast();

  const fetch = () => { api.get('/api/admin/rules').then(r => setRules(r.data)).catch(() => {}); };
  useEffect(() => { fetch(); }, []);

  const openCreate = () => { setEditing(null); setForm({ category: 'General', title: '', description: '', severity: 'info', sort_order: rules.length, is_active: true }); setShowModal(true); };
  const openEdit = (r: SystemRuleData) => { setEditing(r); setForm({ category: r.category, title: r.title, description: r.description, severity: r.severity, sort_order: r.sort_order, is_active: r.is_active }); setShowModal(true); };

  const save = async () => {
    try {
      if (editing) {
        await api.patch(`/api/admin/rules/${editing.id}`, form);
        toast.toast('Rule updated', 'success');
      } else {
        await api.post('/api/admin/rules', form);
        toast.toast('Rule created', 'success');
      }
      setShowModal(false);
      fetch();
    } catch (e: any) {
      const d = e.response?.data?.detail;
      const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((v: any) => v.msg).join(', ') : 'Failed';
      toast.toast(msg, 'error');
    }
  };

  const remove = async (id: string) => {
    if (!confirm('Delete this rule?')) return;
    await api.delete(`/api/admin/rules/${id}`);
    toast.toast('Rule deleted', 'success');
    fetch();
  };

  const severityColor = (s: string) => s === 'restriction' ? 'text-red-400' : s === 'warning' ? 'text-yellow-400' : 'text-blue-400';

  // Group by category
  const grouped = rules.reduce<Record<string, SystemRuleData[]>>((acc, r) => {
    (acc[r.category] = acc[r.category] || []).push(r);
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-paws-text font-semibold">System Rules & Restrictions</h3>
        <Button size="sm" onClick={openCreate}>Add Rule</Button>
      </div>
      {rules.length === 0 ? <p className="text-paws-text-muted">No rules defined. Add rules to display on the user-facing System Rules page.</p> : (
        Object.entries(grouped).map(([cat, items]) => (
          <div key={cat}>
            <h4 className="text-paws-text font-medium mb-2">{cat}</h4>
            <div className="space-y-2">
              {items.map(r => (
                <Card key={r.id} className={!r.is_active ? 'opacity-50' : ''}>
                  <CardContent>
                    <div className="flex justify-between items-start">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className={`font-medium ${severityColor(r.severity)}`}>{r.severity.toUpperCase()}</span>
                          <span className="text-paws-text font-medium">{r.title}</span>
                          {!r.is_active && <Badge variant="default">Inactive</Badge>}
                        </div>
                        <p className="text-sm text-paws-text-muted mt-1 whitespace-pre-wrap">{r.description}</p>
                      </div>
                      <div className="flex gap-1 ml-2">
                        <Button variant="ghost" size="sm" onClick={() => openEdit(r)}>Edit</Button>
                        <Button variant="danger" size="sm" onClick={() => remove(r.id)}>Del</Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        ))
      )}
      <Modal open={showModal} onClose={() => setShowModal(false)} title={editing ? 'Edit Rule' : 'Add Rule'} size="lg">
        <div className="space-y-3">
          <Select label="Category" options={RULE_CATEGORIES.map(c => ({ value: c, label: c }))} value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))} />
          <Input label="Title" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} />
          <Textarea label="Description" rows={4} value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <div className="flex gap-4">
            <Select label="Severity" options={RULE_SEVERITIES.map(s => ({ value: s, label: s }))} value={form.severity} onChange={e => setForm(f => ({ ...f, severity: e.target.value }))} />
            <Input label="Display Order" type="number" value={form.sort_order} onChange={e => setForm(f => ({ ...f, sort_order: parseInt(e.target.value) || 0 }))} />
          </div>
          <label className="flex items-center gap-2 text-sm text-paws-text">
            <input type="checkbox" checked={form.is_active} onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} />
            Active (visible to users)
          </label>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowModal(false)}>Cancel</Button>
            <Button onClick={save}>{editing ? 'Save' : 'Create'}</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// --- Cluster Tab ---------------------------------------------------------

function ClusterTab() {
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  const [tasks, setTasks] = useState<PveTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [nodeFilter, setNodeFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [selectedTask, setSelectedTask] = useState<PveTaskDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  // HA Groups
  const [haGroups, setHaGroups] = useState<any[]>([]);
  const [showHaForm, setShowHaForm] = useState(false);
  const [editingHa, setEditingHa] = useState<any | null>(null);
  const [haForm, setHaForm] = useState({ name: '', description: '', pve_group_name: '', nodes: '', restricted: false, nofailback: false, max_relocate: 1, max_restart: 1 });
  const toast = useToast();

  const fetchStatus = () => {
    api.get('/api/cluster/status').then(r => setStatus(r.data)).catch(() => {});
  };

  const fetchTasks = () => {
    setTasksLoading(true);
    const params = new URLSearchParams();
    params.set('limit', '200');
    if (nodeFilter) params.set('node', nodeFilter);
    if (typeFilter) params.set('type', typeFilter);
    if (errorsOnly) params.set('errors_only', 'true');
    api.get(`/api/cluster/admin/tasks?${params}`)
      .then(r => setTasks(r.data.tasks ?? []))
      .catch(() => {})
      .finally(() => setTasksLoading(false));
  };

  const fetchHaGroups = () => {
    api.get('/api/admin/ha/groups').then(r => setHaGroups(r.data)).catch(() => {});
  };

  const openHaForm = (group?: any) => {
    if (group) {
      setEditingHa(group);
      setHaForm({ name: group.name, description: group.description || '', pve_group_name: group.pve_group_name, nodes: (group.nodes || []).join(','), restricted: group.restricted, nofailback: group.nofailback, max_relocate: group.max_relocate, max_restart: group.max_restart });
    } else {
      setEditingHa(null);
      setHaForm({ name: '', description: '', pve_group_name: '', nodes: '', restricted: false, nofailback: false, max_relocate: 1, max_restart: 1 });
    }
    setShowHaForm(true);
  };

  const saveHaGroup = async () => {
    try {
      const payload = { ...haForm, nodes: haForm.nodes.split(',').map(n => n.trim()).filter(Boolean) };
      if (editingHa) {
        await api.patch(`/api/admin/ha/groups/${editingHa.id}`, payload);
        toast.toast('HA group updated', 'success');
      } else {
        await api.post('/api/admin/ha/groups', payload);
        toast.toast('HA group created', 'success');
      }
      setShowHaForm(false);
      fetchHaGroups();
    } catch (e: any) {
      const _d = e.response?.data?.detail; toast.toast(typeof _d === 'string' ? _d : Array.isArray(_d) ? _d.map((v: any) => v.msg).join(', ') : 'Failed', 'error');
    }
  };

  const deleteHaGroup = async (id: string) => {
    if (!confirm('Delete this HA group? This will also remove it from PVE.')) return;
    try {
      await api.delete(`/api/admin/ha/groups/${id}`);
      toast.toast('HA group deleted', 'success');
      fetchHaGroups();
    } catch (e: any) {
      const _d = e.response?.data?.detail; toast.toast(typeof _d === 'string' ? _d : Array.isArray(_d) ? _d.map((v: any) => v.msg).join(', ') : 'Failed', 'error');
    }
  };

  const syncHaGroups = async () => {
    try {
      const r = await api.post('/api/admin/ha/groups/sync');
      toast.toast(r.data.detail, 'success');
      fetchHaGroups();
    } catch (e: any) {
      toast.toast(e.response?.data?.detail || 'Failed to sync', 'error');
    }
  };

  useEffect(() => { fetchStatus(); fetchTasks(); fetchHaGroups(); }, []);
  useEffect(() => { fetchTasks(); }, [nodeFilter, typeFilter, errorsOnly]);

  useEffect(() => {
    if (!autoRefresh) return;
    const iv = setInterval(() => { fetchStatus(); fetchTasks(); }, 15000);
    return () => clearInterval(iv);
  }, [autoRefresh, nodeFilter, typeFilter, errorsOnly]);

  const openTaskDetail = (task: PveTask) => {
    setDetailLoading(true);
    setSelectedTask(null);
    api.get(`/api/cluster/admin/tasks/${encodeURIComponent(task.node)}/${encodeURIComponent(task.upid)}`)
      .then(r => setSelectedTask(r.data))
      .catch(() => setSelectedTask({ ...task, exitstatus: 'fetch error', log: 'Failed to load task log.' }))
      .finally(() => setDetailLoading(false));
  };

  const fmtDuration = (s: number | null) => {
    if (s === null || s === undefined) return '-';
    if (s < 1) return '<1s';
    if (s < 60) return `${Math.round(s)}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  };

  const fmtTime = (iso: string | null) => {
    if (!iso) return '-';
    return new Date(iso).toLocaleString();
  };

  const statusColor = (st: string) => {
    if (!st || st === 'running') return 'text-blue-400';
    if (st === 'OK') return 'text-green-400';
    return 'text-red-400';
  };

  // Unique nodes/types for filter dropdowns
  const nodeNames = status?.nodes.map(n => n.name) ?? [];
  const typeOptions = [...new Set(tasks.map(t => t.type))].sort();

  if (!status) return <p className="text-paws-text-muted">Loading...</p>;

  return (
    <div className="space-y-6">
      {/* Cluster overview metrics */}
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
      <div className="flex gap-3 flex-wrap mb-6">
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

      {/* HA Groups */}
      <div className="flex items-center justify-between mt-6">
        <h3 className="text-paws-text text-lg font-semibold flex items-center gap-2"><Shield className="w-5 h-5" /> HA Groups</h3>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={syncHaGroups}><RefreshCw className="w-4 h-4 mr-1" />Sync from PVE</Button>
          <Button size="sm" onClick={() => openHaForm()}><Plus className="w-4 h-4 mr-1" />Create</Button>
        </div>
      </div>
      {haGroups.length === 0 ? (
        <p className="text-paws-text-muted text-sm">No HA groups configured. Sync from PVE or create one.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {haGroups.map(g => (
            <Card key={g.id}>
              <CardContent>
                <div className="flex items-start justify-between">
                  <div>
                    <h4 className="text-paws-text font-medium">{g.name}</h4>
                    <p className="text-xs text-paws-text-muted">PVE: {g.pve_group_name}</p>
                  </div>
                  <div className="flex gap-1">
                    <button onClick={() => openHaForm(g)} className="p-1 text-paws-text-muted hover:text-paws-text"><Pencil className="w-4 h-4" /></button>
                    <button onClick={() => deleteHaGroup(g.id)} className="p-1 text-paws-text-muted hover:text-red-400"><Trash2 className="w-4 h-4" /></button>
                  </div>
                </div>
                {g.description && <p className="text-xs text-paws-text-muted mt-1">{g.description}</p>}
                <div className="flex flex-wrap gap-1 mt-2">
                  {(g.nodes || []).map((n: string) => <Badge key={n} variant="info">{n}</Badge>)}
                </div>
                <div className="flex gap-3 mt-2 text-xs text-paws-text-muted">
                  <span>Relocate: {g.max_relocate}</span>
                  <span>Restart: {g.max_restart}</span>
                  {g.nofailback && <span className="text-yellow-400">No failback</span>}
                  {g.restricted && <Badge variant="warning">Restricted</Badge>}
                  {!g.is_active && <Badge variant="danger">Inactive</Badge>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* HA Group Form Modal */}
      <Modal open={showHaForm} onClose={() => setShowHaForm(false)} title={editingHa ? 'Edit HA Group' : 'Create HA Group'}>
        <div className="space-y-3">
          <Input label="Display Name" value={haForm.name} onChange={e => setHaForm(f => ({ ...f, name: e.target.value }))} />
          {!editingHa && <Input label="PVE Group Name" value={haForm.pve_group_name} onChange={e => setHaForm(f => ({ ...f, pve_group_name: e.target.value }))} />}
          <Input label="Description" value={haForm.description} onChange={e => setHaForm(f => ({ ...f, description: e.target.value }))} />
          <Input label="Nodes (comma-separated)" value={haForm.nodes} onChange={e => setHaForm(f => ({ ...f, nodes: e.target.value }))} placeholder="node1,node2,node3" />
          <div className="flex gap-4">
            <Input label="Max Relocate" type="number" value={haForm.max_relocate} onChange={e => setHaForm(f => ({ ...f, max_relocate: parseInt(e.target.value) || 1 }))} />
            <Input label="Max Restart" type="number" value={haForm.max_restart} onChange={e => setHaForm(f => ({ ...f, max_restart: parseInt(e.target.value) || 1 }))} />
          </div>
          <label className="flex items-center gap-2 text-sm text-paws-text">
            <input type="checkbox" checked={haForm.nofailback} onChange={e => setHaForm(f => ({ ...f, nofailback: e.target.checked }))} />
            No failback (don't migrate back to original node)
          </label>
          <label className="flex items-center gap-2 text-sm text-paws-text">
            <input type="checkbox" checked={haForm.restricted} onChange={e => setHaForm(f => ({ ...f, restricted: e.target.checked }))} />
            Restricted (only users with ha.manage capability)
          </label>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowHaForm(false)}>Cancel</Button>
            <Button onClick={saveHaGroup} disabled={!haForm.name || (!editingHa && !haForm.pve_group_name)}>{editingHa ? 'Update' : 'Create'}</Button>
          </div>
        </div>
      </Modal>

      {/* Task History */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-paws-text text-lg font-semibold">Cluster Task History</h3>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1">
            <Filter className="w-4 h-4 text-paws-text-muted" />
          </div>
          <select
            className="bg-paws-card border border-paws-border rounded px-2 py-1 text-sm text-paws-text"
            value={nodeFilter}
            onChange={e => setNodeFilter(e.target.value)}
          >
            <option value="">All Nodes</option>
            {nodeNames.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
          <select
            className="bg-paws-card border border-paws-border rounded px-2 py-1 text-sm text-paws-text"
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
          >
            <option value="">All Types</option>
            {typeOptions.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <label className="flex items-center gap-1 text-sm text-paws-text-muted cursor-pointer">
            <input type="checkbox" checked={errorsOnly} onChange={e => setErrorsOnly(e.target.checked)} />
            Errors only
          </label>
          <label className="flex items-center gap-1 text-sm text-paws-text-muted cursor-pointer ml-2">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
            Auto-refresh
          </label>
          <Button variant="ghost" size="sm" onClick={() => { fetchStatus(); fetchTasks(); }} title="Refresh now">
            <RefreshCw className={`w-4 h-4 ${tasksLoading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {tasksLoading && tasks.length === 0 ? (
        <p className="text-paws-text-muted">Loading tasks...</p>
      ) : tasks.length === 0 ? (
        <p className="text-paws-text-muted">No tasks found.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead>
              <tr className="border-b border-paws-border text-paws-text-muted">
                <th className="py-2 px-3 font-medium">Time</th>
                <th className="py-2 px-3 font-medium">Node</th>
                <th className="py-2 px-3 font-medium">Task</th>
                <th className="py-2 px-3 font-medium">VMID</th>
                <th className="py-2 px-3 font-medium">Status</th>
                <th className="py-2 px-3 font-medium">Duration</th>
                <th className="py-2 px-3 font-medium">PVE User</th>
                <th className="py-2 px-3 font-medium">PAWS Owner</th>
                <th className="py-2 px-3 font-medium">Resource</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.upid} className="border-b border-paws-border/50 hover:bg-paws-card/50 cursor-pointer" onClick={() => openTaskDetail(t)}>
                  <td className="py-2 px-3 text-paws-text whitespace-nowrap">{fmtTime(t.start_iso)}</td>
                  <td className="py-2 px-3">
                    <Badge variant="default">{t.node}</Badge>
                  </td>
                  <td className="py-2 px-3 text-paws-text">{t.type_label}</td>
                  <td className="py-2 px-3 text-paws-text font-mono">{t.vmid ?? '-'}</td>
                  <td className={`py-2 px-3 font-medium ${statusColor(t.status)}`}>
                    {t.status || 'running'}
                  </td>
                  <td className="py-2 px-3 text-paws-text-muted">{fmtDuration(t.duration_seconds)}</td>
                  <td className="py-2 px-3 text-paws-text-muted text-xs">{t.pve_user || '-'}</td>
                  <td className="py-2 px-3">
                    {t.paws ? (
                      <span className="text-paws-accent font-medium" title={t.paws.owner_email ?? ''}>
                        {t.paws.owner_username || '-'}
                      </span>
                    ) : (
                      <span className="text-paws-text-muted">-</span>
                    )}
                  </td>
                  <td className="py-2 px-3">
                    {t.paws ? (
                      <span className="text-paws-text text-xs" title={t.paws.resource_id}>
                        {t.paws.display_name}
                        <Badge variant="default" className="ml-1 text-[10px]">{t.paws.resource_type}</Badge>
                      </span>
                    ) : (
                      <span className="text-paws-text-muted text-xs">system</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-paws-text-muted">
        Showing {tasks.length} tasks. Tasks with a PAWS Owner are linked to user-owned resources.
      </p>

      {/* Task Detail Modal */}
      <Modal
        open={detailLoading || selectedTask !== null}
        onClose={() => { setSelectedTask(null); setDetailLoading(false); }}
        title={selectedTask ? `${selectedTask.type_label} — ${selectedTask.node}` : 'Loading Task...'}
        size="xl"
      >
        {detailLoading ? (
          <p className="text-paws-text-muted py-8 text-center">Loading task details...</p>
        ) : selectedTask ? (
          <div className="space-y-4">
            {/* Meta grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
              <div>
                <span className="text-paws-text-muted">Status</span>
                <p className={`font-medium ${selectedTask.exitstatus === 'OK' ? 'text-green-400' : selectedTask.status === 'running' ? 'text-blue-400' : 'text-red-400'}`}>
                  {selectedTask.exitstatus || selectedTask.status || 'running'}
                </p>
              </div>
              <div>
                <span className="text-paws-text-muted">Node</span>
                <p className="text-paws-text">{selectedTask.node}</p>
              </div>
              <div>
                <span className="text-paws-text-muted">VMID</span>
                <p className="text-paws-text font-mono">{selectedTask.vmid ?? '-'}</p>
              </div>
              <div>
                <span className="text-paws-text-muted">Started</span>
                <p className="text-paws-text">{fmtTime(selectedTask.start_iso)}</p>
              </div>
              <div>
                <span className="text-paws-text-muted">Ended</span>
                <p className="text-paws-text">{fmtTime(selectedTask.end_iso)}</p>
              </div>
              <div>
                <span className="text-paws-text-muted">Duration</span>
                <p className="text-paws-text">{fmtDuration(selectedTask.duration_seconds)}</p>
              </div>
              <div>
                <span className="text-paws-text-muted">PVE User</span>
                <p className="text-paws-text">{selectedTask.pve_user || '-'}</p>
              </div>
              {selectedTask.paws && (
                <>
                  <div>
                    <span className="text-paws-text-muted">PAWS Owner</span>
                    <p className="text-paws-accent font-medium">{selectedTask.paws.owner_username}</p>
                    <p className="text-xs text-paws-text-muted">{selectedTask.paws.owner_email}</p>
                  </div>
                  <div>
                    <span className="text-paws-text-muted">Resource</span>
                    <p className="text-paws-text">
                      {selectedTask.paws.display_name}
                      <Badge variant="default" className="ml-1 text-[10px]">{selectedTask.paws.resource_type}</Badge>
                    </p>
                  </div>
                </>
              )}
            </div>

            {/* UPID */}
            <div>
              <span className="text-xs text-paws-text-muted">UPID</span>
              <p className="text-xs text-paws-text font-mono break-all bg-paws-bg/50 rounded px-2 py-1">{selectedTask.upid}</p>
            </div>

            {/* Task Log */}
            <div>
              <span className="text-sm text-paws-text-muted font-medium">Task Output</span>
              <pre className="mt-1 bg-[#0d1117] text-[#c9d1d9] rounded-md p-3 text-xs font-mono overflow-auto max-h-80 whitespace-pre-wrap border border-paws-border">
                {selectedTask.log || '(no log output)'}
              </pre>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
