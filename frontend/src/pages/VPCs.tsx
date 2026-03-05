import { useEffect, useState } from 'react';
import { Network, Plus, Trash2, Server, Globe, Map } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Input, Modal, Badge, EmptyState, StatusBadge, Tabs,
} from '@/components/ui';
import { cn } from '@/lib/utils';

interface VPC {
  id: string;
  name: string;
  cidr: string;
  status: string;
  is_default: boolean;
  gateway: string | null;
  subnets: Subnet[];
}

interface Subnet {
  id: string;
  name: string;
  cidr: string;
  is_public: boolean;
}

export default function VPCs() {
  const [vpcs, setVpcs] = useState<VPC[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<VPC | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showSubnet, setShowSubnet] = useState(false);
  const [instances, setInstances] = useState<Array<{ id: string; name: string; type: string; status: string; subnet_id?: string }>>([]);
  const [form, setForm] = useState({ name: '', cidr: '10.0.0.0/16' });
  const [subnetForm, setSubnetForm] = useState({ name: '', cidr: '' });
  const [detailTab, setDetailTab] = useState('details');

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
    await api.post('/api/vpcs/', form);
    setShowCreate(false);
    setForm({ name: '', cidr: '10.0.0.0/16' });
    fetchVPCs();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this VPC and all its subnets?')) return;
    await api.delete(`/api/vpcs/${id}`);
    if (selected?.id === id) setSelected(null);
    fetchVPCs();
  };

  const handleAddSubnet = async () => {
    if (!selected) return;
    await api.post(`/api/vpcs/${selected.id}/subnets`, subnetForm);
    setShowSubnet(false);
    setSubnetForm({ name: '', cidr: '' });
    fetchVPCs();
  };

  const handleDeleteSubnet = async (subnetId: string) => {
    if (!selected) return;
    await api.delete(`/api/vpcs/${selected.id}/subnets/${subnetId}`);
    fetchVPCs();
  };

  const detailTabs = [
    { id: 'details', label: 'Details' },
    { id: 'diagram', label: 'Network Diagram', icon: <Map className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">VPCs</h1>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> Create VPC
        </Button>
      </div>

      {loading ? (
        <p className="text-paws-text-muted">Loading...</p>
      ) : vpcs.length === 0 ? (
        <EmptyState icon={Network} title="No VPCs" description="Create a Virtual Private Cloud to isolate your network resources." />
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
                                    <p className="text-xs font-mono text-paws-text-dim">{s.cidr}</p>
                                  </div>
                                  {s.is_public && <Badge variant="warning">Public</Badge>}
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
                          <div className="space-y-2">
                            {instances.map((inst) => (
                              <div key={inst.id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                                <div className="flex items-center gap-2">
                                  <Server className="h-4 w-4 text-paws-text-dim" />
                                  <span className="text-sm text-paws-text">{inst.name}</span>
                                  <Badge variant="default">{inst.type}</Badge>
                                </div>
                                <StatusBadge status={inst.status} />
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
                                    <p className="text-xs font-mono text-paws-text-dim mb-2">{subnet.cidr}</p>

                                    {/* Instances in subnet */}
                                    {subnetInstances.length > 0 ? (
                                      <div className="space-y-1">
                                        {subnetInstances.map((inst) => (
                                          <div key={inst.id} className="flex items-center gap-2 bg-paws-surface rounded px-2 py-1">
                                            <Server className="h-3 w-3 text-paws-text-dim" />
                                            <span className="text-xs text-paws-text">{inst.name}</span>
                                            <span className={cn(
                                              'ml-auto w-1.5 h-1.5 rounded-full',
                                              inst.status === 'running' ? 'bg-paws-success' : 'bg-paws-text-dim',
                                            )} />
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

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create VPC">
        <div className="space-y-4">
          <Input label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input label="CIDR Block" value={form.cidr} placeholder="10.0.0.0/16"
            onChange={(e) => setForm({ ...form, cidr: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name || !form.cidr}>Create</Button>
          </div>
        </div>
      </Modal>

      <Modal open={showSubnet} onClose={() => setShowSubnet(false)} title="Add Subnet">
        <div className="space-y-4">
          <Input label="Name" value={subnetForm.name} onChange={(e) => setSubnetForm({ ...subnetForm, name: e.target.value })} />
          <Input label="CIDR" value={subnetForm.cidr} placeholder="10.0.1.0/24"
            onChange={(e) => setSubnetForm({ ...subnetForm, cidr: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowSubnet(false)}>Cancel</Button>
            <Button onClick={handleAddSubnet} disabled={!subnetForm.name || !subnetForm.cidr}>Add</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
