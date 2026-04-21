import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import {
  ArrowLeft, Monitor, Terminal, Maximize, Minimize, Cloud, RotateCcw,
  Play, Square, Power, Trash2, Clock, Shield, Globe, FileText,
  Plus, X, Camera, HardDrive, Network, MousePointer,
} from 'lucide-react';
import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Area, AreaChart,
} from 'recharts';
import api from '../api/client';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Input, Modal, Badge, StatusBadge, Tabs, Select, ConfirmDialog,
  useToast,
} from '@/components/ui';
import { LifecycleCountdown } from '@/components/ui/LifecycleCountdown';
import MarkdownEditor from '@/components/ui/MarkdownEditor';
import { useAuth } from '@/context/AuthContext';

interface Instance {
  id: string;
  display_name: string;
  resource_type: string;
  status: string;
  live_status?: string;
  proxmox_vmid: number;
  proxmox_node: string;
  cluster_id?: string;
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
interface BackupItem {
  volid: string; size: number; ctime: number; format: string; storage: string; notes?: string;
  pbs?: boolean; backup_type?: string; backup_id?: string; backup_time?: number;
}
interface NetInterface { [key: string]: string; }

export default function InstanceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();
  const { user: authUser } = useAuth();

  // Permission from group sharing (undefined = owner/full access)
  const groupPermission: string | undefined = (location.state as any)?.groupPermission;
  const isReadOnly = groupPermission === 'read';
  const canOperate = !groupPermission || groupPermission === 'operate' || groupPermission === 'admin';
  const canAdmin = !groupPermission || groupPermission === 'admin';
  const auditing = !!authUser?.impersonated_by;
  const lp = authUser?.lifecycle_policy;

  const [inst, setInst] = useState<Instance | null>(null);
  const [tab, setTab] = useState('overview');
  const [loading, setLoading] = useState(true);
  const [showResize, setShowResize] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const [showDestroy, setShowDestroy] = useState(false);
  const [resizeForm, setResizeForm] = useState({ cores: 1, memory_mb: 512, disk_gb: 10 });
  const [configForm, setConfigForm] = useState({
    username: '', password: '', ssh_key_ids: [] as string[], dns_domain: '',
    dns_server: '', hostname: '',
  });
  const [configLoading, setConfigLoading] = useState(false);
  const [configPasswordSet, setConfigPasswordSet] = useState(false);
  const [configIpAddress, setConfigIpAddress] = useState<string | null>(null);
  const [configAllocatedIp, setConfigAllocatedIp] = useState<string | null>(null);
  const [userSshKeys, setUserSshKeys] = useState<Array<{ id: string; name: string }>>([]);

  // Networking
  const [attachedSGs, setAttachedSGs] = useState<SGRef[]>([]);
  const [allSGs, setAllSGs] = useState<SGRef[]>([]);
  const [endpoints, setEndpoints] = useState<EndpointRef[]>([]);
  const [firewallRules, setFirewallRules] = useState<FirewallRule[]>([]);
  const [showAddEndpoint, setShowAddEndpoint] = useState(false);
  const [newEndpoint, setNewEndpoint] = useState({ name: '', protocol: 'http', internal_port: 80, subdomain: '' });
  const [showAddSG, setShowAddSG] = useState(false);
  const [networkMode, setNetworkMode] = useState<{ network_mode: string; bandwidth_limit_mbps: number | null; effective_bandwidth_mbps: number } | null>(null);

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
  const termWsRef = useRef<WebSocket | null>(null);
  const termFitRef = useRef<InstanceType<typeof import('xterm-addon-fit').FitAddon> | null>(null);

  // Metrics, Tasks, Backups, Network
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [metricsTimeframe, setMetricsTimeframe] = useState('hour');
  const [taskHistory, setTaskHistory] = useState<TaskItem[]>([]);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [netInterfaces, setNetInterfaces] = useState<NetInterface>({});
  const [vpcs, setVpcs] = useState<Array<{ id: string; name: string; vnet?: string; vxlan_tag?: number; cidr?: string; network_mode?: string }>>([]);
  const [showBackupModal, setShowBackupModal] = useState(false);
  const [backupForm, setBackupForm] = useState({ storage: '', mode: 'snapshot', compress: 'zstd', notes: '' });
  const [backupStorages, setBackupStorages] = useState<Array<{ storage: string }>>([]);
  const [backupDeleting, setBackupDeleting] = useState<string | null>(null);
  const [backupRestoring, setBackupRestoring] = useState<string | null>(null);
  const [browsingBackup, setBrowsingBackup] = useState<BackupItem | null>(null);
  const [backupFiles, setBackupFiles] = useState<any[]>([]);
  const [backupFilePath, setBackupFilePath] = useState('');
  const [backupFileLoading, setBackupFileLoading] = useState(false);
  const [showNetModal, setShowNetModal] = useState(false);
  const [netForm, setNetForm] = useState({ net_id: 'net0', vpc_id: '' });
  const [selectedNic, setSelectedNic] = useState<string | null>(null);
  const [ipAddresses, setIpAddresses] = useState<Record<string, string[]>>({});
  const [showAddNic, setShowAddNic] = useState(false);
  const [addNicVpc, setAddNicVpc] = useState('');
  const [networkLoading, setNetworkLoading] = useState(false);

  // Notes
  const [notes, setNotes] = useState('');
  const [notesDraft, setNotesDraft] = useState('');
  const [notesEditing, setNotesEditing] = useState(false);
  const [notesSaving, setNotesSaving] = useState(false);

  // Generic confirm dialog state
  const [confirmDialog, setConfirmDialog] = useState<{
    title: string; message: string; confirmLabel?: string;
    variant?: 'danger' | 'primary'; onConfirm: () => void;
  } | null>(null);

  // Volumes (additional disks)
  const [volumes, setVolumes] = useState<Array<{
    id: string; name: string; size_gib: number; storage_pool: string;
    status: string; disk_slot: string | null; proxmox_volid: string | null;
  }>>([]);

