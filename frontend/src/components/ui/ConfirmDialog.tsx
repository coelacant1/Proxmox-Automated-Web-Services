import { AlertTriangle } from 'lucide-react';
import { Button } from './Button';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  variant?: 'danger' | 'primary';
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  variant = 'danger',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/60" onClick={onCancel} />
      <div className="relative z-10 w-full max-w-md rounded-lg border border-paws-border bg-paws-bg p-6 shadow-xl">
        <div className="flex items-start gap-3">
          {variant === 'danger' && (
            <div className="rounded-full bg-paws-danger/20 p-2">
              <AlertTriangle className="h-5 w-5 text-paws-danger" />
            </div>
          )}
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-paws-text">{title}</h3>
            <p className="mt-2 text-sm text-paws-text-muted">{message}</p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="outline" onClick={onCancel}>Cancel</Button>
          <Button variant={variant === 'danger' ? 'danger' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
