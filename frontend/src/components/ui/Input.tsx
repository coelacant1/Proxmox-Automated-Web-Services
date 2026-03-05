import { cn } from '@/lib/utils';
import { forwardRef, type InputHTMLAttributes } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="space-y-1.5">
        {label && (
          <label htmlFor={inputId} className="block text-sm font-medium text-paws-text-muted">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            'w-full rounded-md border bg-paws-surface px-3 py-2 text-sm text-paws-text',
            'placeholder:text-paws-text-dim',
            'focus:outline-none focus:ring-2 focus:ring-paws-primary/50 focus:border-paws-primary',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            error ? 'border-paws-danger' : 'border-paws-border',
            className,
          )}
          {...props}
        />
        {error && <p className="text-xs text-paws-danger">{error}</p>}
      </div>
    );
  },
);
Input.displayName = 'Input';

export { Input };
