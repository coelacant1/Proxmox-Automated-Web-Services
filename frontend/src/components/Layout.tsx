import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui';
import {
  LayoutDashboard,
  Monitor,
  Box,
  BookTemplate,
  HardDrive,
  Network,
  Archive,
  ArrowUpRight,
  Settings,
  Layers,
  Globe,
  Shield,
  Key,
  DatabaseBackup,
  Tag,
  Smartphone,
  Signal,
  DollarSign,
  Book,
  FileDown,
  Bug,
  Users,
  ScrollText,
  Crown,
  KeyRound,
  Eye,
} from 'lucide-react';

const navSections = [
  {
    label: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/resources', label: 'All Resources', icon: Layers },
      { to: '/status', label: 'Service Status', icon: Signal },
    ],
  },
  {
    label: 'Compute',
    items: [
      { to: '/vms', label: 'Virtual Machines', icon: Monitor },
      { to: '/containers', label: 'Containers', icon: Box },
      { to: '/templates', label: 'Templates', icon: BookTemplate },
    ],
  },
  {
    label: 'Storage',
    items: [
      { to: '/storage', label: 'Object Storage', icon: DatabaseBackup },
      { to: '/volumes', label: 'Volumes', icon: HardDrive },
    ],
  },
  {
    label: 'Networking',
    items: [
      { to: '/networks', label: 'Networks', icon: Network },
      { to: '/firewalls', label: 'Firewalls', icon: Shield },
      { to: '/endpoints', label: 'Endpoints', icon: Globe },
      { to: '/ssh-keys', label: 'SSH Keys', icon: Key },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/backups', label: 'Backups', icon: Archive },
      { to: '/costs', label: 'Costs', icon: DollarSign },
      { to: '/tags', label: 'Tags', icon: Tag },
      { to: '/quota-requests', label: 'Quotas', icon: ArrowUpRight },
    ],
  },
  {
    label: 'Account',
    items: [
      { to: '/groups', label: 'Groups', icon: Users },
      { to: '/keys', label: 'API Keys', icon: KeyRound },
      { to: '/tiers', label: 'Account Tier', icon: Crown },
      { to: '/mfa', label: 'MFA Settings', icon: Smartphone },
      { to: '/api-docs', label: 'API Docs', icon: Book },
      { to: '/import-export', label: 'Import/Export', icon: FileDown },
      { to: '/bug-reports', label: 'Bug Reports', icon: Bug },
      { to: '/system-rules', label: 'System Rules', icon: ScrollText },
    ],
  },
];

export default function Layout() {
  const { user, logout, isImpersonating, stopImpersonating } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const handleExitAudit = async () => {
    await stopImpersonating();
    navigate('/admin');
  };

  return (
    <div className="flex min-h-screen">
      {isImpersonating && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-amber-600 text-black text-center py-2 px-4 flex items-center justify-center gap-3 text-sm font-medium">
          <Eye className="w-4 h-4" />
          <span>Viewing as <strong>{user?.username}</strong> ({user?.role})</span>
          <button
            onClick={handleExitAudit}
            className="ml-2 px-3 py-0.5 bg-black/20 hover:bg-black/30 rounded text-sm font-semibold transition-colors"
          >
            Exit Audit Mode
          </button>
        </div>
      )}
      <nav className={cn("w-60 bg-paws-bg border-r border-paws-border flex flex-col p-4 gap-0.5 overflow-y-auto", isImpersonating && "pt-14")}>
        <h2 className="text-xl font-bold text-paws-primary mb-4 px-3">pAWS</h2>
        {navSections.map((section) => (
          <div key={section.label} className="mb-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-paws-text-dim px-3 mb-1">
              {section.label}
            </p>
            {section.items.map(({ to, label, icon: Icon }) => (
              <Link
                key={to}
                to={to}
                className={cn(
                  'flex items-center gap-3 px-3 py-1.5 rounded-md text-sm transition-colors',
                  location.pathname === to
                    ? 'bg-paws-primary/10 text-paws-primary'
                    : 'text-paws-text-muted hover:text-paws-text hover:bg-paws-surface-hover',
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            ))}
          </div>
        ))}
        {user?.role === 'admin' && (
          <Link
            to="/admin"
            className={cn(
              'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
              location.pathname === '/admin'
                ? 'bg-paws-admin/10 text-paws-admin'
                : 'text-paws-admin/70 hover:text-paws-admin hover:bg-paws-surface-hover',
            )}
          >
            <Settings className="h-4 w-4" />
            Admin
          </Link>
        )}
        <div className="mt-auto border-t border-paws-border pt-4">
          <p className="text-sm text-paws-text-muted px-3">{user?.username}</p>
          <p className="text-xs text-paws-text-dim px-3 mb-2">{user?.role}</p>
          <Button variant="outline" size="sm" onClick={logout} className="w-full">
            Sign Out
          </Button>
        </div>
      </nav>
      <main className={cn("flex-1 p-8 overflow-auto", isImpersonating && "pt-14")}>
        <Outlet />
      </main>
    </div>
  );
}
