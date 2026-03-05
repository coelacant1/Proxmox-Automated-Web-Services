import { cn } from '@/lib/utils';
import type { LucideIcon } from 'lucide-react';
import { Button } from './Button';

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
  className?: string;
}

export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-16 text-center', className)}>
      {Icon && (
        <div className="mb-4 rounded-full bg-paws-surface-hover p-4">
          <Icon className="h-8 w-8 text-paws-text-dim" />
        </div>
      )}
      <h3 className="text-lg font-medium text-paws-text">{title}</h3>
      {description && <p className="mt-1.5 max-w-sm text-sm text-paws-text-muted">{description}</p>}
      {action && (
        <Button className="mt-4" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}
