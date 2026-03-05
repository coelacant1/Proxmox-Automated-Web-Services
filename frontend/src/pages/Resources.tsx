import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Server, Box, HardDrive, Network as NetworkIcon } from 'lucide-react';
import api from '../api/client';
import { DataTable, Input, StatusBadge, Select, Badge, type Column } from '@/components/ui';

interface ResourceItem {
  id: string;
  display_name: string;
  resource_type: string;
  status: string;
  specs: Record<string, unknown>;
  created_at: string;
  [key: string]: unknown;
}

const typeIcons: Record<string, React.ReactNode> = {
  vm: <Server className="h-4 w-4" />,
  lxc: <Box className="h-4 w-4" />,
  bucket: <HardDrive className="h-4 w-4" />,
};

const typeOptions = [
  { value: '', label: 'All Types' },
  { value: 'vm', label: 'Virtual Machines' },
  { value: 'lxc', label: 'Containers' },
  { value: 'bucket', label: 'Storage Buckets' },
];

const statusOptions = [
  { value: '', label: 'All Statuses' },
  { value: 'running', label: 'Running' },
  { value: 'stopped', label: 'Stopped' },
  { value: 'creating', label: 'Creating' },
  { value: 'error', label: 'Error' },
];

export default function Resources() {
  const [resources, setResources] = useState<ResourceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    api.get('/api/resources/')
      .then((res) => setResources(res.data.items || res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = resources.filter((r) => {
    if (search && !r.display_name.toLowerCase().includes(search.toLowerCase())) return false;
    if (typeFilter && r.resource_type !== typeFilter) return false;
    if (statusFilter && r.status !== statusFilter) return false;
    return true;
  });

  const columns: Column<ResourceItem>[] = [
    {
      key: 'display_name',
      header: 'Name',
      render: (row) => (
        <div className="flex items-center gap-2">
          <span className="text-paws-text-dim">{typeIcons[row.resource_type] || <NetworkIcon className="h-4 w-4" />}</span>
          <span className="font-medium">{row.display_name}</span>
        </div>
      ),
    },
    {
      key: 'resource_type',
      header: 'Type',
      render: (row) => <Badge variant="default">{row.resource_type.toUpperCase()}</Badge>,
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: 'created_at',
      header: 'Created',
      render: (row) => (
        <span className="text-paws-text-dim text-xs">
          {new Date(row.created_at).toLocaleDateString()}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-paws-text">All Resources</h1>
          <p className="text-sm text-paws-text-muted mt-1">{filtered.length} resources</p>
        </div>
      </div>

      <div className="flex gap-3 mb-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-paws-text-dim" />
          <Input
            placeholder="Search resources..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select
          options={typeOptions}
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="w-44"
        />
        <Select
          options={statusOptions}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="w-44"
        />
      </div>

      <DataTable
        columns={columns}
        data={filtered}
        loading={loading}
        emptyMessage="No resources found"
        onRowClick={(row) => {
          if (row.resource_type === 'vm') navigate(`/vms/${row.id}`);
          else if (row.resource_type === 'lxc') navigate(`/containers/${row.id}`);
          else navigate(`/resources/${row.id}`);
        }}
      />
    </div>
  );
}