  // High Availability
  const [haStatus, setHaStatus] = useState<{ enabled: boolean; state?: string; group?: string; sid?: string } | null>(null);
  const [haGroups, setHaGroups] = useState<Array<{ id: string; name: string; description?: string; nodes: string[] }>>([]);
  const [haGroupId, setHaGroupId] = useState('');
  const [haLoading, setHaLoading] = useState(false);

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
    api.get('/api/compute/backup-storages').then((r) => {
      const storages = r.data || [];
      setBackupStorages(storages);
      if (storages.length > 0) setBackupForm((p) => ({ ...p, storage: storages[0].storage }));
    }).catch(() => {});
    api.get(`/api/compute/vms/${id}/network`).then((r) => {
      setNetInterfaces(r.data?.interfaces || {});
      setVpcs(r.data?.vpcs || []);
      setIpAddresses(r.data?.ip_addresses || {});
    }).catch(() => {});
    api.get(`/api/volumes/?resource_id=${id}`).then((r) => setVolumes(r.data || [])).catch(() => {});
    api.get(`/api/compute/instances/${id}/ha`).then((r) => setHaStatus(r.data)).catch(() => setHaStatus(null));
    api.get('/api/ha/groups').then((r) => setHaGroups(r.data || [])).catch(() => {});
    api.get(`/api/resources/${id}/notes`).then((r) => { setNotes(r.data?.notes || ''); setNotesDraft(r.data?.notes || ''); }).catch(() => {});
  };

  // Targeted refresh helpers to avoid re-fetching everything
  const refreshInstance = () => {
    if (!id) return;
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
    }).catch(() => {});
  };
  const refreshSGs = () => {
    if (!id) return;
    api.get(`/api/security-groups/?resource_id=${id}`).then((r) => setAttachedSGs(r.data || [])).catch(() => {});
    api.get('/api/security-groups/').then((r) => setAllSGs(r.data || [])).catch(() => {});
  };
  const refreshEndpoints = () => {
    if (!id) return;
    api.get(`/api/endpoints?resource_id=${id}`).then((r) => setEndpoints(r.data || [])).catch(() => {});
  };
  const refreshSnapshots = () => {
    if (!id) return;
    api.get(`/api/compute/vms/${id}/snapshots`).then((r) => setSnapshots(r.data || [])).catch(() => {});
  };
  const refreshTasks = () => {
    if (!id) return;
    api.get(`/api/compute/vms/${id}/tasks`).then((r) => setTaskHistory(r.data?.tasks || [])).catch(() => {});
  };
  const refreshBackups = () => {
    if (!id) return;
    api.get(`/api/compute/vms/${id}/backups`).then((r) => setBackups(r.data?.backups || [])).catch(() => {});
    api.get('/api/compute/backup-storages').then((r) => {
      const storages = r.data || [];
      setBackupStorages(storages);
      if (storages.length > 0) setBackupForm((p) => ({ ...p, storage: p.storage || storages[0].storage }));
    }).catch(() => {});
  };
  const refreshNetwork = () => {
    if (!id) return;
    api.get(`/api/compute/vms/${id}/network`).then((r) => {
      setNetInterfaces(r.data?.interfaces || {});
      setVpcs(r.data?.vpcs || []);
      setIpAddresses(r.data?.ip_addresses || {});
    }).catch(() => {});
  };

  const refreshVolumes = () => {
    if (!id) return;
    api.get(`/api/volumes/?resource_id=${id}`).then((r) => setVolumes(r.data || [])).catch(() => {});
  };

  const fetchFirewall = () => {
    if (!inst) return;
    api.get(`/api/networking/vms/${inst.proxmox_node}/${inst.proxmox_vmid}/firewall`)
      .then((r) => setFirewallRules(r.data || []))
      .catch(() => {});
  };

  const fetchNetworkMode = () => {
    if (!id) return;
    api.get(`/api/networking/instances/${id}/network-mode`)
      .then((r) => setNetworkMode(r.data))
      .catch(() => {});
  };

  useEffect(fetchData, [id]);
  useEffect(() => { if (inst && tab === 'networking') { fetchFirewall(); fetchNetworkMode(); } }, [inst, tab]);
  useEffect(() => {
    if (!id) return;
    api.get(`/api/compute/vms/${id}/metrics?timeframe=${metricsTimeframe}`)
      .then((r) => setMetrics(r.data?.data || []))
      .catch(() => {});
  }, [metricsTimeframe, id]);

  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const ACTION_SUCCESS: Record<string, string> = {
    start: 'Start signal sent', stop: 'Force stop signal sent',
    shutdown: 'Graceful shutdown signal sent', reboot: 'Reboot signal sent',
    suspend: 'Suspend signal sent', resume: 'Resume signal sent',
    hibernate: 'Hibernate signal sent',
  };

  const doAction = async (action: string, opts?: { force?: boolean }) => {
    if (!id) return;
    setActionLoading(action);
    try {
      await api.post(`/api/compute/vms/${id}/action`, { action, ...opts });
      toast(ACTION_SUCCESS[action] || `${action} signal sent`, 'success');
      setTimeout(() => { refreshInstance(); refreshTasks(); }, 2000);
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      toast(typeof d === 'string' ? d : `${action} failed`, 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const confirmAction = (action: string, label: string, message: string) => {
    setConfirmDialog({
      title: label,
      message,
      confirmLabel: label,
      variant: action === 'stop' ? 'danger' : 'primary',
      onConfirm: () => { setConfirmDialog(null); doAction(action); },
    });
  };

  const handleResize = async () => {
    if (!id) return;
    try {
      await api.patch(`/api/compute/vms/${id}/resize`, resizeForm);
      setShowResize(false);
      refreshInstance();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Resize failed', 'error');
    }
  };

  const loadConfig = async () => {
    if (!id) return;
    setConfigLoading(true);
    try {
      const [configRes, keysRes] = await Promise.all([
        api.get(`/api/compute/vms/${id}/config`),
        api.get('/api/ssh-keys/'),
      ]);
      const d = configRes.data;
      setUserSshKeys(keysRes.data.map((k: any) => ({ id: k.id, name: k.name })));
      setConfigForm({
        username: d.username || '',
        password: '',
        ssh_key_ids: d.ssh_key_ids || [],
        dns_domain: d.dns_domain || '',
        dns_server: d.dns_server || '',
        hostname: d.hostname || '',
      });
      setConfigPasswordSet(d.password_set || false);
      setConfigIpAddress(d.ip_address || null);
      setConfigAllocatedIp(d.allocated_ip || null);
    } catch {
      toast('Failed to load instance config', 'error');
    } finally {
      setConfigLoading(false);
    }
  };

  const handleSaveConfig = async () => {
    if (!id) return;
    try {
      const payload: Record<string, unknown> = {};
      if (configForm.username) payload.username = configForm.username;
      if (configForm.password) payload.password = configForm.password;
      payload.ssh_key_ids = configForm.ssh_key_ids;
      if (configForm.dns_domain) payload.dns_domain = configForm.dns_domain;
      if (configForm.dns_server) payload.dns_server = configForm.dns_server;
      if (configForm.hostname) payload.hostname = configForm.hostname;
      await api.put(`/api/compute/vms/${id}/config`, payload);
      setShowConfig(false);
      toast('Configuration updated', 'success');
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to save config', 'error');
    }
  };

  const handleDestroy = async () => {
    if (!id) return;
    try {
      await api.delete(`/api/compute/vms/${id}`);
      navigate('/vms');
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      toast(typeof d === 'string' ? d : 'Failed to destroy instance', 'error');
    }
  };

  // HA actions
  const enableHA = async () => {
    if (!id) return;
    setHaLoading(true);
    try {
      await api.post(`/api/compute/instances/${id}/ha`, { ha_group_id: haGroupId || null });
      toast('HA enabled', 'success');
      api.get(`/api/compute/instances/${id}/ha`).then((r) => setHaStatus(r.data)).catch(() => {});
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      toast(typeof d === 'string' ? d : 'Failed to enable HA', 'error');
    }
    setHaLoading(false);
  };

  const disableHA = async () => {
    if (!id) return;
    setHaLoading(true);
    try {
      await api.delete(`/api/compute/instances/${id}/ha`);
      toast('HA disabled', 'success');
      setHaStatus({ enabled: false });
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      toast(typeof d === 'string' ? d : 'Failed to disable HA', 'error');
    }
    setHaLoading(false);
  };

  // Security Group actions
  const attachSG = async (sgId: string) => {
    await api.post(`/api/security-groups/${sgId}/attach`, { resource_id: id });
    setShowAddSG(false);
    refreshSGs();
  };

  const detachSG = async (sgId: string) => {
    await api.post(`/api/security-groups/${sgId}/detach`, { resource_id: id });
    refreshSGs();
  };

  // Endpoint actions
  const createEndpoint = async () => {
    if (!id) return;
    try {
      await api.post('/api/endpoints', { ...newEndpoint, resource_id: id });
      setShowAddEndpoint(false);
      setNewEndpoint({ name: '', protocol: 'http', internal_port: 80, subdomain: '' });
      refreshEndpoints();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to create endpoint', 'error');
    }
  };

  const deleteEndpoint = async (epId: string) => {
    await api.delete(`/api/endpoints/${epId}`);
    refreshEndpoints();
  };

  const toggleEndpoint = async (ep: EndpointRef) => {
    await api.patch(`/api/endpoints/${ep.id}`, { is_active: !ep.is_active });
    refreshEndpoints();
  };

  // Snapshot actions
  const createSnapshot = async () => {
    if (!id) return;
    try {
      await api.post(`/api/compute/vms/${id}/snapshots`, snapshotForm);
      setShowNewSnapshot(false);
      setSnapshotForm({ name: '', description: '' });
      refreshSnapshots();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Snapshot failed', 'error');
    }
  };

  const rollbackSnapshot = (snapname: string) => {
    if (!id) return;
    setConfirmDialog({
      title: 'Rollback Snapshot',
      message: `Rollback to snapshot "${snapname}"? Current state will be lost.`,
      confirmLabel: 'Rollback',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null);
        try {
          await api.post(`/api/compute/vms/${id}/snapshots/${encodeURIComponent(snapname)}/rollback`);
          toast('Snapshot rollback started.', 'info');
          refreshSnapshots();
          refreshInstance();
        } catch (e: any) {
          toast(e?.response?.data?.detail || 'Rollback failed', 'error');
        }
      },
    });
  };

  const deleteSnapshot = (snapname: string) => {
    if (!id) return;
    setConfirmDialog({
      title: 'Delete Snapshot',
      message: `Delete snapshot "${snapname}"? This cannot be undone.`,
      confirmLabel: 'Delete',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null);
        try {
          await api.delete(`/api/compute/vms/${id}/snapshots/${encodeURIComponent(snapname)}`);
          toast('Snapshot deleted.', 'success');
          refreshSnapshots();
        } catch (e: any) {
          toast(e?.response?.data?.detail || 'Delete failed', 'error');
        }
      },
    });
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
      setBackupForm((p) => ({ ...p, mode: 'snapshot', compress: 'zstd', notes: '' }));
      toast('Backup job started. It may take a few minutes to complete.', 'info', 10000);
      refreshBackups();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Backup failed', 'error');
    }
  };

  const handleDeleteBackup = (b: BackupItem) => {
    if (!id) return;
    setConfirmDialog({
      title: 'Delete Backup',
      message: 'Delete this backup? This cannot be undone.',
      confirmLabel: 'Delete',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null);
        setBackupDeleting(b.volid);
        try {
          await api.delete(`/api/compute/vms/${id}/backups`, {
            data: {
              volid: b.volid, storage: b.storage, pbs: !!b.pbs,
              backup_type: b.backup_type || 'vm',
              backup_id: b.backup_id || '', backup_time: b.backup_time || 0,
            },
          });
          toast('Backup deleted.', 'success');
          refreshBackups();
        } catch (e: any) {
          toast(e?.response?.data?.detail || 'Delete failed', 'error');
        } finally {
          setBackupDeleting(null);
        }
      },
    });
  };

  const handleRestoreBackup = (b: BackupItem) => {
    if (!id) return;
    setConfirmDialog({
      title: 'Restore Backup',
      message: 'Restore this backup? This will overwrite the current state of the instance.',
      confirmLabel: 'Restore',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null);
        setBackupRestoring(b.volid);
        try {
          await api.post(`/api/compute/vms/${id}/backups/restore`, {
            volid: b.volid, storage: b.storage, pbs: !!b.pbs,
          });
          toast('Restore started. This may take a few minutes.', 'info', 10000);
          refreshBackups();
          refreshInstance();
        } catch (e: any) {
          toast(e?.response?.data?.detail || 'Restore failed', 'error');
        } finally {
          setBackupRestoring(null);
        }
      },
    });
  };

  const handleBrowseBackup = async (b: BackupItem) => {
    if (!id) return;
    setBrowsingBackup(b);
    setBackupFilePath('');
    setBackupFileLoading(true);
    try {
      const r = await api.post(`/api/compute/vms/${id}/backups/files`, {
        volid: b.volid, storage: b.storage, filepath: '',
      });
      setBackupFiles(r.data?.files || []);
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to browse backup', 'error');
      setBrowsingBackup(null);
    } finally {
      setBackupFileLoading(false);
    }
  };

  const handleBrowsePath = async (filepath: string) => {
    if (!id || !browsingBackup) return;
    setBackupFilePath(filepath);
    setBackupFileLoading(true);
    try {
      const r = await api.post(`/api/compute/vms/${id}/backups/files`, {
        volid: browsingBackup.volid, storage: browsingBackup.storage, filepath,
      });
      setBackupFiles(r.data?.files || []);
    } catch {
      setBackupFiles([]);
    } finally {
      setBackupFileLoading(false);
    }
  };

  const handleDownloadFile = (filepath: string) => {
    if (!id || !browsingBackup) return;
    // Block downloading entire archive roots (e.g. root.pxar.didx) - too large
    if (!filepath || filepath.endsWith('.didx') || filepath.endsWith('.fidx')) {
      toast('Cannot download the entire archive. Browse into it and download individual files or folders.', 'warning', 6000);
      return;
    }
    const baseName = filepath.split('/').pop() || 'download';
    toast(`Preparing download: ${baseName}...`, 'info', 8000);
    const backup = browsingBackup;
    api.post(`/api/compute/vms/${id}/backups/download`, {
      volid: backup.volid, storage: backup.storage, filepath,
    }, { responseType: 'blob' }).then((r) => {
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement('a');
      a.href = url;
      const contentType = r.headers?.['content-type'] || '';
      const isZip = contentType.includes('zip') || (!baseName.includes('.') && r.data.size > 0);
      a.download = isZip && !baseName.endsWith('.zip') ? `${baseName}.zip` : baseName;
      a.click();
      window.URL.revokeObjectURL(url);
      toast(`Download ready: ${a.download}`, 'success');
    }).catch((e: any) => {
      toast(e?.response?.data?.detail || 'Download failed', 'error');
    });
  };

  const handleNetworkUpdate = async () => {
    if (!id) return;
    setNetworkLoading(true);
    try {
      const res = await api.put(`/api/compute/vms/${id}/network`, netForm);
      setShowNetModal(false);
      refreshNetwork();
      const msg = res.data?.message || 'Network updated';
      toast(msg, res.data?.restarted ? 'warning' : 'success');
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Network update failed', 'error');
    } finally {
      setNetworkLoading(false);
    }
  };

  // VNC key sender helpers
  const vncSendKey = (keysym: number, code: string) => rfbRef.current?.sendKey(keysym, code);
  const vncSendCtrlAltDel = () => rfbRef.current?.sendCtrlAltDel();
  const vncToggleLocalCursor = () => {
    if (rfbRef.current) {
      const next = !vncShowLocalCursor;
      rfbRef.current.showDotCursor = next;
      setVncShowLocalCursor(next);
    }
  };

  const consoleToggleFullscreen = () => {
    const el = vncWrapperRef.current;
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen().then(() => setVncFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setVncFullscreen(false)).catch(() => {});
    }
  };
  const vncToggleFullscreen = consoleToggleFullscreen;

  const consoleReconnect = () => {
    setConsoleActive(false);
    setTimeout(() => openConsole(consoleType), 100);
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
          cleanup = () => { rfbRef.current = null; try { rfb.disconnect(); } catch { /* disconnect may throw if already closed */ } };
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
      ]).then(([{ Terminal: XTerminal }, { FitAddon }]) => {
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
        termFitRef.current = fitAddon;

        const ws = new WebSocket(wsUrl);
        ws.binaryType = 'arraybuffer';
        termWsRef.current = ws;

        // PVE vncwebsocket sends raw terminal bytes (binary frames).
        // Input uses termproxy framing: data "0:LEN:MSG", resize "1:COLS:ROWS:", ping "2"
        ws.onmessage = (event) => {
          if (event.data instanceof ArrayBuffer) {
            term.write(new Uint8Array(event.data));
          } else {
            term.write(event.data);
          }
        };

        term.onData((data: string) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('0:' + data.length + ':' + data);
          }
        });

        term.onResize(({ cols, rows }: { cols: number; rows: number }) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('1:' + cols + ':' + rows + ':');
          }
        });

        // Send initial resize after connection opens
        ws.onopen = () => {
          const dims = fitAddon.proposeDimensions();
          if (dims) ws.send('1:' + dims.cols + ':' + dims.rows + ':');
        };

        // Ping every 30s to keep connection alive
        const pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('2');
        }, 30000);

        cleanup = () => {
          clearInterval(pingInterval);
          termWsRef.current = null;
          termFitRef.current = null;
          try { ws.close(); term.dispose(); } catch { /* cleanup may throw if already disposed */ }
        };
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
    { id: 'storage', label: 'Storage', count: volumes.length },
    { id: 'networking', label: 'Networking' },
    { id: 'snapshots', label: 'Snapshots', count: snapshots.filter((s) => s.name !== 'current').length },
    { id: 'backups', label: 'Backups', count: backups.length },
    { id: 'tasks', label: 'Tasks', count: taskHistory.length },
    { id: 'console', label: 'Console' },
    { id: 'lifecycle', label: 'Lifecycle' },
    { id: 'notes', label: 'Notes' },
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
            {lp && (
              <LifecycleCountdown
                lastAccessedAt={(inst as any).last_accessed_at ?? null}
                shutdownDays={lp.idle_shutdown_days}
                destroyDays={lp.idle_destroy_days}
                status={vmStatus}
                onKeepAlive={!auditing ? () => {
                  const type = inst.resource_type === 'lxc' ? 'containers' : 'vms';
                  api.post(`/api/compute/${type}/${id}/keepalive`).then(() => {
                    toast('Idle timer reset', 'success');
                    fetchData();
                  }).catch(() => toast('Failed to reset timer', 'error'));
                } : undefined}
                readOnly={auditing}
              />
            )}
          </div>
          <p className="text-sm text-paws-text-muted mt-0.5">
            VMID {inst.proxmox_vmid} · {inst.proxmox_node} · {String(specs.cores || 1)} vCPU · {String(specs.memory_mb || 512)} MB
          </p>
        </div>
        <div className="flex gap-1.5">
          {isReadOnly && <Badge variant="info">Read Only</Badge>}
          {canOperate && (
            <>
              <Button variant="outline" size="sm" onClick={() => doAction('start')}
                disabled={vmStatus === 'running' || actionLoading !== null} title="Start">
                <Play className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="sm" onClick={() => doAction('shutdown')}
                disabled={vmStatus === 'stopped' || actionLoading !== null} title="Graceful Shutdown">
                <Square className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="sm"
                onClick={() => confirmAction('stop', 'Force Stop', `Force stop "${inst.display_name}"? This is equivalent to pulling the power cord and may cause data loss.`)}
                disabled={vmStatus === 'stopped' || actionLoading !== null} title="Force Stop">
                <Power className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="sm" onClick={() => doAction('reboot')}
                disabled={vmStatus === 'stopped' || actionLoading !== null} title="Reboot">
                <RotateCcw className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
          {canAdmin && (
            <>
              <Button variant="outline" size="sm" onClick={() => setShowResize(true)} title="Resize">
                <Maximize className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="sm" onClick={() => { setShowConfig(true); loadConfig(); }} title="Instance Config">
                <Cloud className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
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
                {inst.cluster_id && inst.cluster_id !== 'default' && (
                  <Stat label="Cluster" value={inst.cluster_id} />
                )}
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
              <MetricsChart title="CPU Usage" data={metrics} dataKey="cpu" color="#e5a00d" unit="%" formatter={(v: number) => `${(v * 100).toFixed(1)}%`} timeframe={metricsTimeframe} />
              <MetricsChart title="Memory Usage" data={metrics} dataKey="mem" color="#3b82f6" unit=" bytes" secondaryKey="maxmem" secondaryColor="#1e40af" formatter={fmtBytes} timeframe={metricsTimeframe} />
              <MetricsChart title="Network Traffic" data={metrics} dataKey="netin" color="#10b981" unit="" secondaryKey="netout" secondaryColor="#f97316" formatter={fmtBytes} legendLabels={['In', 'Out']} timeframe={metricsTimeframe} />
              <MetricsChart title="Disk IO" data={metrics} dataKey="diskread" color="#8b5cf6" unit="" secondaryKey="diskwrite" secondaryColor="#ec4899" formatter={fmtBytes} legendLabels={['Read', 'Write']} timeframe={metricsTimeframe} />
            </div>
          )}
        </div>
      )}

      {/* Storage (Additional Disks) */}
      {tab === 'storage' && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between w-full">
              <CardTitle>Additional Disks</CardTitle>
              <Button variant="outline" size="sm" onClick={() => navigate('/volumes')}>
                <Plus className="h-3.5 w-3.5 mr-1" /> Manage Volumes
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {volumes.length === 0 ? (
              <p className="text-sm text-paws-text-dim">
                No additional disks attached. Go to{' '}
                <button className="text-paws-accent hover:underline" onClick={() => navigate('/volumes')}>
                  Volumes
                </button>{' '}
                to create and attach storage.
              </p>
            ) : (
              <div className="space-y-2">
                {volumes.map((vol) => (
                  <div key={vol.id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                    <div className="flex items-center gap-3">
                      <HardDrive className="h-4 w-4 text-paws-text-dim" />
                      <div>
                        <p className="text-sm font-medium text-paws-text">{vol.name}</p>
                        <p className="text-xs text-paws-text-dim font-mono">
                          {vol.proxmox_volid || vol.storage_pool}
                          {vol.disk_slot ? ` \u2022 ${vol.disk_slot}` : ''}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-paws-text">{vol.size_gib} GiB</span>
                      <StatusBadge status={vol.status} />
                      <Button variant="outline" size="sm" onClick={() => {
                        setConfirmDialog({
                          title: 'Detach Volume',
                          message: `Detach "${vol.name}" from this instance? The disk data will be preserved and can be re-attached later.`,
                          confirmLabel: 'Detach',
                          variant: 'primary',
                          onConfirm: () => {
                            api.post(`/api/volumes/${vol.id}/detach`)
                              .then(() => { toast('Volume detached.', 'success'); refreshVolumes(); })
                              .catch((e: any) => {
                                const d = e?.response?.data?.detail;
                                toast(typeof d === 'string' ? d : 'Failed to detach', 'error');
                              });
                          },
                        });
                      }}>
                        Detach
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Networking */}
      {tab === 'networking' && (
        <div className="space-y-4">
          {/* Network Mode (inherited from network) */}
          <Card>
            <CardHeader><CardTitle>Network Mode</CardTitle></CardHeader>
            <CardContent>
              {networkMode ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-3">
                    <Badge variant={networkMode.network_mode === 'published' ? 'warning' : networkMode.network_mode === 'isolated' ? 'danger' : 'success'} className="text-sm px-3 py-1">
                      {networkMode.network_mode.charAt(0).toUpperCase() + networkMode.network_mode.slice(1)}
                    </Badge>
                    <span className="text-xs text-paws-text-dim">
                      {networkMode.network_mode === 'private' && 'Full LAN + Internet access'}
                      {networkMode.network_mode === 'published' && 'Internet only, LAN blocked'}
                      {networkMode.network_mode === 'isolated' && 'Own subnet only'}
                    </span>
                  </div>
                  <p className="text-xs text-paws-text-dim">
                    Network mode is set per-network.
                    {(networkMode as any).vpc_name && <> Inherited from <span className="text-paws-text font-medium">{(networkMode as any).vpc_name}</span>.</>}
                    {' '}Change it in the <a href="/networks" className="text-paws-primary hover:underline">Networks</a> page.
                  </p>
                  <div className="flex items-center gap-4 text-xs text-paws-text-dim">
                    <span>Bandwidth: <span className="text-paws-text font-mono">{networkMode.effective_bandwidth_mbps} MB/s</span></span>
                    {networkMode.bandwidth_limit_mbps !== null && (
                      <span className="text-paws-warning">(Override: {networkMode.bandwidth_limit_mbps} MB/s)</span>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-paws-text-dim">No network assigned - network mode not available.</p>
              )}
            </CardContent>
          </Card>

          {/* Network Interfaces */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between w-full">
                <CardTitle>Network Interfaces</CardTitle>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={
                    !networkMode ||
                    networkMode.network_mode === 'isolated' ||
                    (networkMode.network_mode === 'published' && Object.keys(netInterfaces).length >= 1)
                  }
                  title={
                    !networkMode ? 'No network assigned' :
                    networkMode.network_mode === 'isolated' ? 'Cannot add NIC on isolated network' :
                    networkMode.network_mode === 'published' && Object.keys(netInterfaces).length >= 1 ? 'Published networks allow only 1 NIC' :
                    'Add network interface'
                  }
                  onClick={() => { setAddNicVpc(''); setShowAddNic(true); }}
                >
                  <Plus className="h-3.5 w-3.5 mr-1" /> Add NIC
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {Object.entries(netInterfaces).length === 0 ? (
                <p className="text-sm text-paws-text-dim">No interfaces configured.</p>
              ) : (
                <div className="space-y-3">
                  {Object.entries(netInterfaces).map(([k, v]) => {
                    const parts = String(v).split(',');
                    const bridge = parts.find((p) => p.startsWith('bridge='))?.split('=')[1] || '';
                    const macPart = parts.find((p) => /^([0-9A-Fa-f]{2}:){5}/.test(p) || p.startsWith('hwaddr='));
                    const mac = macPart ? macPart.replace('hwaddr=', '') : '';
                    const matchingIface = Object.entries(ipAddresses).find(([, ips]) => ips.length > 0);
                    const ifaceIps = k === 'net0' && matchingIface ? matchingIface[1] : (ipAddresses[`eth${k.replace('net', '')}`] || []);
                    const matchedVpc = vpcs.find((vpc) => vpc.vnet === bridge);
                    return (
                      <button
                        key={k}
                        type="button"
                        className="w-full text-left rounded-lg border border-paws-border-subtle p-3 hover:border-paws-primary/50 hover:bg-paws-primary/5 transition-colors cursor-pointer"
                        onClick={() => { setSelectedNic(k); setNetForm({ net_id: k, vpc_id: '' }); setShowNetModal(true); }}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-paws-accent">{k}</span>
                            {matchedVpc && (
                              <span className="text-xs text-paws-text-dim">({matchedVpc.name})</span>
                            )}
                          </div>
                          <span className="text-xs text-paws-text-dim font-mono">{bridge}</span>
                        </div>
                        {mac && <p className="text-xs text-paws-text-dim font-mono">{mac}</p>}
                        {ifaceIps.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {ifaceIps.map((ip) => (
                              <span key={ip} className="inline-block rounded bg-paws-primary/10 px-1.5 py-0.5 text-xs font-mono text-paws-primary">
                                {ip}
                              </span>
                            ))}
                          </div>
                        )}
                      </button>
                    );
                  })}
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
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-paws-text-dim">
                        {snap.snaptime ? new Date(snap.snaptime * 1000).toLocaleString() : ''}
                      </span>
                      <Button variant="outline" size="sm" onClick={() => rollbackSnapshot(snap.name)}>
                        <RotateCcw className="h-3 w-3 mr-1" /> Rollback
                      </Button>
                      <Button variant="danger" size="sm" onClick={() => deleteSnapshot(snap.name)}>
                        <Trash2 className="h-3 w-3 mr-1" /> Delete
                      </Button>
                    </div>
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
                <table className="w-full text-sm table-fixed">
                  <thead>
                    <tr className="text-paws-text-dim border-b border-paws-border-subtle">
                      <th className="text-left py-2 pr-4 w-2/5">Notes</th>
                      <th className="text-left py-2 pr-4">Date</th>
                      <th className="text-left py-2 pr-4">Size</th>
                      <th className="text-left py-2 pr-4">Storage</th>
                      <th className="text-right py-2 w-56">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backups.map((b, i) => {
                      const displayNotes = (b.notes || '').replace(/\[paws:[^\]]+\]\s*/g, '');
                      return (
                      <tr key={i} className="border-b border-paws-border-subtle last:border-0">
                        <td className="py-2 pr-4 text-paws-text text-xs truncate">{displayNotes || <span className="text-paws-text-dim font-mono text-xs">{b.volid}</span>}</td>
                        <td className="py-2 pr-4 text-paws-text whitespace-nowrap">{new Date(b.ctime * 1000).toLocaleString()}</td>
                        <td className="py-2 pr-4 text-paws-text whitespace-nowrap">{fmtBytes(b.size)}</td>
                        <td className="py-2 pr-4 text-paws-text">{b.storage}</td>
                        <td className="py-2 text-right">
                          <div className="flex gap-1 justify-end">
                            <Button variant="outline" size="sm" onClick={() => handleRestoreBackup(b)}
                              disabled={backupRestoring === b.volid}>
                              <RotateCcw className="h-3 w-3 mr-1" /> Restore
                            </Button>
                            <Button variant="outline" size="sm" onClick={() => handleBrowseBackup(b)}>
                              <HardDrive className="h-3 w-3 mr-1" /> Files
                            </Button>
                            <Button variant="danger" size="sm" onClick={() => handleDeleteBackup(b)}
                              disabled={backupDeleting === b.volid}>
                              <Trash2 className="h-3 w-3 mr-1" /> Delete
                            </Button>
                          </div>
                        </td>
                      </tr>
                      );
                    })}
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
                    <Button variant="outline" size="sm" onClick={consoleReconnect} title="Reconnect">
                      <RotateCcw className="h-3.5 w-3.5 mr-1" /> Reconnect
                    </Button>
                  </div>
                )}
                {/* Terminal Toolbar */}
                {consoleType === 'terminal' && (
                  <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                    <Button variant="outline" size="sm" onClick={consoleToggleFullscreen} title="Toggle fullscreen">
                      {vncFullscreen
                        ? <><Minimize className="h-3.5 w-3.5 mr-1" /> Exit Fullscreen</>
                        : <><Maximize className="h-3.5 w-3.5 mr-1" /> Fullscreen</>
                      }
                    </Button>
                    <Button variant="outline" size="sm" onClick={consoleReconnect} title="Reconnect">
                      <RotateCcw className="h-3.5 w-3.5 mr-1" /> Reconnect
                    </Button>
                  </div>
                )}
                {/* Console container */}
                <div
                  ref={consoleRef}
                  className="w-full bg-black overflow-hidden"
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
          {/* Idle Timer Card */}
          {lp && (lp.idle_shutdown_days > 0 || lp.idle_destroy_days > 0) && (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Clock className="h-4 w-4" /> Idle Timer</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {(inst as any).last_accessed_at ? (() => {
                  const lastAccess = new Date((inst as any).last_accessed_at).getTime();
                  const now = Date.now();
                  const shutdownLeft = lp.idle_shutdown_days > 0
                    ? Math.max(0, Math.ceil((lastAccess + lp.idle_shutdown_days * 86400000 - now) / 86400000))
                    : null;
                  const destroyLeft = lp.idle_destroy_days > 0
                    ? Math.max(0, Math.ceil((lastAccess + lp.idle_destroy_days * 86400000 - now) / 86400000))
                    : null;
                  return (
                    <div className="space-y-2">
                      <p className="text-sm text-paws-text-muted">
                        Last accessed: {new Date((inst as any).last_accessed_at).toLocaleString()}
                      </p>
                      <div className="flex items-center gap-4">
                        {shutdownLeft !== null && (
                          <Badge variant={shutdownLeft <= 3 ? 'danger' : shutdownLeft <= 7 ? 'warning' : 'default'}>
                            {shutdownLeft}d until auto-shutdown
                          </Badge>
                        )}
                        {destroyLeft !== null && (
                          <Badge variant={destroyLeft <= 3 ? 'danger' : destroyLeft <= 7 ? 'warning' : 'default'}>
                            {destroyLeft}d until auto-destroy
                          </Badge>
                        )}
                      </div>
                      {!auditing && (
                        <Button variant="outline" size="sm" onClick={() => {
                          const type = inst.resource_type === 'lxc' ? 'containers' : 'vms';
                          api.post(`/api/compute/${type}/${id}/keepalive`).then(() => {
                            toast('Idle timer reset', 'success');
                            fetchData();
                          }).catch(() => toast('Failed to reset timer', 'error'));
                        }}>
                          <RotateCcw className="h-3.5 w-3.5 mr-1" /> Keep Alive
                        </Button>
                      )}
                      {auditing && (
                        <p className="text-xs text-paws-text-dim italic">Audit mode - timer not modifiable</p>
                      )}
                    </div>
                  );
                })() : (
                  <p className="text-sm text-paws-text-muted">No access recorded yet.</p>
                )}
              </CardContent>
            </Card>
          )}
          {isReadOnly && (
            <Card><CardContent>
              <p className="text-sm text-paws-text-muted italic">You have read-only access to this instance via group sharing.</p>
            </CardContent></Card>
          )}
          {canOperate && (
            <Card>
              <CardHeader><CardTitle>Power Actions</CardTitle></CardHeader>
              <CardContent className="flex flex-wrap gap-3">
                <Button variant="outline" onClick={() => doAction('start')}
                  disabled={vmStatus === 'running' || actionLoading !== null}>
                  <Play className="h-4 w-4 mr-1" /> {actionLoading === 'start' ? 'Starting...' : 'Start'}
                </Button>
                <Button variant="outline" onClick={() => doAction('shutdown')}
                  disabled={vmStatus === 'stopped' || actionLoading !== null}>
                  <Square className="h-4 w-4 mr-1" /> {actionLoading === 'shutdown' ? 'Shutting down...' : 'Graceful Shutdown'}
                </Button>
                <Button variant="outline"
                  onClick={() => confirmAction('stop', 'Force Stop', `Force stop "${inst.display_name}"? This is equivalent to pulling the power cord and may cause data loss.`)}
                  disabled={vmStatus === 'stopped' || actionLoading !== null}>
                  <Power className="h-4 w-4 mr-1" /> {actionLoading === 'stop' ? 'Stopping...' : 'Force Stop'}
                </Button>
                <Button variant="outline" onClick={() => doAction('reboot')}
                  disabled={vmStatus === 'stopped' || actionLoading !== null}>
                  <RotateCcw className="h-4 w-4 mr-1" /> {actionLoading === 'reboot' ? 'Rebooting...' : 'Reboot'}
                </Button>
                <Button variant="outline" onClick={() => doAction('suspend')}
                  disabled={vmStatus !== 'running' || actionLoading !== null}>
                  <Clock className="h-4 w-4 mr-1" /> {actionLoading === 'suspend' ? 'Suspending...' : 'Suspend'}
                </Button>
                <Button variant="outline" onClick={() => doAction('resume')}
                  disabled={vmStatus !== 'suspended' || actionLoading !== null}>
                  <Play className="h-4 w-4 mr-1" /> {actionLoading === 'resume' ? 'Resuming...' : 'Resume'}
                </Button>
              </CardContent>
            </Card>
          )}
          {canAdmin && (
            <Card>
              <CardHeader><CardTitle>Configuration</CardTitle></CardHeader>
              <CardContent className="flex flex-wrap gap-3">
                <Button variant="outline" onClick={() => setShowResize(true)}>
                  <Maximize className="h-4 w-4 mr-1" /> Resize
                </Button>
                <Button variant="outline" onClick={() => { setShowConfig(true); loadConfig(); }}>
                  <Cloud className="h-4 w-4 mr-1" /> Instance Config
                </Button>
                <Button variant="outline" onClick={async () => {
                  if (!id || !inst) return;
                  try {
                    await api.post('/api/templates/request', {
                      resource_id: id,
                      name: inst.display_name + ' Template',
                      description: `Template from ${inst.display_name}`,
                      category: inst.resource_type || 'vm',
                      os_type: 'linux',
                      min_cpu: inst.specs?.cores || 1,
                      min_ram_mb: inst.specs?.memory_mb || 512,
                      min_disk_gb: inst.specs?.disk_gb || 10,
                    });
                    toast('Template request submitted for admin review', 'success');
                  } catch (e: any) {
                    const d = e?.response?.data?.detail;
                    toast(typeof d === 'string' ? d : 'Failed to request template', 'error');
                  }
                }}>
                  <Camera className="h-4 w-4 mr-1" /> Request as Template
                </Button>
              </CardContent>
            </Card>
          )}
          {/* High Availability */}
          {canAdmin && (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Shield className="h-4 w-4" /> High Availability</CardTitle></CardHeader>
              <CardContent>
                {haStatus === null ? (
                  <p className="text-paws-text-muted text-sm">Loading HA status...</p>
                ) : haStatus.enabled ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <Badge variant="success">HA Enabled</Badge>
                      {haStatus.state && <span className="text-sm text-paws-text-muted">State: {haStatus.state}</span>}
                      {haStatus.group && <span className="text-sm text-paws-text-muted">Group: {haStatus.group}</span>}
                    </div>
                    <Button variant="outline" size="sm" onClick={disableHA} disabled={haLoading}>
                      {haLoading ? 'Disabling...' : 'Disable HA'}
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <p className="text-paws-text-muted text-sm">HA is not enabled for this instance.</p>
                    {haGroups.length > 0 && (
                      <Select label="HA Group (optional)" placeholder="Auto-assign" options={[{ value: '', label: 'Auto-assign' }, ...haGroups.map(g => ({ value: g.id, label: g.name }))]} value={haGroupId} onChange={e => setHaGroupId(e.target.value)} />
                    )}
                    <Button size="sm" onClick={enableHA} disabled={haLoading}>
                      {haLoading ? 'Enabling...' : 'Enable HA'}
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
          {canAdmin && (
            <Card>
              <CardHeader><CardTitle className="text-paws-danger">Danger Zone</CardTitle></CardHeader>
              <CardContent>
                <Button variant="danger" onClick={() => setShowDestroy(true)}>
                  <Trash2 className="h-4 w-4 mr-1" /> Destroy Instance
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {tab === 'notes' && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2"><FileText className="h-4 w-4" /> Notes</CardTitle>
              {!notesEditing ? (
                <Button variant="outline" size="sm" onClick={() => { setNotesDraft(notes); setNotesEditing(true); }}>
                  Edit
                </Button>
              ) : (
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="sm" onClick={() => { setNotesEditing(false); setNotesDraft(notes); }}>
                    Cancel
                  </Button>
                  <Button size="sm" disabled={notesSaving} onClick={async () => {
                    setNotesSaving(true);
                    try {
                      await api.put(`/api/resources/${id}/notes`, { notes: notesDraft });
                      setNotes(notesDraft);
                      setNotesEditing(false);
                      toast('Notes saved', 'success');
                    } catch { toast('Failed to save notes', 'error'); }
                    finally { setNotesSaving(false); }
                  }}>
                    {notesSaving ? 'Saving...' : 'Save'}
                  </Button>
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {notesEditing ? (
              <MarkdownEditor
                value={notesDraft}
                onChange={setNotesDraft}
                placeholder="Add notes about this instance..."
                minHeight="300px"
              />
            ) : notes ? (
              <div className="prose prose-invert max-w-none markdown-preview">
                <Markdown remarkPlugins={[remarkGfm]}>{notes}</Markdown>
              </div>
            ) : (
              <p className="text-paws-muted italic text-sm">No notes yet. Click Edit to add some.</p>
            )}
          </CardContent>
        </Card>
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

      {/* Instance Configuration Modal */}
      <Modal open={showConfig} onClose={() => setShowConfig(false)} title="Instance Configuration" size="lg">
        {configLoading ? (
          <p className="text-sm text-paws-text-dim py-4">Loading configuration...</p>
        ) : (
          <div className="space-y-4">
            {/* IP Address (read-only) */}
            {(configAllocatedIp || configIpAddress) && (
              <div className="flex items-center gap-3 p-3 rounded-md bg-paws-surface border border-paws-border-subtle">
                <Network className="h-4 w-4 text-paws-primary" />
                <div>
                  <p className="text-xs text-paws-text-dim">IP Address</p>
                  <p className="text-sm font-mono text-paws-text">{configAllocatedIp || configIpAddress}</p>
                </div>
                <p className="text-xs text-paws-text-dim ml-auto">Change IP from VPCs page</p>
              </div>
            )}
            <Input label="Hostname" value={configForm.hostname}
              onChange={(e) => setConfigForm({ ...configForm, hostname: e.target.value })} />
            <div className="grid grid-cols-2 gap-4">
              <Input label="Username" value={configForm.username} placeholder="paws"
                onChange={(e) => setConfigForm({ ...configForm, username: e.target.value })} />
              <div>
                <Input label={configPasswordSet ? 'Password (already set)' : 'Password'} type="password"
                  value={configForm.password} placeholder={configPasswordSet ? '(unchanged)' : 'Set password'}
                  onChange={(e) => setConfigForm({ ...configForm, password: e.target.value })} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Input label="DNS Server" value={configForm.dns_server} placeholder="1.1.1.1"
                onChange={(e) => setConfigForm({ ...configForm, dns_server: e.target.value })} />
              <Input label="DNS Domain" value={configForm.dns_domain} placeholder="example.local"
                onChange={(e) => setConfigForm({ ...configForm, dns_domain: e.target.value })} />
            </div>
            <div>
              <label className="block text-sm font-medium text-paws-text mb-1">SSH Keys</label>
              {userSshKeys.length > 0 ? (
                <div className="space-y-1.5">
                  {userSshKeys.map((k) => (
                    <label key={k.id} className="flex items-center gap-2 text-sm text-paws-text cursor-pointer">
                      <input
                        type="checkbox"
                        checked={configForm.ssh_key_ids.includes(k.id)}
                        onChange={(e) => {
                          const ids = e.target.checked
                            ? [...configForm.ssh_key_ids, k.id]
                            : configForm.ssh_key_ids.filter((x) => x !== k.id);
                          setConfigForm({ ...configForm, ssh_key_ids: ids });
                        }}
                        className="rounded border-paws-border"
                      />
                      {k.name}
                    </label>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-paws-text-dim">No SSH keys added. <a href="/ssh-keys" className="text-paws-primary hover:underline">Add SSH keys</a> to manage them here.</p>
              )}
            </div>
            <p className="text-xs text-paws-text-dim">
              {inst?.resource_type === 'lxc'
                ? 'SSH keys are set in the container config for root. If a username is set, PAWS will also inject keys for that user (container must be running).'
                : 'VM changes are applied via cloud-init. SSH keys are injected for the configured username. A reboot may be required for changes to take effect.'}
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowConfig(false)}>Cancel</Button>
              <Button onClick={handleSaveConfig}>Save</Button>
            </div>
          </div>
        )}
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
          <Select label="Storage" value={backupForm.storage}
            onChange={(e) => setBackupForm((p) => ({ ...p, storage: e.target.value }))}
            options={backupStorages.length > 0
              ? backupStorages.map((s) => ({ value: s.storage, label: s.storage }))
              : [{ value: '', label: 'No storages configured' }]
            } disabled={backupStorages.length === 0} />
          <Select label="Mode" value={backupForm.mode}
            onChange={(e) => setBackupForm((p) => ({ ...p, mode: e.target.value }))}
            options={[{ value: 'snapshot', label: 'Snapshot' }, { value: 'suspend', label: 'Suspend' }, { value: 'stop', label: 'Stop' }]} />
          <Select label="Compression" value={backupForm.compress}
            onChange={(e) => setBackupForm((p) => ({ ...p, compress: e.target.value }))}
            options={[{ value: 'zstd', label: 'ZSTD' }, { value: 'lzo', label: 'LZO' }, { value: 'gzip', label: 'GZIP' }, { value: 'none', label: 'None' }]} />
          <Input label="Notes (optional)" value={backupForm.notes}
            onChange={(e) => setBackupForm((p) => ({ ...p, notes: e.target.value }))} />
          <p className="text-xs text-paws-text-dim">Backup will be tagged: {inst?.display_name} | VMID {inst?.proxmox_vmid} | {inst?.proxmox_node}</p>
          <Button onClick={handleBackup} variant="primary" className="w-full" disabled={backupStorages.length === 0}>Create Backup</Button>
        </div>
      </Modal>

      {/* NIC Detail Modal - edit network or remove */}
      <Modal open={showNetModal} onClose={() => { setShowNetModal(false); setSelectedNic(null); }} title={`Interface ${selectedNic || netForm.net_id}`}>
        <div className="space-y-4">
          {(() => {
            const nicKey = selectedNic || netForm.net_id;
            const nicVal = netInterfaces[nicKey] || '';
            const parts = String(nicVal).split(',');
            const bridge = parts.find((p) => p.startsWith('bridge='))?.split('=')[1] || '';
            const macPart = parts.find((p) => /^([0-9A-Fa-f]{2}:){5}/.test(p) || p.startsWith('hwaddr='));
            const mac = macPart ? macPart.replace('hwaddr=', '') : '';
            const matchedVpc = vpcs.find((vpc) => vpc.vnet === bridge);
            const nicIps = nicKey === 'net0'
              ? (Object.entries(ipAddresses).find(([, ips]) => ips.length > 0)?.[1] || [])
              : (ipAddresses[`eth${nicKey.replace('net', '')}`] || []);
            const isSecondary = nicKey !== 'net0';
            return (
              <>
                <div className="rounded-lg bg-paws-surface p-3 space-y-2 text-sm">
                  <div className="flex justify-between"><span className="text-paws-text-dim">Bridge</span><span className="font-mono text-paws-text">{bridge}</span></div>
                  {matchedVpc && <div className="flex justify-between"><span className="text-paws-text-dim">Network</span><span className="text-paws-text">{matchedVpc.name}</span></div>}
                  {mac && <div className="flex justify-between"><span className="text-paws-text-dim">MAC</span><span className="font-mono text-paws-text">{mac}</span></div>}
                  {nicIps.length > 0 && (
                    <div className="flex justify-between items-start">
                      <span className="text-paws-text-dim">IP</span>
                      <div className="flex flex-wrap gap-1 justify-end">
                        {nicIps.map((ip) => (
                          <span key={ip} className="inline-block rounded bg-paws-primary/10 px-1.5 py-0.5 text-xs font-mono text-paws-primary">{ip}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <div className="border-t border-paws-border pt-3 space-y-3">
                  <p className="text-sm font-medium text-paws-text">Change Network</p>
                  {vpcs.length > 0 ? (
                    <Select label="VPC" value={netForm.vpc_id}
                      onChange={(e) => setNetForm((p) => ({ ...p, vpc_id: e.target.value }))}
                      options={[
                        { value: '', label: '- Select a VPC -' },
                        ...(isSecondary
                          ? vpcs.filter((v) => !v.network_mode || v.network_mode === 'private')
                          : vpcs
                        ).map((v) => ({
                          value: v.id,
                          label: `${v.name}${v.network_mode ? ` (${v.network_mode})` : ''} ${v.vnet ? `- ${v.vnet}` : ''}`,
                        })),
                      ]} />
                  ) : (
                    <p className="text-sm text-paws-text-dim">No VPCs available. Create a VPC first.</p>
                  )}
                  <p className="text-xs text-paws-text-dim">The instance should be stopped before changing network. It will be restarted automatically.</p>
                  <Button onClick={handleNetworkUpdate} variant="primary" className="w-full" disabled={!netForm.vpc_id || networkLoading}>
                    {networkLoading ? 'Updating Network...' : 'Update Network'}
                  </Button>
                </div>

                {isSecondary && (
                  <div className="border-t border-paws-border pt-3">
                    <Button variant="danger" className="w-full"
                      onClick={() => {
                        setShowNetModal(false);
                        setConfirmDialog({
                          title: 'Remove NIC',
                          message: `Remove interface ${nicKey}? The instance should be stopped first.`,
                          variant: 'danger',
                          confirmLabel: 'Remove',
                          onConfirm: async () => {
                            setNetworkLoading(true);
                            try {
                              await api.delete(`/api/compute/vms/${id}/network/nics/${nicKey}`);
                              toast(`Interface ${nicKey} removed`, 'success');
                              refreshNetwork();
                            } catch (e: any) {
                              toast(e.response?.data?.detail || 'Failed to remove NIC', 'error');
                            } finally {
                              setNetworkLoading(false);
                            }
                            setConfirmDialog(null);
                            setSelectedNic(null);
                          },
                        });
                      }}>
                      <Trash2 className="h-3.5 w-3.5 mr-1" /> Remove Interface
                    </Button>
                  </div>
                )}
              </>
            );
          })()}
        </div>
      </Modal>

      {/* Add NIC Modal */}
      <Modal open={showAddNic} onClose={() => setShowAddNic(false)} title="Add Network Interface">
        <div className="space-y-3">
          {vpcs.length > 0 ? (
            <>
              <Select label="Network (private only)" value={addNicVpc}
                onChange={(e) => setAddNicVpc(e.target.value)}
                options={[
                  { value: '', label: '- Select a private network -' },
                  ...vpcs.filter((v) => !v.network_mode || v.network_mode === 'private').map((v) => ({
                    value: v.id,
                    label: `${v.name} ${v.vnet ? `(${v.vnet})` : ''}`,
                  })),
                ]} />
              <p className="text-xs text-paws-text-dim">Secondary NICs can only be added to private networks.</p>
            </>
          ) : (
            <p className="text-sm text-paws-text-dim">No VPCs available.</p>
          )}
          <p className="text-xs text-paws-text-dim">The instance should be stopped before adding a NIC.</p>
          <Button variant="primary" className="w-full" disabled={!addNicVpc || networkLoading}
            onClick={async () => {
              setNetworkLoading(true);
              try {
                await api.post(`/api/compute/vms/${id}/network/nics`, { vpc_id: addNicVpc });
                setShowAddNic(false);
                refreshNetwork();
                toast('Network interface added', 'success');
              } catch (err: any) {
                toast(err?.response?.data?.detail || 'Failed to add NIC', 'error');
              } finally {
                setNetworkLoading(false);
              }
            }}>
            {networkLoading ? 'Adding NIC...' : 'Add NIC'}
          </Button>
        </div>
      </Modal>

      {/* File Browser Modal (PBS) */}
      <Modal open={!!browsingBackup} onClose={() => { setBrowsingBackup(null); setBackupFiles([]); setBackupFilePath(''); }}
        title={`Browse Backup - ${browsingBackup?.backup_id || ''} @ ${browsingBackup ? new Date(browsingBackup.backup_time! * 1000).toLocaleString() : ''}`}>
        <div className="space-y-3">
          {backupFilePath && (
            <div className="flex items-center gap-2 text-sm">
              <Button variant="ghost" size="sm" onClick={() => {
                const parent = backupFilePath.split('/').slice(0, -1).join('/');
                if (parent) handleBrowsePath(parent);
                else handleBrowseBackup(browsingBackup!);
              }}>
                <ArrowLeft className="h-3 w-3 mr-1" /> Back
              </Button>
              <span className="text-paws-text-dim font-mono text-xs">{backupFilePath}</span>
            </div>
          )}
          {backupFileLoading ? (
            <p className="text-sm text-paws-text-dim py-4 text-center">Loading...</p>
          ) : backupFiles.length === 0 ? (
            <p className="text-sm text-paws-text-dim py-4 text-center">No files found.</p>
          ) : (
            <div className="max-h-96 overflow-y-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-paws-text-dim border-b border-paws-border-subtle">
                    <th className="text-left py-1">Name</th>
                    <th className="text-left py-1">Type</th>
                    <th className="text-left py-1">Size</th>
                    <th className="text-right py-1">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {backupFiles.map((f: any, i: number) => {
                    const name = f.filename || f.text || f.name || `item-${i}`;
                    const isDir = f.type === 'd' || f.type === 'directory' || f.leaf === false || f.leaf === 0;
                    const isSymlink = f.type === 'l';
                    const isBrowsable = isDir || isSymlink;
                    const typeLabel = isSymlink ? 'symlink' : isDir ? 'dir' : 'file';
                    const fullPath = backupFilePath ? `${backupFilePath}/${name}` : name;
                    return (
                      <tr key={i} className="border-b border-paws-border-subtle last:border-0">
                        <td className="py-1 text-paws-text font-mono text-xs">
                          {isBrowsable ? (
                            <button className="text-paws-accent hover:underline" onClick={() => handleBrowsePath(fullPath)}>
                              {name}/
                            </button>
                          ) : name}
                        </td>
                        <td className="py-1 text-paws-text-dim text-xs">{typeLabel}</td>
                        <td className="py-1 text-paws-text text-xs">{f.size ? fmtBytes(f.size) : '-'}</td>
                        <td className="py-1 text-right">
                          <Button variant="ghost" size="sm" onClick={() => handleDownloadFile(fullPath)}>
                            Download{isBrowsable ? ' .zip' : ''}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Modal>

      {/* Generic Confirm Dialog */}
      <ConfirmDialog
        open={!!confirmDialog}
        title={confirmDialog?.title || ''}
        message={confirmDialog?.message || ''}
        confirmLabel={confirmDialog?.confirmLabel || 'Confirm'}
        variant={confirmDialog?.variant || 'danger'}
        onConfirm={() => { confirmDialog?.onConfirm(); setConfirmDialog(null); }}
        onCancel={() => setConfirmDialog(null)}
      />
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
  title, data, dataKey, color, unit, secondaryKey, secondaryColor, formatter, legendLabels, timeframe,
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
  timeframe?: string;
}) {
  const fmt = formatter || ((v: number) => `${v}${unit}`);

  const formatTime = (epoch: number): string => {
    const d = new Date(epoch * 1000);
    switch (timeframe) {
      case 'hour':
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      case 'day':
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      case 'week':
        return d.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
      case 'month':
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
      case 'year':
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
      default:
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
  };

  const chartData = data
    .filter((d) => d.time)
    .map((d) => {
      const rec = d as unknown as Record<string, unknown>;
      return {
        time: formatTime(d.time),
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
