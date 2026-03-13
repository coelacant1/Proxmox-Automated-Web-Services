import { useEffect, useState } from 'react';
import { Shield, Plus, Trash2, ArrowDown, ArrowUp, Eye } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  DataTable, Input, Modal, Select, Badge, EmptyState, Tabs, type Column,
} from '@/components/ui';
import { cn } from '@/lib/utils';

interface SecurityGroup {
  id: string;
  name: string;
  description: string;
  is_default: boolean;
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

// Common service presets for the visual builder
const SERVICE_PRESETS = [
  { label: 'SSH', protocol: 'tcp', port: '22', icon: '🔑' },
  { label: 'HTTP', protocol: 'tcp', port: '80', icon: '🌐' },
  { label: 'HTTPS', protocol: 'tcp', port: '443', icon: '🔒' },
  { label: 'RDP', protocol: 'tcp', port: '3389', icon: '🖥️' },
  { label: 'MySQL', protocol: 'tcp', port: '3306', icon: '🗄️' },
  { label: 'PostgreSQL', protocol: 'tcp', port: '5432', icon: '🐘' },
  { label: 'Redis', protocol: 'tcp', port: '6379', icon: '⚡' },
  { label: 'DNS', protocol: 'udp', port: '53', icon: '📡' },
  { label: 'SMTP', protocol: 'tcp', port: '25', icon: '📧' },
  { label: 'Ping', protocol: 'icmp', port: '', icon: '📶' },
  { label: 'Custom TCP', protocol: 'tcp', port: '', icon: '🔧' },
  { label: 'Custom UDP', protocol: 'udp', port: '', icon: '🔧' },
];

export default function SecurityGroups() {
  const [groups, setGroups] = useState<SecurityGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<SecurityGroup | null>(null);
  const [showAddRule, setShowAddRule] = useState(false);
  const [form, setForm] = useState({ name: '', description: '' });
  const [ruleForm, setRuleForm] = useState<Rule>({
    direction: 'inbound', action: 'allow', protocol: 'tcp', port_range: '', source: '0.0.0.0/0',
  });
  const [rulesTab, setRulesTab] = useState('table');

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

  const handleCreate = async () => {
    await api.post('/api/security-groups/', form);
    setShowCreate(false);
    setForm({ name: '', description: '' });
    fetchGroups();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this security group?')) return;
    await api.delete(`/api/security-groups/${id}`);
    if (selected?.id === id) setSelected(null);
    fetchGroups();
  };

  const handleAddRule = async () => {
    if (!selected) return;
    await api.post(`/api/security-groups/${selected.id}/rules`, ruleForm);
    setShowAddRule(false);
    setRuleForm({ direction: 'inbound', action: 'allow', protocol: 'tcp', port_range: '', source: '0.0.0.0/0' });
    fetchGroups();
  };

  const handleDeleteRule = async (ruleId: string) => {
    if (!selected) return;
    await api.delete(`/api/security-groups/${selected.id}/rules/${ruleId}`);
    fetchGroups();
  };

  const handleQuickAdd = async (preset: typeof SERVICE_PRESETS[0], direction: string) => {
    if (!selected) return;
    await api.post(`/api/security-groups/${selected.id}/rules`, {
      direction,
      action: 'allow',
      protocol: preset.protocol,
      port_range: preset.port,
      source: '0.0.0.0/0',
      description: preset.label,
    });
    fetchGroups();
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

  const inboundRules = (selected?.rules || []).filter((r) => r.direction === 'inbound');
  const outboundRules = (selected?.rules || []).filter((r) => r.direction === 'outbound');

  const rulesTabs = [
    { id: 'table', label: 'Rules Table' },
    { id: 'visual', label: 'Visual Builder', icon: <Eye className="h-3.5 w-3.5" /> },
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
                    {g.is_default && <Badge variant="info">Default</Badge>}
                    {!g.is_default && (
                      <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); handleDelete(g.id); }}>
                        <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
                      </Button>
                    )}
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
                <Tabs tabs={rulesTabs} activeTab={rulesTab} onChange={setRulesTab} className="mb-4" />

                {rulesTab === 'table' && (
                  <DataTable
                    columns={ruleColumns}
                    data={selected.rules || []}
                    emptyMessage="No rules. All traffic is blocked by default."
                  />
                )}

                {rulesTab === 'visual' && (
                  <div className="space-y-6">
                    {/* Inbound visual */}
                    <div>
                      <h3 className="text-sm font-medium text-paws-text mb-3 flex items-center gap-2">
                        <ArrowDown className="h-4 w-4 text-paws-info" /> Inbound Rules
                      </h3>
                      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 mb-3">
                        {SERVICE_PRESETS.map((preset) => {
                          const isActive = inboundRules.some(
                            (r) => r.protocol === preset.protocol && r.port_range === preset.port && r.action === 'allow'
                          );
                          return (
                            <button
                              key={`in-${preset.label}`}
                              onClick={() => !isActive && handleQuickAdd(preset, 'inbound')}
                              className={cn(
                                'flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-sm transition-colors',
                                isActive
                                  ? 'border-paws-success/50 bg-paws-success/10 text-paws-text'
                                  : 'border-paws-border hover:border-paws-primary/50 hover:bg-paws-surface-hover text-paws-text-muted',
                              )}
                            >
                              <span>{preset.icon}</span>
                              <span>{preset.label}</span>
                              {isActive && <span className="ml-auto text-xs text-paws-success">✓</span>}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Outbound visual */}
                    <div>
                      <h3 className="text-sm font-medium text-paws-text mb-3 flex items-center gap-2">
                        <ArrowUp className="h-4 w-4 text-paws-warning" /> Outbound Rules
                      </h3>
                      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                        {SERVICE_PRESETS.map((preset) => {
                          const isActive = outboundRules.some(
                            (r) => r.protocol === preset.protocol && r.port_range === preset.port && r.action === 'allow'
                          );
                          return (
                            <button
                              key={`out-${preset.label}`}
                              onClick={() => !isActive && handleQuickAdd(preset, 'outbound')}
                              className={cn(
                                'flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-sm transition-colors',
                                isActive
                                  ? 'border-paws-success/50 bg-paws-success/10 text-paws-text'
                                  : 'border-paws-border hover:border-paws-primary/50 hover:bg-paws-surface-hover text-paws-text-muted',
                              )}
                            >
                              <span>{preset.icon}</span>
                              <span>{preset.label}</span>
                              {isActive && <span className="ml-auto text-xs text-paws-success">✓</span>}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Summary */}
                    <div className="bg-paws-bg rounded-lg p-4 text-xs text-paws-text-dim">
                      <p className="font-medium text-paws-text mb-2">Traffic Summary</p>
                      <div className="flex gap-8">
                        <div>
                          <span className="text-paws-info">Inbound:</span>{' '}
                          {inboundRules.filter((r) => r.action === 'allow').length} allowed,{' '}
                          {inboundRules.filter((r) => r.action === 'deny').length} denied
                        </div>
                        <div>
                          <span className="text-paws-warning">Outbound:</span>{' '}
                          {outboundRules.filter((r) => r.action === 'allow').length} allowed,{' '}
                          {outboundRules.filter((r) => r.action === 'deny').length} denied
                        </div>
                      </div>
                    </div>
                  </div>
                )}
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
