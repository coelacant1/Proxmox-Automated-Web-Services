import { useEffect, useState } from 'react';
import { Network, Plus, Trash2, Server, Globe, Map, Edit2 } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Input, Modal, Badge, EmptyState, StatusBadge, Tabs,
  useToast,
} from '@/components/ui';
import { cn } from '@/lib/utils';

interface VPC {
  id: string;
  name: string;
  cidr: string;
  status: string; // active, creating, error
  is_default: boolean;
  gateway: string | null;
  vxlan_tag: number | null;
  proxmox_zone: string | null;
  proxmox_vnet: string | null;
  dhcp_enabled: boolean;
  network_mode?: string;
  subnets: Subnet[];
  created_at: string;
}

interface Subnet {
  id: string;
  name: string;
  cidr: string;
  gateway: string | null;
  is_public: boolean;
  snat_enabled: boolean;
  dhcp_enabled: boolean;
  dhcp_start: string | null;
  dhcp_end: string | null;
  dns_server: string | null;
  proxmox_subnet_id: string | null;
  status: string;
  created_at: string;
}

interface VPCInstance {
  id: string;
  name: string;
  type: string;
  status: string;
  subnet_id?: string;
  allocated_ips?: string[];
  live_ips?: string[];
  ip_addresses?: string[];
}

