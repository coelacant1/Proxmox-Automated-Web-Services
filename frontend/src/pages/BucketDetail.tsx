import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Share2, History,
  FileText, Trash2, Users,
} from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Input, Modal, Select, Badge, Tabs, EmptyState,
} from '@/components/ui';

interface BucketInfo {
  id: string;
  name: string;
  bucket_name: string;
  created_at: string;
  owner_id?: string;
  versioning_enabled?: boolean;
  encryption_enabled?: boolean;
  encryption_algorithm?: string;
  lifecycle_rules?: LifecycleRule[];
  cors_rules?: CorsRule[];
  shared_with?: SharedUser[];
  total_size?: number;
  object_count?: number;
}

interface LifecycleRule {
  id: string;
  prefix: string;
  action: string;
  days: number;
  enabled: boolean;
}

interface CorsRule {
  allowed_origins: string[];
  allowed_methods: string[];
  max_age_seconds: number;
}

interface SharedUser {
  user_id: string;
  username: string;
  permission: string;
}

interface VersionEntry {
  version_id: string;
  key: string;
  size: number;
  last_modified: string;
  is_latest: boolean;
}

function formatSize(bytes: number): string {
  if (!bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export default function BucketDetail() {
  const { bucketName } = useParams<{ bucketName: string }>();
  const navigate = useNavigate();
  const [bucket, setBucket] = useState<BucketInfo | null>(null);
  const [tab, setTab] = useState('overview');
  const [versions, setVersions] = useState<VersionEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // Sharing state
  const [showShare, setShowShare] = useState(false);
  const [shareForm, setShareForm] = useState({ user_id: '', permission: 'read' });

  // Lifecycle state
  const [showLifecycle, setShowLifecycle] = useState(false);
  const [lcForm, setLcForm] = useState({ prefix: '', action: 'delete', days: 30 });

  // CORS state
  const [showCors, setShowCors] = useState(false);
  const [corsForm, setCorsForm] = useState({ allowed_origins: '*', allowed_methods: 'GET,PUT', max_age_seconds: 3600 });

  const fetchBucket = () => {
    if (!bucketName) return;
    setLoading(true);
    api.get(`/api/storage/buckets/${bucketName}`)
      .then((res) => setBucket(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  const fetchVersions = () => {
    if (!bucketName) return;
    api.get(`/api/storage/buckets/${bucketName}/versions`)
      .then((res) => setVersions(res.data.versions || res.data || []))
      .catch(() => setVersions([]));
  };

  useEffect(fetchBucket, [bucketName]);
  useEffect(() => { if (tab === 'versions') fetchVersions(); }, [tab]);

  const toggleVersioning = async () => {
    if (!bucketName) return;
    await api.patch(`/api/storage/buckets/${bucketName}`, {
      versioning_enabled: !bucket?.versioning_enabled,
    });
    fetchBucket();
  };

  const toggleEncryption = async () => {
    if (!bucketName) return;
    await api.patch(`/api/storage/buckets/${bucketName}`, {
      encryption_enabled: !bucket?.encryption_enabled,
      encryption_algorithm: 'AES-256',
    });
    fetchBucket();
  };

  const handleShare = async () => {
    if (!bucketName) return;
    await api.post(`/api/storage/buckets/${bucketName}/share`, shareForm);
    setShowShare(false);
    setShareForm({ user_id: '', permission: 'read' });
    fetchBucket();
  };

  const handleUnshare = async (userId: string) => {
    if (!bucketName) return;
    await api.delete(`/api/storage/buckets/${bucketName}/share/${userId}`);
    fetchBucket();
  };

  const handleAddLifecycle = async () => {
    if (!bucketName) return;
    await api.post(`/api/storage/buckets/${bucketName}/lifecycle`, lcForm);
    setShowLifecycle(false);
    setLcForm({ prefix: '', action: 'delete', days: 30 });
    fetchBucket();
  };

  const handleDeleteLifecycle = async (ruleId: string) => {
    if (!bucketName) return;
    await api.delete(`/api/storage/buckets/${bucketName}/lifecycle/${ruleId}`);
    fetchBucket();
  };

  const handleAddCors = async () => {
    if (!bucketName) return;
    await api.post(`/api/storage/buckets/${bucketName}/cors`, {
      allowed_origins: corsForm.allowed_origins.split(',').map((s) => s.trim()),
      allowed_methods: corsForm.allowed_methods.split(',').map((s) => s.trim()),
      max_age_seconds: corsForm.max_age_seconds,
    });
    setShowCors(false);
    fetchBucket();
  };

  if (loading) return <p className="text-paws-text-muted p-8">Loading...</p>;
  if (!bucket) return <p className="text-paws-text-muted p-8">Bucket not found</p>;

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'sharing', label: 'Sharing', count: bucket.shared_with?.length || 0 },
    { id: 'security', label: 'Security' },
    { id: 'lifecycle', label: 'Lifecycle', count: bucket.lifecycle_rules?.length || 0 },
    { id: 'versions', label: 'Versions' },
    { id: 'metrics', label: 'Metrics' },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/storage')} className="p-1 rounded hover:bg-paws-surface-hover text-paws-text-dim">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-paws-text">{bucket.name}</h1>
            {bucket.versioning_enabled && <Badge variant="info">Versioned</Badge>}
            {bucket.encryption_enabled && <Badge variant="success">Encrypted</Badge>}
          </div>
          <p className="text-sm text-paws-text-muted mt-0.5">
            {bucket.object_count || 0} objects · {formatSize(bucket.total_size || 0)} · Created {new Date(bucket.created_at).toLocaleDateString()}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => navigate(`/storage/${bucketName}/files`)}>
          <FileText className="h-4 w-4 mr-1" /> Browse Files
        </Button>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} className="mb-6" />

      {/* Overview */}
      {tab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader><CardTitle>Bucket Info</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-3">
                <InfoRow label="Bucket Name" value={bucket.bucket_name} />
                <InfoRow label="Objects" value={String(bucket.object_count || 0)} />
                <InfoRow label="Total Size" value={formatSize(bucket.total_size || 0)} />
                <InfoRow label="Created" value={new Date(bucket.created_at).toLocaleString()} />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Quick Settings</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-paws-text">Versioning</p>
                  <p className="text-xs text-paws-text-dim">Keep previous versions of objects</p>
                </div>
                <ToggleSwitch enabled={!!bucket.versioning_enabled} onToggle={toggleVersioning} />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-paws-text">Encryption</p>
                  <p className="text-xs text-paws-text-dim">AES-256 server-side encryption</p>
                </div>
                <ToggleSwitch enabled={!!bucket.encryption_enabled} onToggle={toggleEncryption} />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Sharing */}
      {tab === 'sharing' && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Shared Access</CardTitle>
              <Button size="sm" onClick={() => setShowShare(true)}>
                <Share2 className="h-4 w-4 mr-1" /> Share
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {(bucket.shared_with || []).length === 0 ? (
              <EmptyState icon={Users} title="Not shared" description="Share this bucket to give other users access." />
            ) : (
              <div className="space-y-2">
                {bucket.shared_with!.map((s) => (
                  <div key={s.user_id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                    <div className="flex items-center gap-3">
                      <div className="w-7 h-7 rounded-full bg-paws-primary/20 flex items-center justify-center text-xs font-bold text-paws-primary">
                        {s.username?.charAt(0).toUpperCase() || '?'}
                      </div>
                      <span className="text-sm text-paws-text">{s.username || s.user_id}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={s.permission === 'write' ? 'warning' : 'default'}>{s.permission}</Badge>
                      <Button variant="ghost" size="sm" onClick={() => handleUnshare(s.user_id)}>
                        <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Security (Encryption + CORS) */}
      {tab === 'security' && (
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Encryption</CardTitle></CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-paws-text">
                    {bucket.encryption_enabled
                      ? `Enabled - ${bucket.encryption_algorithm || 'AES-256'}`
                      : 'Disabled - Objects stored unencrypted'}
                  </p>
                </div>
                <ToggleSwitch enabled={!!bucket.encryption_enabled} onToggle={toggleEncryption} />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>CORS Rules</CardTitle>
                <Button size="sm" onClick={() => setShowCors(true)}>Add Rule</Button>
              </div>
            </CardHeader>
            <CardContent>
              {(bucket.cors_rules || []).length === 0 ? (
                <p className="text-sm text-paws-text-dim">No CORS rules. Cross-origin requests are blocked by default.</p>
              ) : (
                <div className="space-y-2">
                  {bucket.cors_rules!.map((rule, i) => (
                    <div key={i} className="bg-paws-bg rounded-md p-3 text-xs font-mono">
                      <p>Origins: {rule.allowed_origins?.join(', ')}</p>
                      <p>Methods: {rule.allowed_methods?.join(', ')}</p>
                      <p>Max Age: {rule.max_age_seconds}s</p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Lifecycle */}
      {tab === 'lifecycle' && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Lifecycle Rules</CardTitle>
              <Button size="sm" onClick={() => setShowLifecycle(true)}>Add Rule</Button>
            </div>
          </CardHeader>
          <CardContent>
            {(bucket.lifecycle_rules || []).length === 0 ? (
              <EmptyState icon={History} title="No lifecycle rules" description="Add rules to automatically manage object retention." />
            ) : (
              <div className="space-y-2">
                {bucket.lifecycle_rules!.map((rule) => (
                  <div key={rule.id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                    <div>
                      <p className="text-sm text-paws-text">
                        <span className="font-mono">{rule.prefix || '*'}</span> {'->'} {rule.action} after {rule.days} days
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={rule.enabled ? 'success' : 'default'}>{rule.enabled ? 'Active' : 'Disabled'}</Badge>
                      <Button variant="ghost" size="sm" onClick={() => handleDeleteLifecycle(rule.id)}>
                        <Trash2 className="h-3.5 w-3.5 text-paws-danger" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Versions */}
      {tab === 'versions' && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Object Versions</CardTitle>
              {!bucket.versioning_enabled && (
                <Badge variant="warning">Versioning Disabled</Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {!bucket.versioning_enabled ? (
              <div className="text-center py-6">
                <p className="text-sm text-paws-text-dim mb-3">Enable versioning to track object history.</p>
                <Button size="sm" onClick={toggleVersioning}>Enable Versioning</Button>
              </div>
            ) : versions.length === 0 ? (
              <p className="text-sm text-paws-text-dim">No versions recorded yet.</p>
            ) : (
              <div className="space-y-1">
                {versions.map((v) => (
                  <div key={v.version_id} className="flex items-center justify-between py-2 border-b border-paws-border-subtle last:border-0">
                    <div className="flex items-center gap-2">
                      <FileText className="h-3.5 w-3.5 text-paws-text-dim" />
                      <span className="text-sm text-paws-text">{v.key}</span>
                      {v.is_latest && <Badge variant="info">Latest</Badge>}
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-xs text-paws-text-dim">{formatSize(v.size)}</span>
                      <span className="text-xs text-paws-text-dim">{new Date(v.last_modified).toLocaleString()}</span>
                      <span className="text-xs font-mono text-paws-text-dim">{v.version_id.slice(0, 8)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Metrics */}
      {tab === 'metrics' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader><CardTitle>Storage Usage</CardTitle></CardHeader>
            <CardContent className="text-center py-8">
              <p className="text-4xl font-bold text-paws-text">{formatSize(bucket.total_size || 0)}</p>
              <p className="text-sm text-paws-text-dim mt-1">{bucket.object_count || 0} objects</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Request Metrics</CardTitle></CardHeader>
            <CardContent className="h-48 flex items-center justify-center text-paws-text-dim text-sm">
              Request metrics chart placeholder
            </CardContent>
          </Card>
        </div>
      )}

      {/* Share Modal */}
      <Modal open={showShare} onClose={() => setShowShare(false)} title="Share Bucket">
        <div className="space-y-4">
          <Input label="User ID" value={shareForm.user_id} onChange={(e) => setShareForm({ ...shareForm, user_id: e.target.value })} />
          <Select label="Permission" options={[
            { value: 'read', label: 'Read Only' },
            { value: 'write', label: 'Read & Write' },
          ]} value={shareForm.permission} onChange={(e) => setShareForm({ ...shareForm, permission: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowShare(false)}>Cancel</Button>
            <Button onClick={handleShare} disabled={!shareForm.user_id}>Share</Button>
          </div>
        </div>
      </Modal>

      {/* Lifecycle Modal */}
      <Modal open={showLifecycle} onClose={() => setShowLifecycle(false)} title="Add Lifecycle Rule">
        <div className="space-y-4">
          <Input label="Key Prefix" placeholder="logs/ or leave empty for all" value={lcForm.prefix}
            onChange={(e) => setLcForm({ ...lcForm, prefix: e.target.value })} />
          <Select label="Action" options={[
            { value: 'delete', label: 'Delete objects' },
            { value: 'archive', label: 'Move to archive' },
            { value: 'expire_versions', label: 'Expire old versions' },
          ]} value={lcForm.action} onChange={(e) => setLcForm({ ...lcForm, action: e.target.value })} />
          <Input label="After (days)" type="number" min={1} value={lcForm.days}
            onChange={(e) => setLcForm({ ...lcForm, days: +e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowLifecycle(false)}>Cancel</Button>
            <Button onClick={handleAddLifecycle}>Add Rule</Button>
          </div>
        </div>
      </Modal>

      {/* CORS Modal */}
      <Modal open={showCors} onClose={() => setShowCors(false)} title="Add CORS Rule">
        <div className="space-y-4">
          <Input label="Allowed Origins" placeholder="*, https://example.com" value={corsForm.allowed_origins}
            onChange={(e) => setCorsForm({ ...corsForm, allowed_origins: e.target.value })} />
          <Input label="Allowed Methods" placeholder="GET,PUT,POST,DELETE" value={corsForm.allowed_methods}
            onChange={(e) => setCorsForm({ ...corsForm, allowed_methods: e.target.value })} />
          <Input label="Max Age (seconds)" type="number" value={corsForm.max_age_seconds}
            onChange={(e) => setCorsForm({ ...corsForm, max_age_seconds: +e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCors(false)}>Cancel</Button>
            <Button onClick={handleAddCors}>Add Rule</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-paws-text-dim">{label}</span>
      <span className="text-sm text-paws-text font-mono">{value}</span>
    </div>
  );
}

function ToggleSwitch({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className={`w-10 h-5 rounded-full transition-colors ${enabled ? 'bg-paws-primary' : 'bg-paws-surface-hover'}`}
    >
      <span className={`block w-4 h-4 rounded-full bg-white transform transition-transform ${enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
    </button>
  );
}
