import { useEffect, useState } from 'react';
import api from '../api/client';
import { Button, Card, Input } from '@/components/ui';

interface Snapshot {
  name: string;
  description: string;
  snaptime?: number;
  parent?: string;
}

interface ResourceItem {
  id: string;
  name: string;
  resource_type: string;
  status: string;
}

export default function Backups() {
  const [resources, setResources] = useState<ResourceItem[]>([]);
  const [selectedResource, setSelectedResource] = useState<string>('');
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [loading, setLoading] = useState(false);
  const [snapName, setSnapName] = useState('');
  const [snapDesc, setSnapDesc] = useState('');

  useEffect(() => {
    api.get('/api/resources').then((res) => {
      const data = res.data.items ?? res.data;
      const items = data.filter((r: ResourceItem) => r.resource_type === 'vm' || r.resource_type === 'container');
      setResources(items);
    }).catch(() => {});
  }, []);

  const fetchSnapshots = async (resourceId: string) => {
    setSelectedResource(resourceId);
    setLoading(true);
    try {
      const res = await api.get(`/api/backups/${resourceId}/snapshots`);
      setSnapshots(res.data);
    } catch {
      setSnapshots([]);
    } finally {
      setLoading(false);
    }
  };

  const createSnapshot = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedResource || !snapName) return;
    await api.post(`/api/backups/${selectedResource}/snapshots`, {
      name: snapName, description: snapDesc,
    });
    setSnapName('');
    setSnapDesc('');
    fetchSnapshots(selectedResource);
  };

  const rollback = async (snapName: string) => {
    if (!confirm(`Rollback to snapshot "${snapName}"?`)) return;
    await api.post(`/api/backups/${selectedResource}/snapshots/${snapName}/rollback`);
  };

  const deleteSnap = async (name: string) => {
    if (!confirm(`Delete snapshot "${name}"?`)) return;
    await api.delete(`/api/backups/${selectedResource}/snapshots/${name}`);
    fetchSnapshots(selectedResource);
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-paws-text">Backups &amp; Snapshots</h1>

      {/* Resource selector */}
      <div>
        <label className="text-sm font-medium text-paws-text-muted mr-2">Select resource:</label>
        <select
          className="min-w-[200px] rounded-md border border-paws-border bg-paws-surface px-3 py-2 text-sm text-paws-text focus:outline-none focus:ring-2 focus:ring-paws-primary/50 focus:border-paws-primary"
          value={selectedResource}
          onChange={(e) => fetchSnapshots(e.target.value)}
        >
          <option value="">-- Select --</option>
          {resources.map((r) => (
            <option key={r.id} value={r.id}>{r.name} ({r.resource_type})</option>
          ))}
        </select>
      </div>

      {selectedResource && (
        <>
          {/* Create snapshot form */}
          <form onSubmit={createSnapshot} className="flex flex-wrap gap-2">
            <Input placeholder="Snapshot name" value={snapName} onChange={(e) => setSnapName(e.target.value)} />
            <div className="flex-1">
              <Input placeholder="Description (optional)" value={snapDesc} onChange={(e) => setSnapDesc(e.target.value)} />
            </div>
            <Button type="submit" variant="primary">Create Snapshot</Button>
          </form>

          {/* Snapshots list */}
          {loading ? <p className="text-paws-text-muted">Loading...</p> : snapshots.length === 0 ? (
            <p className="text-paws-text-dim">No snapshots found.</p>
          ) : (
            <div className="flex flex-col gap-3">
              {snapshots.filter(s => s.name !== 'current').map((s) => (
                <Card key={s.name} className="flex items-center justify-between">
                  <div>
                    <p className="font-bold">{s.name}</p>
                    <p className="text-xs text-paws-text-muted">
                      {s.description || 'No description'}
                      {s.snaptime && ` · ${new Date(s.snaptime * 1000).toLocaleString()}`}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => rollback(s.name)}>Rollback</Button>
                    <Button variant="danger" size="sm" onClick={() => deleteSnap(s.name)}>Delete</Button>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
