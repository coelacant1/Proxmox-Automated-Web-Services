import { useState } from 'react';
import { Upload, Download, AlertTriangle } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardHeader, CardTitle, CardContent,
  Select, Tabs,
} from '@/components/ui';

export default function ImportExport() {
  const [tab, setTab] = useState('export');
  const [exportType, setExportType] = useState('all');
  const [importFile, setImportFile] = useState<File | null>(null);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const handleExport = async () => {
    setExporting(true);
    setResult(null);
    try {
      const res = await api.get(`/api/admin/export?type=${exportType}`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = `paws-export-${exportType}-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      window.URL.revokeObjectURL(url);
      setResult('Export completed successfully.');
    } catch {
      setResult('Export failed.');
    }
    setExporting(false);
  };

  const handleImport = async () => {
    if (!importFile) return;
    setImporting(true);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append('file', importFile);
      await api.post('/api/admin/import', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResult('Import completed successfully.');
      setImportFile(null);
    } catch {
      setResult('Import failed. Check the file format.');
    }
    setImporting(false);
  };

  const tabs = [
    { id: 'export', label: 'Export' },
    { id: 'import', label: 'Import' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-paws-text">Import / Export</h1>
        <p className="text-sm text-paws-text-muted mt-1">Migrate data between PAWS instances or create backups of configuration.</p>
      </div>

      <Tabs tabs={tabs} activeTab={tab} onChange={setTab} className="mb-6" />

      <div className="max-w-lg">
        {tab === 'export' && (
          <Card>
            <CardHeader><CardTitle>Export Data</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <Select label="Export Type" options={[
                { value: 'all', label: 'All Data' },
                { value: 'resources', label: 'Resources Only' },
                { value: 'config', label: 'Configuration Only' },
                { value: 'users', label: 'Users & Quotas' },
                { value: 'backups', label: 'Backup Plans' },
              ]} value={exportType} onChange={(e) => setExportType(e.target.value)} />
              <p className="text-xs text-paws-text-dim">
                Exports are JSON files containing your PAWS configuration and resource definitions.
                Sensitive data (passwords, keys) is excluded.
              </p>
              <Button onClick={handleExport} disabled={exporting}>
                <Download className="h-4 w-4 mr-1" /> {exporting ? 'Exporting...' : 'Download Export'}
              </Button>
            </CardContent>
          </Card>
        )}

        {tab === 'import' && (
          <Card>
            <CardHeader><CardTitle>Import Data</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-start gap-2 bg-paws-warning/10 border border-paws-warning/30 rounded-md px-3 py-2">
                <AlertTriangle className="h-4 w-4 text-paws-warning mt-0.5 shrink-0" />
                <p className="text-xs text-paws-warning">
                  Importing may overwrite existing data. Create a backup before importing.
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-paws-text mb-1">Select File</label>
                <input
                  type="file"
                  accept=".json"
                  onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                  className="block w-full text-sm text-paws-text-dim file:mr-4 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-paws-primary file:text-white hover:file:bg-paws-primary/90 cursor-pointer"
                />
              </div>
              {importFile && (
                <p className="text-xs text-paws-text-dim">
                  Selected: {importFile.name} ({(importFile.size / 1024).toFixed(1)} KB)
                </p>
              )}
              <Button onClick={handleImport} disabled={!importFile || importing}>
                <Upload className="h-4 w-4 mr-1" /> {importing ? 'Importing...' : 'Import'}
              </Button>
            </CardContent>
          </Card>
        )}

        {result && (
          <div className={`mt-4 p-3 rounded-md text-sm ${result.includes('failed') ? 'bg-paws-danger/10 text-paws-danger' : 'bg-paws-success/10 text-paws-success'}`}>
            {result}
          </div>
        )}
      </div>
    </div>
  );
}
