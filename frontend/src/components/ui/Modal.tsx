import { cn } from '@/lib/utils';
import { X } from 'lucide-react';
import { useEffect, useRef } from 'react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

const sizeClasses = {
  sm: 'max-w-md',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
};

export function Modal({ open, onClose, title, description, children, className, size = 'md' }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (open) document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => e.target === overlayRef.current && onClose()}
    >
      <div
        className={cn(
          'w-full rounded-lg border border-paws-border bg-paws-bg shadow-xl',
          sizeClasses[size],
          'animate-in fade-in-0 zoom-in-95',
          className,
        )}
      >
        <div className="flex items-center justify-between border-b border-paws-border px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-paws-text">{title}</h2>
            {description && <p className="mt-0.5 text-sm text-paws-text-muted">{description}</p>}
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-paws-text-dim hover:text-paws-text hover:bg-paws-surface-hover transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="px-6 py-4">{children}</div>
      </div>
    </div>
  );
}
