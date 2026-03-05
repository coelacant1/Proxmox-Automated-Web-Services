import { cn } from '@/lib/utils';

interface CardProps {
  className?: string;
  children: React.ReactNode;
}

export function Card({ className, children }: CardProps) {
  return (
    <div className={cn('rounded-lg border border-paws-border bg-paws-surface p-6', className)}>
      {children}
    </div>
  );
}

export function CardHeader({ className, children }: CardProps) {
  return (
    <div className={cn('mb-4', className)}>
      {children}
    </div>
  );
}

export function CardTitle({ className, children }: CardProps) {
  return (
    <h3 className={cn('text-lg font-semibold text-paws-text', className)}>
      {children}
    </h3>
  );
}

export function CardDescription({ className, children }: CardProps) {
  return (
    <p className={cn('text-sm text-paws-text-muted', className)}>
      {children}
    </p>
  );
}

export function CardContent({ className, children }: CardProps) {
  return (
    <div className={cn(className)}>
      {children}
    </div>
  );
}
