import { cn } from '@/lib/utils';

interface Tab {
  id: string;
  label: string;
  icon?: React.ReactNode;
  count?: number;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onChange: (id: string) => void;
  className?: string;
}

export function Tabs({ tabs, activeTab, onChange, className }: TabsProps) {
  return (
    <div className={cn('flex gap-1 border-b border-paws-border', className)}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            'flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px',
            activeTab === tab.id
              ? 'border-paws-primary text-paws-primary'
              : 'border-transparent text-paws-text-muted hover:text-paws-text hover:border-paws-border',
          )}
        >
          {tab.icon}
          {tab.label}
          {tab.count !== undefined && (
            <span className={cn(
              'ml-1 rounded-full px-2 py-0.5 text-xs',
              activeTab === tab.id
                ? 'bg-paws-primary/20 text-paws-primary'
                : 'bg-paws-surface-hover text-paws-text-dim',
            )}>
              {tab.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
