import { useState, useEffect } from 'react';
import api from '../api/client';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { Modal, useToast } from '@/components/ui';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { KeyRound, Plus, Copy, Trash2, AlertTriangle } from 'lucide-react';

interface APIKey {
  id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export default function APIKeys() {
  const [keys, setKeys] = useState<APIKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [tokenName, setTokenName] = useState('');
  const [newTokenRaw, setNewTokenRaw] = useState<string | null>(null);
  const [showRawToken, setShowRawToken] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<APIKey | null>(null);
  const toast = useToast();

  const fetchKeys = () => {
    setLoading(true);
    api.get('/api/keys/').then(r => setKeys(r.data)).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { fetchKeys(); }, []);

  const createKey = async () => {
    if (!tokenName.trim()) return;
    try {
      const r = await api.post('/api/keys/', { name: tokenName });
      setNewTokenRaw(r.data.raw_key);
      setShowRawToken(true);
      setShowCreate(false);
      setTokenName('');
      toast.toast('API key created', 'success');
      fetchKeys();
    } catch (e: any) {
      const d = e.response?.data?.detail;
      toast.toast(typeof d === 'string' ? d : 'Failed to create key', 'error');
    }
  };

  const revokeKey = async () => {
    if (!revokeTarget) return;
    try {
      await api.delete(`/api/keys/${revokeTarget.id}`);
      toast.toast('API key revoked', 'success');
      setRevokeTarget(null);
      fetchKeys();
    } catch {
      toast.toast('Failed to revoke key', 'error');
    }
  };

  const activeKeys = keys.filter(k => k.is_active);
  const revokedKeys = keys.filter(k => !k.is_active);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-paws-text">API Keys</h1>
          <p className="text-sm text-paws-text-muted mt-1">
            Create personal API keys for programmatic access. Use as <code className="bg-paws-card px-1 rounded">Bearer paws_...</code> in the Authorization header.
          </p>
        </div>
        <Button onClick={() => setShowCreate(true)}><Plus className="w-4 h-4 mr-1" /> Create Key</Button>
      </div>

      {/* Active Keys */}
      {loading ? (
        <LoadingSpinner message="Loading API keys..." />
      ) : activeKeys.length === 0 && revokedKeys.length === 0 ? (
        <Card><CardContent>
          <div className="text-center py-8">
            <KeyRound className="w-12 h-12 text-paws-text-muted mx-auto mb-3" />
            <p className="text-paws-text-muted">No API keys yet. Create one to get started.</p>
          </div>
        </CardContent></Card>
      ) : (
        <>
          {activeKeys.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-sm font-semibold text-paws-text-muted uppercase tracking-wider">Active Keys</h2>
              {activeKeys.map(k => (
                <div key={k.id} className="flex items-center justify-between px-4 py-3 rounded bg-paws-card border border-paws-border">
                  <div className="flex items-center gap-3">
                    <KeyRound className="w-4 h-4 text-paws-accent" />
                    <span className="text-paws-text font-medium">{k.name}</span>
                    <code className="text-xs text-paws-text-muted bg-paws-bg px-1.5 py-0.5 rounded">{k.key_prefix}...</code>
                    <Badge variant="success">Active</Badge>
                    <span className="text-xs text-paws-text-muted">Created {new Date(k.created_at).toLocaleDateString()}</span>
                    {k.last_used_at && (
                      <span className="text-xs text-paws-text-muted">Last used {new Date(k.last_used_at).toLocaleDateString()}</span>
                    )}
                  </div>
                  <Button variant="danger" size="sm" onClick={() => setRevokeTarget(k)}>
                    <Trash2 className="w-3.5 h-3.5 mr-1" /> Revoke
                  </Button>
                </div>
              ))}
            </div>
          )}

          {revokedKeys.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-sm font-semibold text-paws-text-muted uppercase tracking-wider">Revoked Keys</h2>
              {revokedKeys.map(k => (
                <div key={k.id} className="flex items-center gap-3 px-4 py-3 rounded bg-paws-card border border-paws-border opacity-50">
                  <KeyRound className="w-4 h-4 text-paws-text-muted" />
                  <span className="text-paws-text font-medium">{k.name}</span>
                  <code className="text-xs text-paws-text-muted bg-paws-bg px-1.5 py-0.5 rounded">{k.key_prefix}...</code>
                  <Badge variant="danger">Revoked</Badge>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Create Key Modal */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create API Key">
        <div className="space-y-3">
          <Input label="Key Name" placeholder="e.g. CI Pipeline, My Script" value={tokenName} onChange={e => setTokenName(e.target.value)} />
          <p className="text-xs text-paws-text-muted">
            This key will have the same permissions as your account. Keep it secure.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={createKey} disabled={!tokenName.trim()}>Create Key</Button>
          </div>
        </div>
      </Modal>

      {/* Show Raw Key Modal (once-only) */}
      <Modal open={showRawToken} onClose={() => { setShowRawToken(false); setNewTokenRaw(null); }} title="API Key Created">
        <div className="space-y-3">
          <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded flex items-start gap-2">
            <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0 mt-0.5" />
            <p className="text-sm text-yellow-200">Copy this key now - it won't be shown again.</p>
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-sm bg-paws-bg border border-paws-border rounded px-3 py-2 text-paws-text break-all select-all">
              {newTokenRaw}
            </code>
            <Button size="sm" variant="outline" onClick={() => { navigator.clipboard.writeText(newTokenRaw || ''); toast.toast('Copied!', 'success'); }}>
              <Copy className="w-4 h-4" />
            </Button>
          </div>
          <div className="flex justify-end">
            <Button onClick={() => { setShowRawToken(false); setNewTokenRaw(null); }}>Done</Button>
          </div>
        </div>
      </Modal>

      {/* Revoke Confirmation Modal */}
      <Modal open={!!revokeTarget} onClose={() => setRevokeTarget(null)} title="Revoke API Key">
        <div className="space-y-4">
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded flex items-start gap-2">
            <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <p className="text-sm text-red-200">
              This will immediately revoke the key <strong>{revokeTarget?.name}</strong> ({revokeTarget?.key_prefix}...). Any applications using this key will lose access.
            </p>
          </div>
          <div className="flex gap-2 justify-end">
            <Button variant="ghost" onClick={() => setRevokeTarget(null)}>Cancel</Button>
            <Button variant="danger" onClick={revokeKey}>Revoke Key</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
