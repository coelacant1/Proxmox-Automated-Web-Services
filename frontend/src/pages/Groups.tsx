import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { Tabs } from '@/components/ui/Tabs';
import { Modal, Textarea, Select, useToast } from '@/components/ui';
import {
  Users, Plus, Trash2, Share2, ArrowLeft, Play, Square,
  RotateCcw, HardDrive, Network, Key, Shield, Globe, Database,
  Bell, Server, Terminal, Archive, ExternalLink, KeyRound, Copy, AlertTriangle,
} from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';

interface Group {
  id: string; name: string; description: string | null;
  owner_id: string; owner_username: string | null;
  created_at: string | null; member_count: number;
}
interface Member {
  id: string; user_id: string; username: string | null;
  email: string | null; role: string; joined_at: string | null;
}
interface DashboardItem {
  share_id: string; entity_id: string; entity_name: string;
  permission: string; shared_by: string;
  [key: string]: any;
}
interface DashboardData {
  types: Record<string, { label: string; items: DashboardItem[] }>;
}
interface EntityOption {
  id: string; name: string; type: string; label: string;
}

const TYPE_ICONS: Record<string, React.ReactNode> = {
  resource: <Server className="w-4 h-4" />,
  vpc: <Network className="w-4 h-4" />,
  volume: <HardDrive className="w-4 h-4" />,
  bucket: <Database className="w-4 h-4" />,
  endpoint: <Globe className="w-4 h-4" />,
  ssh_key: <Key className="w-4 h-4" />,
  security_group: <Shield className="w-4 h-4" />,
  dns_record: <Globe className="w-4 h-4" />,
  backup: <Archive className="w-4 h-4" />,
  alarm: <Bell className="w-4 h-4" />,
};

const STATUS_VARIANT: Record<string, 'success' | 'danger' | 'warning' | 'info' | 'default'> = {
  running: 'success', active: 'success', enabled: 'success',
  stopped: 'danger', error: 'danger', failed: 'danger', alarm: 'danger',
  pending: 'warning', creating: 'warning', attaching: 'warning',
  available: 'info', ok: 'info', completed: 'info',
};

const ENTITY_TYPES_LABELS: Record<string, string> = {
  resource: 'Instance', vpc: 'VPC', volume: 'Volume', bucket: 'Bucket',
  endpoint: 'Endpoint', ssh_key: 'SSH Key', security_group: 'Security Group',
  dns_record: 'DNS Record', backup: 'Backup', alarm: 'Alarm',
};

function toastErr(toast: any, e: any, fallback: string) {
  const d = e.response?.data?.detail;
  toast.toast(typeof d === 'string' ? d : Array.isArray(d) ? d.map((v: any) => v.msg).join(', ') : fallback, 'error');
}

function PermBadge({ perm }: { perm: string }) {
  const v = perm === 'admin' ? 'danger' : perm === 'operate' ? 'warning' : 'info';
  return <Badge variant={v}>{perm}</Badge>;
}

// Maps entity types to their detail routes (null = no detail page, use modal)
function getEntityRoute(type: string, item: DashboardItem): string | null {
  switch (type) {
    case 'resource':
      if (item.resource_type === 'vm') return `/vms/${item.entity_id}`;
      if (item.resource_type === 'lxc') return `/containers/${item.entity_id}`;
      return `/resources/${item.entity_id}`;
    case 'backup': return `/backups/${item.entity_id}`;
    default: return null;
  }
}

