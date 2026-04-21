import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { LifecycleCountdown } from '@/components/ui/LifecycleCountdown';
import { useToast, useConfirm } from '@/components/ui';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { useAuth } from '@/context/AuthContext';

interface Container {
  id: string;
  name: string;
  vmid: number;
  node: string;
  cluster_id?: string;
  status: string;
  live_status?: string;
  specs: { cores?: number; memory_mb?: number; disk_gb?: number };
  created_at: string;
  last_accessed_at: string | null;
}

export default function Containers() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { toast } = useToast();
  const { confirm } = useConfirm();
  const [containers, setContainers] = useState<Container[]>([]);
  const [loading, setLoading] = useState(true);

  const fetch = () => {
    api.get('/api/compute/containers').then((res) => setContainers(res.data)).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(fetch, []);

  const doAction = async (id: string, action: string) => {
    await api.post(`/api/compute/containers/${id}/action`, { action });
    setTimeout(fetch, 2000);
  };

  const deleteContainer = async (id: string) => {
    if (!await confirm({ title: 'Destroy Container', message: 'Are you sure you want to destroy this container? This action cannot be undone.' })) return;
    try {
      await api.delete(`/api/compute/containers/${id}`);
      toast('Container destroyed successfully', 'success');
      fetch();
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      toast(typeof d === 'string' ? d : 'Failed to destroy container', 'error');
    }
  };

  const keepAlive = async (id: string) => {
    await api.post(`/api/compute/containers/${id}/keepalive`);
    fetch();
  };

  const lp = user?.lifecycle_policy;
  const auditing = !!user?.impersonated_by;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Containers</h1>
        <Button variant="primary" onClick={() => navigate('/create-instance')}>+ Create Container</Button>
      </div>
      {loading ? <LoadingSpinner message="Loading containers..." /> : containers.length === 0 ? (
        <p className="text-paws-text-dim">No containers yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {containers.map((ct) => (
            <Card key={ct.id} className="flex items-center gap-6 px-6 py-4 cursor-pointer hover:bg-paws-surface-hover transition-colors">
              <div className="flex items-center gap-6 flex-1 min-w-0" onClick={() => navigate(`/containers/${ct.id}`)}>
                <div className="flex-1">
                  <p className="font-bold text-paws-text">{ct.name}</p>
                  <p className="text-xs text-paws-text-muted">
                    CTID {ct.vmid} · {ct.node} · {ct.specs.cores}c / {ct.specs.memory_mb}MB
                  </p>
                </div>
                <StatusBadge status={ct.live_status || ct.status} />
                {lp && (
                  <LifecycleCountdown
                    lastAccessedAt={ct.last_accessed_at}
                    shutdownDays={lp.idle_shutdown_days}
                    destroyDays={lp.idle_destroy_days}
                    status={ct.live_status || ct.status}
                    onKeepAlive={() => keepAlive(ct.id)}
                    readOnly={auditing}
                  />
                )}
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => doAction(ct.id, 'start')}>Start</Button>
                <Button variant="outline" size="sm" onClick={() => doAction(ct.id, 'shutdown')}>Stop</Button>
                <Button variant="danger" size="sm" onClick={() => deleteContainer(ct.id)}>Destroy</Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
