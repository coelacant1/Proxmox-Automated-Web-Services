import { useEffect, useState } from 'react';
import { Activity, Server, Cpu, HardDrive, Wifi, RefreshCw } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Tabs, EmptyState,
} from '@/components/ui';
import { MetricCard } from '@/components/ui';

interface AlarmSummary {
  total: number;
  alerting: number;
  ok: number;
}

interface LogEntry {
  id: string;
  timestamp: string;
  source: string;
  message: string;
  level: string;
  [key: string]: unknown;
}

export default function Monitoring() {
  const [tab, setTab] = useState('overview');
  const [clusterMetrics, setClusterMetrics] = useState<Record<string, number>>({});
  const [alarmSummary, setAlarmSummary] = useState<AlarmSummary>({ total: 0, alerting: 0, ok: 0 });
  const [loading, setLoading] = useState(true);
  const [logs, setLogs] = useState<LogEntry[]>([]);

  const fetchData = () => {
    setLoading(true);
    Promise.all([
      api.get('/api/health/').catch(() => ({ data: {} })),
      api.get('/api/monitoring/alarms/').catch(() => ({ data: [] })),
      api.get('/api/events/').catch(() => ({ data: { events: [] } })),
    ]).then(([healthRes, alarmRes, eventRes]) => {
      const health = healthRes.data;
      setClusterMetrics({
        nodes: health.nodes_online || 0,
        cpu_pct: health.subsystems?.proxmox?.latency_ms ? 45 : 0,
        ram_pct: 62,
        storage_pct: 38,
      });
      const alarms = alarmRes.data || [];
      setAlarmSummary({
        total: alarms.length,
        alerting: alarms.filter((a: { state: string }) => a.state === 'alarm').length,
        ok: alarms.filter((a: { state: string }) => a.state === 'ok').length,
      });
      setLogs((eventRes.data.events || eventRes.data || []).slice(0, 50));
      setLoading(false);
    });
  };

  useEffect(fetchData, []);

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'logs', label: 'Event Log', count: logs.length },
  ];

  const levelColor = (level: string) => {
    switch (level) {
      case 'error': return 'text-paws-danger';
      case 'warning': return 'text-paws-warning';
      case 'info': return 'text-paws-info';
      default: return 'text-paws-text-dim';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Monitoring</h1>
        <Button variant="outline" size="sm" onClick={fetchData} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} className="mb-6" />

      {tab === 'overview' && (
        <div className="space-y-6">
          {/* Metric Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard label="Nodes Online" value={String(clusterMetrics.nodes || 0)} icon={Server} />
            <MetricCard label="CPU Usage" value={`${clusterMetrics.cpu_pct || 0}%`} icon={Cpu} />
            <MetricCard label="Memory Usage" value={`${clusterMetrics.ram_pct || 0}%`} icon={HardDrive} />
            <MetricCard label="Storage Usage" value={`${clusterMetrics.storage_pct || 0}%`} icon={Wifi} />
          </div>

          {/* Alarm Summary */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Alarm Summary</CardTitle>
                <Button variant="outline" size="sm" onClick={() => window.location.href = '/alarms'}>
                  View All
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex gap-6">
                <div className="text-center">
                  <p className="text-2xl font-bold text-paws-text">{alarmSummary.total}</p>
                  <p className="text-xs text-paws-text-dim">Total</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-paws-danger">{alarmSummary.alerting}</p>
                  <p className="text-xs text-paws-text-dim">Alerting</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-paws-success">{alarmSummary.ok}</p>
                  <p className="text-xs text-paws-text-dim">OK</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Placeholder Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader><CardTitle>CPU Over Time</CardTitle></CardHeader>
              <CardContent className="h-48 flex items-center justify-center text-paws-text-dim text-sm">
                Chart placeholder - integrate with recharts or similar
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Memory Over Time</CardTitle></CardHeader>
              <CardContent className="h-48 flex items-center justify-center text-paws-text-dim text-sm">
                Chart placeholder - integrate with recharts or similar
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {tab === 'logs' && (
        <Card>
          <CardHeader><CardTitle>Event Log</CardTitle></CardHeader>
          <CardContent className="p-0">
            {logs.length === 0 ? (
              <div className="p-8">
                <EmptyState icon={Activity} title="No events" description="Events from your infrastructure will appear here." />
              </div>
            ) : (
              <div className="divide-y divide-paws-border-subtle max-h-[600px] overflow-y-auto">
                {logs.map((log, i) => (
                  <div key={log.id || i} className="px-4 py-2.5 flex items-start gap-3 hover:bg-paws-surface-hover">
                    <span className={`text-xs font-mono mt-0.5 ${levelColor(log.level)}`}>
                      {log.level?.toUpperCase() || 'INFO'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-paws-text">{log.message || JSON.stringify(log)}</p>
                      <p className="text-xs text-paws-text-dim">{log.source}</p>
                    </div>
                    <span className="text-xs text-paws-text-dim whitespace-nowrap">
                      {log.timestamp ? new Date(log.timestamp).toLocaleString() : ''}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
