import { Badge } from '@/components/ui';
import { Clock, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';

interface LifecycleCountdownProps {
  lastAccessedAt: string | null;
  shutdownDays: number;
  destroyDays: number;
  status: string;
  onKeepAlive?: () => void;
  readOnly?: boolean;
}

export function LifecycleCountdown({ lastAccessedAt, shutdownDays, destroyDays, status, onKeepAlive, readOnly }: LifecycleCountdownProps) {
  if (shutdownDays <= 0 && destroyDays <= 0) return null;
  if (!lastAccessedAt) return null;

  const lastAccess = new Date(lastAccessedAt).getTime();
  const now = Date.now();

  let policyDays = 0;
  let policyLabel = '';
  if ((status === 'running' || status === 'paused' || status === 'suspended') && shutdownDays > 0) {
    policyDays = shutdownDays;
    policyLabel = 'auto-shutdown';
  } else if (status === 'stopped' && destroyDays > 0) {
    policyDays = destroyDays;
    policyLabel = 'auto-destroy';
  } else {
    // Show whichever policy is active as a general countdown
    if (shutdownDays > 0) { policyDays = shutdownDays; policyLabel = 'idle shutdown'; }
    else if (destroyDays > 0) { policyDays = destroyDays; policyLabel = 'idle destroy'; }
    else return null;
  }

  const expiresAt = lastAccess + policyDays * 86400000;
  const daysLeft = Math.max(0, Math.ceil((expiresAt - now) / 86400000));

  const variant: 'danger' | 'warning' | 'default' =
    daysLeft <= 3 ? 'danger' : daysLeft <= 7 ? 'warning' : 'default';

  return (
    <div className="flex items-center gap-2">
      <Badge variant={variant} className="flex items-center gap-1 text-[10px] whitespace-nowrap">
        <Clock className="h-3 w-3" />
        {daysLeft}d {policyLabel}
      </Badge>
      {onKeepAlive && !readOnly && (
        <button
          onClick={(e) => { e.stopPropagation(); onKeepAlive(); }}
          className={cn(
            'p-1 rounded hover:bg-paws-surface-hover transition-colors',
            'text-paws-text-dim hover:text-paws-primary',
          )}
          title="Keep alive - reset idle timer"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
