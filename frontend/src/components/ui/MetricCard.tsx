import { cn } from '@/lib/utils';
import { Card } from './Card';
import type { LucideIcon } from 'lucide-react';

interface MetricCardProps {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  change?: string;
  variant?: 'default' | 'success' | 'warning' | 'danger';
  className?: string;
}

const variantColors = {
  default: 'text-paws-primary',
  success: 'text-paws-success',
  warning: 'text-paws-warning',
  danger: 'text-paws-danger',
};

export function MetricCard({ label, value, icon: Icon, change, variant = 'default', className }: MetricCardProps) {
  return (
    <Card className={cn('flex items-start gap-4', className)}>
      {Icon && (
        <div className={cn('rounded-lg bg-paws-surface-hover p-2', variantColors[variant])}>
          <Icon className="h-5 w-5" />
        </div>
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-paws-text-muted">{label}</p>
        <p className="text-2xl font-semibold text-paws-text">{value}</p>
        {change && <p className="text-xs text-paws-text-dim mt-1">{change}</p>}
      </div>
    </Card>
  );
}
