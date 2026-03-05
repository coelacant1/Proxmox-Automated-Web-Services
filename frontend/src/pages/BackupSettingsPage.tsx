import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Input,
} from '@/components/ui';

interface BackupSettings {
  default_retention_days: number;
  auto_backup_enabled: boolean;
  auto_backup_schedule: string;
  max_backups_per_resource: number;
  preferred_storage: string;
}

export default function BackupSettings() {
  const [settings, setSettings] = useState<BackupSettings>({
    default_retention_days: 30,
    auto_backup_enabled: false,
    auto_backup_schedule: '0 2 * * *',
    max_backups_per_resource: 5,
    preferred_storage: 'local',
  });
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get('/api/backups/settings')
      .then((res) => setSettings((prev) => ({ ...prev, ...res.data })))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    await api.put('/api/backups/settings', settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  if (loading) return <p className="text-paws-text-muted p-8">Loading...</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Backup Settings</h1>
        <Button onClick={handleSave}>
          <Save className="h-4 w-4 mr-1" /> {saved ? 'Saved!' : 'Save Settings'}
        </Button>
      </div>

      <div className="max-w-lg space-y-4">
        <Card>
          <CardHeader><CardTitle>Retention</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <Input label="Default Retention (days)" type="number" min={1} value={settings.default_retention_days}
              onChange={(e) => setSettings({ ...settings, default_retention_days: +e.target.value })} />
            <Input label="Max Backups Per Resource" type="number" min={1} value={settings.max_backups_per_resource}
              onChange={(e) => setSettings({ ...settings, max_backups_per_resource: +e.target.value })} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Automatic Backups</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-paws-text">Auto Backup</p>
                <p className="text-xs text-paws-text-dim">Automatically back up all resources on schedule</p>
              </div>
              <button
                onClick={() => setSettings({ ...settings, auto_backup_enabled: !settings.auto_backup_enabled })}
                className={`w-10 h-5 rounded-full transition-colors ${settings.auto_backup_enabled ? 'bg-paws-primary' : 'bg-paws-surface-hover'}`}
              >
                <span className={`block w-4 h-4 rounded-full bg-white transform transition-transform ${settings.auto_backup_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>
            {settings.auto_backup_enabled && (
              <Input label="Cron Schedule" value={settings.auto_backup_schedule}
                onChange={(e) => setSettings({ ...settings, auto_backup_schedule: e.target.value })} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Storage</CardTitle></CardHeader>
          <CardContent>
            <Input label="Preferred Storage Pool" value={settings.preferred_storage}
              onChange={(e) => setSettings({ ...settings, preferred_storage: e.target.value })} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