// ---- Instance row with inline actions ----
function InstanceRow({ item, canOperate, canAdmin, onUnshare, onAction, toast, onNavigate }: {
  item: DashboardItem; canOperate: boolean; canAdmin: boolean;
  onUnshare: () => void; onAction: (id: string, action: string) => Promise<void>; toast: any;
  onNavigate: (route: string, perm: string) => void;
}) {
  const [acting, setActing] = useState('');
  const doAction = async (action: string) => {
    setActing(action);
    try { await onAction(item.entity_id, action); }
    finally { setActing(''); }
  };
  const status = item.status || 'unknown';
  const route = getEntityRoute('resource', item);
  return (
    <div className="flex items-center justify-between px-3 py-2.5 rounded bg-paws-card border border-paws-border">
      <div className="flex items-center gap-3 min-w-0">
        <Server className="w-4 h-4 text-paws-accent shrink-0" />
        <span
          className={`text-paws-text font-medium truncate ${route ? 'cursor-pointer hover:text-paws-accent hover:underline' : ''}`}
          onClick={() => route && onNavigate(route, item.permission)}
        >
          {item.entity_name}
          {route && <ExternalLink className="w-3 h-3 inline ml-1 opacity-50" />}
        </span>
        {item.resource_type && <Badge variant="default">{item.resource_type}</Badge>}
        <Badge variant={STATUS_VARIANT[status] || 'default'}>{status}</Badge>
        {item.proxmox_vmid && <span className="text-xs text-paws-text-muted">VMID {item.proxmox_vmid}</span>}
        {item.proxmox_node && <span className="text-xs text-paws-text-muted">{item.proxmox_node}</span>}
        <PermBadge perm={item.permission} />
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {canOperate && (
          <>
            <Button variant="ghost" size="sm" onClick={() => doAction('start')} disabled={!!acting || status === 'running'} title="Start">
              <Play className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => doAction('shutdown')} disabled={!!acting || status === 'stopped'} title="Shutdown">
              <Square className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => doAction('reboot')} disabled={!!acting || status === 'stopped'} title="Reboot">
              <RotateCcw className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="sm" onClick={async () => {
              try {
                const r = await api.post(`/api/compute/vms/${item.entity_id}/console`);
                const url = r.data?.url;
                if (url) window.open(url, '_blank');
                else toast.toast('Console not available', 'warning');
              } catch { toast.toast('Console failed', 'error'); }
            }} title="Console">
              <Terminal className="w-3.5 h-3.5" />
            </Button>
          </>
        )}
        {canAdmin && (
          <Button variant="ghost" size="sm" onClick={onUnshare} title="Unshare">
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        )}
      </div>
    </div>
  );
}

// ---- Generic entity row for non-instance types ----
function EntityRow({ item, entityType, detailFields, canAdmin, onUnshare, onNavigate, onShowDetail }: {
  item: DashboardItem; entityType: string;
  detailFields: { key: string; label: string; format?: (v: any) => string }[];
  canAdmin: boolean; onUnshare: () => void;
  onNavigate: (route: string, perm: string) => void;
  onShowDetail: (item: DashboardItem, type: string) => void;
}) {
  const status = item.status || item.state;
  const route = getEntityRoute(entityType, item);
  return (
    <div className="flex items-center justify-between px-3 py-2.5 rounded bg-paws-card border border-paws-border">
      <div className="flex items-center gap-3 min-w-0 flex-wrap">
        {TYPE_ICONS[entityType] || <Database className="w-4 h-4 text-paws-accent shrink-0" />}
        <span
          className="text-paws-text font-medium truncate cursor-pointer hover:text-paws-accent hover:underline"
          onClick={() => route ? onNavigate(route, item.permission) : onShowDetail(item, entityType)}
        >
          {item.entity_name}
          <ExternalLink className="w-3 h-3 inline ml-1 opacity-50" />
        </span>
        {status && <Badge variant={STATUS_VARIANT[status] || 'default'}>{status}</Badge>}
        {detailFields.map(f => {
          const val = item[f.key];
          if (val === null || val === undefined) return null;
          return (
            <span key={f.key} className="text-xs text-paws-text-muted">
              {f.label}: {f.format ? f.format(val) : String(val)}
            </span>
          );
        })}
        <PermBadge perm={item.permission} />
      </div>
      {canAdmin && (
        <Button variant="ghost" size="sm" onClick={onUnshare} title="Unshare" className="shrink-0">
          <Trash2 className="w-3.5 h-3.5" />
        </Button>
      )}
    </div>
  );
}

