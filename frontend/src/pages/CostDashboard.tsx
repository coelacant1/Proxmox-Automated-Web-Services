import { useEffect, useState } from 'react';
import { DollarSign, TrendingUp, RefreshCw, AlertTriangle } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Badge, Tabs,
} from '@/components/ui';
import { MetricCard } from '@/components/ui';

interface CostSummary {
  total_monthly: number;
  total_daily: number;
  credits_remaining: number;
  usage_percent: number;
  threshold_warning?: string;
}

interface ResourceCost {
  resource_id: string;
  resource_name: string;
  resource_type: string;
  daily_cost: number;
  monthly_cost: number;
  [key: string]: unknown;
}

interface CostRate {
  resource: string;
  unit: string;
  rate_per_hour: number;
}

export default function CostDashboard() {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [breakdown, setBreakdown] = useState<ResourceCost[]>([]);
  const [rates, setRates] = useState<CostRate[]>([]);
  const [tab, setTab] = useState('overview');
  const [loading, setLoading] = useState(true);

  const fetchData = () => {
    setLoading(true);
    Promise.all([
      api.get('/api/billing/quota-status').catch(() => ({ data: {} })),
      api.get('/api/billing/summary').catch(() => ({ data: { breakdown: [] } })),
      api.get('/api/billing/rates').catch(() => ({ data: [] })),
    ]).then(([quotaRes, summaryRes, ratesRes]) => {
      const q = quotaRes.data;
      setSummary({
        total_monthly: q.cost_this_month || summaryRes.data.total || 0,
        total_daily: summaryRes.data.daily_estimate || 0,
        credits_remaining: (q.monthly_credits || 0) - (q.cost_this_month || 0),
        usage_percent: q.usage_percent || 0,
        threshold_warning: q.warning,
      });
      setBreakdown(summaryRes.data.breakdown || []);
      setRates(ratesRes.data.rates || ratesRes.data || []);
      setLoading(false);
    });
  };

  useEffect(fetchData, []);

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'breakdown', label: 'Breakdown', count: breakdown.length },
    { id: 'rates', label: 'Pricing' },
  ];

  const usageColor = (pct: number) =>
    pct >= 100 ? 'text-paws-danger' : pct >= 80 ? 'text-paws-warning' : 'text-paws-success';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Cost Dashboard</h1>
        <Button variant="outline" size="sm" onClick={fetchData} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {summary?.threshold_warning && (
        <div className="flex items-center gap-2 bg-paws-warning/10 border border-paws-warning/30 rounded-md px-4 py-2.5 mb-4">
          <AlertTriangle className="h-4 w-4 text-paws-warning" />
          <span className="text-sm text-paws-warning">{summary.threshold_warning}</span>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <MetricCard label="Monthly Cost" value={`$${(summary?.total_monthly || 0).toFixed(2)}`} icon={DollarSign} />
        <MetricCard label="Daily Rate" value={`$${(summary?.total_daily || 0).toFixed(2)}`} icon={TrendingUp} />
        <MetricCard label="Credits Left" value={`$${(summary?.credits_remaining || 0).toFixed(2)}`} icon={DollarSign}
          variant={summary && summary.credits_remaining <= 0 ? 'danger' : 'default'} />
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-paws-text-dim mb-1">Usage</p>
            <p className={`text-2xl font-bold ${usageColor(summary?.usage_percent || 0)}`}>
              {(summary?.usage_percent || 0).toFixed(0)}%
            </p>
            <div className="w-full bg-paws-surface-hover rounded-full h-1.5 mt-2">
              <div
                className={`h-1.5 rounded-full transition-all ${
                  (summary?.usage_percent || 0) >= 100 ? 'bg-paws-danger' : (summary?.usage_percent || 0) >= 80 ? 'bg-paws-warning' : 'bg-paws-success'
                }`}
                style={{ width: `${Math.min(summary?.usage_percent || 0, 100)}%` }}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} className="mb-4" />

      {/* Overview */}
      {tab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader><CardTitle>Cost Trend</CardTitle></CardHeader>
            <CardContent className="h-48 flex items-center justify-center text-paws-text-dim text-sm">
              Cost trend chart placeholder
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Top Resources by Cost</CardTitle></CardHeader>
            <CardContent>
              {breakdown.length === 0 ? (
                <p className="text-sm text-paws-text-dim">No resource costs recorded.</p>
              ) : (
                <div className="space-y-2">
                  {breakdown.slice(0, 5).map((r) => (
                    <div key={r.resource_id} className="flex items-center justify-between py-1.5">
                      <div className="flex items-center gap-2">
                        <Badge variant="default">{r.resource_type}</Badge>
                        <span className="text-sm text-paws-text">{r.resource_name}</span>
                      </div>
                      <span className="text-sm font-mono text-paws-text">${r.monthly_cost.toFixed(2)}/mo</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Breakdown */}
      {tab === 'breakdown' && (
        <Card>
          <CardHeader><CardTitle>All Resource Costs</CardTitle></CardHeader>
          <CardContent className="p-0">
            {breakdown.length === 0 ? (
              <p className="text-sm text-paws-text-dim p-4">No costs to display.</p>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-paws-border text-xs text-paws-text-dim">
                    <th className="text-left px-4 py-2">Resource</th>
                    <th className="text-left px-4 py-2">Type</th>
                    <th className="text-right px-4 py-2">Daily</th>
                    <th className="text-right px-4 py-2">Monthly</th>
                  </tr>
                </thead>
                <tbody>
                  {breakdown.map((r) => (
                    <tr key={r.resource_id} className="border-b border-paws-border-subtle hover:bg-paws-surface-hover">
                      <td className="px-4 py-2.5 text-sm text-paws-text">{r.resource_name}</td>
                      <td className="px-4 py-2.5"><Badge variant="default">{r.resource_type}</Badge></td>
                      <td className="px-4 py-2.5 text-right text-sm font-mono text-paws-text">${r.daily_cost.toFixed(2)}</td>
                      <td className="px-4 py-2.5 text-right text-sm font-mono text-paws-text font-medium">${r.monthly_cost.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Pricing */}
      {tab === 'rates' && (
        <Card>
          <CardHeader><CardTitle>Resource Pricing</CardTitle></CardHeader>
          <CardContent className="p-0">
            <table className="w-full">
              <thead>
                <tr className="border-b border-paws-border text-xs text-paws-text-dim">
                  <th className="text-left px-4 py-2">Resource</th>
                  <th className="text-left px-4 py-2">Unit</th>
                  <th className="text-right px-4 py-2">Rate/hr</th>
                  <th className="text-right px-4 py-2">Rate/mo (est)</th>
                </tr>
              </thead>
              <tbody>
                {rates.map((r, i) => (
                  <tr key={i} className="border-b border-paws-border-subtle">
                    <td className="px-4 py-2.5 text-sm text-paws-text">{r.resource}</td>
                    <td className="px-4 py-2.5 text-sm text-paws-text-dim">{r.unit}</td>
                    <td className="px-4 py-2.5 text-right text-sm font-mono text-paws-text">${r.rate_per_hour.toFixed(4)}</td>
                    <td className="px-4 py-2.5 text-right text-sm font-mono text-paws-text">${(r.rate_per_hour * 730).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
