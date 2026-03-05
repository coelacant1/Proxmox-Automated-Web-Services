import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Monitor, Terminal, Maximize, Minimize, Cloud, RotateCcw,
  Play, Square, Power, Trash2, Clock, Shield, Globe,
  Plus, X, Camera, HardDrive, Network, MousePointer,
} from 'lucide-react';
import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Area, AreaChart,
} from 'recharts';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Input, Modal, Badge, StatusBadge, Tabs, Select, ConfirmDialog,
} from '@/components/ui';

interface Instance {
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

interface SGRef { id: string; name: string; description?: string; rules?: SGRuleRef[]; }
interface SGRuleRef { id: string; direction: string; protocol: string; port_range_min?: number; port_range_max?: number; cidr?: string; }
interface EndpointRef { id: string; name: string; protocol: string; subdomain: string; fqdn: string; internal_port: number; is_active: boolean; }
interface SnapshotRef { name: string; description?: string; snaptime?: number; }
interface FirewallRule { pos: number; type: string; action: string; proto?: string; dport?: string; source?: string; comment?: string; enable: number; }

interface MetricPoint { time: number; cpu?: number; mem?: number; maxmem?: number; disk?: number; maxdisk?: number; netin?: number; netout?: number; diskread?: number; diskwrite?: number; }
interface TaskItem { upid: string; type: string; status?: string; starttime: number; endtime?: number; user?: string; node?: string; }
interface BackupItem { volid: string; size: number; ctime: number; format: string; storage: string; }
interface NetInterface { [key: string]: string; }

export default function InstanceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [inst, setInst] = useState<Instance | null>(null);
  const [tab, setTab] = useState('overview');
  const [loading, setLoading] = useState(true);
  const [showResize, setShowResize] = useState(false);
  const [showCloudInit, setShowCloudInit] = useState(false);
  const [showDestroy, setShowDestroy] = useState(false);
  const [resizeForm, setResizeForm] = useState({ cores: 1, memory_mb: 512, disk_gb: 10 });
  const [cloudInitForm, setCloudInitForm] = useState({ hostname: '', ssh_keys: '', user_data: '' });

  // Networking
  const [attachedSGs, setAttachedSGs] = useState<SGRef[]>([]);
  const [allSGs, setAllSGs] = useState<SGRef[]>([]);
  const [endpoints, setEndpoints] = useState<EndpointRef[]>([]);
  const [firewallRules, setFirewallRules] = useState<FirewallRule[]>([]);
  const [showAddEndpoint, setShowAddEndpoint] = useState(false);
  const [newEndpoint, setNewEndpoint] = useState({ name: '', protocol: 'http', internal_port: 80, subdomain: '' });
  const [showAddSG, setShowAddSG] = useState(false);

  // Snapshots
  const [snapshots, setSnapshots] = useState<SnapshotRef[]>([]);
  const [showNewSnapshot, setShowNewSnapshot] = useState(false);
  const [snapshotForm, setSnapshotForm] = useState({ name: '', description: '' });

  // Console
  const [consoleActive, setConsoleActive] = useState(false);
  const [consoleType, setConsoleType] = useState<'vnc' | 'terminal'>('vnc');
  const consoleRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<InstanceType<typeof import('@novnc/novnc').default> | null>(null);
  const [vncShowLocalCursor, setVncShowLocalCursor] = useState(false);
  const [vncFullscreen, setVncFullscreen] = useState(false);
  const vncWrapperRef = useRef<HTMLDivElement>(null);

  // Metrics, Tasks, Backups, Network
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [metricsTimeframe, setMetricsTimeframe] = useState('hour');
  const [taskHistory, setTaskHistory] = useState<TaskItem[]>([]);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [netInterfaces, setNetInterfaces] = useState<NetInterface>({});
  const [vpcs, setVpcs] = useState<Array<{ id: string; name: string; vnet?: string; vxlan_tag?: number; cidr?: string }>>([]);
  const [showBackupModal, setShowBackupModal] = useState(false);
  const [backupForm, setBackupForm] = useState({ storage: 'local', mode: 'snapshot', compress: 'zstd', notes: '' });
  const [showNetModal, setShowNetModal] = useState(false);
  const [netForm, setNetForm] = useState({ net_id: 'net0', vpc_id: '' });