// Detail fields shown inline for each entity type
const DETAIL_FIELDS: Record<string, { key: string; label: string; format?: (v: any) => string }[]> = {
  vpc: [{ key: 'cidr', label: 'CIDR' }, { key: 'gateway', label: 'GW' }],
  volume: [
    { key: 'size_gib', label: 'Size', format: (v: any) => `${v} GiB` },
    { key: 'storage_pool', label: 'Pool' },
    { key: 'disk_slot', label: 'Slot' },
  ],
  bucket: [
    { key: 'object_count', label: 'Objects' },
    { key: 'size_bytes', label: 'Size', format: (v: any) => v >= 1073741824 ? `${(v / 1073741824).toFixed(1)} GB` : v >= 1048576 ? `${(v / 1048576).toFixed(1)} MB` : `${v} B` },
  ],
  endpoint: [
    { key: 'protocol', label: 'Proto' },
    { key: 'internal_port', label: 'Port' },
    { key: 'subdomain', label: 'Sub' },
  ],
  ssh_key: [{ key: 'fingerprint', label: 'FP' }],
  security_group: [{ key: 'description', label: 'Desc' }],
  dns_record: [
    { key: 'record_type', label: 'Type' },
    { key: 'value', label: 'Value' },
    { key: 'ttl', label: 'TTL' },
  ],
  backup: [
    { key: 'backup_type', label: 'Type' },
    { key: 'size_bytes', label: 'Size', format: (v: any) => v >= 1073741824 ? `${(v / 1073741824).toFixed(1)} GB` : v >= 1048576 ? `${(v / 1048576).toFixed(1)} MB` : `${v} B` },
    { key: 'proxmox_storage', label: 'Storage' },
  ],
  alarm: [
    { key: 'metric', label: 'Metric' },
    { key: 'comparison', label: 'Op' },
    { key: 'threshold', label: 'Thresh' },
  ],
};

