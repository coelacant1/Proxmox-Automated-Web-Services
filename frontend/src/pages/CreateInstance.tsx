import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Check, Server } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardContent, Input, Select,
  Badge,
} from '@/components/ui';
import { cn } from '@/lib/utils';

interface Template {
  id: string;
  name: string;
  os_type: string;
  category: string;
  min_cpu: number;
  min_ram_mb: number;
  min_disk_gb: number;
  proxmox_vmid: number;
  cluster_id?: string;
}

interface InstanceType {
  id: string;
  name: string;
  vcpus: number;
  ram_mib: number;
  disk_gib: number;
  category: string;
  description: string | null;
}

const STEPS = ['Template', 'Size', 'Network', 'Configuration', 'Review'];

export default function CreateInstance() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [step, setStep] = useState(0);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [instanceTypes, setInstanceTypes] = useState<InstanceType[]>([]);
  const [vpcs, setVpcs] = useState<Array<{ id: string; name: string; cidr: string }>>([]);
  const [sshKeys, setSshKeys] = useState<Array<{ id: string; name: string }>>([]);
  const [storagePools, setStoragePools] = useState<string[]>([]);
  const [clusters, setClusters] = useState<Array<{ name: string }>>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const [templateFilter, setTemplateFilter] = useState<'all' | 'vm' | 'lxc'>('all');

  // Form state
  const [form, setForm] = useState({
    name: '',
    template_vmid: 0,
    selectedTemplate: null as Template | null,
    instance_type: '',
    cluster_id: '',
    cores: 2,
    memory_mb: 2048,
    disk_gb: 32,
    storage: 'local-lvm',
    vpc_id: '',
    network_mode: 'private',
    hostname: '',
    ssh_key_ids: [] as string[],
    ci_user: '',
    ci_password: '',
    dns_server: '',
    dns_domain: '',
  });

  useEffect(() => {
    const templateVmid = searchParams.get('template');

    api.get('/api/templates/').then((res) => {
      setTemplates(res.data);
      // Auto-select template from URL query param
      if (templateVmid) {
        const match = res.data.find((t: Template) => String(t.proxmox_vmid) === templateVmid);
        if (match) {
          setForm((prev) => ({
            ...prev,
            template_vmid: match.proxmox_vmid,
            selectedTemplate: match,
            cores: Math.max(prev.cores, match.min_cpu),
            memory_mb: Math.max(prev.memory_mb, match.min_ram_mb),
            disk_gb: Math.max(prev.disk_gb, match.min_disk_gb),
          }));
          setStep(1);
        }
      }
    }).catch(() => {});

    api.get('/api/instance-types/').then((res) => setInstanceTypes(res.data)).catch(() => {});
    api.get('/api/vpcs/').then((res) => {
      const data = res.data.items ?? res.data;
      setVpcs(data);
    }).catch(() => {});
    api.get('/api/ssh-keys/').then((res) => setSshKeys(res.data)).catch(() => {});
    api.get('/api/cluster/list').then((res) => {
      setClusters(res.data);
      if (res.data.length === 1) {
        setForm((prev) => ({ ...prev, cluster_id: res.data[0].name }));
      }
    }).catch(() => {});
    api.get('/api/storage-pools/').then((res) => {
      setStoragePools(res.data.pools || []);
      if (res.data.default) {
        setForm((prev) => ({ ...prev, storage: res.data.default }));
      }
    }).catch(() => {});
  }, []);

  const selectTemplate = (t: Template) => {
    setForm({
      ...form,
      template_vmid: t.proxmox_vmid,
      selectedTemplate: t,
      cores: Math.max(form.cores, t.min_cpu),
      memory_mb: Math.max(form.memory_mb, t.min_ram_mb),
      disk_gb: Math.max(form.disk_gb, t.min_disk_gb),
    });
  };

  const selectInstanceType = (it: InstanceType) => {
    setForm({
      ...form,
      instance_type: it.name,
      cores: it.vcpus,
      memory_mb: it.ram_mib,
      disk_gb: it.disk_gib,
    });
  };

  const canProceed = () => {
    if (step === 0) return form.template_vmid > 0;
    if (step === 1) return form.cores > 0 && form.memory_mb > 0 && form.disk_gb > 0;
    if (step === 3) return form.name.length > 0;
    return true;
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError('');
    try {
      const isLxc = form.selectedTemplate?.category === 'lxc';
      const payload = {
        name: form.name,
        template_vmid: form.template_vmid,
        cores: form.cores,
        memory_mb: form.memory_mb,
        disk_gb: form.disk_gb,
        storage: form.storage,
        cluster_id: form.cluster_id || undefined,
        vpc_id: form.vpc_id || undefined,
        network_mode: form.network_mode,
        hostname: form.hostname || undefined,
        ssh_key_ids: form.ssh_key_ids.length > 0 ? form.ssh_key_ids : undefined,
        ci_user: form.ci_user || undefined,
        ci_password: form.ci_password || undefined,
        dns_server: form.dns_server || undefined,
        dns_domain: form.dns_domain || undefined,
        instance_type: form.instance_type || undefined,
      };
      await api.post('/api/compute/vms', payload);
      navigate(isLxc ? '/containers' : '/vms');
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to create instance';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <button onClick={() => navigate(-1)} className="p-1 rounded hover:bg-paws-surface-hover text-paws-text-dim">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <h1 className="text-2xl font-bold text-paws-text">Create Instance</h1>
      </div>

      {/* Step indicators */}
      <div className="flex items-center gap-2 mb-8">
        {STEPS.map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <div
              className={cn(
                'flex items-center justify-center h-7 w-7 rounded-full text-xs font-medium transition-colors',
                i < step ? 'bg-paws-success text-white' :
                i === step ? 'bg-paws-primary text-white' :
                'bg-paws-surface-hover text-paws-text-dim',
              )}
            >
              {i < step ? <Check className="h-3.5 w-3.5" /> : i + 1}
            </div>
            <span className={cn('text-sm', i === step ? 'text-paws-text font-medium' : 'text-paws-text-dim')}>
              {s}
            </span>
            {i < STEPS.length - 1 && <div className="w-8 h-px bg-paws-border" />}
          </div>
        ))}
      </div>

      {/* Step 0: Template */}
      {step === 0 && (
        <div>
          <div className="flex gap-2 mb-4">
            {(['all', 'vm', 'lxc'] as const).map((f) => (
              <Button key={f} size="sm" variant={templateFilter === f ? 'primary' : 'outline'} onClick={() => setTemplateFilter(f)}>
                {f === 'all' ? 'All' : f === 'vm' ? 'Virtual Machines' : 'Containers'}
              </Button>
            ))}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {templates.filter((t) => templateFilter === 'all' || t.category === templateFilter).map((t) => (
            <div
              key={t.id}
              className={cn(
                'cursor-pointer transition-colors rounded-lg',
                form.template_vmid === t.proxmox_vmid
                  ? 'ring-2 ring-paws-primary border-paws-primary'
                  : 'hover:border-paws-text-dim',
              )}
              onClick={() => selectTemplate(t)}
            >
              <Card>
              <CardContent className="flex items-center gap-3 py-3">
                <Server className="h-8 w-8 text-paws-primary shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-paws-text">{t.name}</p>
                  <p className="text-xs text-paws-text-muted">{t.os_type} · Min: {t.min_cpu}c / {t.min_ram_mb}MB / {t.min_disk_gb}GB</p>
                </div>
              <Badge variant="default">{t.category}</Badge>
              </CardContent>
            </Card>
            </div>
          ))}
          {templates.length === 0 && (
            <p className="col-span-2 text-center text-paws-text-dim py-8">No templates available. Ask an admin to create templates.</p>
          )}
          </div>
        </div>
      )}

      {/* Step 1: Size */}
      {step === 1 && (
        <div className="space-y-6">
          {instanceTypes.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-paws-text-muted mb-3">Instance Types</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {instanceTypes.map((it) => (
                  <div
                    key={it.id}
                    className={cn(
                      'cursor-pointer transition-colors py-2 rounded-lg',
                      form.instance_type === it.name ? 'ring-2 ring-paws-primary' : 'hover:border-paws-text-dim',
                    )}
                    onClick={() => selectInstanceType(it)}
                  >
                    <Card>
                    <CardContent className="py-1">
                      <p className="font-medium text-paws-text text-sm">{it.name}</p>
                      <p className="text-xs text-paws-text-dim">{it.vcpus} vCPU · {it.ram_mib} MiB · {it.disk_gib} GiB</p>
                    </CardContent>
                    </Card>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="grid grid-cols-3 gap-4">
            <Input label="CPU Cores" type="number" min={1} max={32} value={form.cores}
              onChange={(e) => setForm({ ...form, cores: +e.target.value })} />
            <Input label="Memory (MB)" type="number" min={256} step={256} value={form.memory_mb}
              onChange={(e) => setForm({ ...form, memory_mb: +e.target.value })} />
            <Input label="Disk (GB)" type="number" min={8} value={form.disk_gb}
              onChange={(e) => setForm({ ...form, disk_gb: +e.target.value })} />
          </div>
          <Select
            label="Storage Pool"
            options={storagePools.length > 0
              ? storagePools.map((p) => ({ value: p, label: p }))
              : [{ value: form.storage, label: form.storage }]}
            value={form.storage}
            onChange={(e) => setForm({ ...form, storage: e.target.value })}
          />
        </div>
      )}

      {/* Step 2: Network */}
      {step === 2 && (
        <div className="space-y-4">
          <Select
            label="VPC"
            placeholder="Select a VPC (optional)"
            options={[{ value: '', label: 'No VPC' }, ...vpcs.map((v) => ({ value: v.id, label: `${v.name} (${v.cidr})` }))]}
            value={form.vpc_id}
            onChange={(e) => setForm({ ...form, vpc_id: e.target.value })}
          />
          <Select
            label="Network Mode"
            options={[
              { value: 'private', label: 'Private - Full LAN + Internet access' },
              { value: 'published', label: 'Published - Internet only, LAN blocked (for public services)' },
              { value: 'isolated', label: 'Isolated - Own subnet only (airgapped)' },
            ]}
            value={form.network_mode}
            onChange={(e) => setForm({ ...form, network_mode: e.target.value })}
          />
          {form.vpc_id && (
            <p className="text-xs text-paws-text-dim">IP address will be automatically allocated from the VPC subnet.</p>
          )}
        </div>
      )}

      {/* Step 3: Configuration */}
      {step === 3 && (
        <div className="space-y-4">
          <Input label="Instance Name" value={form.name} placeholder="my-instance"
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          {clusters.length > 1 && (
            <Select label="Cluster" value={form.cluster_id}
              options={clusters.map((c) => ({ value: c.name, label: c.name }))}
              onChange={(e) => setForm({ ...form, cluster_id: e.target.value })} />
          )}
          <Input label="Hostname" value={form.hostname} placeholder="Optional hostname"
            onChange={(e) => setForm({ ...form, hostname: e.target.value })} />
          <div className="grid grid-cols-2 gap-4">
            <Input label="Username" value={form.ci_user} placeholder="paws (default)"
              onChange={(e) => setForm({ ...form, ci_user: e.target.value })} />
            <Input label="Password" type="password" value={form.ci_password} placeholder="Optional"
              onChange={(e) => setForm({ ...form, ci_password: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Input label="DNS Server" value={form.dns_server} placeholder="1.1.1.1 (default)"
              onChange={(e) => setForm({ ...form, dns_server: e.target.value })} />
            <Input label="DNS Domain" value={form.dns_domain} placeholder="Optional"
              onChange={(e) => setForm({ ...form, dns_domain: e.target.value })} />
          </div>
          {sshKeys.length > 0 ? (
            <div>
              <label className="block text-sm font-medium text-paws-text-muted mb-1.5">SSH Keys</label>
              <div className="space-y-1">
                {sshKeys.map((k) => (
                  <label key={k.id} className="flex items-center gap-2 text-sm text-paws-text cursor-pointer">
                    <input type="checkbox" checked={form.ssh_key_ids.includes(k.id)}
                      onChange={(e) => {
                        const ids = e.target.checked
                          ? [...form.ssh_key_ids, k.id]
                          : form.ssh_key_ids.filter((x) => x !== k.id);
                        setForm({ ...form, ssh_key_ids: ids });
                      }}
                      className="rounded border-paws-border"
                    />
                    {k.name}
                  </label>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-paws-text-dim">No SSH keys added. <a href="/ssh-keys" className="text-paws-primary hover:underline">Add SSH keys</a> to inject them into instances.</p>
          )}
        </div>
      )}

      {/* Step 4: Review */}
      {step === 4 && (
        <Card>
          <CardContent className="space-y-3">
            <ReviewRow label="Template" value={form.selectedTemplate?.name || '-'} />
            <ReviewRow label="Name" value={form.name} />
            {clusters.length > 1 && <ReviewRow label="Cluster" value={form.cluster_id || 'Default'} />}
            <ReviewRow label="Size" value={`${form.cores} vCPU · ${form.memory_mb} MB RAM · ${form.disk_gb} GB Disk`} />
            <ReviewRow label="Storage" value={form.storage} />
            <ReviewRow label="VPC" value={vpcs.find((v) => v.id === form.vpc_id)?.name || 'None'} />
            <ReviewRow label="Network Mode" value={form.network_mode.charAt(0).toUpperCase() + form.network_mode.slice(1)} />
            <ReviewRow label="Hostname" value={form.hostname || '-'} />
            <ReviewRow label="Username" value={form.ci_user || 'paws (default)'} />
            <ReviewRow label="Password" value={form.ci_password ? '***' : 'Not set'} />
            <ReviewRow label="DNS" value={form.dns_server || '1.1.1.1 (default)'} />
            <ReviewRow label="SSH Keys" value={form.ssh_key_ids.length > 0 ? `${form.ssh_key_ids.length} selected` : 'None'} />
          </CardContent>
        </Card>
      )}

      {/* Error display */}
      {error && (
        <div className="mt-4 p-3 rounded-lg bg-red-900/30 border border-paws-danger text-paws-danger text-sm">
          {error}
        </div>
      )}

      {/* Navigation */}
      <div className="flex justify-between mt-8">
        <Button variant="outline" onClick={() => setStep(step - 1)} disabled={step === 0}>
          <ArrowLeft className="h-4 w-4 mr-1" /> Back
        </Button>
        {step < STEPS.length - 1 ? (
          <Button onClick={() => setStep(step + 1)} disabled={!canProceed()}>
            Next <ArrowRight className="h-4 w-4 ml-1" />
          </Button>
        ) : (
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Creating...' : 'Create Instance'}
          </Button>
        )}
      </div>
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-2 border-b border-paws-border-subtle last:border-0">
      <span className="text-sm text-paws-text-muted">{label}</span>
      <span className="text-sm font-medium text-paws-text">{value}</span>
    </div>
  );
}
