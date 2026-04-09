import { useEffect, useState } from 'react';
import { Network, Plus, Trash2, Server, Globe, Edit2, Shield } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Input, Modal, Badge, EmptyState, StatusBadge, Select,
  useToast, useConfirm,
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
  cluster_id?: string;
  security_group_id?: string | null;
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
  const { confirm } = useConfirm();
  const [vpcs, setVpcs] = useState<VPC[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<VPC | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [instances, setInstances] = useState<VPCInstance[]>([]);
  const [clusters, setClusters] = useState<{name: string}[]>([]);
  const [form, setForm] = useState({ name: '', network_mode: 'private', cluster_id: '' });
  const [changingMode, setChangingMode] = useState(false);
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
    api.get('/api/cluster/list').then((res) => {
      setClusters(res.data || []);
      if (res.data?.length === 1) {
        setForm((prev) => ({ ...prev, cluster_id: res.data![0].name }));
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (selected) {
      api.get(`/api/vpcs/${selected.id}/instances`).then((res) => setInstances(res.data)).catch(() => setInstances([]));
    }
  }, [selected?.id]);

  const handleCreate = async () => {
    try {
      await api.post('/api/vpcs/', { name: form.name, network_mode: form.network_mode, cluster_id: form.cluster_id || undefined });
      setShowCreate(false);
      setForm({ name: '', network_mode: 'private', cluster_id: clusters.length === 1 ? clusters[0]?.name ?? '' : '' });
      fetchVPCs();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to create network', 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!await confirm({ title: 'Delete Network', message: 'Delete this network and its subnet?' })) return;
    try {
      await api.delete(`/api/vpcs/${id}`);
      if (selected?.id === id) setSelected(null);
      toast('Network deleted', 'success');
      fetchVPCs();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to delete network', 'error');
    }
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
      toast(typeof d === 'string' ? d : 'Failed to change IP', 'error');
    }
  };

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
                      {clusters.length > 1 && vpc.cluster_id && <Badge variant="default">{vpc.cluster_id}</Badge>}
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
                            <p className="font-mono text-sm text-paws-text">{selected.proxmox_vnet || '-'}</p>
                          </div>
                          <div>
                            <p className="text-xs text-paws-text-dim">VXLAN Tag</p>
                            <p className="font-mono text-sm text-paws-text">{selected.vxlan_tag ?? '-'}</p>
                          </div>
                          <div>
                            <p className="text-xs text-paws-text-dim">Zone</p>
                            <p className="font-mono text-sm text-paws-text">{selected.proxmox_zone || '-'}</p>
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

                    {/* Managed Firewall (Published Networks) */}
                    {selected.network_mode === 'published' && selected.security_group_id && (
                      <Card>
                        <CardContent>
                          <div className="flex items-center gap-3">
                            <Shield className="h-5 w-5 text-yellow-400 shrink-0" />
                            <div>
                              <p className="text-sm font-medium text-paws-text">Managed Firewall Active</p>
                              <p className="text-xs text-paws-text-dim">
                                This published network has an auto-managed firewall group that blocks all bogon/RFC1918 traffic.
                                Only your own subnet and admin-configured upstream proxies are allowed.
                              </p>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    )}

                    {/* Subnet */}
                    <Card>
                      <CardHeader>
                        <CardTitle>Subnet</CardTitle>
                      </CardHeader>
                      <CardContent>
                        {(selected.subnets || []).length === 0 ? (
                          <p className="text-sm text-paws-text-dim">No subnet configured.</p>
                        ) : (
                          <div className="flex items-center gap-3 py-1">
                            <Globe className="h-4 w-4 text-paws-text-dim" />
                            <div>
                              <p className="text-sm font-medium text-paws-text">{selected.subnets?.[0]?.name}</p>
                              <p className="text-xs font-mono text-paws-text-dim">
                                {selected.subnets?.[0]?.cidr}{selected.subnets?.[0]?.gateway ? ` · gw ${selected.subnets[0].gateway}` : ''}
                              </p>
                            </div>
                            <Badge variant={selected.subnets?.[0]?.snat_enabled ? 'success' : 'default'}>SNAT</Badge>
                            <Badge variant="info">Static IP</Badge>
                            <StatusBadge status={selected.subnets?.[0]?.status ?? 'unknown'} />
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
              ) : (
              <Card>
                <CardContent className="py-16 text-center text-paws-text-dim">
                  Select a network to view details and attached instances.
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

      <Modal open={!!editIpInst} onClose={() => { setEditIpInst(null); setNewIp(''); }} title="Change Instance IP">
        <div className="space-y-4">
          <p className="text-sm text-paws-text">
            Change the static IP for <span className="font-medium">{editIpInst?.name}</span>.
            The new IP must be within the network's subnet range.
          </p>
          {editIpInst?.allocated_ips && editIpInst.allocated_ips.length > 0 && (
            <p className="text-xs text-paws-text-dim">
              Current allocated IP: <span className="font-mono">{editIpInst.allocated_ips.join(', ')}</span>
            </p>
          )}
          {selected?.subnets && selected.subnets.length > 0 && (
            <p className="text-xs text-paws-text-dim">
              Available range: {selected.subnets?.[0]?.cidr}
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
