import { useState, useEffect } from 'react';
import api from '../api/client';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { Modal, Textarea, Select, useToast } from '@/components/ui';
import { Users, Plus, Trash2, Share2, ArrowLeft } from 'lucide-react';

interface Group {
  id: string; name: string; description: string | null;
  owner_id: string; owner_username: string | null;
  created_at: string | null; member_count: number;
}
interface Member {
  id: string; user_id: string; username: string | null;
  email: string | null; role: string; joined_at: string | null;
}
interface SharedItem {
  id: string; entity_type: string; entity_id: string;
  entity_name: string | null; entity_label: string;
  permission: string; shared_by: string; created_at: string | null;
}
interface EntityOption {
  id: string; name: string; type: string; label: string;
}

export default function Groups() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [groupDetail, setGroupDetail] = useState<(Group & { members: Member[] }) | null>(null);
  const [sharedItems, setSharedItems] = useState<SharedItem[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [showAddMember, setShowAddMember] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [createForm, setCreateForm] = useState({ name: '', description: '' });
  const [memberForm, setMemberForm] = useState({ username: '', role: 'member' });
  const [shareForm, setShareForm] = useState({ entity_type: '', entity_id: '', permission: 'read' });
  const [myEntities, setMyEntities] = useState<Record<string, EntityOption[]>>({});
  const [entityTypeFilter, setEntityTypeFilter] = useState('');
  const toast = useToast();

  const fetchGroups = () => api.get('/api/groups/').then(r => setGroups(r.data)).catch(() => {});
  useEffect(() => { fetchGroups(); }, []);

  const fetchDetail = (id: string) => {
    setSelectedGroup(id);
    api.get(`/api/groups/${id}`).then(r => setGroupDetail(r.data)).catch(() => {});
    api.get(`/api/groups/${id}/resources`).then(r => setSharedItems(r.data)).catch(() => {});
  };

  const createGroup = async () => {
    try {
      await api.post('/api/groups/', createForm);
      toast.toast('Group created', 'success');
      setShowCreate(false);
      setCreateForm({ name: '', description: '' });
      fetchGroups();
    } catch (e: any) {
      const d = e.response?.data?.detail;
      toast.toast(typeof d === 'string' ? d : Array.isArray(d) ? d.map((v: any) => v.msg).join(', ') : 'Failed', 'error');
    }
  };

  const deleteGroup = async (id: string) => {
    if (!confirm('Delete this group? All shared items will be unshared.')) return;
    await api.delete(`/api/groups/${id}`);
    toast.toast('Group deleted', 'success');
    setSelectedGroup(null);
    setGroupDetail(null);
    fetchGroups();
  };

  const addMember = async () => {
    if (!selectedGroup) return;
    try {
      await api.post(`/api/groups/${selectedGroup}/members`, memberForm);
      toast.toast(`Added ${memberForm.username}`, 'success');
      setShowAddMember(false);
      setMemberForm({ username: '', role: 'member' });
      fetchDetail(selectedGroup);
    } catch (e: any) {
      const d = e.response?.data?.detail;
      toast.toast(typeof d === 'string' ? d : 'Failed', 'error');
    }
  };

  const removeMember = async (userId: string) => {
    if (!selectedGroup || !confirm('Remove this member?')) return;
    await api.delete(`/api/groups/${selectedGroup}/members/${userId}`);
    toast.toast('Member removed', 'success');
    fetchDetail(selectedGroup);
  };

  const shareEntity = async () => {
    if (!selectedGroup) return;
    try {
      await api.post(`/api/groups/${selectedGroup}/share`, shareForm);
      toast.toast('Shared successfully', 'success');
      setShowShare(false);
      fetchDetail(selectedGroup);
    } catch (e: any) {
      const d = e.response?.data?.detail;
      toast.toast(typeof d === 'string' ? d : 'Failed', 'error');
    }
  };

  const unshareEntity = async (shareId: string) => {
    if (!selectedGroup) return;
    await api.delete(`/api/groups/${selectedGroup}/share/${shareId}`);
    toast.toast('Unshared', 'success');
    fetchDetail(selectedGroup);
  };

  const openShareModal = () => {
    api.get('/api/groups/my-entities').then(r => {
      setMyEntities(r.data || {});
      setEntityTypeFilter('');
      setShareForm({ entity_type: '', entity_id: '', permission: 'read' });
      setShowShare(true);
    }).catch(() => setShowShare(true));
  };

  // Build flat list of options filtered by selected type
  const filteredEntities = entityTypeFilter ? (myEntities[entityTypeFilter] || []) : Object.values(myEntities).flat();

  // Group list view
  if (!selectedGroup) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-paws-text">Groups</h1>
          <Button onClick={() => setShowCreate(true)}><Plus className="w-4 h-4 mr-1" /> Create Group</Button>
        </div>

        {groups.length === 0 ? (
          <Card>
            <CardContent>
              <div className="text-center py-8">
                <Users className="w-12 h-12 text-paws-text-muted mx-auto mb-3" />
                <p className="text-paws-text-muted">No groups yet. Create a group to share resources with other users.</p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {groups.map(g => (
              <div key={g.id} className="cursor-pointer" onClick={() => fetchDetail(g.id)}>
                <Card>
                  <CardContent>
                    <div className="flex items-center gap-2 mb-1">
                      <Users className="w-4 h-4 text-paws-accent" />
                      <span className="font-bold text-paws-text">{g.name}</span>
                    </div>
                    {g.description && <p className="text-xs text-paws-text-muted mb-2">{g.description}</p>}
                    <div className="flex items-center gap-3 text-xs text-paws-text-muted">
                      <span>{g.member_count} members</span>
                      <span>Owner: {g.owner_username}</span>
                    </div>
                  </CardContent>
                </Card>
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

  // Group detail view
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => { setSelectedGroup(null); setGroupDetail(null); }}>
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <h1 className="text-2xl font-bold text-paws-text">{groupDetail?.name || 'Loading...'}</h1>
        {groupDetail && (
          <Button variant="danger" size="sm" onClick={() => deleteGroup(groupDetail.id)} className="ml-auto">
            <Trash2 className="w-4 h-4 mr-1" /> Delete Group
          </Button>
        )}
      </div>

      {groupDetail?.description && <p className="text-paws-text-muted">{groupDetail.description}</p>}

      {/* Members */}
      <div>
        <div className="flex justify-between items-center mb-3">
          <h3 className="text-paws-text font-semibold">Members</h3>
          <Button size="sm" onClick={() => setShowAddMember(true)}><Plus className="w-4 h-4 mr-1" /> Add Member</Button>
        </div>
        <div className="space-y-2">
          {groupDetail?.members.map(m => (
            <div key={m.id} className="flex items-center justify-between px-3 py-2 rounded bg-paws-card border border-paws-border">
              <div className="flex items-center gap-3">
                <span className="text-paws-text font-medium">{m.username}</span>
                <span className="text-xs text-paws-text-muted">{m.email}</span>
                <Badge variant={m.role === 'owner' ? 'success' : m.role === 'admin' ? 'info' : 'default'}>{m.role}</Badge>
              </div>
              {m.role !== 'owner' && (
                <Button variant="ghost" size="sm" onClick={() => removeMember(m.user_id)}>
                  <Trash2 className="w-3 h-3" />
                </Button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Shared Items */}
      <div>
        <div className="flex justify-between items-center mb-3">
          <h3 className="text-paws-text font-semibold">Shared Items</h3>
          <Button size="sm" onClick={openShareModal}><Share2 className="w-4 h-4 mr-1" /> Share</Button>
        </div>
        {sharedItems.length === 0 ? (
          <p className="text-paws-text-muted text-sm">Nothing shared yet. Share VMs, VPCs, volumes, buckets, keys, and more.</p>
        ) : (
          <div className="space-y-2">
            {sharedItems.map(s => (
              <div key={s.id} className="flex items-center justify-between px-3 py-2 rounded bg-paws-card border border-paws-border">
                <div className="flex items-center gap-3">
                  <span className="text-paws-text font-medium">{s.entity_name || s.entity_id}</span>
                  <Badge variant="default">{s.entity_label}</Badge>
                  <Badge variant={s.permission === 'admin' ? 'danger' : s.permission === 'operate' ? 'warning' : 'info'}>{s.permission}</Badge>
                </div>
                <Button variant="ghost" size="sm" onClick={() => unshareEntity(s.id)}>
                  <Trash2 className="w-3 h-3" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>

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
    </div>
  );
}
