import { cn } from '@/lib/utils';

interface QuotaBarProps {
  label: string;
  used: number;
  limit: number;
  unit?: string;
  className?: string;
}

function getBarColor(ratio: number) {
  if (ratio >= 0.9) return 'bg-paws-danger';
  if (ratio >= 0.7) return 'bg-paws-warning';
  return 'bg-paws-primary';
}

export function QuotaBar({ label, used, limit, unit = '', className }: QuotaBarProps) {
  const ratio = limit > 0 ? used / limit : 0;
  const percent = Math.min(ratio * 100, 100);

  return (
    <div className={cn('space-y-1', className)}>
      <div className="flex items-center justify-between text-sm">
        <span className="text-paws-text-muted">{label}</span>
        <span className="text-paws-text font-medium">
          {used}{unit} / {limit}{unit}
        </span>
      </div>
      <div className="h-2 rounded-full bg-paws-surface-hover overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all', getBarColor(ratio))}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
