import { useState, useEffect, useRef } from 'react';
import { Bug, Paperclip, X, Send } from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardContent,
  Input, Textarea, Select, Modal, useToast,
} from '@/components/ui';

interface BugReportData {
  id: string;
  title: string;
  description: string;
  severity: string;
  status: string;
  admin_notes: string | null;
  has_attachment: boolean;
  attachment_filename: string | null;
  created_at: string | null;
  updated_at: string | null;
}

const SEVERITY_OPTIONS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
];

const severityColor = (s: string) => {
  switch (s) {
    case 'critical': return 'bg-red-500/20 text-red-400';
    case 'high': return 'bg-orange-500/20 text-orange-400';
    case 'medium': return 'bg-yellow-500/20 text-yellow-400';
    case 'low': return 'bg-blue-500/20 text-blue-400';
    default: return 'bg-paws-surface text-paws-text-muted';
  }
};

const statusColor = (s: string) => {
  switch (s) {
    case 'open': return 'bg-blue-500/20 text-blue-400';
    case 'in_progress': return 'bg-yellow-500/20 text-yellow-400';
    case 'resolved': return 'bg-green-500/20 text-green-400';
    case 'closed': return 'bg-paws-surface text-paws-text-dim';
    case 'wont_fix': return 'bg-paws-surface text-paws-text-dim';
    default: return 'bg-paws-surface text-paws-text-muted';
  }
};

export default function BugReports() {
  const { toast } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);

  const [reports, setReports] = useState<BugReportData[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [severity, setSeverity] = useState('medium');
  const [attachment, setAttachment] = useState<File | null>(null);
  const [viewReport, setViewReport] = useState<BugReportData | null>(null);

  const fetchReports = () => {
    api.get('/api/bug-reports/mine').then(r => setReports(r.data)).catch(() => {});
  };

  useEffect(fetchReports, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      toast('File must be under 10 MB', 'error');
      return;
    }
    setAttachment(file);
  };

  const handleSubmit = async () => {
    if (!title.trim() || !description.trim()) {
      toast('Title and description are required', 'error');
      return;
    }
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append('title', title);
      formData.append('description', description);
      formData.append('severity', severity);
      if (attachment) formData.append('attachment', attachment);

      await api.post('/api/bug-reports/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      toast('Bug report submitted', 'success');
      setShowForm(false);
      setTitle('');
      setDescription('');
      setSeverity('medium');
      setAttachment(null);
      fetchReports();
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      toast(typeof d === 'string' ? d : 'Failed to submit report', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const downloadAttachment = async (id: string, filename: string | null) => {
    try {
      const res = await api.get(`/api/bug-reports/${id}/attachment`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || 'attachment';
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      toast('Failed to download attachment', 'error');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-paws-text">Bug Reports</h1>
          <p className="text-sm text-paws-text-muted mt-1">Report issues and track their status</p>
        </div>
        <Button onClick={() => setShowForm(true)}>
          <Bug className="h-4 w-4 mr-1" /> New Report
        </Button>
      </div>

      {reports.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Bug className="h-10 w-10 mx-auto text-paws-text-dim mb-3" />
            <p className="text-paws-text-muted">No bug reports yet</p>
            <p className="text-sm text-paws-text-dim mt-1">Submit a report if you encounter any issues</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {reports.map(r => (
            <div key={r.id} onClick={() => setViewReport(r)}
              className="cursor-pointer rounded-lg border border-paws-border bg-paws-surface p-6 hover:border-paws-primary/30 transition-colors">
              <CardContent className="py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${severityColor(r.severity)}`}>
                      {r.severity}
                    </span>
                    <span className="text-sm font-medium text-paws-text truncate">{r.title}</span>
                    {r.has_attachment && <Paperclip className="h-3.5 w-3.5 text-paws-text-dim flex-shrink-0" />}
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor(r.status)}`}>
                      {r.status.replace('_', ' ')}
                    </span>
                    <span className="text-xs text-paws-text-dim">
                      {r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}
                    </span>
                  </div>
                </div>
              </CardContent>
            </div>
          ))}
        </div>
      )}

      {/* Submit form modal */}
      <Modal open={showForm} onClose={() => setShowForm(false)} title="Submit Bug Report">
        <div className="space-y-4">
          <Input label="Title" value={title} onChange={e => setTitle(e.target.value)}
            placeholder="Brief description of the issue" />
          <Textarea label="Description" value={description} onChange={e => setDescription(e.target.value)}
            placeholder="Steps to reproduce, expected vs actual behavior..." rows={5} />
          <Select label="Severity" options={SEVERITY_OPTIONS} value={severity}
            onChange={e => setSeverity(e.target.value)} />

          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-paws-text-muted">Attachment (optional, max 10 MB)</label>
            <div className="flex items-center gap-2">
              <input ref={fileRef} type="file" className="hidden"
                accept="image/*,.pdf,.txt,.log,.json,.zip" onChange={handleFileChange} />
              <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <Paperclip className="h-4 w-4 mr-1" /> Choose File
              </Button>
              {attachment && (
                <div className="flex items-center gap-1 text-sm text-paws-text-muted">
                  <span className="truncate max-w-[200px]">{attachment.name}</span>
                  <button onClick={() => setAttachment(null)} className="text-paws-text-dim hover:text-paws-danger">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setShowForm(false)}>Cancel</Button>
            <Button onClick={handleSubmit} disabled={submitting || !title.trim() || !description.trim()}>
              <Send className="h-4 w-4 mr-1" /> {submitting ? 'Submitting...' : 'Submit'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* View report detail */}
      <Modal open={!!viewReport} onClose={() => setViewReport(null)}
        title={viewReport?.title || 'Bug Report'}>
        {viewReport && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${severityColor(viewReport.severity)}`}>
                {viewReport.severity}
              </span>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor(viewReport.status)}`}>
                {viewReport.status.replace('_', ' ')}
              </span>
              <span className="text-xs text-paws-text-dim ml-auto">
                {viewReport.created_at ? new Date(viewReport.created_at).toLocaleString() : ''}
              </span>
            </div>
            <div className="bg-paws-surface rounded-md p-3">
              <p className="text-sm text-paws-text whitespace-pre-wrap">{viewReport.description}</p>
            </div>
            {viewReport.has_attachment && (
              <Button variant="outline" size="sm"
                onClick={() => downloadAttachment(viewReport.id, viewReport.attachment_filename)}>
                <Paperclip className="h-4 w-4 mr-1" /> {viewReport.attachment_filename || 'Download Attachment'}
              </Button>
            )}
            {viewReport.admin_notes && (
              <div className="border-t border-paws-border pt-3">
                <p className="text-xs font-medium text-paws-text-muted mb-1">Admin Response</p>
                <div className="bg-paws-primary/5 border border-paws-primary/20 rounded-md p-3">
                  <p className="text-sm text-paws-text whitespace-pre-wrap">{viewReport.admin_notes}</p>
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
