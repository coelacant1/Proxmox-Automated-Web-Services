import { useEffect, useState } from 'react';
import { ChevronRight, Copy, Check } from 'lucide-react';
import api from '../api/client';
import {
  Card, CardContent,
  Badge, Input,
} from '@/components/ui';

interface APIEndpoint {
  method: string;
  path: string;
  summary: string;
  tag: string;
  auth_required: boolean;
  admin_only: boolean;
}

const METHOD_COLORS: Record<string, string> = {
  GET: 'bg-paws-success/20 text-paws-success',
  POST: 'bg-paws-primary/20 text-paws-primary',
  PUT: 'bg-paws-warning/20 text-paws-warning',
  PATCH: 'bg-paws-info/20 text-paws-info',
  DELETE: 'bg-paws-danger/20 text-paws-danger',
};

export default function APIDocs() {
  const [endpoints, setEndpoints] = useState<APIEndpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [expandedTag, setExpandedTag] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    api.get('/openapi.json')
      .then((res) => {
        const paths = res.data.paths || {};
        const eps: APIEndpoint[] = [];
        Object.entries(paths).forEach(([path, methods]: [string, unknown]) => {
          Object.entries(methods as Record<string, unknown>).forEach(([method, info]: [string, unknown]) => {
            const i = info as Record<string, unknown>;
            eps.push({
              method: method.toUpperCase(),
              path,
              summary: String(i.summary || ''),
              tag: ((i.tags as string[]) || ['Other'])[0] || 'Other',
              auth_required: !!i.security,
              admin_only: String(i.summary || '').toLowerCase().includes('admin'),
            });
          });
        });
        setEndpoints(eps);
      })
      .catch(() => {
        // Fallback: show static API sections
        setEndpoints([
          { method: 'POST', path: '/api/auth/register', summary: 'Register new account', tag: 'Auth', auth_required: false, admin_only: false },
          { method: 'POST', path: '/api/auth/login', summary: 'Login', tag: 'Auth', auth_required: false, admin_only: false },
          { method: 'GET', path: '/api/compute/vms/', summary: 'List VMs', tag: 'Compute', auth_required: true, admin_only: false },
          { method: 'POST', path: '/api/compute/vms/', summary: 'Create VM', tag: 'Compute', auth_required: true, admin_only: false },
          { method: 'GET', path: '/api/storage/buckets', summary: 'List buckets', tag: 'Storage', auth_required: true, admin_only: false },
          { method: 'GET', path: '/api/vpcs/', summary: 'List VPCs', tag: 'Networking', auth_required: true, admin_only: false },
          { method: 'GET', path: '/api/backups/', summary: 'List backups', tag: 'Backups', auth_required: true, admin_only: false },
          { method: 'GET', path: '/api/monitoring/alarms/', summary: 'List alarms', tag: 'Monitoring', auth_required: true, admin_only: false },
          { method: 'GET', path: '/api/health/', summary: 'Health check', tag: 'System', auth_required: false, admin_only: false },
        ]);
      })
      .finally(() => setLoading(false));
  }, []);

  const filtered = endpoints.filter(
    (ep) =>
      !search ||
      ep.path.toLowerCase().includes(search.toLowerCase()) ||
      ep.summary.toLowerCase().includes(search.toLowerCase()),
  );

  const tags = [...new Set(filtered.map((ep) => ep.tag))].sort();

  const copyPath = (path: string) => {
    navigator.clipboard.writeText(path);
    setCopied(path);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-paws-text">API Documentation</h1>
        <p className="text-sm text-paws-text-muted mt-1">{endpoints.length} endpoints across {tags.length} categories</p>
      </div>

      <div className="max-w-sm mb-4">
        <Input placeholder="Search endpoints..." value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {loading ? (
        <p className="text-paws-text-muted">Loading...</p>
      ) : (
        <div className="space-y-2">
          {tags.map((tag) => {
            const tagEndpoints = filtered.filter((ep) => ep.tag === tag);
            const isExpanded = expandedTag === tag;
            return (
              <Card key={tag}>
                <button
                  className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-paws-surface-hover rounded-t-lg"
                  onClick={() => setExpandedTag(isExpanded ? null : tag)}
                >
                  <div className="flex items-center gap-2">
                    <ChevronRight className={`h-4 w-4 text-paws-text-dim transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                    <span className="font-medium text-paws-text">{tag}</span>
                    <Badge variant="default">{tagEndpoints.length}</Badge>
                  </div>
                </button>
                {isExpanded && (
                  <CardContent className="pt-0 border-t border-paws-border-subtle">
                    <div className="space-y-1">
                      {tagEndpoints.map((ep, i) => (
                        <div key={i} className="flex items-center gap-3 py-2 border-b border-paws-border-subtle last:border-0 group">
                          <span className={`text-xs font-bold px-2 py-0.5 rounded font-mono ${METHOD_COLORS[ep.method] || 'bg-paws-surface-hover text-paws-text-dim'}`}>
                            {ep.method}
                          </span>
                          <code className="text-sm font-mono text-paws-text flex-1">{ep.path}</code>
                          <span className="text-xs text-paws-text-dim">{ep.summary}</span>
                          {ep.admin_only && <Badge variant="warning">Admin</Badge>}
                          <button
                            onClick={() => copyPath(ep.path)}
                            className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-paws-surface-hover text-paws-text-dim"
                          >
                            {copied === ep.path ? <Check className="h-3.5 w-3.5 text-paws-success" /> : <Copy className="h-3.5 w-3.5" />}
                          </button>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