export default function Groups() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [groupDetail, setGroupDetail] = useState<(Group & { members: Member[]; my_role?: string }) | null>(null);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [showCreate, setShowCreate] = useState(false);
  const [showAddMember, setShowAddMember] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [showDetail, setShowDetail] = useState<{ item: DashboardItem; type: string } | null>(null);
  const [groupTokens, setGroupTokens] = useState<any[]>([]);
  const [showCreateToken, setShowCreateToken] = useState(false);
  const [tokenName, setTokenName] = useState('');
  const [newTokenRaw, setNewTokenRaw] = useState<string | null>(null);
  const [showRawToken, setShowRawToken] = useState(false);
  const [createForm, setCreateForm] = useState({ name: '', description: '' });
  const [memberForm, setMemberForm] = useState({ username: '', role: 'member' });
  const [shareForm, setShareForm] = useState({ entity_type: '', entity_id: '', permission: 'read' });
  const [myEntities, setMyEntities] = useState<Record<string, EntityOption[]>>({});
  const [entityTypeFilter, setEntityTypeFilter] = useState('');
  const [loadingGroups, setLoadingGroups] = useState(true);
  const [revokeTarget, setRevokeTarget] = useState<any | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<string | null>(null);
  const toast = useToast();
  const navigate = useNavigate();

  const navigateToEntity = (route: string, permission: string) => {
    navigate(route, { state: { groupPermission: permission } });
  };

  const openDetailModal = (item: DashboardItem, type: string) => {
    setShowDetail({ item, type });
  };

  const fetchGroups = () => {
    setLoadingGroups(true);
    api.get('/api/groups/').then(r => setGroups(r.data)).catch(() => {}).finally(() => setLoadingGroups(false));
  };
  useEffect(() => { fetchGroups(); }, []);

  const fetchDetail = useCallback((id: string) => {
    setSelectedGroup(id);
    api.get(`/api/groups/${id}`).then(r => setGroupDetail(r.data)).catch(() => {});
    api.get(`/api/groups/${id}/dashboard`).then(r => setDashboard(r.data)).catch(() => {});
  }, []);

  const refresh = () => { if (selectedGroup) fetchDetail(selectedGroup); };

  const createGroup = async () => {
    try {
      await api.post('/api/groups/', createForm);
      toast.toast('Group created', 'success');
      setShowCreate(false);
      setCreateForm({ name: '', description: '' });
      fetchGroups();
    } catch (e: any) { toastErr(toast, e, 'Failed'); }
  };

  const deleteGroup = async () => {
    if (!selectedGroup) return;
    try {
      await api.delete(`/api/groups/${selectedGroup}`);
      toast.toast('Group deleted', 'success');
      setSelectedGroup(null);
      setGroupDetail(null);
      setDashboard(null);
      setDeleteConfirm(false);
      fetchGroups();
    } catch { toast.toast('Failed to delete group', 'error'); }
  };

  const addMember = async () => {
    if (!selectedGroup) return;
    try {
      await api.post(`/api/groups/${selectedGroup}/members`, memberForm);
      toast.toast(`Added ${memberForm.username}`, 'success');
      setShowAddMember(false);
      setMemberForm({ username: '', role: 'member' });
      refresh();
    } catch (e: any) { toastErr(toast, e, 'Failed'); }
  };

  const removeMember = async (userId?: string) => {
    const uid = userId || removeTarget;
    if (!selectedGroup || !uid) return;
    try {
      await api.delete(`/api/groups/${selectedGroup}/members/${uid}`);
      toast.toast('Member removed', 'success');
      setRemoveTarget(null);
      refresh();
    } catch { toast.toast('Failed to remove member', 'error'); }
  };

  const changeMemberRole = async (userId: string, role: string) => {
    if (!selectedGroup) return;
    try {
      await api.patch(`/api/groups/${selectedGroup}/members/${userId}?role=${role}`);
      toast.toast('Role updated', 'success');
      refresh();
    } catch (e: any) { toastErr(toast, e, 'Failed to update role'); }
  };

  const shareEntity = async () => {
    if (!selectedGroup) return;
    try {
      await api.post(`/api/groups/${selectedGroup}/share`, shareForm);
      toast.toast('Shared successfully', 'success');
      setShowShare(false);
      refresh();
    } catch (e: any) { toastErr(toast, e, 'Failed'); }
  };

  const unshareEntity = async (shareId: string) => {
    if (!selectedGroup) return;
    await api.delete(`/api/groups/${selectedGroup}/share/${shareId}`);
    toast.toast('Unshared', 'success');
    refresh();
  };

  const vmAction = async (entityId: string, action: string) => {
    try {
      await api.post(`/api/compute/vms/${entityId}/action`, { action });
      toast.toast(`${action} sent`, 'success');
      setTimeout(refresh, 2000);
    } catch (e: any) { toastErr(toast, e, `${action} failed`); }
  };

  const openShareModal = () => {
    api.get('/api/groups/my-entities').then(r => {
      setMyEntities(r.data || {});
      setEntityTypeFilter('');
      setShareForm({ entity_type: '', entity_id: '', permission: 'read' });
      setShowShare(true);
    }).catch(() => setShowShare(true));
  };

  const fetchGroupTokens = useCallback(() => {
    if (!selectedGroup) return;
    api.get(`/api/groups/${selectedGroup}/tokens`).then(r => setGroupTokens(r.data)).catch(() => setGroupTokens([]));
  }, [selectedGroup]);

  useEffect(() => { if (selectedGroup) fetchGroupTokens(); }, [selectedGroup, fetchGroupTokens]);

  const createGroupToken = async () => {
    if (!selectedGroup || !tokenName) return;
    try {
      const r = await api.post(`/api/groups/${selectedGroup}/tokens`, { name: tokenName });
      setNewTokenRaw(r.data.raw_key);
      setShowRawToken(true);
      setShowCreateToken(false);
      setTokenName('');
      toast.toast('Token created', 'success');
      fetchGroupTokens();
    } catch (e: any) { toastErr(toast, e, 'Failed to create token'); }
  };

  const revokeGroupToken = async () => {
    if (!selectedGroup || !revokeTarget) return;
    try {
      await api.delete(`/api/groups/${selectedGroup}/tokens/${revokeTarget.id}`);
      toast.toast('Token revoked', 'success');
      setRevokeTarget(null);
      fetchGroupTokens();
    } catch { toast.toast('Failed to revoke token', 'error'); }
  };

  const filteredEntities = entityTypeFilter ? (myEntities[entityTypeFilter] || []) : Object.values(myEntities).flat();

  // Compute tab definitions from dashboard data
  const types = dashboard?.types || {};
  const totalItems = Object.values(types).reduce((n, t) => n + t.items.length, 0);
  const tabs = [
    { id: 'overview', label: 'Overview', icon: <Users className="w-4 h-4" />, count: totalItems },
    { id: 'members', label: 'Members', icon: <Users className="w-4 h-4" />, count: groupDetail?.members.length },
    { id: 'tokens', label: 'API Tokens', icon: <KeyRound className="w-4 h-4" />, count: groupTokens.filter(t => t.is_active).length },
    ...Object.entries(types).map(([type, data]) => ({
      id: type,
      label: data.label + 's',
      icon: TYPE_ICONS[type] || <Database className="w-4 h-4" />,
      count: data.items.length,
    })),
  ];

  // ---- Group list view ----
  if (!selectedGroup) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-paws-text">Groups</h1>
          <Button onClick={() => setShowCreate(true)}><Plus className="w-4 h-4 mr-1" /> Create Group</Button>
        </div>

        {loadingGroups ? (
          <Card><CardContent>
            <LoadingSpinner message="Loading groups..." />
          </CardContent></Card>
        ) : groups.length === 0 ? (
          <Card><CardContent>
            <div className="text-center py-8">
              <Users className="w-12 h-12 text-paws-text-muted mx-auto mb-3" />
              <p className="text-paws-text-muted">No groups yet. Create a group to share resources with other users.</p>
            </div>
          </CardContent></Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {groups.map(g => (
              <div key={g.id} className="cursor-pointer" onClick={() => { fetchDetail(g.id); setActiveTab('overview'); }}>
                <Card><CardContent>
                  <div className="flex items-center gap-2 mb-1">
                    <Users className="w-4 h-4 text-paws-accent" />
                    <span className="font-bold text-paws-text">{g.name}</span>
                  </div>
                  {g.description && <p className="text-xs text-paws-text-muted mb-2">{g.description}</p>}
                  <div className="flex items-center gap-3 text-xs text-paws-text-muted">
                    <span>{g.member_count} members</span>
                    <span>Owner: {g.owner_username}</span>
                  </div>
                </CardContent></Card>
              </div>
            ))}
          </div>
        )}

        <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Group">
          <div className="space-y-3">
            <Input label="Group Name" value={createForm.name} onChange={e => setCreateForm(f => ({ ...f, name: e.target.value }))} />
            <Textarea label="Description (optional)" value={createForm.description} onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))} />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
              <Button onClick={createGroup} disabled={!createForm.name}>Create</Button>
            </div>
          </div>
        </Modal>
      </div>
    );
  }

  // ---- Group detail / dashboard view ----
  const isGroupAdmin = groupDetail?.my_role === 'owner' || groupDetail?.my_role === 'admin';

  const renderEntitySection = (type: string, data: { label: string; items: DashboardItem[] }) => {
    if (type === 'resource') {
      return (
        <div className="space-y-2">
          {data.items.map(item => (
            <InstanceRow
              key={item.share_id}
              item={item}
              canOperate={item.permission === 'operate' || item.permission === 'admin'}
              canAdmin={item.permission === 'admin' || isGroupAdmin}
              onUnshare={() => unshareEntity(item.share_id)}
              onAction={vmAction}
              toast={toast}
              onNavigate={navigateToEntity}
            />
          ))}
        </div>
      );
    }
    return (
      <div className="space-y-2">
        {data.items.map(item => (
          <EntityRow
            key={item.share_id}
            item={item}
            entityType={type}
            detailFields={DETAIL_FIELDS[type] || []}
            canAdmin={item.permission === 'admin' || isGroupAdmin}
            onUnshare={() => unshareEntity(item.share_id)}
            onNavigate={navigateToEntity}
            onShowDetail={openDetailModal}
          />
        ))}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => { setSelectedGroup(null); setGroupDetail(null); setDashboard(null); }}>
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <h1 className="text-2xl font-bold text-paws-text">{groupDetail?.name || 'Loading...'}</h1>
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" onClick={openShareModal}><Share2 className="w-4 h-4 mr-1" /> Share</Button>
          {groupDetail && (
            <Button variant="danger" size="sm" onClick={() => setDeleteConfirm(true)}>
              <Trash2 className="w-4 h-4 mr-1" /> Delete
            </Button>
          )}
        </div>
      </div>
      {groupDetail?.description && <p className="text-paws-text-muted text-sm">{groupDetail.description}</p>}

      {/* Tabs */}
      <Tabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />

      {/* Overview tab */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Summary cards */}
          <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
            <Card><CardContent>
              <p className="text-xs text-paws-text-muted">Members</p>
              <p className="text-2xl font-bold text-paws-text">{groupDetail?.members.length || 0}</p>
            </CardContent></Card>
            {Object.entries(types).map(([type, data]) => (
              <Card key={type}><CardContent>
                <div className="flex items-center gap-1.5">
                  {TYPE_ICONS[type]}
                  <p className="text-xs text-paws-text-muted">{data.label}s</p>
                </div>
                <p className="text-2xl font-bold text-paws-text">{data.items.length}</p>
              </CardContent></Card>
            ))}
          </div>

          {/* All shared items, grouped */}
          {Object.keys(types).length === 0 ? (
            <Card><CardContent>
              <div className="text-center py-6">
                <Share2 className="w-10 h-10 text-paws-text-muted mx-auto mb-2" />
                <p className="text-paws-text-muted">Nothing shared yet. Use the Share button to add items.</p>
              </div>
            </CardContent></Card>
          ) : (
            Object.entries(types).map(([type, data]) => (
              <div key={type}>
                <div className="flex items-center gap-2 mb-2">
                  {TYPE_ICONS[type]}
                  <h3 className="text-paws-text font-semibold">{data.label}s</h3>
                  <Badge variant="default">{data.items.length}</Badge>
                </div>
                {renderEntitySection(type, data)}
              </div>
            ))
          )}
        </div>
      )}

      {/* Members tab */}
      {activeTab === 'members' && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <Button size="sm" onClick={() => setShowAddMember(true)}><Plus className="w-4 h-4 mr-1" /> Add Member</Button>
          </div>
          <div className="space-y-2">
            {groupDetail?.members.map(m => (
              <div key={m.id} className="flex items-center justify-between px-3 py-2.5 rounded bg-paws-card border border-paws-border">
                <div className="flex items-center gap-3">
                  <Users className="w-4 h-4 text-paws-accent" />
                  <span className="text-paws-text font-medium">{m.username}</span>
                  <span className="text-xs text-paws-text-muted">{m.email}</span>
                  {m.role === 'owner' ? (
                    <Badge variant="success">owner</Badge>
                  ) : isGroupAdmin ? (
                    <select
                      value={m.role}
                      onChange={e => changeMemberRole(m.user_id, e.target.value)}
                      className="rounded border border-paws-border bg-paws-bg text-paws-text text-sm px-2 py-1"
                    >
                      <option value="admin">admin</option>
                      <option value="member">member</option>
                      <option value="viewer">viewer</option>
                    </select>
                  ) : (
                    <Badge variant={m.role === 'admin' ? 'info' : 'default'}>{m.role}</Badge>
                  )}
                </div>
                {m.role !== 'owner' && isGroupAdmin && (
                  <Button variant="ghost" size="sm" onClick={() => setRemoveTarget(m.user_id)}>
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* API Tokens tab */}
      {activeTab === 'tokens' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-paws-text-muted">
              Group API tokens provide programmatic access scoped to this group's shared resources.
            </p>
            <Button size="sm" onClick={() => setShowCreateToken(true)}><Plus className="w-4 h-4 mr-1" /> Create Token</Button>
          </div>
          {groupTokens.length === 0 ? (
            <Card><CardContent>
              <div className="text-center py-6">
                <KeyRound className="w-10 h-10 text-paws-text-muted mx-auto mb-2" />
                <p className="text-paws-text-muted">No API tokens for this group yet.</p>
              </div>
            </CardContent></Card>
          ) : (
            <div className="space-y-2">
              {groupTokens.map(t => (
                <div key={t.id} className={`flex items-center justify-between px-3 py-2.5 rounded bg-paws-card border border-paws-border${!t.is_active ? ' opacity-50' : ''}`}>
                  <div className="flex items-center gap-3">
                    <KeyRound className={`w-4 h-4 ${t.is_active ? 'text-paws-accent' : 'text-paws-text-muted'}`} />
                    <span className="text-paws-text font-medium">{t.name}</span>
                    <code className="text-xs text-paws-text-muted bg-paws-bg px-1.5 py-0.5 rounded">{t.key_prefix}...</code>
                    <Badge variant={t.is_active ? 'success' : 'danger'}>{t.is_active ? 'Active' : 'Revoked'}</Badge>
                    <span className="text-xs text-paws-text-muted">by {t.created_by_username}</span>
                    {t.last_used_at && <span className="text-xs text-paws-text-muted">Last used: {new Date(t.last_used_at).toLocaleDateString()}</span>}
                  </div>
                  {t.is_active && (
                    <Button variant="danger" size="sm" onClick={() => setRevokeTarget(t)}>Revoke</Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Per-type tabs */}
      {activeTab !== 'overview' && activeTab !== 'members' && activeTab !== 'tokens' && types[activeTab] && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {TYPE_ICONS[activeTab]}
              <h3 className="text-paws-text font-semibold">{types[activeTab].label}s</h3>
              <Badge variant="default">{types[activeTab].items.length}</Badge>
            </div>
            <Button size="sm" onClick={openShareModal}><Plus className="w-4 h-4 mr-1" /> Share More</Button>
          </div>
          {renderEntitySection(activeTab, types[activeTab])}
        </div>
      )}

      {/* Add Member Modal */}
      <Modal open={showAddMember} onClose={() => setShowAddMember(false)} title="Add Member">
        <div className="space-y-3">
          <Input label="Username" value={memberForm.username} onChange={e => setMemberForm(f => ({ ...f, username: e.target.value }))} />
          <Select label="Role" options={[{value:'member',label:'Member'},{value:'admin',label:'Admin'},{value:'viewer',label:'Viewer'}]} value={memberForm.role} onChange={e => setMemberForm(f => ({ ...f, role: e.target.value }))} />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setShowAddMember(false)}>Cancel</Button>
            <Button onClick={addMember} disabled={!memberForm.username}>Add</Button>
          </div>
        </div>
      </Modal>

      {/* Share Modal */}
      <Modal open={showShare} onClose={() => setShowShare(false)} title="Share with Group" size="lg">
        <div className="space-y-3">
          <Select
            label="Filter by Type"
            placeholder="All types"
            options={[{value:'',label:'All types'}, ...Object.keys(myEntities).map(t => ({value: t, label: (myEntities[t]?.[0]?.label || t)}))]}
            value={entityTypeFilter}
            onChange={e => { setEntityTypeFilter(e.target.value); setShareForm(f => ({ ...f, entity_type: '', entity_id: '' })); }}
          />
          <Select
            label="Item to Share"
            placeholder="Select an item..."
            options={filteredEntities.map(e => ({value: `${e.type}::${e.id}`, label: `${e.name} (${e.label})`}))}
            value={shareForm.entity_type ? `${shareForm.entity_type}::${shareForm.entity_id}` : ''}
            onChange={e => {
              const parts = e.target.value.split('::');
              setShareForm(f => ({ ...f, entity_type: parts[0] || '', entity_id: parts.slice(1).join('::') }));
            }}
          />
          <Select
            label="Permission Level"
            options={[
              {value:'read',label:'Read (view only)'},
              {value:'operate',label:'Operate (start/stop/console)'},
              {value:'admin',label:'Admin (full control)'},
            ]}
            value={shareForm.permission}
            onChange={e => setShareForm(f => ({ ...f, permission: e.target.value }))}
          />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setShowShare(false)}>Cancel</Button>
            <Button onClick={shareEntity} disabled={!shareForm.entity_id}>Share</Button>
          </div>
        </div>
      </Modal>

      {/* Entity Detail Modal (for types without dedicated pages) */}
      <Modal
        open={!!showDetail}
        onClose={() => setShowDetail(null)}
        title={showDetail ? `${ENTITY_TYPES_LABELS[showDetail.type] || showDetail.type} Details` : ''}
        size="lg"
      >
        {showDetail && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 mb-2">
              {TYPE_ICONS[showDetail.type]}
              <span className="text-lg font-semibold text-paws-text">{showDetail.item.entity_name}</span>
              <PermBadge perm={showDetail.item.permission} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              {(DETAIL_FIELDS[showDetail.type] || []).map(f => {
                const val = showDetail.item[f.key];
                if (val === null || val === undefined) return null;
                return (
                  <div key={f.key} className="bg-paws-bg rounded p-2 border border-paws-border">
                    <p className="text-xs text-paws-text-muted">{f.label}</p>
                    <p className="text-sm text-paws-text font-medium">{f.format ? f.format(val) : String(val)}</p>
                  </div>
                );
              })}
              {showDetail.item.status && (
                <div className="bg-paws-bg rounded p-2 border border-paws-border">
                  <p className="text-xs text-paws-text-muted">Status</p>
                  <Badge variant={STATUS_VARIANT[showDetail.item.status] || 'default'}>{showDetail.item.status}</Badge>
                </div>
              )}
              {showDetail.item.state && (
                <div className="bg-paws-bg rounded p-2 border border-paws-border">
                  <p className="text-xs text-paws-text-muted">State</p>
                  <Badge variant={STATUS_VARIANT[showDetail.item.state] || 'default'}>{showDetail.item.state}</Badge>
                </div>
              )}
            </div>
            {showDetail.item.permission === 'read' && (
              <p className="text-xs text-paws-text-muted italic">You have read-only access to this resource.</p>
            )}
          </div>
        )}
      </Modal>

      {/* Create Group Token Modal */}
      <Modal open={showCreateToken} onClose={() => setShowCreateToken(false)} title="Create Group API Token">
        <div className="space-y-3">
          <Input label="Token Name" placeholder="e.g. CI/CD Pipeline" value={tokenName} onChange={e => setTokenName(e.target.value)} />
          <p className="text-xs text-paws-text-muted">
            This token will authenticate as you but only grant access to resources shared within this group.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setShowCreateToken(false)}>Cancel</Button>
            <Button onClick={createGroupToken} disabled={!tokenName.trim()}>Create Token</Button>
          </div>
        </div>
      </Modal>

      {/* Show Raw Token Modal (once-only) */}
      <Modal open={showRawToken} onClose={() => { setShowRawToken(false); setNewTokenRaw(null); }} title="Token Created">
        <div className="space-y-3">
          <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded">
            <p className="text-sm text-yellow-200 font-medium mb-1">Copy this token now - it won't be shown again.</p>
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-sm bg-paws-bg border border-paws-border rounded px-3 py-2 text-paws-text break-all">
              {newTokenRaw}
            </code>
            <Button size="sm" variant="outline" onClick={() => { navigator.clipboard.writeText(newTokenRaw || ''); toast.toast('Copied!', 'success'); }}>
              <Copy className="w-4 h-4" />
            </Button>
          </div>
          <div className="flex justify-end">
            <Button onClick={() => { setShowRawToken(false); setNewTokenRaw(null); }}>Done</Button>
          </div>
        </div>
      </Modal>

      {/* Revoke Token Confirmation */}
      <Modal open={!!revokeTarget} onClose={() => setRevokeTarget(null)} title="Revoke Token">
        <div className="space-y-4">
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded flex items-start gap-2">
            <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <p className="text-sm text-red-200">
              This will immediately revoke the token <strong>{revokeTarget?.name}</strong>. Any applications using it will lose access.
            </p>
          </div>
          <div className="flex gap-2 justify-end">
            <Button variant="ghost" onClick={() => setRevokeTarget(null)}>Cancel</Button>
            <Button variant="danger" onClick={revokeGroupToken}>Revoke Token</Button>
          </div>
        </div>
      </Modal>

      {/* Delete Group Confirmation */}
      <Modal open={deleteConfirm} onClose={() => setDeleteConfirm(false)} title="Delete Group">
        <div className="space-y-4">
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded flex items-start gap-2">
            <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <p className="text-sm text-red-200">
              Are you sure you want to delete this group? All shared items will be unshared and all members removed. This action cannot be undone.
            </p>
          </div>
          <div className="flex gap-2 justify-end">
            <Button variant="ghost" onClick={() => setDeleteConfirm(false)}>Cancel</Button>
            <Button variant="danger" onClick={deleteGroup}>Delete Group</Button>
          </div>
        </div>
      </Modal>

      {/* Remove Member Confirmation */}
      <Modal open={!!removeTarget} onClose={() => setRemoveTarget(null)} title="Remove Member">
        <div className="space-y-4">
          <p className="text-sm text-gray-300">Are you sure you want to remove this member from the group?</p>
          <div className="flex gap-2 justify-end">
            <Button variant="ghost" onClick={() => setRemoveTarget(null)}>Cancel</Button>
            <Button variant="danger" onClick={() => removeMember()}>Remove</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
