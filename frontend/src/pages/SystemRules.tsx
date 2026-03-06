import { useState, useEffect } from 'react';
import api from '../api/client';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Info, AlertTriangle, ShieldAlert, ChevronDown, ChevronRight } from 'lucide-react';

interface Rule {
  id: string;
  category: string;
  title: string;
  description: string;
  severity: string;
  sort_order: number;
}

const defaultSeverity = { icon: Info, color: 'text-blue-400', bg: 'border-blue-500/30' };

const severityConfig: Record<string, { icon: typeof Info; color: string; bg: string }> = {
  info: { icon: Info, color: 'text-blue-400', bg: 'border-blue-500/30' },
  warning: { icon: AlertTriangle, color: 'text-yellow-400', bg: 'border-yellow-500/30' },
  restriction: { icon: ShieldAlert, color: 'text-red-400', bg: 'border-red-500/30' },
};

export default function SystemRules() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    api.get('/api/system/rules').then(r => setRules(r.data)).catch(() => {});
  }, []);

  const grouped = rules.reduce<Record<string, Rule[]>>((acc, r) => {
    (acc[r.category] = acc[r.category] || []).push(r);
    return acc;
  }, {});

  const toggle = (cat: string) => setCollapsed(c => ({ ...c, [cat]: !c[cat] }));

  if (rules.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-paws-text">System Rules & Restrictions</h1>
        <p className="text-paws-text-muted">No system rules have been configured yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-paws-text">System Rules & Restrictions</h1>
      <p className="text-paws-text-muted text-sm">
        These rules and restrictions apply to all users of this platform.
      </p>

      {Object.entries(grouped).map(([category, items]) => (
        <div key={category}>
          <button
            className="flex items-center gap-2 w-full text-left py-2 hover:bg-paws-card/30 rounded px-2 transition-colors"
            onClick={() => toggle(category)}
          >
            {collapsed[category] ? (
              <ChevronRight className="w-4 h-4 text-paws-text-muted" />
            ) : (
              <ChevronDown className="w-4 h-4 text-paws-text-muted" />
            )}
            <h2 className="text-lg font-semibold text-paws-text">{category}</h2>
            <Badge variant="default" className="ml-2">{items.length}</Badge>
          </button>

          {!collapsed[category] && (
            <div className="space-y-2 ml-6 mt-1">
              {items.map(rule => {
                const cfg = severityConfig[rule.severity] ?? defaultSeverity;
                const Icon = cfg.icon;
                return (
                  <Card key={rule.id} className={`border-l-4 ${cfg.bg}`}>
                    <CardContent>
                      <div className="flex items-start gap-3">
                        <Icon className={`w-5 h-5 mt-0.5 flex-shrink-0 ${cfg.color}`} />
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-paws-text">{rule.title}</span>
                            <Badge variant={rule.severity === 'restriction' ? 'danger' : rule.severity === 'warning' ? 'warning' : 'info'}>
                              {rule.severity}
                            </Badge>
                          </div>
                          <p className="text-sm text-paws-text-muted mt-1 whitespace-pre-wrap">
                            {rule.description}
                          </p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