  const fetchData = () => {
    if (!id) return;
    setLoading(true);
    api.get(`/api/compute/vms/${id}`).then((res) => {
      if (res?.data) {
        setInst(res.data);
        const sp = res.data.specs || {};
        setResizeForm({
          cores: Number(sp.cores || sp.cpu || 1),
          memory_mb: Number(sp.memory_mb || sp.ram_mb || 512),
          disk_gb: Number(sp.disk_gb || 10),
        });
      }
      setLoading(false);
    }).catch(() => setLoading(false));
    // Fetch related data
    api.get(`/api/security-groups/?resource_id=${id}`).then((r) => setAttachedSGs(r.data || [])).catch(() => {});
    api.get('/api/security-groups/').then((r) => setAllSGs(r.data || [])).catch(() => {});
    api.get(`/api/endpoints?resource_id=${id}`).then((r) => setEndpoints(r.data || [])).catch(() => {});
    api.get(`/api/compute/vms/${id}/snapshots`).then((r) => setSnapshots(r.data || [])).catch(() => {});
    // Metrics, tasks, backups, network
    api.get(`/api/compute/vms/${id}/metrics?timeframe=${metricsTimeframe}`).then((r) => setMetrics(r.data?.data || [])).catch(() => {});
    api.get(`/api/compute/vms/${id}/tasks`).then((r) => setTaskHistory(r.data?.tasks || [])).catch(() => {});
    api.get(`/api/compute/vms/${id}/backups`).then((r) => setBackups(r.data?.backups || [])).catch(() => {});
    api.get(`/api/compute/vms/${id}/network`).then((r) => {
      setNetInterfaces(r.data?.interfaces || {});
      setVpcs(r.data?.vpcs || []);
    }).catch(() => {});
  };

  const fetchFirewall = () => {
    if (!inst) return;
    api.get(`/api/networking/vms/${inst.proxmox_node}/${inst.proxmox_vmid}/firewall`)
      .then((r) => setFirewallRules(r.data || []))
      .catch(() => {});
  };

  useEffect(fetchData, [id]);
  useEffect(() => { if (inst && tab === 'networking') fetchFirewall(); }, [inst, tab]);
  useEffect(() => {
    if (!id) return;
    api.get(`/api/compute/vms/${id}/metrics?timeframe=${metricsTimeframe}`)
      .then((r) => setMetrics(r.data?.data || []))
      .catch(() => {});
  }, [metricsTimeframe, id]);

  const doAction = async (action: string) => {
    if (!id) return;
    await api.post(`/api/compute/vms/${id}/action`, { action });
    setTimeout(fetchData, 2000);
  };

  const handleResize = async () => {
    if (!id) return;
    try {
      await api.patch(`/api/compute/vms/${id}/resize`, resizeForm);
      setShowResize(false);
      fetchData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Resize failed');
    }
  };

  const handleCloudInit = async () => {
    if (!id) return;
    await api.put(`/api/compute/vms/${id}/cloud-init`, cloudInitForm);
    setShowCloudInit(false);
  };

  const handleDestroy = async () => {
    if (!id) return;
    await api.delete(`/api/compute/vms/${id}`);
    navigate('/vms');
  };

  // Security Group actions
  const attachSG = async (sgId: string) => {
    await api.post(`/api/security-groups/${sgId}/attach`, { resource_id: id });
    setShowAddSG(false);
    fetchData();
  };

  const detachSG = async (sgId: string) => {
    await api.post(`/api/security-groups/${sgId}/detach`, { resource_id: id });
    fetchData();
  };

  // Endpoint actions
  const createEndpoint = async () => {
    if (!id) return;
    try {
      await api.post('/api/endpoints', { ...newEndpoint, resource_id: id });
      setShowAddEndpoint(false);
      setNewEndpoint({ name: '', protocol: 'http', internal_port: 80, subdomain: '' });
      fetchData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Failed to create endpoint');
    }
  };

  const deleteEndpoint = async (epId: string) => {
    await api.delete(`/api/endpoints/${epId}`);
    fetchData();
  };

  const toggleEndpoint = async (ep: EndpointRef) => {
    await api.patch(`/api/endpoints/${ep.id}`, { is_active: !ep.is_active });
    fetchData();
  };

  // Snapshot actions
  const createSnapshot = async () => {
    if (!id) return;
    try {
      await api.post(`/api/compute/vms/${id}/snapshots`, snapshotForm);
      setShowNewSnapshot(false);
      setSnapshotForm({ name: '', description: '' });
      fetchData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Snapshot failed');
    }
  };

  // Console
  const openConsole = async (type: 'vnc' | 'terminal') => {
    setConsoleType(type);
    setConsoleActive(true);
  };

  const handleBackup = async () => {
    if (!id) return;
    try {
      await api.post(`/api/compute/vms/${id}/backups`, backupForm);
      setShowBackupModal(false);
      setBackupForm({ storage: 'local', mode: 'snapshot', compress: 'zstd', notes: '' });
      fetchData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Backup failed');
    }
  };

  const handleNetworkUpdate = async () => {
    if (!id) return;
    try {
      await api.put(`/api/compute/vms/${id}/network`, netForm);
      setShowNetModal(false);
      fetchData();
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Network update failed');
    }
  };

