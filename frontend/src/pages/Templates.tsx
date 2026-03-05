import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';

interface Template {
  id: string; proxmox_vmid: number; name: string; description: string | null;
  os_type: string | null; category: string; min_cpu: number; min_ram_mb: number;
  min_disk_gb: number; icon_url: string | null; is_active: boolean;
  tags: string[] | null; created_at: string;
}

const osIcons: Record<string, string> = {
  linux: '🐧', windows: '🪟', bsd: '😈', other: '💻',
};

export default function Templates() {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [filter, setFilter] = useState<string>('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const params = filter ? `?category=${filter}` : '';
    api.get(`/api/templates/${params}`)
      .then(r => setTemplates(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [filter]);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-paws-text">Template Catalog</h1>
        <div className="flex gap-2">
          {['', 'vm', 'lxc'].map(cat => (
            <Button
              key={cat}
              size="sm"
              variant={filter === cat ? 'primary' : 'ghost'}
              onClick={() => setFilter(cat)}
            >
              {cat === '' ? 'All' : cat.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>

      {loading ? <p className="text-paws-text-muted">Loading...</p> : templates.length === 0 ? (
        <p className="text-paws-text-dim">No templates available. Ask your administrator to configure templates.</p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-4">
          {templates.map(t => (
            <div key={t.id} onClick={() => navigate(`/create-instance?template=${t.proxmox_vmid}&name=${encodeURIComponent(t.name)}&category=${t.category}`)}>
            <Card className="cursor-pointer transition-transform duration-150 hover:scale-[1.02]">
              <div className="flex items-center gap-3 mb-3">
                <span className="text-3xl">{osIcons[t.os_type || 'other'] || osIcons.other}</span>
                <div>
                  <p className="font-bold text-base text-paws-text">{t.name}</p>
                  <Badge variant={t.category === 'vm' ? 'info' : 'primary'}>
                    {t.category.toUpperCase()}
                  </Badge>
                </div>
              </div>
              {t.description && (
                <p className="text-paws-text-muted text-sm mb-3 leading-snug">
                  {t.description}
                </p>
              )}
              <div className="text-paws-text-dim text-xs flex gap-4">
                <span>≥ {t.min_cpu} CPU</span>
                <span>≥ {t.min_ram_mb} MB</span>
                <span>≥ {t.min_disk_gb} GB</span>
              </div>
              {t.tags && t.tags.length > 0 && (
                <div className="mt-2 flex gap-1 flex-wrap">
                  {t.tags.map(tag => (
                    <Badge key={tag} variant="default">{tag}</Badge>
                  ))}
                </div>
              )}
            </Card>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
