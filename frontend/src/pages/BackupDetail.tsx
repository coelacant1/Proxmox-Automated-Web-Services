import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Trash2 } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Badge, StatusBadge, Tabs, useConfirm, useToast,
} from '@/components/ui';

interface BackupInfo {
  id: string;
  resource_id: string;
  resource_name: string;
  type: string;
  status: string;
  size_mb: number;
  created_at: string;
  retention_days: number;
  expires_at?: string;
  notes?: string;
  verified?: boolean;
  [key: string]: unknown;
}

interface BackupHistory {
  id: string;
  action: string;
  status: string;
  timestamp: string;
  details?: string;
}

export default function BackupDetail() {
  const { backupId } = useParams<{ backupId: string }>();
  const navigate = useNavigate();
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const [backup, setBackup] = useState<BackupInfo | null>(null);
  const [history, setHistory] = useState<BackupHistory[]>([]);
  const [tab, setTab] = useState('info');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!backupId) return;
    Promise.all([
      api.get(`/api/backups/${backupId}`).catch(() => null),
      api.get(`/api/backups/${backupId}/history`).catch(() => ({ data: [] })),
    ]).then(([bRes, hRes]) => {
      if (bRes?.data) setBackup(bRes.data);
      setHistory(hRes?.data || []);
      setLoading(false);
    });
  }, [backupId]);

  const handleRestore = async () => {
    if (!backupId) return;
    if (!await confirm({ title: 'Restore Backup', message: 'Restore this backup? The current state will be replaced.' })) return;
    try {
      await api.post(`/api/backups/${backupId}/restore`);
      toast('Backup restore started', 'success');
    } catch {
      toast('Failed to restore backup', 'error');
    }
  };

  const handleDelete = async () => {
    if (!backupId) return;
    if (!await confirm({ title: 'Delete Backup', message: 'Permanently delete this backup? This action cannot be undone.' })) return;
    try {
      await api.delete(`/api/backups/${backupId}`);
      toast('Backup deleted', 'success');
      navigate('/backups');
    } catch {
      toast('Failed to delete backup', 'error');
    }
  };

  if (loading) return <p className="text-paws-text-muted p-8">Loading...</p>;
  if (!backup) return <p className="text-paws-text-muted p-8">Backup not found</p>;

  const tabs = [
    { id: 'info', label: 'Details' },
    { id: 'history', label: 'History', count: history.length },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/backups')} className="p-1 rounded hover:bg-paws-surface-hover text-paws-text-dim">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-paws-text">Backup {backup.id.slice(0, 8)}</h1>
            <StatusBadge status={backup.status} />
            <Badge variant="default">{backup.type}</Badge>
            {backup.verified && <Badge variant="success">Verified</Badge>}
          </div>
          <p className="text-sm text-paws-text-muted mt-0.5">
            {backup.resource_name || backup.resource_id} · {backup.size_mb} MB · {new Date(backup.created_at).toLocaleString()}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleRestore}>
            <Play className="h-3.5 w-3.5 mr-1" /> Restore
          </Button>
          <Button variant="danger" size="sm" onClick={handleDelete}>
            <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
          </Button>
        </div>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} className="mb-6" />

      {tab === 'info' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader><CardTitle>Backup Info</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-3">
                <Row label="ID" value={backup.id} />
                <Row label="Resource" value={backup.resource_name || backup.resource_id} />
                <Row label="Type" value={backup.type} />
                <Row label="Size" value={`${backup.size_mb} MB`} />
                <Row label="Created" value={new Date(backup.created_at).toLocaleString()} />
                <Row label="Retention" value={`${backup.retention_days} days`} />
                {backup.expires_at && <Row label="Expires" value={new Date(backup.expires_at).toLocaleString()} />}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Compliance</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-paws-text">Integrity Verified</span>
                  <Badge variant={backup.verified ? 'success' : 'warning'}>{backup.verified ? 'Yes' : 'Pending'}</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-paws-text">Retention Policy</span>
                  <Badge variant="default">{backup.retention_days}d</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-paws-text">Status</span>
                  <StatusBadge status={backup.status} />
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {tab === 'history' && (
        <Card>
          <CardHeader><CardTitle>Activity Timeline</CardTitle></CardHeader>
          <CardContent>
            {history.length === 0 ? (
              <p className="text-sm text-paws-text-dim">No activity recorded.</p>
            ) : (
              <div className="space-y-0">
                {history.map((h, i) => (
                  <div key={h.id || i} className="flex gap-4 pb-4 last:pb-0">
                    <div className="flex flex-col items-center">
                      <div className="w-2 h-2 rounded-full bg-paws-primary mt-2" />
                      {i < history.length - 1 && <div className="w-px flex-1 bg-paws-border-subtle mt-1" />}
                    </div>
                    <div className="flex-1 pb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-paws-text">{h.action}</span>
                        <StatusBadge status={h.status} />
                      </div>
                      {h.details && <p className="text-xs text-paws-text-dim mt-0.5">{h.details}</p>}
                      <p className="text-xs text-paws-text-dim mt-0.5">
                        {new Date(h.timestamp).toLocaleString()}
                      </p>
                    </div>
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

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-paws-text-dim">{label}</span>
      <span className="text-sm text-paws-text font-mono">{value}</span>
    </div>
  );
}
