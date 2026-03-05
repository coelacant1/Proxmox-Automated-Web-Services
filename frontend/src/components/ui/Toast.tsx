import { useEffect, useState, useCallback, createContext, useContext } from 'react';
import { cn } from '@/lib/utils';
import { X, CheckCircle, AlertTriangle, Info, XCircle } from 'lucide-react';

interface Toast {
  id: string;
  message: string;
  variant: 'success' | 'error' | 'warning' | 'info';
  duration?: number;
}

interface ToastContextType {
  toast: (message: string, variant?: Toast['variant'], duration?: number) => void;
}

const ToastContext = createContext<ToastContextType>({ toast: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

const icons = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const colors = {
  success: 'border-paws-success/50 bg-paws-success/10',
  error: 'border-paws-danger/50 bg-paws-danger/10',
  warning: 'border-paws-warning/50 bg-paws-warning/10',
  info: 'border-paws-info/50 bg-paws-info/10',
};

const iconColors = {
  success: 'text-paws-success',
  error: 'text-paws-danger',
  warning: 'text-paws-warning',
  info: 'text-paws-info',
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string, variant: Toast['variant'] = 'info', duration = 4000) => {
    const id = crypto.randomUUID();
    setToasts((prev) => [...prev, { id, message, variant, duration }]);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast: addToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const Icon = icons[toast.variant];

  useEffect(() => {
    if (toast.duration && toast.duration > 0) {
      const timer = setTimeout(() => onDismiss(toast.id), toast.duration);
      return () => clearTimeout(timer);
    }
  }, [toast.id, toast.duration, onDismiss]);

  return (
    <div
      className={cn(
        'flex items-start gap-3 rounded-lg border p-4 shadow-lg animate-in slide-in-from-right',
        colors[toast.variant],
      )}
    >
      <Icon className={cn('h-5 w-5 shrink-0 mt-0.5', iconColors[toast.variant])} />
      <p className="flex-1 text-sm text-paws-text">{toast.message}</p>
      <button onClick={() => onDismiss(toast.id)} className="shrink-0 text-paws-text-muted hover:text-paws-text">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
