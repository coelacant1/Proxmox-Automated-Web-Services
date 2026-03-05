import { useEffect, useState } from 'react';
import { CheckCircle, AlertTriangle, XCircle, RefreshCw } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent, Badge,
} from '@/components/ui';

interface ServiceStatus {
  name: string;
  status: 'healthy' | 'degraded' | 'offline';
  latency_ms?: number;
  message?: string;
}

export default function StatusPage() {
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [overall, setOverall] = useState<string>('unknown');
  const [loading, setLoading] = useState(true);
  const [lastCheck, setLastCheck] = useState<Date>(new Date());

  const fetchStatus = () => {
    setLoading(true);
    Promise.all([
      api.get('/health'),
      api.get('/api/cluster/status').catch(() => ({ data: { api_reachable: false } })),
    ])
      .then(([healthRes, clusterRes]) => {
        const health = healthRes.data;
        const cluster = clusterRes.data;
        setOverall(
          health.status === 'healthy' && cluster.api_reachable ? 'healthy'
            : health.status === 'healthy' || cluster.api_reachable ? 'degraded'
            : 'offline',
        );
        setServices([
          { name: 'API', status: health.status === 'healthy' ? 'healthy' : 'offline' },
          { name: 'Database', status: 'healthy' },
          { name: 'Proxmox Cluster', status: cluster.api_reachable ? 'healthy' : 'offline' },
        ]);
        setLastCheck(new Date());
      })
      .catch(() => {
        setOverall('offline');
        setServices([{ name: 'API', status: 'offline', message: 'Unable to connect' }]);
      })
      .finally(() => setLoading(false));
  };

  useEffect(fetchStatus, []);

  const statusIcon = (status: string) => {
    switch (status) {
      case 'healthy': return <CheckCircle className="h-5 w-5 text-paws-success" />;
      case 'degraded': return <AlertTriangle className="h-5 w-5 text-paws-warning" />;
      default: return <XCircle className="h-5 w-5 text-paws-danger" />;
    }
  };

  const overallColor = overall === 'healthy' ? 'text-paws-success' : overall === 'degraded' ? 'text-paws-warning' : 'text-paws-danger';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Service Status</h1>
        <div className="flex items-center gap-3">
          <span className="text-xs text-paws-text-dim">
            Last checked: {lastCheck.toLocaleTimeString()}
          </span>
          <Button variant="outline" size="sm" onClick={fetchStatus} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {/* Overall Status */}
      <Card className="mb-6">
        <CardContent className="py-8 text-center">
          <div className="flex items-center justify-center gap-3 mb-2">
            {statusIcon(overall)}
            <span className={`text-3xl font-bold capitalize ${overallColor}`}>{overall}</span>
          </div>
          <p className="text-sm text-paws-text-dim">
            {overall === 'healthy' ? 'All systems operational.' : overall === 'degraded' ? 'Some services are experiencing issues.' : 'Service disruption detected.'}
          </p>
        </CardContent>
      </Card>

      {/* Individual Services */}
      <Card>
        <CardHeader><CardTitle>Services</CardTitle></CardHeader>
        <CardContent className="p-0">
          <div className="divide-y divide-paws-border-subtle">
            {services.map((svc) => (
              <div key={svc.name} className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-3">
                  {statusIcon(svc.status)}
                  <span className="text-sm font-medium text-paws-text capitalize">{svc.name}</span>
                </div>
                <div className="flex items-center gap-3">
                  {svc.latency_ms !== undefined && (
                    <span className="text-xs text-paws-text-dim">{svc.latency_ms}ms</span>
                  )}
                  <Badge variant={svc.status === 'healthy' ? 'success' : svc.status === 'degraded' ? 'warning' : 'danger'}>
                    {svc.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
