import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

const variants = {
  primary: 'bg-paws-primary hover:bg-paws-primary-hover text-white',
  danger: 'bg-paws-danger hover:bg-paws-danger-hover text-white hover:shadow-sm',
  outline: 'border border-paws-border bg-transparent hover:bg-paws-surface-hover hover:border-paws-text-muted text-paws-text cursor-pointer',
  ghost: 'bg-transparent hover:bg-paws-surface-hover text-paws-text cursor-pointer',
  success: 'bg-paws-success hover:bg-paws-success/80 text-white',
} as const;

const sizes = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-6 py-3 text-base',
} as const;

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', disabled, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        'inline-flex items-center justify-center rounded-md font-medium transition-all duration-150',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-paws-primary',
        'disabled:opacity-50 disabled:pointer-events-none cursor-pointer',
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled}
      {...props}
    />
  ),
);
Button.displayName = 'Button';

export { Button };
export type { ButtonProps };
