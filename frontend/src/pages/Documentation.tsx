import { useState, useEffect } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Plus, FileText, Globe, Users, Lock, Pencil, Trash2, ArrowLeft, Save } from 'lucide-react';
import MarkdownEditor from '../components/ui/MarkdownEditor';
import { useToast, useConfirm } from '@/components/ui';
import api from '../api/client';

interface DocPage {
  id: string;
  owner_id: string;
  owner_username: string;
  title: string;
  slug: string;
  content: string;
  visibility: 'private' | 'group' | 'public';
  group_id: string | null;
  group_name: string | null;
  locked_by: string | null;
  locked_at: string | null;
  created_at: string;
  updated_at: string;
}

interface Group {
  id: string;
  name: string;
}

const visibilityIcons = {
  private: Lock,
  group: Users,
  public: Globe,
};

const visibilityLabels = {
  private: 'Private',
  group: 'Group',
  public: 'Public',
};

export default function Documentation() {
  const toast = useToast();
  const { confirm } = useConfirm();

  const [docs, setDocs] = useState<DocPage[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDoc, setSelectedDoc] = useState<DocPage | null>(null);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);

  // Form state
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'group' | 'public'>('private');
  const [groupId, setGroupId] = useState<string>('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchDocs();
    fetchGroups();
  }, []);

  const fetchDocs = async () => {
    try {
      const res = await api.get('/api/docs/');
      setDocs(res.data);
    } catch {
      toast.toast('Failed to load documentation', 'error');
    } finally {
      setLoading(false);
    }
  };

  const fetchGroups = async () => {
    try {
      const res = await api.get('/api/groups/');
      setGroups(res.data.items || res.data || []);
    } catch {
      // non-critical
    }
  };

  const openDoc = async (doc: DocPage) => {
    try {
      const res = await api.get(`/api/docs/${doc.id}`);
      setSelectedDoc(res.data);
      setEditing(false);
    } catch {
      toast.toast('Failed to load document', 'error');
    }
  };

  const startCreate = () => {
    setCreating(true);
    setSelectedDoc(null);
    setEditing(false);
    setTitle('');
    setContent('');
    setVisibility('private');
    setGroupId('');
  };

  const startEdit = () => {
    if (!selectedDoc) return;
    setTitle(selectedDoc.title);
    setContent(selectedDoc.content);
    setVisibility(selectedDoc.visibility);
    setGroupId(selectedDoc.group_id || '');
    setEditing(true);
  };

  const handleSave = async () => {
    if (!title.trim()) {
      toast.toast('Title is required', 'error');
      return;
    }
    setSaving(true);
    try {
      if (creating) {
        const res = await api.post('/api/docs/', {
          title: title.trim(),
          content,
          visibility,
          group_id: visibility === 'group' ? groupId : null,
        });
        toast.toast('Document created', 'success');
        setCreating(false);
        setSelectedDoc(res.data);
        setEditing(false);
      } else if (selectedDoc) {
        const res = await api.patch(`/api/docs/${selectedDoc.id}`, {
          title: title.trim(),
          content,
          visibility,
          group_id: visibility === 'group' ? groupId : null,
        });
        toast.toast('Document saved', 'success');
        setSelectedDoc(res.data);
        setEditing(false);
      }
      fetchDocs();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to save';
      toast.toast(msg, 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedDoc) return;
    const ok = await confirm({
      title: 'Delete Document',
      message: `Are you sure you want to delete "${selectedDoc.title}"? This cannot be undone.`,
      confirmLabel: 'Delete',
      variant: 'danger',
    });
    if (!ok) return;

    try {
      await api.delete(`/api/docs/${selectedDoc.id}`);
      toast.toast('Document deleted', 'success');
      setSelectedDoc(null);
      setEditing(false);
      fetchDocs();
    } catch {
      toast.toast('Failed to delete document', 'error');
    }
  };

  const goBack = () => {
    if (editing) {
      setEditing(false);
    } else if (creating) {
      setCreating(false);
    } else {
      setSelectedDoc(null);
    }
  };

  // Render loading
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-paws-accent" />
      </div>
    );
  }

  // Render editor (create or edit mode)
  if (creating || editing) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={goBack} className="text-paws-muted hover:text-paws-text">
              <ArrowLeft className="h-5 w-5" />
            </button>
            <h1 className="text-2xl font-bold text-paws-text">
              {creating ? 'New Document' : `Edit: ${selectedDoc?.title}`}
            </h1>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-paws-accent text-white rounded-lg hover:bg-paws-accent/80 disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-paws-muted mb-1">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Document title"
              className="w-full px-3 py-2 bg-paws-bg-card border border-paws-border rounded-lg text-paws-text"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-paws-muted mb-1">Visibility</label>
            <select
              value={visibility}
              onChange={(e) => setVisibility(e.target.value as 'private' | 'group' | 'public')}
              className="w-full px-3 py-2 bg-paws-bg-card border border-paws-border rounded-lg text-paws-text"
            >
              <option value="private">Private</option>
              <option value="group">Group</option>
              <option value="public">Public</option>
            </select>
          </div>
        </div>

        {visibility === 'group' && (
          <div>
            <label className="block text-sm font-medium text-paws-muted mb-1">Share with Group</label>
            <select
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              className="w-full px-3 py-2 bg-paws-bg-card border border-paws-border rounded-lg text-paws-text"
            >
              <option value="">Select a group...</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-paws-muted mb-1">Content</label>
          <MarkdownEditor
            value={content}
            onChange={setContent}
            placeholder="Write your documentation in markdown..."
            minHeight="400px"
          />
        </div>
      </div>
    );
  }

  // Render doc viewer
  if (selectedDoc) {
    const VisIcon = visibilityIcons[selectedDoc.visibility];
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={goBack} className="text-paws-muted hover:text-paws-text">
              <ArrowLeft className="h-5 w-5" />
            </button>
            <h1 className="text-2xl font-bold text-paws-text">{selectedDoc.title}</h1>
            <span className="flex items-center gap-1 text-xs text-paws-muted bg-paws-bg-alt px-2 py-1 rounded">
              <VisIcon className="h-3 w-3" />
              {visibilityLabels[selectedDoc.visibility]}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={startEdit}
              className="flex items-center gap-2 px-3 py-2 bg-paws-bg-alt border border-paws-border text-paws-text rounded-lg hover:bg-paws-bg-card"
            >
              <Pencil className="h-4 w-4" />
              Edit
            </button>
            <button
              onClick={handleDelete}
              className="flex items-center gap-2 px-3 py-2 bg-red-600/20 border border-red-500/30 text-red-400 rounded-lg hover:bg-red-600/30"
            >
              <Trash2 className="h-4 w-4" />
              Delete
            </button>
          </div>
        </div>

        <div className="text-xs text-paws-muted flex items-center gap-4">
          <span>By {selectedDoc.owner_username}</span>
          {selectedDoc.group_name && <span>Shared with {selectedDoc.group_name}</span>}
          <span>Updated {new Date(selectedDoc.updated_at).toLocaleDateString()}</span>
        </div>

        <div className="bg-paws-bg-card border border-paws-border rounded-lg p-6 prose prose-invert max-w-none markdown-preview">
          <Markdown remarkPlugins={[remarkGfm]}>{selectedDoc.content || '*No content yet*'}</Markdown>
        </div>
      </div>
    );
  }

  // Render doc list
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Documentation</h1>
        <button
          onClick={startCreate}
          className="flex items-center gap-2 px-4 py-2 bg-paws-accent text-white rounded-lg hover:bg-paws-accent/80"
        >
          <Plus className="h-4 w-4" />
          New Document
        </button>
      </div>

      {docs.length === 0 ? (
        <div className="text-center py-16">
          <FileText className="h-12 w-12 text-paws-muted mx-auto mb-4" />
          <p className="text-paws-muted">No documentation pages yet</p>
          <p className="text-sm text-paws-muted mt-1">Create your first document to get started</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {docs.map((doc) => {
            const VisIcon = visibilityIcons[doc.visibility];
            return (
              <button
                key={doc.id}
                onClick={() => openDoc(doc)}
                className="text-left bg-paws-bg-card border border-paws-border rounded-lg p-4 hover:border-paws-accent/50 transition-colors"
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="font-semibold text-paws-text truncate pr-2">{doc.title}</h3>
                  <VisIcon className="h-4 w-4 text-paws-muted flex-shrink-0" />
                </div>
                <p className="text-sm text-paws-muted line-clamp-2 mb-3">
                  {doc.content.slice(0, 120) || 'Empty document'}
                </p>
                <div className="flex items-center justify-between text-xs text-paws-muted">
                  <span>{doc.owner_username}</span>
                  <div className="flex items-center gap-2">
                    {doc.group_name && (
                      <span className="flex items-center gap-1 bg-paws-bg-alt px-1.5 py-0.5 rounded text-paws-info">
                        <Users className="h-3 w-3" />{doc.group_name}
                      </span>
                    )}
                    <span>{new Date(doc.updated_at).toLocaleDateString()}</span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
