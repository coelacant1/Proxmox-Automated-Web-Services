import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

interface TagPillsProps {
  tags: Record<string, string>;
  onRemove?: (key: string) => void;
  className?: string;
}

export function TagPills({ tags, onRemove, className }: TagPillsProps) {
  const entries = Object.entries(tags);
  if (entries.length === 0) return null;

  return (
    <div className={cn('flex flex-wrap gap-1.5', className)}>
      {entries.map(([key, value]) => (
        <span
          key={key}
          className="inline-flex items-center gap-1 rounded-md bg-paws-primary/10 px-2 py-0.5 text-xs text-paws-primary"
        >
          <span className="font-medium">{key}</span>
          <span className="text-paws-primary/60">=</span>
          <span>{value}</span>
          {onRemove && (
            <button
              onClick={() => onRemove(key)}
              className="ml-0.5 rounded hover:bg-paws-primary/20 p-0.5"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      ))}
    </div>
  );
}
