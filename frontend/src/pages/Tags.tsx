import { useEffect, useState } from 'react';
import { Tag as TagIcon, Plus, Search } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Input, Modal, Badge, EmptyState, TagPills,
} from '@/components/ui';

interface TagEntry {
  key: string;
  value: string;
  resource_id: string;
  resource_name?: string;
}

export default function Tags() {
  const [tags, setTags] = useState<TagEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ resource_id: '', key: '', value: '' });

  const fetchTags = () => {
    api.get('/api/tags/')
      .then((res) => setTags(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(fetchTags, []);

  const handleAdd = async () => {
    await api.post('/api/tags/', form);
    setShowAdd(false);
    setForm({ resource_id: '', key: '', value: '' });
    fetchTags();
  };

  const handleRemove = async (resourceId: string, key: string) => {
    await api.delete(`/api/tags/${resourceId}/${key}`);
    fetchTags();
  };

  const filtered = tags.filter(
    (t) =>
      !search ||
      t.key.toLowerCase().includes(search.toLowerCase()) ||
      t.value.toLowerCase().includes(search.toLowerCase()),
  );

  // Group by resource
  const grouped = filtered.reduce<Record<string, TagEntry[]>>((acc, t) => {
    const rid = t.resource_id;
    if (!acc[rid]) acc[rid] = [];
    acc[rid].push(t);
    return acc;
  }, {});

  // Unique tag keys for summary
  const uniqueKeys = [...new Set(tags.map((t) => t.key))];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-paws-text">Tags</h1>
          <p className="text-sm text-paws-text-muted mt-1">
            {tags.length} tags across {Object.keys(grouped).length} resources
          </p>
        </div>
        <Button onClick={() => setShowAdd(true)}>
          <Plus className="h-4 w-4 mr-1" /> Add Tag
        </Button>
      </div>

      {/* Tag Key Summary */}
      {uniqueKeys.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {uniqueKeys.map((k) => (
            <button key={k} onClick={() => setSearch(k)}>
              <Badge variant="default">
                {k} ({tags.filter((t) => t.key === k).length})
              </Badge>
            </button>
          ))}
        </div>
      )}

      <div className="relative max-w-sm mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-paws-text-dim" />
        <Input placeholder="Filter tags..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
      </div>

      {loading ? (
        <p className="text-paws-text-muted">Loading...</p>
      ) : Object.keys(grouped).length === 0 ? (
        <EmptyState
          icon={TagIcon}
          title="No tags"
          description="Add tags to organize and categorize your resources."
          action={{ label: 'Add Tag', onClick: () => setShowAdd(true) }}
        />
      ) : (
        <div className="space-y-3">
          {Object.entries(grouped).map(([resourceId, resourceTags]) => (
            <Card key={resourceId}>
              <CardHeader>
                <CardTitle className="text-sm font-mono">{resourceTags[0]?.resource_name || resourceId}</CardTitle>
              </CardHeader>
              <CardContent>
                <TagPills
                  tags={Object.fromEntries(resourceTags.map((t) => [t.key, t.value]))}
                  onRemove={(key) => handleRemove(resourceId, key)}
                />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add Tag">
        <div className="space-y-4">
          <Input label="Resource ID" value={form.resource_id} onChange={(e) => setForm({ ...form, resource_id: e.target.value })} />
          <Input label="Key" placeholder="e.g. environment, project" value={form.key}
            onChange={(e) => setForm({ ...form, key: e.target.value })} />
          <Input label="Value" placeholder="e.g. production, frontend" value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowAdd(false)}>Cancel</Button>
            <Button onClick={handleAdd} disabled={!form.resource_id || !form.key}>Add Tag</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
