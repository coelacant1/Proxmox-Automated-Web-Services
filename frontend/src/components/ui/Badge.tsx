import { cn } from '@/lib/utils';

const variants = {
  default: 'bg-paws-surface-hover text-paws-text',
  success: 'bg-paws-success/20 text-paws-success',
  warning: 'bg-paws-warning/20 text-paws-warning',
  danger: 'bg-paws-danger/20 text-paws-danger',
  info: 'bg-paws-info/20 text-paws-info',
  primary: 'bg-paws-primary/20 text-paws-primary',
} as const;

interface BadgeProps {
  variant?: keyof typeof variants;
  className?: string;
  children: React.ReactNode;
}

export function Badge({ variant = 'default', className, children }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
        variants[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
