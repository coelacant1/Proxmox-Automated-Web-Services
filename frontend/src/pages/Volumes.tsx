import { useEffect, useState } from 'react';
import { HardDrive, Plus, Trash2, Link2, Unlink, ArrowUpCircle } from 'lucide-react';
import api from '../api/client';
import {
  Button, DataTable, Input, Modal, Select,
  StatusBadge, EmptyState, ConfirmDialog, useToast, type Column,
} from '@/components/ui';

interface Volume {
  id: string;
  name: string;
  size_gib: number;
  storage_pool: string;
  status: string;
  resource_id: string | null;
  disk_slot: string | null;
  proxmox_volid: string | null;
  proxmox_owner_vmid: number | null;
  display_name: string | null;
  created_at: string;
  [key: string]: unknown;
}

interface VM {
  id: string;
  display_name: string;
  proxmox_vmid: number;
  status: string;
}

export default function Volumes() {
  const [volumes, setVolumes] = useState<Volume[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [storagePools, setStoragePools] = useState<string[]>([]);
  const [defaultPool, setDefaultPool] = useState('');
  const [vms, setVms] = useState<VM[]>([]);
  const [form, setForm] = useState({ name: '', size_gib: 10, storage_pool: '', resource_id: '' });
  const [confirmDelete, setConfirmDelete] = useState<Volume | null>(null);
  const [confirmDetach, setConfirmDetach] = useState<Volume | null>(null);
  const [attachModal, setAttachModal] = useState<Volume | null>(null);
  const [attachTarget, setAttachTarget] = useState('');
  const [resizeModal, setResizeModal] = useState<Volume | null>(null);
  const [resizeValue, setResizeValue] = useState(0);
  const [actionLoading, setActionLoading] = useState(false);
  const { toast } = useToast();

  const fetchVolumes = () => {
    api.get('/api/volumes/').then((res) => setVolumes(res.data)).catch(() => {}).finally(() => setLoading(false));
  };

  const fetchVMs = () => {
    api.get('/api/compute/vms').then((res) => {
      const list = (res.data || []).map((vm: any) => ({
        id: vm.id,
        display_name: vm.display_name || vm.name,
        proxmox_vmid: vm.proxmox_vmid,
        status: vm.status,
      }));
      setVms(list);
    }).catch(() => {});
  };

  useEffect(() => {
    fetchVolumes();
    fetchVMs();
    api.get('/api/storage-pools/').then((res) => {
      const pools = res.data?.pools || [];
      const def = res.data?.default || '';
      setStoragePools(pools);
      setDefaultPool(def);
      setForm((f) => ({ ...f, storage_pool: f.storage_pool || def }));
    }).catch(() => {});
  }, []);

  const extractError = (e: any): string => {
    const detail = e?.response?.data?.detail;
    if (!detail) return 'An unexpected error occurred';
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ');
    return JSON.stringify(detail);
  };

  const handleCreate = async () => {
    setActionLoading(true);
    try {
      await api.post('/api/volumes/', form);
      setShowCreate(false);
      setForm({ name: '', size_gib: 10, storage_pool: defaultPool, resource_id: '' });
      toast('Volume created and attached.', 'success');
      fetchVolumes();
    } catch (e: any) {
      toast(extractError(e), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async (vol: Volume) => {
    setActionLoading(true);
    try {
      await api.delete(`/api/volumes/${vol.id}`);
      toast('Volume deleted.', 'success');
      fetchVolumes();
    } catch (e: any) {
      toast(extractError(e), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleDetach = async (vol: Volume) => {
    setActionLoading(true);
    try {
      await api.post(`/api/volumes/${vol.id}/detach`);
      toast('Volume detached.', 'success');
      fetchVolumes();
    } catch (e: any) {
      toast(extractError(e), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleAttach = async () => {
    if (!attachModal || !attachTarget) return;
    setActionLoading(true);
    try {
      await api.post(`/api/volumes/${attachModal.id}/attach`, { resource_id: attachTarget });
      setAttachModal(null);
      setAttachTarget('');
      toast('Volume attached.', 'success');
      fetchVolumes();
    } catch (e: any) {
      toast(extractError(e), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleResize = async () => {
    if (!resizeModal) return;
    setActionLoading(true);
    try {
      await api.post(`/api/volumes/${resizeModal.id}/resize`, { size_gib: resizeValue });
      setResizeModal(null);
      toast('Volume resized.', 'success');
      fetchVolumes();
    } catch (e: any) {
      toast(extractError(e), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const columns: Column<Volume>[] = [
    {
      key: 'name',
      header: 'Name',
      render: (row) => (
        <div className="flex items-center gap-2">
          <HardDrive className="h-4 w-4 text-paws-text-dim" />
          <div>
            <span className="font-medium">{row.name}</span>
            {row.proxmox_volid && (
              <p className="text-xs text-paws-text-dim font-mono">{row.proxmox_volid}</p>
            )}
          </div>
        </div>
      ),
    },
    { key: 'size_gib', header: 'Size', render: (row) => <span>{row.size_gib} GiB</span> },
    { key: 'storage_pool', header: 'Pool' },
    { key: 'status', header: 'Status', render: (row) => <StatusBadge status={row.status} /> },
    {
      key: 'display_name',
      header: 'Attached To',
      render: (row) => row.status === 'attached' ? (
        <span className="text-paws-text">
          {row.display_name || 'VM'}{row.disk_slot ? ` (${row.disk_slot})` : ''}
        </span>
      ) : (
        <span className="text-paws-text-dim">Unattached</span>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (row) => (
        <div className="flex items-center gap-1">
          {row.status === 'attached' && (
            <Button variant="ghost" size="sm" onClick={() => setConfirmDetach(row)} title="Detach">
              <Unlink className="h-4 w-4" />
            </Button>
          )}
          {row.status === 'available' && (
            <Button variant="ghost" size="sm" onClick={() => { setAttachModal(row); setAttachTarget(''); }} title="Attach to VM">
              <Link2 className="h-4 w-4" />
            </Button>
          )}
          {row.status === 'attached' && (
            <Button variant="ghost" size="sm" onClick={() => { setResizeModal(row); setResizeValue(row.size_gib + 1); }} title="Resize">
              <ArrowUpCircle className="h-4 w-4" />
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(row)}
            disabled={row.status === 'attached'} title={row.status === 'attached' ? 'Detach first' : 'Delete'}>
            <Trash2 className="h-4 w-4 text-paws-danger" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Volumes</h1>
        <Button onClick={() => { setShowCreate(true); setForm({ name: '', size_gib: 10, storage_pool: defaultPool, resource_id: '' }); }}>
          <Plus className="h-4 w-4 mr-1" /> Create Volume
        </Button>
      </div>

      {volumes.length === 0 && !loading ? (
        <EmptyState
          icon={HardDrive}
          title="No volumes"
          description="Create a volume to add persistent storage to a virtual machine."
          action={{ label: 'Create Volume', onClick: () => setShowCreate(true) }}
        />
      ) : (
        <DataTable columns={columns} data={volumes} loading={loading} />
      )}

      {/* Create Volume Modal */}
      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Volume">
        <div className="space-y-4">
          <Select label="Virtual Machine" value={form.resource_id}
            onChange={(e) => setForm({ ...form, resource_id: e.target.value })}
            options={[
              { value: '', label: 'Select a VM...' },
              ...vms.map((vm) => ({ value: vm.id, label: `${vm.display_name} (VMID ${vm.proxmox_vmid})` })),
            ]} />
          <Input label="Volume Name" value={form.name}
            placeholder="e.g. data-disk, app-storage"
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Input label="Size (GiB)" type="number" min={1} value={form.size_gib}
            onChange={(e) => setForm({ ...form, size_gib: +e.target.value })} />
          <Select label="Storage Pool" value={form.storage_pool}
            onChange={(e) => setForm({ ...form, storage_pool: e.target.value })}
            options={storagePools.map((p) => ({ value: p, label: p }))} />
          <p className="text-xs text-paws-text-dim">
            Creates a new SCSI disk on the selected storage pool and attaches it to the VM.
            The disk can later be detached and moved to another VM.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name || !form.storage_pool || !form.resource_id || actionLoading}>
              {actionLoading ? 'Creating...' : 'Create'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Attach Volume Modal */}
      <Modal open={!!attachModal} onClose={() => setAttachModal(null)} title="Attach Volume">
        <div className="space-y-4">
          <p className="text-sm text-paws-text-dim">
            Attach <strong className="text-paws-text">{attachModal?.name}</strong> ({attachModal?.size_gib} GiB) to a virtual machine.
          </p>
          <Select label="Target VM" value={attachTarget}
            onChange={(e) => setAttachTarget(e.target.value)}
            options={[
              { value: '', label: 'Select a VM...' },
              ...vms.map((vm) => ({ value: vm.id, label: `${vm.display_name} (VMID ${vm.proxmox_vmid})` })),
            ]} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setAttachModal(null)}>Cancel</Button>
            <Button onClick={handleAttach} disabled={!attachTarget || actionLoading}>
              {actionLoading ? 'Attaching...' : 'Attach'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Resize Volume Modal */}
      <Modal open={!!resizeModal} onClose={() => setResizeModal(null)} title="Resize Volume">
        <div className="space-y-4">
          <p className="text-sm text-paws-text-dim">
            Resize <strong className="text-paws-text">{resizeModal?.name}</strong> (currently {resizeModal?.size_gib} GiB).
            Volumes can only grow, not shrink.
          </p>
          <Input label="New Size (GiB)" type="number" min={(resizeModal?.size_gib || 0) + 1}
            value={resizeValue}
            onChange={(e) => setResizeValue(+e.target.value)} />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setResizeModal(null)}>Cancel</Button>
            <Button onClick={handleResize}
              disabled={resizeValue <= (resizeModal?.size_gib || 0) || actionLoading}>
              {actionLoading ? 'Resizing...' : 'Resize'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Confirm Dialogs */}
      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete Volume"
        message={`Delete volume "${confirmDelete?.name}"? The disk and all data will be permanently removed from Proxmox storage.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={() => { if (confirmDelete) handleDelete(confirmDelete); setConfirmDelete(null); }}
        onCancel={() => setConfirmDelete(null)}
      />
      <ConfirmDialog
        open={!!confirmDetach}
        title="Detach Volume"
        message={`Detach "${confirmDetach?.name}" from ${confirmDetach?.display_name || 'the VM'}? The disk will remain on storage and can be re-attached later.`}
        confirmLabel="Detach"
        variant="primary"
        onConfirm={() => { if (confirmDetach) handleDetach(confirmDetach); setConfirmDetach(null); }}
        onCancel={() => setConfirmDetach(null)}
      />
    </div>
  );
}