export default function VPCs() {
  const { toast } = useToast();
  const [vpcs, setVpcs] = useState<VPC[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<VPC | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showSubnet, setShowSubnet] = useState(false);
  const [instances, setInstances] = useState<VPCInstance[]>([]);
  const [form, setForm] = useState({ name: '', network_mode: 'private' });
  const [changingMode, setChangingMode] = useState(false);
  const [subnetForm, setSubnetForm] = useState({
    name: '', cidr: '', gateway: '', snat_enabled: true, dns_server: '',
  });
  const [detailTab, setDetailTab] = useState('details');
  const [editIpInst, setEditIpInst] = useState<VPCInstance | null>(null);
  const [newIp, setNewIp] = useState('');

  const fetchVPCs = () => {
    api.get('/api/vpcs/')
      .then((res) => {
        setVpcs(res.data);
        if (selected) {
          const updated = res.data.find((v: VPC) => v.id === selected.id);
          if (updated) setSelected(updated);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(fetchVPCs, []);

  useEffect(() => {
    if (selected) {
      api.get(`/api/vpcs/${selected.id}/instances`).then((res) => setInstances(res.data)).catch(() => setInstances([]));
    }
  }, [selected?.id]);

  const handleCreate = async () => {
    try {
      await api.post('/api/vpcs/', { name: form.name, network_mode: form.network_mode });
      setShowCreate(false);
      setForm({ name: '', network_mode: 'private' });
      fetchVPCs();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to create network', 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this network and all its subnets?')) return;
    try {
      await api.delete(`/api/vpcs/${id}`);
      if (selected?.id === id) setSelected(null);
      fetchVPCs();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to delete network', 'error');
    }
  };

  const handleAddSubnet = async () => {
    if (!selected) return;
    const payload: Record<string, unknown> = {
      name: subnetForm.name,
      snat_enabled: subnetForm.snat_enabled,
    };
    if (subnetForm.cidr) payload.cidr = subnetForm.cidr;
    if (subnetForm.gateway) payload.gateway = subnetForm.gateway;
    if (subnetForm.dns_server) payload.dns_server = subnetForm.dns_server;
    await api.post(`/api/vpcs/${selected.id}/subnets`, payload);
    setShowSubnet(false);
    setSubnetForm({
      name: '', cidr: '', gateway: '', snat_enabled: true, dns_server: '',
    });
    fetchVPCs();
  };

  const handleDeleteSubnet = async (subnetId: string) => {
    if (!selected) return;
    await api.delete(`/api/vpcs/${selected.id}/subnets/${subnetId}`);
    fetchVPCs();
  };

  const handleChangeIp = async () => {
    if (!selected || !editIpInst || !newIp.trim()) return;
    try {
      await api.put(`/api/vpcs/${selected.id}/instances/${editIpInst.id}/ip`, { new_ip: newIp.trim() });
      setEditIpInst(null);
      setNewIp('');
      api.get(`/api/vpcs/${selected.id}/instances`).then((res) => setInstances(res.data)).catch(() => {});
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      alert(typeof d === 'string' ? d : 'Failed to change IP');
    }
  };

  const detailTabs = [
    { id: 'details', label: 'Details' },
    { id: 'diagram', label: 'Network Diagram', icon: <Map className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Networks</h1>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> Create VPC
        </Button>
      </div>

      {loading ? (
        <p className="text-paws-text-muted">Loading...</p>
      ) : vpcs.length === 0 ? (
        <EmptyState icon={Network} title="No Networks" description="Create a Virtual Private Cloud to isolate your network resources." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* VPC List */}
          <div className="space-y-2">
            {vpcs.map((vpc) => (
              <div
                key={vpc.id}
                className={cn('cursor-pointer transition-colors rounded-lg', selected?.id === vpc.id && 'ring-2 ring-paws-primary')}
                onClick={() => setSelected(vpc)}
              >
                <Card>
                <CardContent className="py-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium text-paws-text">{vpc.name}</p>
                      <p className="text-xs font-mono text-paws-text-dim">{vpc.cidr}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {vpc.is_default && <Badge variant="info">Default</Badge>}
                      <Badge variant={vpc.network_mode === 'published' ? 'warning' : vpc.network_mode === 'isolated' ? 'danger' : 'success'}>
                        {(vpc.network_mode || 'private').charAt(0).toUpperCase() + (vpc.network_mode || 'private').slice(1)}
                      </Badge>
                      <StatusBadge status={vpc.status} />
                    </div>
                  </div>
                </CardContent>
              </Card>
              </div>
            ))}
          </div>

          {/* Detail Panel */}
          <div className="lg:col-span-2 space-y-4">
            {selected ? (
              <>
                <Tabs tabs={detailTabs} activeTab={detailTab} onChange={setDetailTab} className="mb-4" />

                {detailTab === 'details' && (
                  <>
                    <Card>
                      <CardHeader>
                        <div className="flex items-center justify-between">
                          <CardTitle>{selected.name}</CardTitle>
                          {!selected.is_default && (
                            <Button variant="danger" size="sm" onClick={() => handleDelete(selected.id)}>
                              <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
                            </Button>
                          )}
                        </div>
                      </CardHeader>
                      <CardContent>
                        {selected.status === 'error' && (
                          <div className="mb-4 rounded-lg border border-paws-danger/40 bg-paws-danger/10 px-4 py-2 text-sm text-paws-danger">
                            This VPC encountered an error during provisioning.
                          </div>
                        )}
                        <div className="grid grid-cols-3 gap-4">
                          <div>
                            <p className="text-xs text-paws-text-dim">CIDR</p>
                            <p className="font-mono text-sm text-paws-text">{selected.cidr}</p>
                          </div>
                          <div>
                            <p className="text-xs text-paws-text-dim">Gateway</p>
                            <p className="font-mono text-sm text-paws-text">{selected.gateway || 'Auto'}</p>
                          </div>
                          <div>
                            <p className="text-xs text-paws-text-dim">Status</p>
                            <StatusBadge status={selected.status} />
                          </div>
                          <div>
                            <p className="text-xs text-paws-text-dim">VNet</p>
                            <p className="font-mono text-sm text-paws-text">{selected.proxmox_vnet || '—'}</p>
                          </div>
                          <div>
                            <p className="text-xs text-paws-text-dim">VXLAN Tag</p>
                            <p className="font-mono text-sm text-paws-text">{selected.vxlan_tag ?? '—'}</p>
                          </div>
                          <div>
                            <p className="text-xs text-paws-text-dim">Zone</p>
                            <p className="font-mono text-sm text-paws-text">{selected.proxmox_zone || '—'}</p>
                          </div>
                          <div>
                            <p className="text-xs text-paws-text-dim">Network Mode</p>
                            <div className="flex items-center gap-2">
                              <Badge variant={selected.network_mode === 'published' ? 'warning' : selected.network_mode === 'isolated' ? 'danger' : 'success'}>
                                {(selected.network_mode || 'private').charAt(0).toUpperCase() + (selected.network_mode || 'private').slice(1)}
                              </Badge>
                            </div>
                          </div>
                          <div>
                            <p className="text-xs text-paws-text-dim">IP Mode</p>
                            <Badge variant="info">Static (Auto-assigned)</Badge>
                          </div>
                        </div>
                      </CardContent>
                    </Card>

                    {/* Network Mode Control */}
                    <Card>
                      <CardHeader><CardTitle>Change Network Mode</CardTitle></CardHeader>
                      <CardContent>
                        <div className="grid grid-cols-3 gap-2">
                          {(['private', 'published', 'isolated'] as const).map((mode) => (
                            <button
                              key={mode}
                              type="button"
                              disabled={changingMode}
                              onClick={async () => {
                                if (mode === selected.network_mode) return;
                                setChangingMode(true);
                                try {
                                  const res = await api.put(`/api/vpcs/${selected.id}/mode`, { network_mode: mode });
                                  toast(res.data.updated_instances > 0
                                    ? `Mode changed to ${mode}. Updated ${res.data.updated_instances} instance(s).`
                                    : `Mode changed to ${mode}.`, 'success');
                                  if (res.data.warnings) toast(res.data.warnings, 'warning');
                                  fetchVPCs();
                                } catch (e: any) {
                                  toast(e.response?.data?.detail || 'Failed to change mode', 'error');
                                } finally {
                                  setChangingMode(false);
                                }
                              }}
                              className={`rounded-lg border p-3 text-left transition-colors ${
                                (selected.network_mode || 'private') === mode
                                  ? 'border-paws-primary bg-paws-primary/10 ring-1 ring-paws-primary'
                                  : 'border-paws-border hover:border-paws-text-dim'
                              }`}
                            >
                              <p className="text-sm font-medium text-paws-text capitalize">{mode}</p>
                              <p className="text-xs text-paws-text-dim mt-0.5">
                                {mode === 'private' && 'Full LAN + Internet access'}
                                {mode === 'published' && 'Internet only, LAN blocked'}
                                {mode === 'isolated' && 'Own subnet only'}
                              </p>
                            </button>
                          ))}
                        </div>
                      </CardContent>
                    </Card>

                    {/* Subnets */}
                    <Card>
                      <CardHeader>
                        <div className="flex items-center justify-between">
                          <CardTitle>Subnets</CardTitle>
                          <Button size="sm" onClick={() => setShowSubnet(true)}>
                            <Plus className="h-4 w-4 mr-1" /> Add Subnet
                          </Button>
                        </div>
                      </CardHeader>
                      <CardContent>
                        {(selected.subnets || []).length === 0 ? (
                          <p className="text-sm text-paws-text-dim">No subnets.</p>
                        ) : (
                          <div className="space-y-2">
                            {selected.subnets.map((s) => (
                              <div key={s.id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                                <div className="flex items-center gap-3">
                                  <Globe className="h-4 w-4 text-paws-text-dim" />
                                  <div>
                                    <p className="text-sm font-medium text-paws-text">{s.name}</p>
                                    <p className="text-xs font-mono text-paws-text-dim">
                                      {s.cidr}{s.gateway ? ` · gw ${s.gateway}` : ''}
                                    </p>
                                  </div>
                                  {s.is_public && <Badge variant="warning">Public</Badge>}
                                  <Badge variant={s.snat_enabled ? 'success' : 'default'}>SNAT</Badge>
                                  <Badge variant="info">Static IP</Badge>
                                  <StatusBadge status={s.status} />
                                </div>
                                <Button variant="ghost" size="sm" onClick={() => handleDeleteSubnet(s.id)}>
                                  <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
                                </Button>
                              </div>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>

                    {/* Instances in VPC */}
                    <Card>
                      <CardHeader><CardTitle>Instances</CardTitle></CardHeader>
                      <CardContent>
                        {instances.length === 0 ? (
                          <p className="text-sm text-paws-text-dim">No instances attached to this VPC.</p>
                        ) : (
                          <div className="space-y-3">
                            {instances.map((inst) => (
                              <div key={inst.id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <Server className="h-4 w-4 text-paws-text-dim" />
                                  <span className="text-sm font-medium text-paws-text">{inst.name}</span>
                                  <Badge variant="default">{inst.type}</Badge>
                                  {inst.allocated_ips && inst.allocated_ips.length > 0 && inst.allocated_ips.map((ip) => (
                                    <span key={`alloc-${ip}`} className="text-xs font-mono px-1.5 py-0.5 rounded bg-paws-primary/10 text-paws-primary" title="Allocated IP">
                                      {ip}
                                    </span>
                                  ))}
                                  {inst.live_ips && inst.live_ips.length > 0 && inst.live_ips.filter(
                                    (lip) => !inst.allocated_ips?.includes(lip)
                                  ).map((ip) => (
                                    <span key={`live-${ip}`} className="text-xs font-mono px-1.5 py-0.5 rounded bg-paws-success/10 text-paws-success" title="Live IP (from guest agent)">
                                      {ip}
                                    </span>
                                  ))}
                                  {(!inst.allocated_ips || inst.allocated_ips.length === 0) && (!inst.live_ips || inst.live_ips.length === 0) && (
                                    <span className="text-xs text-paws-text-dim italic">No IP</span>
                                  )}
                                </div>
                                <div className="flex items-center gap-2">
                                  <button
                                    className="p-1 rounded hover:bg-paws-surface text-paws-text-dim hover:text-paws-primary"
                                    title="Change IP"
                                    onClick={() => {
                                      setEditIpInst(inst);
                                      setNewIp(inst.allocated_ips?.[0] || '');
                                    }}
                                  >
                                    <Edit2 className="h-3.5 w-3.5" />
                                  </button>
                                  <StatusBadge status={inst.status} />
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </>
                )}

                {/* Network Diagram Tab */}
                {detailTab === 'diagram' && (
                  <Card>
                    <CardHeader><CardTitle>Network Topology</CardTitle></CardHeader>
                    <CardContent>
                      <div className="bg-paws-bg rounded-lg p-6 min-h-[400px]">
                        {/* VPC container */}
                        <div className="border-2 border-paws-primary/30 rounded-xl p-4">
                          <div className="flex items-center gap-2 mb-4">
                            <Network className="h-5 w-5 text-paws-primary" />
                            <span className="font-bold text-paws-text">{selected.name}</span>
                            <span className="text-xs font-mono text-paws-text-dim">{selected.cidr}</span>
                          </div>

                          {/* Gateway */}
                          <div className="flex justify-center mb-6">
                            <div className="bg-paws-surface border border-paws-border rounded-lg px-4 py-2 text-center">
                              <p className="text-xs text-paws-text-dim">Gateway</p>
                              <p className="text-sm font-mono text-paws-text">{selected.gateway || 'Auto'}</p>
                            </div>
                          </div>

                          {/* Subnets */}
                          {(selected.subnets || []).length === 0 ? (
                            <div className="text-center py-8 text-sm text-paws-text-dim">
                              No subnets configured
                            </div>
                          ) : (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              {selected.subnets.map((subnet) => {
                                const subnetInstances = instances.filter((i) => i.subnet_id === subnet.id);
                                const hasMatchedAny = instances.some((i) => i.subnet_id);
                                // If no instances have subnet_id, show all instances under every subnet (or the first one)
                                const displayInstances = subnetInstances.length > 0
                                  ? subnetInstances
                                  : !hasMatchedAny
                                    ? instances
                                    : [];
                                return (
                                  <div
                                    key={subnet.id}
                                    className={cn(
                                      'border rounded-lg p-3',
                                      subnet.is_public ? 'border-paws-warning/40 bg-paws-warning/5' : 'border-paws-info/40 bg-paws-info/5',
                                    )}
                                  >
                                    <div className="flex items-center justify-between mb-2">
                                      <div className="flex items-center gap-2">
                                        <Globe className="h-4 w-4 text-paws-text-dim" />
                                        <span className="text-sm font-medium text-paws-text">{subnet.name}</span>
                                      </div>
                                      <Badge variant={subnet.is_public ? 'warning' : 'info'}>
                                        {subnet.is_public ? 'Public' : 'Private'}
                                      </Badge>
                                    </div>
                                    <p className="text-xs font-mono text-paws-text-dim mb-1">{subnet.cidr}</p>
                                    {subnet.gateway && (
                                      <p className="text-xs font-mono text-paws-text-dim mb-2">GW: {subnet.gateway}</p>
                                    )}

                                    {/* Instances in subnet */}
                                    {displayInstances.length > 0 ? (
                                      <div className="space-y-1">
                                        {displayInstances.map((inst) => (
                                          <div key={inst.id} className="flex items-center gap-2 bg-paws-surface rounded px-2 py-1 flex-wrap">
                                            <Server className="h-3 w-3 text-paws-text-dim" />
                                            <span className="text-xs text-paws-text">{inst.name}</span>
                                            <span className={cn(
                                              'w-1.5 h-1.5 rounded-full',
                                              inst.status === 'running' ? 'bg-paws-success' : 'bg-paws-text-dim',
                                            )} />
                                            {inst.allocated_ips && inst.allocated_ips.length > 0 && inst.allocated_ips.map((ip) => (
                                              <span key={`d-${ip}`} className="text-[10px] font-mono px-1 py-0.5 rounded bg-paws-primary/10 text-paws-primary">{ip}</span>
                                            ))}
                                            {(!inst.allocated_ips || inst.allocated_ips.length === 0) && inst.live_ips && inst.live_ips.length > 0 && inst.live_ips.map((ip) => (
                                              <span key={`dl-${ip}`} className="text-[10px] font-mono px-1 py-0.5 rounded bg-paws-success/10 text-paws-success">{ip}</span>
                                            ))}
                                          </div>
                                        ))}
                                      </div>
                                    ) : (
                                      <p className="text-xs text-paws-text-dim italic">No instances</p>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>

                        {/* Legend */}
                        <div className="flex items-center gap-6 mt-4 text-xs text-paws-text-dim">
                          <div className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full bg-paws-success" /> Running
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full bg-paws-text-dim" /> Stopped
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="w-3 h-2 rounded bg-paws-warning/30 border border-paws-warning/40" /> Public Subnet
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="w-3 h-2 rounded bg-paws-info/30 border border-paws-info/40" /> Private Subnet
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            ) : (
              <Card>
                <CardContent className="py-16 text-center text-paws-text-dim">
                  Select a VPC to view details, subnets, and attached instances.
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Network">
        <div className="space-y-4">
          <Input label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div>
            <label className="text-sm text-paws-text-dim mb-1 block">Network Mode</label>
            <div className="grid grid-cols-3 gap-2">
              {(['private', 'published', 'isolated'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setForm({ ...form, network_mode: mode })}
                  className={`rounded-lg border p-3 text-left transition-colors ${
                    form.network_mode === mode
                      ? 'border-paws-primary bg-paws-primary/10 ring-1 ring-paws-primary'
                      : 'border-paws-border hover:border-paws-text-dim'
                  }`}
                >
                  <p className="text-sm font-medium text-paws-text capitalize">{mode}</p>
                  <p className="text-xs text-paws-text-dim mt-0.5">
                    {mode === 'private' && 'Full LAN + Internet access'}
                    {mode === 'published' && 'Internet only, LAN blocked'}
                    {mode === 'isolated' && 'Own subnet only'}
                  </p>
                </button>
              ))}
            </div>
          </div>
          <p className="text-xs text-paws-text-dim">CIDR will be auto-allocated. IPs are assigned statically to instances.</p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name}>Create</Button>
          </div>
        </div>
      </Modal>

      <Modal open={showSubnet} onClose={() => setShowSubnet(false)} title="Add Subnet">
        <div className="space-y-4">
          <Input label="Name" value={subnetForm.name} onChange={(e) => setSubnetForm({ ...subnetForm, name: e.target.value })} />
          <Input label="CIDR (optional)" value={subnetForm.cidr} placeholder="Auto-allocate /24"
            onChange={(e) => setSubnetForm({ ...subnetForm, cidr: e.target.value })} />
          <Input label="Gateway (optional)" value={subnetForm.gateway} placeholder="Auto (first host IP)"
            onChange={(e) => setSubnetForm({ ...subnetForm, gateway: e.target.value })} />
          <label className="flex items-center gap-2 text-sm text-paws-text">
            <input
              type="checkbox"
              checked={subnetForm.snat_enabled}
              onChange={(e) => setSubnetForm({ ...subnetForm, snat_enabled: e.target.checked })}
              className="accent-paws-primary"
            />
            Enable Internet Access (SNAT)
          </label>
          <Input label="DNS Server (optional)" value={subnetForm.dns_server} placeholder="Default: 1.1.1.1"
            onChange={(e) => setSubnetForm({ ...subnetForm, dns_server: e.target.value })} />
          <p className="text-xs text-paws-text-dim">IPs are auto-allocated from this subnet when instances are assigned to the VPC.</p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowSubnet(false)}>Cancel</Button>
            <Button onClick={handleAddSubnet} disabled={!subnetForm.name}>Add</Button>
          </div>
        </div>
      </Modal>

      <Modal open={!!editIpInst} onClose={() => { setEditIpInst(null); setNewIp(''); }} title="Change Instance IP">
        <div className="space-y-4">
          <p className="text-sm text-paws-text">
            Change the static IP for <span className="font-medium">{editIpInst?.name}</span>.
            The new IP must be within one of the VPC subnet ranges.
          </p>
          {editIpInst?.allocated_ips && editIpInst.allocated_ips.length > 0 && (
            <p className="text-xs text-paws-text-dim">
              Current allocated IP: <span className="font-mono">{editIpInst.allocated_ips.join(', ')}</span>
            </p>
          )}
          {selected?.subnets && selected.subnets.length > 0 && (
            <p className="text-xs text-paws-text-dim">
              Available ranges: {selected.subnets.map((s) => s.cidr).join(', ')}
            </p>
          )}
          <Input
            label="New IP Address"
            value={newIp}
            onChange={(e) => setNewIp(e.target.value)}
            placeholder="e.g. 10.1.0.5"
          />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => { setEditIpInst(null); setNewIp(''); }}>Cancel</Button>
            <Button onClick={handleChangeIp} disabled={!newIp.trim()}>Change IP</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
