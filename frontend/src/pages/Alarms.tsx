import { useEffect, useState } from 'react';
import { Bell, Plus, Trash2, AlertTriangle, CheckCircle, Clock } from 'lucide-react';
import api from '../api/client';
import {
  Button, DataTable, Input, Modal, Select, Badge, EmptyState, Tabs, type Column,
} from '@/components/ui';

interface Alarm {
  id: string;
  name: string;
  metric_name: string;
  comparison: string;
  threshold: number;
  period_seconds: number;
  state: string;
  resource_id: string | null;
  enabled: boolean;
  actions: AlarmAction[];
  created_at: string;
  [key: string]: unknown;
}

interface AlarmAction {
  type: string;
  target: string;
}

const stateIcon = (state: string) => {
  switch (state) {
    case 'alarm': return <AlertTriangle className="h-4 w-4 text-paws-danger" />;
    case 'ok': return <CheckCircle className="h-4 w-4 text-paws-success" />;
    default: return <Clock className="h-4 w-4 text-paws-text-dim" />;
  }
};

const stateVariant = (state: string): 'danger' | 'success' | 'default' => {
  if (state === 'alarm') return 'danger';
  if (state === 'ok') return 'success';
  return 'default';
};

export default function Alarms() {
  const [alarms, setAlarms] = useState<Alarm[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all');
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    name: '', metric_name: 'cpu_usage', comparison: 'GreaterThanThreshold',
    threshold: 80, period_seconds: 300, resource_id: '',
  });

  const fetchAlarms = () => {
    api.get('/api/monitoring/alarms/')
      .then((res) => setAlarms(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(fetchAlarms, []);

  const handleCreate = async () => {
    await api.post('/api/monitoring/alarms/', form);
    setShowCreate(false);
    setForm({ name: '', metric_name: 'cpu_usage', comparison: 'GreaterThanThreshold', threshold: 80, period_seconds: 300, resource_id: '' });
    fetchAlarms();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this alarm?')) return;
    await api.delete(`/api/monitoring/alarms/${id}`);
    fetchAlarms();
  };

  const handleToggle = async (alarm: Alarm) => {
    await api.patch(`/api/monitoring/alarms/${alarm.id}`, { enabled: !alarm.enabled });
    fetchAlarms();
  };

  const filtered = activeTab === 'all'
    ? alarms
    : activeTab === 'alerting' ? alarms.filter((a) => a.state === 'alarm')
    : alarms.filter((a) => a.state === 'ok' || a.state === 'insufficient_data');

  const tabs = [
    { id: 'all', label: 'All', count: alarms.length },
    { id: 'alerting', label: 'Alerting', count: alarms.filter((a) => a.state === 'alarm').length },
    { id: 'healthy', label: 'Healthy', count: alarms.filter((a) => a.state !== 'alarm').length },
  ];

  const columns: Column<Alarm>[] = [
    {
      key: 'state',
      header: '',
      render: (row) => stateIcon(row.state),
    },
    {
      key: 'name',
      header: 'Alarm',
      render: (row) => (
        <div>
          <p className="font-medium text-paws-text">{row.name}</p>
          <p className="text-xs text-paws-text-dim">
            {row.metric_name} {row.comparison.replace(/([A-Z])/g, ' $1').trim()} {row.threshold}
          </p>
        </div>
      ),
    },
    {
      key: 'stateLabel',
      header: 'State',
      render: (row) => <Badge variant={stateVariant(row.state)}>{row.state}</Badge>,
    },
    {
      key: 'period',
      header: 'Period',
      render: (row) => <span className="text-sm text-paws-text-dim">{row.period_seconds}s</span>,
    },
    {
      key: 'enabled',
      header: 'Enabled',
      render: (row) => (
        <button
          onClick={() => handleToggle(row)}
          className={`w-10 h-5 rounded-full transition-colors ${row.enabled ? 'bg-paws-primary' : 'bg-paws-surface-hover'}`}
        >
          <span className={`block w-4 h-4 rounded-full bg-white transform transition-transform ${row.enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
        </button>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (row) => (
        <Button variant="ghost" size="sm" onClick={() => handleDelete(row.id)}>
          <Trash2 className="h-4 w-4 text-paws-danger" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Alarms</h1>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> Create Alarm
        </Button>
      </div>

      <Tabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} className="mb-4" />

      {filtered.length === 0 && !loading ? (
        <EmptyState
          icon={Bell}
          title={activeTab === 'alerting' ? 'No active alerts' : 'No alarms configured'}
          description={activeTab === 'alerting' ? 'All systems operating normally.' : 'Create alarms to monitor your infrastructure metrics.'}
          action={activeTab === 'all' ? { label: 'Create Alarm', onClick: () => setShowCreate(true) } : undefined}
        />
      ) : (
        <DataTable columns={columns} data={filtered} loading={loading} />
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Alarm" size="lg">
        <div className="space-y-4">
          <Input label="Alarm Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div className="grid grid-cols-2 gap-4">
            <Select label="Metric" options={[
              { value: 'cpu_usage', label: 'CPU Usage (%)' },
              { value: 'memory_usage', label: 'Memory Usage (%)' },
              { value: 'disk_usage', label: 'Disk Usage (%)' },
              { value: 'network_in', label: 'Network In (MB/s)' },
              { value: 'network_out', label: 'Network Out (MB/s)' },
            ]} value={form.metric_name} onChange={(e) => setForm({ ...form, metric_name: e.target.value })} />
            <Select label="Condition" options={[
              { value: 'GreaterThanThreshold', label: 'Greater Than' },
              { value: 'LessThanThreshold', label: 'Less Than' },
              { value: 'GreaterThanOrEqual', label: '>= Threshold' },
              { value: 'LessThanOrEqual', label: '<= Threshold' },
            ]} value={form.comparison} onChange={(e) => setForm({ ...form, comparison: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Input label="Threshold" type="number" value={form.threshold}
              onChange={(e) => setForm({ ...form, threshold: +e.target.value })} />
            <Select label="Evaluation Period" options={[
              { value: '60', label: '1 minute' },
              { value: '300', label: '5 minutes' },
              { value: '900', label: '15 minutes' },
              { value: '3600', label: '1 hour' },
            ]} value={String(form.period_seconds)}
              onChange={(e) => setForm({ ...form, period_seconds: +e.target.value })} />
          </div>
          <Input label="Resource ID (optional)" placeholder="Leave empty for cluster-wide" value={form.resource_id}
            onChange={(e) => setForm({ ...form, resource_id: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name}>Create Alarm</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
