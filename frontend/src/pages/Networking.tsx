import { useEffect, useState } from 'react';
import api from '../api/client';
import { Button, Card, DataTable } from '@/components/ui';
import type { Column } from '@/components/ui';

interface FirewallRule {
  type: string;
  action: string;
  proto?: string;
  dport?: string;
  source?: string;
  dest?: string;
  comment?: string;
  enable?: number;
  pos: number;
}

interface VNet {
  vnet: string;
  zone: string;
  alias?: string;
  tag?: number;
}

const firewallColumns: Column<Record<string, unknown>>[] = [
  { key: 'pos', header: '#', className: 'text-paws-text-dim' },
  { key: 'type', header: 'Type' },
  {
    key: 'action', header: 'Action',
    render: (row) => (
      <span className={row.action === 'ACCEPT' ? 'text-paws-success' : 'text-paws-danger'}>
        {String(row.action)}
      </span>
    ),
  },
  { key: 'proto', header: 'Proto', render: (row) => String(row.proto || '-') },
  { key: 'dport', header: 'Port', render: (row) => String(row.dport || '-') },
  { key: 'source', header: 'Source', render: (row) => String(row.source || '-') },
  { key: 'comment', header: 'Comment', className: 'text-paws-text-muted', render: (row) => String(row.comment || '-') },
];

export default function Networking() {
  const [tab, setTab] = useState<'vnets' | 'firewall'>('vnets');
  const [vnets, setVnets] = useState<VNet[]>([]);
  const [rules, setRules] = useState<FirewallRule[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (tab === 'vnets') {
      api.get('/api/networking/vnets').then(r => setVnets(r.data)).catch(() => {}).finally(() => setLoading(false));
    } else {
      api.get('/api/networking/firewall/cluster').then(r => setRules(r.data)).catch(() => {}).finally(() => setLoading(false));
    }
  }, [tab]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-paws-text">Networking</h1>
      <div className="flex gap-2">
        <Button
          variant={tab === 'vnets' ? 'primary' : 'ghost'}
          onClick={() => { setTab('vnets'); setLoading(true); }}
        >
          VNets
        </Button>
        <Button
          variant={tab === 'firewall' ? 'primary' : 'ghost'}
          onClick={() => { setTab('firewall'); setLoading(true); }}
        >
          Firewall
        </Button>
      </div>

      {loading ? <p className="text-paws-text-muted">Loading...</p> : tab === 'vnets' ? (
        vnets.length === 0 ? <p className="text-paws-text-dim">No virtual networks found.</p> : (
          <div className="flex flex-col gap-3">
            {vnets.map((v) => (
              <Card key={v.vnet} className="flex items-center justify-between">
                <div>
                  <p className="font-bold">{v.vnet}</p>
                  <p className="text-xs text-paws-text-muted">
                    Zone: {v.zone}{v.alias ? ` · ${v.alias}` : ''}{v.tag ? ` · Tag ${v.tag}` : ''}
                  </p>
                </div>
              </Card>
            ))}
          </div>
        )
      ) : (
        <DataTable
          columns={firewallColumns}
          data={rules as unknown as Record<string, unknown>[]}
          emptyMessage="No firewall rules found."
        />
      )}
    </div>
  );
}
