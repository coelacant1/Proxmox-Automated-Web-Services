import { useEffect, useState } from 'react';
import { Monitor, Box, Network, HardDrive, AlertTriangle, Clock } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { MetricCard, QuotaBar, Card, CardHeader, CardTitle, CardContent, Badge, Button } from '@/components/ui';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { cn } from '@/lib/utils';
import { useAuth } from '@/context/AuthContext';

interface BackupQuota {
  max_snapshots: number;
  max_backups: number;
  max_backup_size_gb: number;
  snapshot_count: number;
  proxmox_backup_count: number;
  total_backup_size: number;
}

interface DashboardData {
  resources: {
    vms: number; containers: number; networks: number; storage_buckets: number;
    storage_size_gb: number;
    vcpus_used: number; ram_mb_used: number; disk_gb_used: number; snapshots: number;
  };
  quota: {
    max_vms: number; max_containers: number; max_vcpus: number;
    max_ram_mb: number; max_disk_gb: number; max_snapshots: number;
    max_backups: number; max_backup_size_gb: number;
    max_networks: number; max_elastic_ips: number;
    max_buckets: number; max_storage_gb: number;
  };
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

function clusterVariant(cluster: ClusterStatus): 'success' | 'warning' | 'danger' {
  if (!cluster.api_reachable) return 'danger';
  return cluster.nodes_online === cluster.node_count ? 'success' : 'warning';
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [health, setHealth] = useState<{ status: string } | null>(null);
  const [cluster, setCluster] = useState<ClusterStatus | null>(null);
  const [backupQuota, setBackupQuota] = useState<BackupQuota | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [clusterLoading, setClusterLoading] = useState(true);

  useEffect(() => {
    api.get('/health').then((res) => setHealth(res.data)).catch(() => {});
    api.get('/api/dashboard/summary').then((res) => setData(res.data)).catch(() => {}).finally(() => setSummaryLoading(false));
    api.get('/api/cluster/status').then((res) => setCluster(res.data)).catch(() => {}).finally(() => setClusterLoading(false));
    api.get('/api/backups/quota-summary').then((res) => setBackupQuota(res.data)).catch(() => {});
  }, []);

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
        {!cluster && clusterLoading && (
          <span className="text-xs text-paws-text-muted">Loading cluster status...</span>
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
      </div>

      {/* Account Lifecycle Countdown */}
      {user?.lifecycle_policy && user.lifecycle_policy.account_inactive_days > 0 && (() => {
        const lastLogin = user.last_login_at ? new Date(user.last_login_at) : null;
        if (!lastLogin) return null;
        const expiresAt = new Date(lastLogin.getTime() + user.lifecycle_policy.account_inactive_days * 86400000);
        const daysLeft = Math.max(0, Math.ceil((expiresAt.getTime() - Date.now()) / 86400000));
        const variant = daysLeft <= 3 ? 'border-paws-danger/50' : daysLeft <= 7 ? 'border-paws-warning/50' : 'border-paws-border-subtle';
        const textColor = daysLeft <= 3 ? 'text-paws-danger' : daysLeft <= 7 ? 'text-paws-warning' : 'text-paws-text-muted';
        return (
          <Card className={variant}>
            <CardContent className="py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={cn('p-2 rounded-full', daysLeft <= 7 ? 'bg-paws-warning/10' : 'bg-paws-primary/10')}>
                    <Clock className={cn('h-5 w-5', textColor)} />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-paws-text">
                      Account active for <span className={textColor}>{daysLeft} day{daysLeft !== 1 ? 's' : ''}</span>
                    </p>
                    <p className="text-xs text-paws-text-dim">
                      Log in regularly to keep your account and resources active. Resets each login.
                    </p>
                  </div>
                </div>
                <Badge variant={daysLeft <= 3 ? 'danger' : daysLeft <= 7 ? 'warning' : 'default'}>
                  {daysLeft}d remaining
                </Badge>
              </div>
            </CardContent>
          </Card>
        );
      })()}

      {summaryLoading ? (
        <LoadingSpinner message="Loading dashboard..." />
      ) : data && (
        <>
          {/* Over-quota warning banner */}
          {(() => {
            const overItems: string[] = [];
            if (data.resources.vms > data.quota.max_vms) overItems.push('VMs');
            if (data.resources.containers > data.quota.max_containers) overItems.push('Containers');
            if (data.resources.vcpus_used > data.quota.max_vcpus) overItems.push('vCPUs');
            if (data.resources.ram_mb_used > data.quota.max_ram_mb) overItems.push('RAM');
            if (data.resources.disk_gb_used > data.quota.max_disk_gb) overItems.push('Disk');
            if (data.resources.networks > data.quota.max_networks) overItems.push('Networks');
            if (data.resources.snapshots > data.quota.max_snapshots) overItems.push('Snapshots');
            if (backupQuota && backupQuota.proxmox_backup_count > data.quota.max_backups) overItems.push('Backups');
            if (backupQuota && backupQuota.total_backup_size > data.quota.max_backup_size_gb * 1024 * 1024 * 1024) overItems.push('Backup Storage');
            if (overItems.length === 0) return null;
            return (
              <Card className="border-paws-danger/50 bg-paws-danger/5">
                <CardContent className="py-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-full bg-paws-danger/10">
                        <AlertTriangle className="h-5 w-5 text-paws-danger" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-paws-danger">Quota Exceeded</p>
                        <p className="text-xs text-paws-text-dim">
                          You are over quota for: {overItems.join(', ')}. Running instances may be shut down automatically. Reduce usage or request a quota increase.
                        </p>
                      </div>
                    </div>
                    <Button variant="outline" size="sm" onClick={() => navigate('/quota-requests')}>
                      Request Increase
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })()}
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
              value={`${data.resources.networks} / ${data.quota.max_networks}`}
              icon={Network}
              variant="default"
            />
            <MetricCard
              label="Storage Buckets"
              value={`${data.resources.storage_buckets} / ${data.quota.max_buckets}`}
              icon={HardDrive}
              variant="default"
            />
          </div>

          {/* Quota usage */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Quota Usage</CardTitle>
                <Button variant="outline" size="sm" onClick={() => navigate('/quota-requests')}>View All</Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <QuotaBar label="VMs" used={data.resources.vms} limit={data.quota.max_vms} />
              <QuotaBar label="Containers" used={data.resources.containers} limit={data.quota.max_containers} />
              <QuotaBar label="vCPUs" used={data.resources.vcpus_used} limit={data.quota.max_vcpus} />
              <QuotaBar label="RAM" used={data.resources.ram_mb_used} limit={data.quota.max_ram_mb} unit=" MB" />
              <QuotaBar label="Disk" used={data.resources.disk_gb_used} limit={data.quota.max_disk_gb} unit=" GB" />
              <QuotaBar label="Networks" used={data.resources.networks} limit={data.quota.max_networks} />
              <QuotaBar label="Snapshots" used={backupQuota?.snapshot_count ?? data.resources.snapshots} limit={data.quota.max_snapshots} />
              <QuotaBar label="Backups" used={backupQuota?.proxmox_backup_count ?? 0} limit={data.quota.max_backups} />
              <QuotaBar label="Backup Storage" used={backupQuota ? Math.round(backupQuota.total_backup_size / (1024 * 1024 * 1024)) : 0} limit={data.quota.max_backup_size_gb} unit=" GB" />
              <QuotaBar label="S3 Buckets" used={data.resources.storage_buckets} limit={data.quota.max_buckets} />
              <QuotaBar label="S3 Storage" used={data.resources.storage_size_gb} limit={data.quota.max_storage_gb} unit=" GB" />
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
