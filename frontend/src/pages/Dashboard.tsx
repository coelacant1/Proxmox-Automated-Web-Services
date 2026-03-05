import { useEffect, useState } from 'react';
import { Monitor, Box, Network, HardDrive, Bell, AlertTriangle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { MetricCard, QuotaBar, Card, CardHeader, CardTitle, CardContent, Badge, Button } from '@/components/ui';
import { cn } from '@/lib/utils';

interface DashboardData {
  resources: { vms: number; containers: number; networks: number; storage_buckets: number };
  quota: { max_vms: number; max_containers: number; max_vcpus: number; max_ram_mb: number; max_disk_gb: number };
  status_breakdown: Record<string, number>;
  recent_activity: Array<{ action: string; resource_type: string; created_at: string }>;
}

interface ClusterStatus {
  api_reachable: boolean;
  cluster_name: string | null;
  node_count: number;
  nodes_online: number;
  quorate: boolean;
}

interface AlarmSummary {
  id: string;
  name: string;
  state: string;
  severity: string;
  resource_id?: string;
}

function clusterVariant(cluster: ClusterStatus): 'success' | 'warning' | 'danger' {
  if (!cluster.api_reachable) return 'danger';
  return cluster.nodes_online === cluster.node_count ? 'success' : 'warning';
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardData | null>(null);
  const [health, setHealth] = useState<{ status: string } | null>(null);
  const [cluster, setCluster] = useState<ClusterStatus | null>(null);
  const [alarms, setAlarms] = useState<AlarmSummary[]>([]);

  useEffect(() => {
    api.get('/health').then((res) => setHealth(res.data)).catch(() => {});
    api.get('/api/dashboard/summary').then((res) => setData(res.data)).catch(() => {});
    api.get('/api/cluster/status').then((res) => setCluster(res.data)).catch(() => {});
    api.get('/api/monitoring/alarms').then((res) => {
      const all = res.data?.alarms || res.data || [];
      setAlarms(all.filter((a: AlarmSummary) => a.state === 'ALARM'));
    }).catch(() => {});
  }, []);

  const alarmCount = alarms.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-paws-text">Dashboard</h1>
        <p className="mt-1 text-paws-text-muted">
          Welcome to Proxmox Automated Web Services
        </p>
      </div>

      {/* Health & Cluster indicators */}
      <div className="flex items-center gap-6 flex-wrap">
        {health && (
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'inline-block h-2.5 w-2.5 rounded-full',
                health.status === 'healthy' ? 'bg-paws-success' : 'bg-paws-danger',
              )}
            />
            <span className="text-sm text-paws-text-muted">
              API: {health.status}
            </span>
          </div>
        )}
        {cluster && (
          <Badge variant={clusterVariant(cluster)}>
            <span
              className={cn(
                'mr-1.5 inline-block h-2 w-2 rounded-full',
                clusterVariant(cluster) === 'success'
                  ? 'bg-paws-success'
                  : clusterVariant(cluster) === 'warning'
                    ? 'bg-paws-warning'
                    : 'bg-paws-danger',
              )}
            />
            {cluster.api_reachable
              ? `Cluster: ${cluster.nodes_online}/${cluster.node_count} nodes`
              : 'Cluster: Unreachable'}
          </Badge>
        )}
        {/* Alarm indicator */}
        {alarmCount > 0 && (
          <div onClick={() => navigate('/alarms')} className="cursor-pointer">
            <Badge variant="danger">
              <AlertTriangle className="h-3 w-3 mr-1" />
              {alarmCount} active alarm{alarmCount !== 1 ? 's' : ''}
            </Badge>
          </div>
        )}
      </div>

      {/* Active Alarms Banner */}
      {alarmCount > 0 && (
        <Card className="border-paws-danger/30">
          <CardContent className="py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-full bg-paws-danger/10">
                  <Bell className="h-5 w-5 text-paws-danger" />
                </div>
                <div>
                  <p className="text-sm font-medium text-paws-text">{alarmCount} Active Alarm{alarmCount !== 1 ? 's' : ''}</p>
                  <p className="text-xs text-paws-text-dim">
                    {alarms.slice(0, 3).map((a) => a.name).join(', ')}
                    {alarms.length > 3 ? ` and ${alarms.length - 3} more` : ''}
                  </p>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={() => navigate('/alarms')}>
                View Alarms
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          {/* Resource cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="Virtual Machines"
              value={`${data.resources.vms} / ${data.quota.max_vms}`}
              icon={Monitor}
              variant="default"
            />
            <MetricCard
              label="Containers"
              value={`${data.resources.containers} / ${data.quota.max_containers}`}
              icon={Box}
              variant="default"
            />
            <MetricCard
              label="Networks"
              value={data.resources.networks}
              icon={Network}
              variant="default"
            />
            <MetricCard
              label="Storage Buckets"
              value={data.resources.storage_buckets}
              icon={HardDrive}
              variant="warning"
            />
          </div>

          {/* Quota usage */}
          <Card>
            <CardHeader>
              <CardTitle>Quota Usage</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <QuotaBar label="VMs" used={data.resources.vms} limit={data.quota.max_vms} />
              <QuotaBar label="Containers" used={data.resources.containers} limit={data.quota.max_containers} />
              <QuotaBar label="vCPUs" used={0} limit={data.quota.max_vcpus} />
              <QuotaBar label="RAM" used={0} limit={data.quota.max_ram_mb} unit=" MB" />
              <QuotaBar label="Disk" used={0} limit={data.quota.max_disk_gb} unit=" GB" />
            </CardContent>
          </Card>

          {/* Recent activity */}
          <Card>
            <CardHeader>
              <CardTitle>Recent Activity</CardTitle>
            </CardHeader>
            <CardContent>
              {data.recent_activity.length === 0 ? (
                <p className="text-paws-text-dim">No recent activity</p>
              ) : (
                <div className="relative pl-6">
                  {data.recent_activity.map((a, i) => (
                    <div key={i} className="relative pb-4 last:pb-0">
                      {/* Timeline line */}
                      {i < data.recent_activity.length - 1 && (
                        <div className="absolute left-[-16px] top-3 w-px h-full bg-paws-border-subtle" />
                      )}
                      {/* Timeline dot */}
                      <div className="absolute left-[-20px] top-1.5 w-2 h-2 rounded-full bg-paws-primary ring-2 ring-paws-surface" />
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-paws-text">
                          {a.action}{' '}
                          <span className="text-paws-text-dim">({a.resource_type})</span>
                        </span>
                        <span className="text-xs text-paws-text-dim">
                          {new Date(a.created_at).toLocaleString()}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
