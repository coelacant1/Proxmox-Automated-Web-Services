import { useEffect, useState } from 'react';
import api from '../api/client';
import { Button, Card, Input } from '@/components/ui';

interface Bucket {
  id: string;
  name: string;
  bucket_name: string;
  created_at: string;
}

export default function Storage() {
  const [buckets, setBuckets] = useState<Bucket[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState('');

  const [error, setError] = useState('');

  const fetchBuckets = () => {
    api.get('/api/storage/buckets').then((res) => setBuckets(res.data)).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(fetchBuckets, []);

  const createBucket = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setError('');
    try {
      await api.post('/api/storage/buckets', { name: newName.toLowerCase().trim() });
      setNewName('');
      fetchBuckets();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Failed to create bucket');
    }
  };

  const deleteBucket = async (id: string) => {
    if (!confirm('Delete this bucket and all its contents?')) return;
    await api.delete(`/api/storage/buckets/${id}`);
    fetchBuckets();
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-paws-text">Object Storage</h1>
      <div>
        <form onSubmit={createBucket} className="flex gap-2">
          <div className="flex-1">
            <Input
              placeholder="New bucket name (lowercase, 3-63 chars)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </div>
          <Button type="submit" variant="primary">Create Bucket</Button>
        </form>
        {error && <p className="mt-2 text-sm text-paws-danger">{error}</p>}
        <p className="mt-1 text-xs text-paws-text-dim">Lowercase letters, numbers, dots, hyphens only. Must start/end with alphanumeric.</p>
      </div>

      {loading ? <p className="text-paws-text-muted">Loading...</p> : buckets.length === 0 ? (
        <p className="text-paws-text-dim">No buckets yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {buckets.map((b) => (
            <Card key={b.id} className="flex items-center justify-between">
              <div>
                <p className="font-bold">{b.name}</p>
                <p className="text-xs text-paws-text-muted">{b.bucket_name}</p>
              </div>
              <Button variant="danger" size="sm" onClick={() => deleteBucket(b.id)}>
                Delete
              </Button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
