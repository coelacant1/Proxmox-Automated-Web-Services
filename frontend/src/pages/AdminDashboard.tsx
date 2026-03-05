import { useEffect, useState } from 'react';
import {
  Users, Server, Activity, AlertTriangle,
  CheckCircle, RefreshCw,
} from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Badge, StatusBadge, Tabs,
} from '@/components/ui';
import { MetricCard } from '@/components/ui';

interface HealthData {
  status: string;
  nodes_online?: number;
  total_nodes?: number;
  subsystems?: Record<string, { status: string; latency_ms?: number }>;
}

interface UserInfo {
  id: string;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  [key: string]: unknown;
}

export default function AdminDashboard() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [tab, setTab] = useState('health');
  const [loading, setLoading] = useState(true);

  const fetchData = () => {
    setLoading(true);
    Promise.all([
      api.get('/api/health/').catch(() => ({ data: { status: 'unknown' } })),
      api.get('/api/admin/users').catch(() => ({ data: [] })),
    ]).then(([healthRes, usersRes]) => {
      setHealth(healthRes.data);
      setUsers(usersRes.data);
      setLoading(false);
    });
  };

  useEffect(fetchData, []);

  const tabs = [
    { id: 'health', label: 'Cluster Health' },
    { id: 'users', label: 'Users', count: users.length },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-paws-text">Admin Dashboard</h1>
          <p className="text-sm text-paws-text-muted">System health and user management</p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <MetricCard label="Status" value={health?.status || 'Unknown'} icon={health?.status === 'healthy' ? CheckCircle : AlertTriangle} />
        <MetricCard label="Nodes" value={`${health?.nodes_online || 0} / ${health?.total_nodes || 0}`} icon={Server} />
        <MetricCard label="Users" value={String(users.length)} icon={Users} />
        <MetricCard label="Active" value={String(users.filter((u) => u.is_active).length)} icon={Activity} />
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} className="mb-6" />

      {tab === 'health' && health && (
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Subsystem Status</CardTitle></CardHeader>
            <CardContent>
              {health.subsystems ? (
                <div className="space-y-3">
                  {Object.entries(health.subsystems).map(([name, info]) => (
                    <div key={name} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                      <div className="flex items-center gap-3">
                        <StatusBadge status={info.status} />
                        <span className="text-sm font-medium text-paws-text capitalize">{name}</span>
                      </div>
                      {info.latency_ms !== undefined && (
                        <span className="text-xs text-paws-text-dim">{info.latency_ms}ms</span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-paws-text-dim">No subsystem data available.</p>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {tab === 'users' && (
        <Card>
          <CardHeader><CardTitle>All Users</CardTitle></CardHeader>
          <CardContent className="p-0">
            <div className="divide-y divide-paws-border-subtle">
              {users.map((u) => (
                <div key={u.id} className="flex items-center justify-between px-4 py-3 hover:bg-paws-surface-hover">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-paws-primary/20 flex items-center justify-center text-xs font-bold text-paws-primary">
                      {u.username.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-paws-text">{u.username}</p>
                      <p className="text-xs text-paws-text-dim">{u.email}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge variant={u.role === 'admin' ? 'warning' : 'default'}>{u.role}</Badge>
                    <Badge variant={u.is_active ? 'success' : 'danger'}>{u.is_active ? 'Active' : 'Disabled'}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
