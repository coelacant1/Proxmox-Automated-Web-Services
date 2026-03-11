import { Badge } from './Badge';

const statusVariants: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'default'> = {
  running: 'success',
  online: 'success',
  active: 'success',
  approved: 'success',
  creating: 'info',
  provisioning: 'info',
  pending: 'warning',
  stopped: 'default',
  offline: 'default',
  error: 'danger',
  denied: 'danger',
  destroyed: 'danger',
};

interface StatusBadgeProps {
  status: string;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const variant = statusVariants[status.toLowerCase()] ?? 'default';
  return (
    <Badge variant={variant} className={className}>
      {status}
    </Badge>
  );
}
