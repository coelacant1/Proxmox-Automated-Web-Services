import { useEffect, useState } from 'react';
import { Shield, Plus, Trash2, ArrowDown, ArrowUp } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  DataTable, Input, Modal, Select, Badge, EmptyState, useConfirm, useToast, type Column,
} from '@/components/ui';
import { cn } from '@/lib/utils';

interface SecurityGroup {
  id: string;
  name: string;
  description: string;
  is_default: boolean;
  cluster_id?: string;
  rules: Rule[];
}

interface Rule {
  id?: string;
  direction: string;
  action: string;
  protocol: string;
  port_range: string;
  source: string;
  description?: string;
  [key: string]: unknown;
}

export default function SecurityGroups() {
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const [groups, setGroups] = useState<SecurityGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<SecurityGroup | null>(null);
  const [showAddRule, setShowAddRule] = useState(false);
  const [clusters, setClusters] = useState<{name: string}[]>([]);
  const [form, setForm] = useState({ name: '', description: '', cluster_id: '' });
  const [ruleForm, setRuleForm] = useState<Rule>({
    direction: 'inbound', action: 'allow', protocol: 'tcp', port_range: '', source: '0.0.0.0/0',
  });

  const fetchGroups = () => {
    api.get('/api/security-groups/')
      .then((res) => {
        setGroups(res.data);
        if (selected) {
          const updated = res.data.find((g: SecurityGroup) => g.id === selected.id);
          if (updated) setSelected(updated);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(fetchGroups, []);

  useEffect(() => {
    api.get('/api/cluster/list').then((res) => {
      setClusters(res.data || []);
      if (res.data?.length === 1) {
        setForm((prev) => ({ ...prev, cluster_id: res.data![0].name }));
      }
    }).catch(() => {});
  }, []);

  const handleCreate = async () => {
    try {
      await api.post('/api/security-groups/', { ...form, cluster_id: form.cluster_id || undefined });
      toast('Firewall group created', 'success');
      setShowCreate(false);
      setForm({ name: '', description: '', cluster_id: clusters.length === 1 ? clusters[0]?.name ?? '' : '' });
      fetchGroups();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to create firewall group', 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!await confirm({ title: 'Delete Firewall', message: 'Delete this firewall rule group and all its rules?' })) return;
    try {
      await api.delete(`/api/security-groups/${id}`);
      if (selected?.id === id) setSelected(null);
      toast('Firewall group deleted', 'success');
      fetchGroups();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to delete firewall group', 'error');
    }
  };

  const handleAddRule = async () => {
    if (!selected) return;
    try {
      await api.post(`/api/security-groups/${selected.id}/rules`, ruleForm);
      toast('Rule added', 'success');
      setShowAddRule(false);
      setRuleForm({ direction: 'inbound', action: 'allow', protocol: 'tcp', port_range: '', source: '0.0.0.0/0' });
      fetchGroups();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to add rule', 'error');
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    if (!selected) return;
    try {
      await api.delete(`/api/security-groups/${selected.id}/rules/${ruleId}`);
      toast('Rule deleted', 'success');
      fetchGroups();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to delete rule', 'error');
    }
  };

  const ruleColumns: Column<Rule>[] = [
    {
      key: 'direction',
      header: 'Direction',
      render: (row) => (
        <Badge variant={row.direction === 'inbound' ? 'info' : 'warning'}>
          {row.direction === 'inbound' ? <ArrowDown className="h-3 w-3 mr-1" /> : <ArrowUp className="h-3 w-3 mr-1" />}
          {row.direction}
        </Badge>
      ),
    },
    { key: 'protocol', header: 'Protocol', render: (row) => <span className="uppercase text-xs font-mono">{row.protocol}</span> },
    { key: 'port_range', header: 'Ports', render: (row) => <span className="font-mono text-sm">{row.port_range || 'All'}</span> },
    { key: 'source', header: 'Source/Dest', render: (row) => <span className="font-mono text-sm">{row.source}</span> },
    { key: 'action', header: 'Action', render: (row) => <Badge variant={row.action === 'allow' ? 'success' : 'danger'}>{row.action}</Badge> },
    {
      key: 'actions',
      header: '',
      render: (row) => (
        <Button variant="ghost" size="sm" onClick={() => row.id && handleDeleteRule(row.id)}>
          <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Firewalls</h1>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> Create Group
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Group List */}
        <div className="space-y-2">
          {loading ? (
            <p className="text-paws-text-muted">Loading...</p>
          ) : groups.length === 0 ? (
            <EmptyState icon={Shield} title="No security groups" description="Create a security group to manage firewall rules." />
          ) : (
            groups.map((g) => (
              <div
                key={g.id}
                className={cn('cursor-pointer transition-colors rounded-lg', selected?.id === g.id && 'ring-2 ring-paws-primary')}
                onClick={() => setSelected(g)}
              >
                <Card>
                <CardContent className="py-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium text-paws-text">{g.name}</p>
                      <p className="text-xs text-paws-text-dim">{g.rules?.length || 0} rules</p>
                    </div>
                    <div className="flex items-center gap-1">
                    {clusters.length > 1 && g.cluster_id && <Badge variant="default">{g.cluster_id}</Badge>}
                    {g.is_default && <Badge variant="info">Default</Badge>}
                    {!g.is_default && (
                      <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); handleDelete(g.id); }}>
                        <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
                      </Button>
                    )}
                    </div>
                  </div>
                </CardContent>
              </Card>
              </div>
            ))
          )}
        </div>

        {/* Rules Panel */}
        <div className="lg:col-span-2">
          {selected ? (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>{selected.name} - Rules</CardTitle>
                  <Button size="sm" onClick={() => setShowAddRule(true)}>
                    <Plus className="h-4 w-4 mr-1" /> Add Rule
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <DataTable
                  columns={ruleColumns}
                  data={selected.rules || []}
                  emptyMessage="No rules. All traffic is blocked by default."
                />
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="py-16 text-center text-paws-text-dim">
                Select a security group to view and manage its rules.
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Create Group Modal */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Firewall Rule Group">
        <div className="space-y-4">
          <Input label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input label="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          {clusters.length > 1 && (
            <Select label="Cluster" value={form.cluster_id}
              options={clusters.map((c) => ({ value: c.name, label: c.name }))}
              onChange={(e) => setForm({ ...form, cluster_id: e.target.value })} />
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name}>Create</Button>
          </div>
        </div>
      </Modal>

      {/* Add Rule Modal */}
      <Modal open={showAddRule} onClose={() => setShowAddRule(false)} title="Add Firewall Rule">
        <div className="space-y-4">
          <Select label="Direction" options={[
            { value: 'inbound', label: 'Inbound' },
            { value: 'outbound', label: 'Outbound' },
          ]} value={ruleForm.direction} onChange={(e) => setRuleForm({ ...ruleForm, direction: e.target.value })} />
          <Select label="Action" options={[
            { value: 'allow', label: 'Allow' },
            { value: 'deny', label: 'Deny' },
          ]} value={ruleForm.action} onChange={(e) => setRuleForm({ ...ruleForm, action: e.target.value })} />
          <Select label="Protocol" options={[
            { value: 'tcp', label: 'TCP' },
            { value: 'udp', label: 'UDP' },
            { value: 'icmp', label: 'ICMP' },
            { value: 'any', label: 'Any' },
          ]} value={ruleForm.protocol} onChange={(e) => setRuleForm({ ...ruleForm, protocol: e.target.value })} />
          <Input label="Port Range" placeholder="e.g. 80, 443, 8000-9000" value={ruleForm.port_range}
            onChange={(e) => setRuleForm({ ...ruleForm, port_range: e.target.value })} />
          <Input label="Source CIDR" value={ruleForm.source}
            onChange={(e) => setRuleForm({ ...ruleForm, source: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowAddRule(false)}>Cancel</Button>
            <Button onClick={handleAddRule}>Add Rule</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
