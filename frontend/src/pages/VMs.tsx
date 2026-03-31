import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { LifecycleCountdown } from '@/components/ui/LifecycleCountdown';
import { cn } from '@/lib/utils';
import { useToast, useConfirm } from '@/components/ui';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useAuth } from '@/context/AuthContext';

interface VM {
  id: string;
  name: string;
  resource_type?: string;
  vmid: number;
  node: string;
  cluster_id?: string;
  status: string;
  live_status?: string;
  specs: { cores?: number; memory_mb?: number; disk_gb?: number };
  created_at: string;
  last_accessed_at: string | null;
}

const statusDotColor = (s: string) => {
  if (s === 'running') return 'bg-paws-success';
  if (s === 'stopped') return 'bg-paws-danger';
  if (s === 'provisioning' || s === 'creating') return 'bg-paws-warning';
  return 'bg-paws-text-dim';
};

export default function VMs() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { toast } = useToast();
  const { confirm } = useConfirm();
  const [vms, setVms] = useState<VM[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchVMs = () => {
    api.get('/api/compute/vms').then((res) => setVms(res.data)).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(fetchVMs, []);

  const doAction = async (id: string, action: string) => {
    try {
      await api.post(`/api/compute/vms/${id}/action`, { action });
      setTimeout(fetchVMs, 2000);
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      toast(typeof d === 'string' ? d : `${action} failed`, 'error');
    }
  };

  const deleteVM = async (id: string) => {
    if (!await confirm({ title: 'Destroy VM', message: 'Are you sure you want to destroy this VM? This action cannot be undone.' })) return;
    try {
      await api.delete(`/api/compute/vms/${id}`);
      toast('VM destroyed successfully', 'success');
      fetchVMs();
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      toast(typeof d === 'string' ? d : 'Failed to destroy instance', 'error');
    }
  };

  const keepAlive = async (id: string) => {
    await api.post(`/api/compute/vms/${id}/keepalive`);
    fetchVMs();
  };

  const lp = user?.lifecycle_policy;
  const auditing = !!user?.impersonated_by;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Instances</h1>
        <Button variant="primary" onClick={() => navigate('/create-instance')}>+ Create Instance</Button>
      </div>
      {loading ? (
        <LoadingSpinner message="Loading instances..." />
      ) : vms.length === 0 ? (
        <p className="text-paws-text-dim">No instances yet. Create one from a template.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {vms.map((vm) => {
            const effectiveStatus = vm.live_status || vm.status;
            return (
              <Card
                key={vm.id}
                className="flex items-center gap-6 px-6 py-4 cursor-pointer hover:bg-paws-surface-hover transition-colors"
              >
                <div
                  className="flex items-center gap-6 flex-1 min-w-0"
                  onClick={() => navigate(`/vms/${vm.id}`)}
                >
                  <div
                    className={cn(
                      'h-2.5 w-2.5 shrink-0 rounded-full',
                      statusDotColor(effectiveStatus),
                    )}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="font-bold text-paws-text truncate">
                      {vm.name}
                      {vm.resource_type && (
                        <span className="ml-2 text-[10px] font-medium text-paws-text-dim uppercase bg-paws-surface px-1.5 py-0.5 rounded">
                          {vm.resource_type}
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-paws-text-muted">
                      VMID {vm.vmid} · {vm.node} · {vm.specs.cores}c / {vm.specs.memory_mb}MB / {vm.specs.disk_gb}GB
                    </p>
                  </div>
                  <StatusBadge status={effectiveStatus} />
                  {lp && (
                    <LifecycleCountdown
                      lastAccessedAt={vm.last_accessed_at}
                      shutdownDays={lp.idle_shutdown_days}
                      destroyDays={lp.idle_destroy_days}
                      status={effectiveStatus}
                      onKeepAlive={() => keepAlive(vm.id)}
                      readOnly={auditing}
                    />
                  )}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => doAction(vm.id, 'start')}>Start</Button>
                  <Button variant="outline" size="sm" onClick={() => doAction(vm.id, 'shutdown')}>Stop</Button>
                  <Button variant="outline" size="sm" onClick={() => doAction(vm.id, 'reboot')}>Reboot</Button>
                  <Button variant="danger" size="sm" onClick={() => deleteVM(vm.id)}>Destroy</Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
