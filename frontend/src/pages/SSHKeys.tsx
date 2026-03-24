import { useEffect, useState } from 'react';
import { Key, Plus, Trash2, Copy, Check } from 'lucide-react';
import api from '../api/client';
import {
  Button, DataTable, Input, Modal,
  Textarea, EmptyState, useConfirm, useToast, type Column,
} from '@/components/ui';

interface SSHKey {
  id: string;
  name: string;
  fingerprint: string;
  public_key: string;
  created_at: string;
  [key: string]: unknown;
}

export default function SSHKeys() {
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const [keys, setKeys] = useState<SSHKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', public_key: '' });
  const [copied, setCopied] = useState<string | null>(null);

  const fetchKeys = () => {
    api.get('/api/ssh-keys/')
      .then((res) => setKeys(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(fetchKeys, []);

  const handleCreate = async () => {
    try {
      await api.post('/api/ssh-keys/', form);
      toast('SSH key added', 'success');
      setShowCreate(false);
      setForm({ name: '', public_key: '' });
      fetchKeys();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to add SSH key', 'error');
    }
  };

  const handleDelete = async (id: string) => {
    if (!await confirm({ title: 'Delete SSH Key', message: 'Delete this SSH key?' })) return;
    try {
      await api.delete(`/api/ssh-keys/${id}`);
      toast('SSH key deleted', 'success');
      fetchKeys();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to delete SSH key', 'error');
    }
  };

  const copyFingerprint = (fp: string) => {
    navigator.clipboard.writeText(fp);
    setCopied(fp);
    setTimeout(() => setCopied(null), 2000);
  };

  const columns: Column<SSHKey>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (row) => (
        <div className="flex items-center gap-2">
          <Key className="h-4 w-4 text-paws-text-dim" />
          <span className="font-medium">{row.name}</span>
        </div>
      ),
    },
    {
      key: 'fingerprint',
      header: 'Fingerprint',
      render: (row) => (
        <div className="flex items-center gap-1">
          <code className="text-xs text-paws-text-dim font-mono">{row.fingerprint}</code>
          <button
            onClick={() => copyFingerprint(row.fingerprint)}
            className="p-0.5 rounded hover:bg-paws-surface-hover text-paws-text-dim"
          >
            {copied === row.fingerprint ? <Check className="h-3.5 w-3.5 text-paws-success" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
        </div>
      ),
    },
    {
      key: 'created_at',
      header: 'Added',
      render: (row) => <span className="text-xs text-paws-text-dim">{new Date(row.created_at).toLocaleDateString()}</span>,
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
        <h1 className="text-2xl font-bold text-paws-text">SSH Keys</h1>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4 mr-1" /> Add Key
        </Button>
      </div>

      {keys.length === 0 && !loading ? (
        <EmptyState
          icon={Key}
          title="No SSH keys"
          description="Add an SSH public key to inject it into new instances via cloud-init."
          action={{ label: 'Add SSH Key', onClick: () => setShowCreate(true) }}
        />
      ) : (
        <DataTable columns={columns} data={keys} loading={loading} />
      )}

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Add SSH Key" size="lg">
        <div className="space-y-4">
          <Input label="Name" placeholder="e.g. laptop, workstation" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Textarea
            label="Public Key"
            placeholder="ssh-ed25519 AAAA... user@host"
            value={form.public_key}
            onChange={(e) => setForm({ ...form, public_key: e.target.value })}
            rows={4}
          />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name || !form.public_key}>Add Key</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