  // VNC key sender helpers
  const vncSendKey = (keysym: number, code: string) => rfbRef.current?.sendKey(keysym, code);
  const vncSendCtrlAltDel = () => rfbRef.current?.sendCtrlAltDel();
  const vncToggleFullscreen = () => {
    const el = vncWrapperRef.current;
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen().then(() => setVncFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setVncFullscreen(false)).catch(() => {});
    }
  };
  const vncToggleLocalCursor = () => {
    if (rfbRef.current) {
      const next = !vncShowLocalCursor;
      rfbRef.current.showDotCursor = next;
      setVncShowLocalCursor(next);
    }
  };

  useEffect(() => {
    if (!consoleActive || !consoleRef.current || !id) return;
    const token = localStorage.getItem('access_token') || '';
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/api/compute/ws/console/${id}?token=${token}&type=${consoleType}`;

    let cleanup: (() => void) | undefined;

    if (consoleType === 'vnc') {
      // Fetch VNC ticket first, then connect noVNC with credentials
      const initVnc = async () => {
        const el = consoleRef.current;
        if (!el) return;
        el.innerHTML = '<p class="text-paws-text-dim p-4">Connecting to VNC console...</p>';
        try {
          // Get VNC ticket from backend
          const ticketRes = await fetch(`/api/compute/vms/${id}/console?console_type=vnc`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (!ticketRes.ok) throw new Error('Failed to get VNC ticket');
          const ticketData = await ticketRes.json();
          const vncTicket = ticketData.ticket;

          const { default: RFB } = await import('@novnc/novnc');
          el.innerHTML = '';
          const rfb = new RFB(el, wsUrl);
          rfbRef.current = rfb;
          rfb.scaleViewport = true;
          rfb.resizeSession = true;
          rfb.background = '#1a1a1a';
          rfb.showDotCursor = vncShowLocalCursor;
          rfb.addEventListener('connect', () => console.log('[noVNC] Connected'));
          rfb.addEventListener('disconnect', (e: any) => {
            console.log('[noVNC] Disconnected:', e.detail);
            rfbRef.current = null;
            if (el) el.innerHTML = `<p class="text-orange-400 p-4">VNC disconnected: ${e.detail?.reason || 'unknown'}</p>`;
          });
          rfb.addEventListener('securityfailure', (e: any) => console.error('[noVNC] Security failure:', e.detail));
          rfb.addEventListener('credentialsrequired', () => {
            console.log('[noVNC] Credentials required, sending VNC ticket');
            rfb.sendCredentials({ password: vncTicket });
          });
          cleanup = () => { rfbRef.current = null; try { rfb.disconnect(); } catch {} };
        } catch (err) {
          console.error('[noVNC] Init error:', err);
          if (el) el.innerHTML = '<p class="text-paws-text-dim p-4">Failed to connect to VNC console.</p>';
        }
      };
      initVnc();
    } else {
      Promise.all([
        import('xterm'),
        import('xterm-addon-fit'),
        import('xterm-addon-attach'),
      ]).then(([{ Terminal: XTerminal }, { FitAddon }, { AttachAddon }]) => {
        const el = consoleRef.current;
        if (!el) return;
        el.innerHTML = '';
        const term = new XTerminal({
          theme: { background: '#1a1a1a', foreground: '#f2f2f2', cursor: '#e57000' },
          fontFamily: 'monospace',
          fontSize: 14,
        });
        const fitAddon = new FitAddon();
        term.loadAddon(fitAddon);
        term.open(el);
        fitAddon.fit();

        const ws = new WebSocket(wsUrl);
        ws.binaryType = 'arraybuffer';
        const attachAddon = new AttachAddon(ws);
        term.loadAddon(attachAddon);

        cleanup = () => { try { ws.close(); term.dispose(); } catch {} };
      });
    }

    return () => {
      cleanup?.();
    };
  }, [consoleActive, consoleType, id]);

  // Sync fullscreen state when user presses Escape to exit
  useEffect(() => {
    const onFsChange = () => { if (!document.fullscreenElement) setVncFullscreen(false); };
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  if (loading) return <p className="text-paws-text-muted p-8">Loading...</p>;
  if (!inst) return <p className="text-paws-text-muted p-8">Instance not found</p>;

  const vmStatus = inst.live_status || inst.status;
  const specs = inst.specs || {};

  const unattachedSGs = allSGs.filter((sg) => !attachedSGs.some((a) => a.id === sg.id));

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'monitoring', label: 'Monitoring' },
    { id: 'networking', label: 'Networking' },
    { id: 'snapshots', label: 'Snapshots', count: snapshots.filter((s) => s.name !== 'current').length },
    { id: 'backups', label: 'Backups', count: backups.length },
    { id: 'tasks', label: 'Tasks', count: taskHistory.length },
    { id: 'console', label: 'Console' },
    { id: 'lifecycle', label: 'Lifecycle' },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="p-1 rounded hover:bg-paws-surface-hover text-paws-text-dim">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-paws-text truncate">{inst.display_name}</h1>
            <StatusBadge status={vmStatus} />
            <Badge variant="default">{inst.resource_type.toUpperCase()}</Badge>
          </div>
          <p className="text-sm text-paws-text-muted mt-0.5">
            VMID {inst.proxmox_vmid} · {inst.proxmox_node} · {String(specs.cores || 1)} vCPU · {String(specs.memory_mb || 512)} MB
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button variant="outline" size="sm" onClick={() => doAction('start')} disabled={vmStatus === 'running'}>
            <Play className="h-3.5 w-3.5" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => doAction('shutdown')} disabled={vmStatus === 'stopped'}>
            <Square className="h-3.5 w-3.5" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => doAction('reboot')} disabled={vmStatus === 'stopped'}>
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => setShowResize(true)}>
            <Maximize className="h-3.5 w-3.5" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => setShowCloudInit(true)}>
            <Cloud className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} className="mb-6" />

      {/* Overview */}
      {tab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle>Specifications</CardTitle></CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4">
                <Stat label="CPU Cores" value={String(specs.cores || specs.cpu || 1)} />
                <Stat label="Memory" value={`${specs.memory_mb || specs.ram_mb || 0} MB`} />
                <Stat label="Disk" value={`${specs.disk_gb || 0} GB`} />
                <Stat label="Storage Pool" value={String(specs.storage || 'local')} />
                <Stat label="Hostname" value={String(specs.hostname || '-')} />
                <Stat label="Instance Type" value={String(specs.instance_type || 'Custom')} />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Status</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                <Stat label="Status" value={vmStatus} />
                <Stat label="Created" value={new Date(inst.created_at).toLocaleString()} />
                <Stat label="VMID" value={String(inst.proxmox_vmid)} />
                <Stat label="Node" value={inst.proxmox_node} />
              </div>
            </CardContent>
          </Card>
          <Card className="lg:col-span-3">
            <CardHeader><CardTitle>Network Interfaces</CardTitle></CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {Object.entries(netInterfaces).length > 0 ? Object.entries(netInterfaces).map(([k, v]) => (
                  <Stat key={k} label={k} value={String(v).substring(0, 60)} />
                )) : <p className="text-sm text-paws-text-dim">No network interfaces found.</p>}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Monitoring - Proxmox-style charts */}
      {tab === 'monitoring' && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm text-paws-text-dim">Timeframe:</span>
            {['hour', 'day', 'week', 'month', 'year'].map((tf) => (
              <Button key={tf} size="sm" variant={metricsTimeframe === tf ? 'primary' : 'outline'}
                onClick={() => setMetricsTimeframe(tf)} className="capitalize text-xs">{tf}</Button>
            ))}
          </div>
          {metrics.length === 0 ? (
            <Card><CardContent><p className="text-sm text-paws-text-dim py-4">No metrics data available.</p></CardContent></Card>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <MetricsChart title="CPU Usage" data={metrics} dataKey="cpu" color="#e5a00d" unit="%" formatter={(v: number) => `${(v * 100).toFixed(1)}%`} />
              <MetricsChart title="Memory Usage" data={metrics} dataKey="mem" color="#3b82f6" unit=" bytes" secondaryKey="maxmem" secondaryColor="#1e40af" formatter={fmtBytes} />
              <MetricsChart title="Network Traffic" data={metrics} dataKey="netin" color="#10b981" unit="" secondaryKey="netout" secondaryColor="#f97316" formatter={fmtBytes} legendLabels={['In', 'Out']} />
              <MetricsChart title="Disk IO" data={metrics} dataKey="diskread" color="#8b5cf6" unit="" secondaryKey="diskwrite" secondaryColor="#ec4899" formatter={fmtBytes} legendLabels={['Read', 'Write']} />
            </div>
          )}
        </div>
      )}

      {/* Networking */}
      {tab === 'networking' && (
        <div className="space-y-4">
          {/* Network Interfaces */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between w-full">
                <CardTitle>Network Interfaces</CardTitle>
                <Button variant="outline" size="sm" onClick={() => setShowNetModal(true)}>
                  <Network className="h-3.5 w-3.5 mr-1" /> Change Network
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {Object.entries(netInterfaces).length === 0 ? (
                <p className="text-sm text-paws-text-dim">No interfaces configured.</p>
              ) : (
                <div className="space-y-2">
                  {Object.entries(netInterfaces).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                      <span className="text-sm font-medium text-paws-accent">{k}</span>
                      <span className="text-sm text-paws-text font-mono">{String(v)}</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Security Groups */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between w-full">
                <CardTitle>Security Groups</CardTitle>
                <Button variant="outline" size="sm" onClick={() => setShowAddSG(true)}>
                  <Plus className="h-3.5 w-3.5 mr-1" /> Attach
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {attachedSGs.length === 0 ? (
                <p className="text-sm text-paws-text-dim">No security groups attached.</p>
              ) : (
                <div className="space-y-2">
                  {attachedSGs.map((sg) => (
                    <div key={sg.id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                      <div className="flex items-center gap-2">
                        <Shield className="h-4 w-4 text-paws-text-dim" />
                        <span className="text-sm font-medium text-paws-text">{sg.name}</span>
                        {sg.description && <span className="text-xs text-paws-text-dim">- {sg.description}</span>}
                      </div>
                      <Button variant="outline" size="sm" onClick={() => detachSG(sg.id)}>
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Service Endpoints */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between w-full">
                <CardTitle>Service Endpoints</CardTitle>
                <Button variant="outline" size="sm" onClick={() => setShowAddEndpoint(true)}>
                  <Plus className="h-3.5 w-3.5 mr-1" /> Add Endpoint
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {endpoints.length === 0 ? (
                <p className="text-sm text-paws-text-dim">No endpoints configured.</p>
              ) : (
                <div className="space-y-2">
                  {endpoints.map((ep) => (
                    <div key={ep.id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                      <div className="flex items-center gap-2">
                        <Globe className="h-3.5 w-3.5 text-paws-text-dim" />
                        <span className="text-sm text-paws-text">{ep.name}</span>
                        <Badge variant="default">{ep.protocol}</Badge>
                        <span className="text-xs font-mono text-paws-text-dim">{ep.fqdn}:{ep.internal_port}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button variant="outline" size="sm" onClick={() => toggleEndpoint(ep)}>
                          {ep.is_active ? 'Disable' : 'Enable'}
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => deleteEndpoint(ep.id)}>
                          <X className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Firewall Rules */}
          <Card>
            <CardHeader><CardTitle>Proxmox Firewall Rules</CardTitle></CardHeader>
            <CardContent>
              {firewallRules.length === 0 ? (
                <p className="text-sm text-paws-text-dim">No firewall rules configured on Proxmox.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-paws-text-dim border-b border-paws-border-subtle">
                        <th className="pb-2 pr-4">#</th>
                        <th className="pb-2 pr-4">Direction</th>
                        <th className="pb-2 pr-4">Action</th>
                        <th className="pb-2 pr-4">Protocol</th>
                        <th className="pb-2 pr-4">Port</th>
                        <th className="pb-2 pr-4">Source</th>
                        <th className="pb-2">Comment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {firewallRules.map((r, i) => (
                        <tr key={i} className="border-b border-paws-border-subtle last:border-0">
                          <td className="py-1.5 pr-4 text-paws-text-dim">{r.pos}</td>
                          <td className="py-1.5 pr-4 text-paws-text">{r.type}</td>
                          <td className="py-1.5 pr-4">
                            <Badge variant={r.action === 'ACCEPT' ? 'success' : 'danger'}>{r.action}</Badge>
                          </td>
                          <td className="py-1.5 pr-4 text-paws-text">{r.proto || 'any'}</td>
                          <td className="py-1.5 pr-4 font-mono text-paws-text">{r.dport || '-'}</td>
                          <td className="py-1.5 pr-4 font-mono text-paws-text-dim">{r.source || 'any'}</td>
                          <td className="py-1.5 text-paws-text-dim">{r.comment || ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Snapshots */}
      {tab === 'snapshots' && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between w-full">
              <CardTitle>Snapshots</CardTitle>
              <Button variant="outline" size="sm" onClick={() => setShowNewSnapshot(true)}>
                <Camera className="h-3.5 w-3.5 mr-1" /> Take Snapshot
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {snapshots.filter((s) => s.name !== 'current').length === 0 ? (
              <p className="text-sm text-paws-text-dim">No snapshots yet.</p>
            ) : (
              <div className="space-y-2">
                {snapshots.filter((s) => s.name !== 'current').map((snap) => (
                  <div key={snap.name} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                    <div>
                      <p className="text-sm font-medium text-paws-text">{snap.name}</p>
                      {snap.description && <p className="text-xs text-paws-text-dim">{snap.description}</p>}
                    </div>
                    <span className="text-xs text-paws-text-dim">
                      {snap.snaptime ? new Date(snap.snaptime * 1000).toLocaleString() : ''}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Backups */}
      {tab === 'backups' && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between w-full">
                <CardTitle>Backups</CardTitle>
                <Button variant="outline" size="sm" onClick={() => setShowBackupModal(true)}>
                  <HardDrive className="h-3.5 w-3.5 mr-1" /> Create Backup
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {backups.length === 0 ? (
                <p className="text-sm text-paws-text-dim">No backups found.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-paws-text-dim border-b border-paws-border-subtle">
                      <th className="text-left py-2">Volume</th>
                      <th className="text-left py-2">Date</th>
                      <th className="text-left py-2">Size</th>
                      <th className="text-left py-2">Format</th>
                      <th className="text-left py-2">Storage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backups.map((b, i) => (
                      <tr key={i} className="border-b border-paws-border-subtle last:border-0">
                        <td className="py-2 font-mono text-xs text-paws-text">{b.volid}</td>
                        <td className="py-2 text-paws-text">{new Date(b.ctime * 1000).toLocaleString()}</td>
                        <td className="py-2 text-paws-text">{fmtBytes(b.size)}</td>
                        <td className="py-2 text-paws-text">{b.format}</td>
                        <td className="py-2 text-paws-text">{b.storage}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tasks */}
      {tab === 'tasks' && (
        <Card>
          <CardHeader><CardTitle>Task History</CardTitle></CardHeader>
          <CardContent>
            {taskHistory.length === 0 ? (
              <p className="text-sm text-paws-text-dim">No task history available.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-paws-text-dim border-b border-paws-border-subtle">
                    <th className="text-left py-2">Type</th>
                    <th className="text-left py-2">Status</th>
                    <th className="text-left py-2">Started</th>
                    <th className="text-left py-2">Ended</th>
                    <th className="text-left py-2">User</th>
                    <th className="text-left py-2">Node</th>
                  </tr>
                </thead>
                <tbody>
                  {taskHistory.map((t, i) => (
                    <tr key={i} className="border-b border-paws-border-subtle last:border-0">
                      <td className="py-2 text-paws-text font-medium">{t.type}</td>
                      <td className="py-2">
                        <Badge variant={t.status === 'OK' ? 'success' : t.status ? 'danger' : 'default'}>{t.status || 'running'}</Badge>
                      </td>
                      <td className="py-2 text-paws-text">{new Date(t.starttime * 1000).toLocaleString()}</td>
                      <td className="py-2 text-paws-text">{t.endtime ? new Date(t.endtime * 1000).toLocaleString() : '-'}</td>
                      <td className="py-2 text-paws-text">{t.user || '-'}</td>
                      <td className="py-2 text-paws-text">{t.node || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Console */}
      {tab === 'console' && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between w-full">
              <CardTitle>Console</CardTitle>
              {consoleActive && (
                <Button variant="outline" size="sm" onClick={() => setConsoleActive(false)}>Disconnect</Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {vmStatus !== 'running' ? (
              <p className="text-sm text-paws-text-dim">Start the instance to access the console.</p>
            ) : !consoleActive ? (
              <div className="flex gap-3">
                <Button variant="outline" onClick={() => openConsole('vnc')}>
                  <Monitor className="h-4 w-4 mr-2" /> VNC Console
                </Button>
                <Button variant="outline" onClick={() => openConsole('terminal')}>
                  <Terminal className="h-4 w-4 mr-2" /> Terminal (xterm.js)
                </Button>
              </div>
            ) : (
              <div ref={vncWrapperRef}>
                {/* VNC Toolbar */}
                {consoleType === 'vnc' && (
                  <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                    <Button variant="outline" size="sm" onClick={() => vncSendKey(0xffe3, 'ControlLeft')} title="Send Ctrl">
                      Ctrl
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => vncSendKey(0xffe9, 'AltLeft')} title="Send Alt">
                      Alt
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => vncSendKey(0xffeb, 'SuperLeft')} title="Send Windows/Super key">
                      ⊞ Win
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => vncSendKey(0xff1b, 'Escape')} title="Send Escape">
                      Esc
                    </Button>
                    <Button variant="outline" size="sm" onClick={vncSendCtrlAltDel} title="Send Ctrl+Alt+Delete">
                      Ctrl+Alt+Del
                    </Button>
                    <div className="w-px h-6 bg-paws-border mx-1" />
                    <Button
                      variant={vncShowLocalCursor ? 'primary' : 'outline'}
                      size="sm"
                      onClick={vncToggleLocalCursor}
                      title="Toggle local cursor"
                    >
                      <MousePointer className="h-3.5 w-3.5 mr-1" />
                      Cursor
                    </Button>
                    <Button variant="outline" size="sm" onClick={vncToggleFullscreen} title="Toggle fullscreen">
                      {vncFullscreen
                        ? <><Minimize className="h-3.5 w-3.5 mr-1" /> Exit Fullscreen</>
                        : <><Maximize className="h-3.5 w-3.5 mr-1" /> Fullscreen</>
                      }
                    </Button>
                  </div>
                )}
                {/* 16:9 console container */}
                <div
                  ref={consoleRef}
                  className="w-full bg-black rounded-md overflow-hidden"
                  style={{ aspectRatio: '16 / 9', maxHeight: vncFullscreen ? '100vh' : '70vh' }}
                />
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Lifecycle */}
      {tab === 'lifecycle' && (
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Power Actions</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-3">
              <Button variant="outline" onClick={() => doAction('start')} disabled={vmStatus === 'running'}>
                <Play className="h-4 w-4 mr-1" /> Start
              </Button>
              <Button variant="outline" onClick={() => doAction('shutdown')} disabled={vmStatus === 'stopped'}>
                <Square className="h-4 w-4 mr-1" /> Graceful Shutdown
              </Button>
              <Button variant="outline" onClick={() => doAction('stop')} disabled={vmStatus === 'stopped'}>
                <Power className="h-4 w-4 mr-1" /> Force Stop
              </Button>
              <Button variant="outline" onClick={() => doAction('reboot')} disabled={vmStatus === 'stopped'}>
                <RotateCcw className="h-4 w-4 mr-1" /> Reboot
              </Button>
              <Button variant="outline" onClick={() => doAction('suspend')} disabled={vmStatus !== 'running'}>
                <Clock className="h-4 w-4 mr-1" /> Suspend
              </Button>
              <Button variant="outline" onClick={() => doAction('resume')} disabled={vmStatus !== 'suspended'}>
                <Play className="h-4 w-4 mr-1" /> Resume
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Configuration</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-3">
              <Button variant="outline" onClick={() => setShowResize(true)}>
                <Maximize className="h-4 w-4 mr-1" /> Resize
              </Button>
              <Button variant="outline" onClick={() => setShowCloudInit(true)}>
                <Cloud className="h-4 w-4 mr-1" /> Cloud-Init
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="text-paws-danger">Danger Zone</CardTitle></CardHeader>
            <CardContent>
              <Button variant="danger" onClick={() => setShowDestroy(true)}>
                <Trash2 className="h-4 w-4 mr-1" /> Destroy Instance
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Resize Modal */}
      <Modal open={showResize} onClose={() => setShowResize(false)} title="Resize Instance">
        <div className="space-y-4">
          <p className="text-xs text-paws-text-dim">Instance must be stopped to resize CPU/Memory. Disk can only be increased.</p>
          <Input label="CPU Cores" type="number" min={1} max={32} value={resizeForm.cores}
            onChange={(e) => setResizeForm({ ...resizeForm, cores: +e.target.value })} />
          <Input label="Memory (MB)" type="number" min={256} step={256} value={resizeForm.memory_mb}
            onChange={(e) => setResizeForm({ ...resizeForm, memory_mb: +e.target.value })} />
          <Input label="Disk (GB)" type="number" min={resizeForm.disk_gb} value={resizeForm.disk_gb}
            onChange={(e) => setResizeForm({ ...resizeForm, disk_gb: +e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowResize(false)}>Cancel</Button>
            <Button onClick={handleResize}>Resize</Button>
          </div>
        </div>
      </Modal>

      {/* Cloud-Init Modal */}
      <Modal open={showCloudInit} onClose={() => setShowCloudInit(false)} title="Cloud-Init Configuration" size="lg">
        <div className="space-y-4">
          <Input label="Hostname" value={cloudInitForm.hostname}
            onChange={(e) => setCloudInitForm({ ...cloudInitForm, hostname: e.target.value })} />
          <div>
            <label className="block text-sm font-medium text-paws-text mb-1">SSH Keys</label>
            <textarea
              className="w-full h-20 bg-paws-bg border border-paws-border rounded-md px-3 py-2 text-sm text-paws-text font-mono resize-y"
              value={cloudInitForm.ssh_keys}
              onChange={(e) => setCloudInitForm({ ...cloudInitForm, ssh_keys: e.target.value })}
              placeholder="ssh-ed25519 AAAA..."
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-paws-text mb-1">User Data (cloud-config)</label>
            <textarea
              className="w-full h-32 bg-paws-bg border border-paws-border rounded-md px-3 py-2 text-sm text-paws-text font-mono resize-y"
              value={cloudInitForm.user_data}
              onChange={(e) => setCloudInitForm({ ...cloudInitForm, user_data: e.target.value })}
              placeholder="#cloud-config&#10;packages:&#10;  - nginx"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCloudInit(false)}>Cancel</Button>
            <Button onClick={handleCloudInit}>Save</Button>
          </div>
        </div>
      </Modal>

      {/* Attach Security Group Modal */}
      <Modal open={showAddSG} onClose={() => setShowAddSG(false)} title="Attach Security Group">
        <div className="space-y-3">
          {unattachedSGs.length === 0 ? (
            <p className="text-sm text-paws-text-dim">All your security groups are already attached.</p>
          ) : (
            unattachedSGs.map((sg) => (
              <div key={sg.id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                <div>
                  <p className="text-sm font-medium text-paws-text">{sg.name}</p>
                  {sg.description && <p className="text-xs text-paws-text-dim">{sg.description}</p>}
                </div>
                <Button variant="outline" size="sm" onClick={() => attachSG(sg.id)}>Attach</Button>
              </div>
            ))
          )}
        </div>
      </Modal>

      {/* Add Endpoint Modal */}
      <Modal open={showAddEndpoint} onClose={() => setShowAddEndpoint(false)} title="Add Service Endpoint">
        <div className="space-y-4">
          <Input label="Name" value={newEndpoint.name}
            onChange={(e) => setNewEndpoint({ ...newEndpoint, name: e.target.value })} />
          <Select label="Protocol" options={[
            { value: 'http', label: 'HTTP' },
            { value: 'https', label: 'HTTPS' },
            { value: 'tcp', label: 'TCP' },
            { value: 'ssh', label: 'SSH' },
            { value: 'rdp', label: 'RDP' },
          ]} value={newEndpoint.protocol}
            onChange={(e) => setNewEndpoint({ ...newEndpoint, protocol: e.target.value })} />
          <Input label="Internal Port" type="number" min={1} max={65535} value={newEndpoint.internal_port}
            onChange={(e) => setNewEndpoint({ ...newEndpoint, internal_port: +e.target.value })} />
          <Input label="Subdomain" value={newEndpoint.subdomain} placeholder="my-app"
            onChange={(e) => setNewEndpoint({ ...newEndpoint, subdomain: e.target.value.toLowerCase() })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowAddEndpoint(false)}>Cancel</Button>
            <Button onClick={createEndpoint}>Create</Button>
          </div>
        </div>
      </Modal>

      {/* New Snapshot Modal */}
      <Modal open={showNewSnapshot} onClose={() => setShowNewSnapshot(false)} title="Take Snapshot">
        <div className="space-y-4">
          <Input label="Snapshot Name" value={snapshotForm.name} placeholder="pre-upgrade"
            onChange={(e) => setSnapshotForm({ ...snapshotForm, name: e.target.value })} />
          <Input label="Description (optional)" value={snapshotForm.description}
            onChange={(e) => setSnapshotForm({ ...snapshotForm, description: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowNewSnapshot(false)}>Cancel</Button>
            <Button onClick={createSnapshot}>Create Snapshot</Button>
          </div>
        </div>
      </Modal>

      {/* Destroy Confirm */}
      <ConfirmDialog
        open={showDestroy}
        onCancel={() => setShowDestroy(false)}
        onConfirm={handleDestroy}
        title="Destroy Instance"
        message={`Are you sure you want to permanently destroy "${inst.display_name}"? This action cannot be undone.`}
        variant="danger"
        confirmLabel="Destroy"
      />

      {/* Backup Modal */}
      <Modal open={showBackupModal} onClose={() => setShowBackupModal(false)} title="Create Backup">
        <div className="space-y-3">
          <Input label="Storage" value={backupForm.storage}
            onChange={(e) => setBackupForm((p) => ({ ...p, storage: e.target.value }))} />
          <Select label="Mode" value={backupForm.mode}
            onChange={(e) => setBackupForm((p) => ({ ...p, mode: e.target.value }))}
            options={[{ value: 'snapshot', label: 'Snapshot' }, { value: 'suspend', label: 'Suspend' }, { value: 'stop', label: 'Stop' }]} />
          <Select label="Compression" value={backupForm.compress}
            onChange={(e) => setBackupForm((p) => ({ ...p, compress: e.target.value }))}
            options={[{ value: 'zstd', label: 'ZSTD' }, { value: 'lzo', label: 'LZO' }, { value: 'gzip', label: 'GZIP' }, { value: 'none', label: 'None' }]} />
          <Input label="Notes" value={backupForm.notes}
            onChange={(e) => setBackupForm((p) => ({ ...p, notes: e.target.value }))} />
          <Button onClick={handleBackup} variant="primary" className="w-full">Create Backup</Button>
        </div>
      </Modal>

      {/* Network Change Modal */}
      <Modal open={showNetModal} onClose={() => setShowNetModal(false)} title="Change VPC Network">
        <div className="space-y-3">
          <Select label="Interface" value={netForm.net_id}
            onChange={(e) => setNetForm((p) => ({ ...p, net_id: e.target.value }))}
            options={Object.keys(netInterfaces).length > 0
              ? Object.keys(netInterfaces).map((k) => ({ value: k, label: k }))
              : [{ value: 'net0', label: 'net0' }]} />
          {vpcs.length > 0 ? (
            <Select label="VPC" value={netForm.vpc_id}
              onChange={(e) => setNetForm((p) => ({ ...p, vpc_id: e.target.value }))}
              options={[
                { value: '', label: '- Select a VPC -' },
                ...vpcs.map((v) => ({
                  value: v.id,
                  label: `${v.name} (${v.cidr || ''}) ${v.vnet ? `- vnet: ${v.vnet}` : ''}`,
                })),
              ]} />
          ) : (
            <p className="text-sm text-paws-text-dim">No VPCs available. Create a VPC first.</p>
          )}
          <p className="text-xs text-paws-text-dim">Note: VM should be stopped before changing network.</p>
          <Button onClick={handleNetworkUpdate} variant="primary" className="w-full" disabled={!netForm.vpc_id}>
            Update Network
          </Button>
        </div>
      </Modal>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-paws-text-dim">{label}</p>
      <p className="text-sm font-medium text-paws-text">{value}</p>
    </div>
  );
}

function fmtBytes(bytes: number): string {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[Math.min(i, 4)]}`;
}

function MetricsChart({
  title, data, dataKey, color, unit, secondaryKey, secondaryColor, formatter, legendLabels,
}: {
  title: string;
  data: MetricPoint[];
  dataKey: string;
  color: string;
  unit: string;
  secondaryKey?: string;
  secondaryColor?: string;
  formatter?: (v: number) => string;
  legendLabels?: [string, string];
}) {
  const fmt = formatter || ((v: number) => `${v}${unit}`);
  const chartData = data
    .filter((d) => d.time)
    .map((d) => {
      const rec = d as unknown as Record<string, unknown>;
      return {
        time: new Date((d.time) * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        [dataKey]: rec[dataKey] ?? 0,
        ...(secondaryKey ? { [secondaryKey]: rec[secondaryKey] ?? 0 } : {}),
      };
    });

  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">{title}</CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis dataKey="time" stroke="#888" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis stroke="#888" tick={{ fontSize: 10 }} tickFormatter={fmt} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #444', borderRadius: '8px' }}
              labelStyle={{ color: '#ccc' }}
              formatter={(value: unknown, name?: string) => [fmt(Number(value || 0)), legendLabels ? ((name === dataKey) ? legendLabels[0] : legendLabels[1]) : (name || '')]}
            />
            <Area type="monotone" dataKey={dataKey} stroke={color} fill={color} fillOpacity={0.15} strokeWidth={2}
              name={legendLabels ? legendLabels[0] : dataKey} />
            {secondaryKey && (
              <Area type="monotone" dataKey={secondaryKey} stroke={secondaryColor || '#888'} fill={secondaryColor || '#888'}
                fillOpacity={0.1} strokeWidth={2} name={legendLabels ? legendLabels[1] : secondaryKey} />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
