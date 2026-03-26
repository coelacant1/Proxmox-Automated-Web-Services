import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface LoadingSpinnerProps {
  message?: string;
  className?: string;
  size?: 'sm' | 'md' | 'lg';
  inline?: boolean;
}

const sizes = {
  sm: 'h-5 w-5',
  md: 'h-8 w-8',
  lg: 'h-12 w-12',
};

export function LoadingSpinner({
  message = 'Loading...',
  className,
  size = 'md',
  inline = false,
}: LoadingSpinnerProps) {
  if (inline) {
    return (
      <span className={cn('inline-flex items-center gap-2 text-paws-text-muted', className)}>
        <Loader2 className={cn(sizes[size], 'animate-spin')} />
        {message && <span className="text-sm">{message}</span>}
      </span>
    );
  }

  return (
    <div className={cn('flex flex-col items-center justify-center py-12', className)}>
      <Loader2 className={cn(sizes[size], 'text-paws-text-muted animate-spin mb-3')} />
      {message && <p className="text-paws-text-muted text-sm">{message}</p>}
    </div>
  );
}
