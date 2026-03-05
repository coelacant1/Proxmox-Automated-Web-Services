import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Play, Square, RotateCcw, Trash2, Terminal, Monitor,
  Activity,
} from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  StatusBadge, Badge, Tabs, TagPills, ConfirmDialog,
} from '@/components/ui';

interface ResourceDetail {
  id: string;
  display_name: string;
  resource_type: string;
  status: string;
  live_status?: string;
  proxmox_vmid: number;
  proxmox_node: string;
  specs: Record<string, unknown>;
  created_at: string;
  [key: string]: unknown;
}

interface TaskLog {
  upid: string;
  type: string;
  status: string;
  starttime: number;
}

export default function ResourceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [resource, setResource] = useState<ResourceDetail | null>(null);
  const [tasks, setTasks] = useState<TaskLog[]>([]);
  const [tags, setTags] = useState<Array<{ key: string; value: string }>>([]);
  const [tab, setTab] = useState('overview');
  const [showDestroy, setShowDestroy] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchData = () => {
    if (!id) return;
    // Try VM first, then container
    api.get(`/api/compute/vms/${id}`).then((res) => {
      if (res?.data) {
        setResource(res.data);
        setLoading(false);
      }
    }).catch(() => {
      // Not a VM - try container
      api.get(`/api/compute/containers/${id}`).then((res) => {
        if (res?.data) {
          setResource(res.data);
          setLoading(false);
        }
      }).catch(() => setLoading(false));
    });
    api.get(`/api/logs/tasks/${id}`).then((r) => setTasks(r?.data?.tasks || [])).catch(() => {});
    api.get(`/api/tags/?resource_id=${id}`).then((r) => setTags(r?.data || [])).catch(() => {});
  };

   useEffect(fetchData, [id]);

  const doAction = async (action: string) => {
    if (!id || !resource) return;
    const base = resource.resource_type === 'lxc' ? '/api/compute/containers' : '/api/compute/vms';
    await api.post(`${base}/${id}/action`, { action });
    setTimeout(fetchData, 2000);
  };

  const handleDestroy = async () => {
    if (!id || !resource) return;
    const base = resource.resource_type === 'lxc' ? '/api/compute/containers' : '/api/compute/vms';
    await api.delete(`${base}/${id}`);
    navigate(resource.resource_type === 'lxc' ? '/containers' : '/vms');
  };

  if (loading) return <p className="text-paws-text-muted p-8">Loading...</p>;
  if (!resource) return <p className="text-paws-text-muted p-8">Resource not found</p>;

  const effectiveStatus = resource.live_status || resource.status;
  const specs = resource.specs || {};

  const tabList = [
    { id: 'overview', label: 'Overview' },
    { id: 'monitoring', label: 'Monitoring', icon: <Activity className="h-3.5 w-3.5" /> },
    { id: 'activity', label: 'Activity', count: tasks.length },
    { id: 'tags', label: 'Tags', count: tags.length },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate(-1)} className="p-1 rounded hover:bg-paws-surface-hover text-paws-text-dim">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-paws-text truncate">{resource.display_name}</h1>
            <StatusBadge status={effectiveStatus} />
            <Badge variant="default">{resource.resource_type.toUpperCase()}</Badge>
          </div>
          <p className="text-sm text-paws-text-muted mt-0.5">
            VMID {resource.proxmox_vmid} · {resource.proxmox_node} · Created {new Date(resource.created_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => doAction('start')} disabled={effectiveStatus === 'running'}>
            <Play className="h-3.5 w-3.5 mr-1" /> Start
          </Button>
          <Button variant="outline" size="sm" onClick={() => doAction('shutdown')} disabled={effectiveStatus === 'stopped'}>
            <Square className="h-3.5 w-3.5 mr-1" /> Stop
          </Button>
          <Button variant="outline" size="sm" onClick={() => doAction('reboot')} disabled={effectiveStatus === 'stopped'}>
            <RotateCcw className="h-3.5 w-3.5 mr-1" /> Reboot
          </Button>
          <Button variant="danger" size="sm" onClick={() => setShowDestroy(true)}>
            <Trash2 className="h-3.5 w-3.5 mr-1" /> Destroy
          </Button>
        </div>
      </div>

      <Tabs tabs={tabList} activeTab={tab} onChange={setTab} className="mb-6" />

      {/* Overview Tab */}
      {tab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle>Specifications</CardTitle></CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4">
                <InfoRow label="CPU Cores" value={String(specs.cores || specs.cpu || '-')} />
                <InfoRow label="Memory" value={`${specs.memory_mb || specs.ram_mb || 0} MB`} />
                <InfoRow label="Disk" value={`${specs.disk_gb || 0} GB`} />
                <InfoRow label="Storage" value={String(specs.storage || '-')} />
                <InfoRow label="Hostname" value={String(specs.hostname || '-')} />
                <InfoRow label="VPC" value={String(specs.vpc_id || 'None')} />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Console</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <Button variant="outline" size="sm" className="w-full justify-start gap-2">
                <Monitor className="h-4 w-4" /> VNC Console
              </Button>
              <Button variant="outline" size="sm" className="w-full justify-start gap-2">
                <Terminal className="h-4 w-4" /> Terminal
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Monitoring Tab */}
      {tab === 'monitoring' && (
        <Card>
          <CardHeader><CardTitle>Metrics</CardTitle></CardHeader>
          <CardContent>
            {effectiveStatus === 'running' ? (
              <p className="text-sm text-paws-text-muted">
                CPU, Memory, Disk I/O, and Network metrics are available via the monitoring API.
              </p>
            ) : (
              <p className="text-sm text-paws-text-dim">Instance is stopped. Start it to view live metrics.</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Activity Tab */}
      {tab === 'activity' && (
        <Card>
          <CardHeader><CardTitle>Activity Timeline</CardTitle></CardHeader>
          <CardContent>
            {tasks.length === 0 ? (
              <p className="text-sm text-paws-text-dim">No activity recorded.</p>
            ) : (
              <div className="relative pl-6">
                {tasks.map((t, i) => (
                  <div key={i} className="relative pb-5 last:pb-0">
                    {/* Connector line */}
                    {i < tasks.length - 1 && (
                      <div className="absolute left-[-16px] top-3 w-px h-full bg-paws-border-subtle" />
                    )}
                    {/* Dot */}
                    <div className={`absolute left-[-20px] top-1.5 w-2.5 h-2.5 rounded-full ring-2 ring-paws-surface ${
                      (t.status || '').includes('OK') ? 'bg-paws-success'
                      : (t.status || '').includes('error') ? 'bg-paws-danger'
                      : 'bg-paws-primary'
                    }`} />
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-paws-text">{t.type}</span>
                          <StatusBadge status={t.status || 'unknown'} />
                        </div>
                        <p className="text-xs text-paws-text-dim mt-0.5 font-mono">{t.upid?.slice(0, 30)}</p>
                      </div>
                      <span className="text-xs text-paws-text-dim whitespace-nowrap">
                        {t.starttime ? new Date(t.starttime * 1000).toLocaleString() : '-'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Tags Tab */}
      {tab === 'tags' && (
        <Card>
          <CardHeader><CardTitle>Tags</CardTitle></CardHeader>
          <CardContent>
            {tags.length > 0 ? (
              <TagPills tags={Object.fromEntries(tags.map((t) => [t.key, t.value]))} />
            ) : (
              <p className="text-sm text-paws-text-dim">No tags assigned.</p>
            )}
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={showDestroy}
        onCancel={() => setShowDestroy(false)}
        onConfirm={handleDestroy}
        title="Destroy Resource"
        message={`Are you sure you want to permanently destroy "${resource.display_name}"? This action cannot be undone.`}
        variant="danger"
        confirmLabel="Destroy"
      />
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="space-y-6">
      <p className="text-xs text-paws-text-dim">{label}</p>
      <p className="text-sm font-medium text-paws-text">{String(value)}</p>
    </div>
  );
}
