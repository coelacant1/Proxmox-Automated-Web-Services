import { forwardRef, type TextareaHTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, className, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');
    return (
      <div className="space-y-1.5">
        {label && (
          <label htmlFor={inputId} className="block text-sm font-medium text-paws-text-muted">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={inputId}
          className={cn(
            'w-full rounded-md border border-paws-border bg-paws-surface px-3 py-2 text-sm text-paws-text',
            'focus:border-paws-primary focus:outline-none focus:ring-1 focus:ring-paws-primary',
            'disabled:cursor-not-allowed disabled:opacity-50',
            'min-h-[80px] resize-y',
            error && 'border-paws-danger',
            className,
          )}
          {...props}
        />
        {error && <p className="text-xs text-paws-danger">{error}</p>}
      </div>
    );
  },
);

Textarea.displayName = 'Textarea';
