import { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Folder, FileText, Upload, Trash2,
  ChevronRight, RefreshCw, Copy, Check, Link,
  Image, FileCode, Eye, CheckSquare, Square,
} from 'lucide-react';
import api from '../api/client';
import {
  Button, Card, CardContent,
  Input, Modal, Badge, EmptyState,
  useToast, useConfirm,
} from '@/components/ui';

interface S3Object {
  key: string;
  size: number;
  last_modified: string;
  is_folder: boolean;
  content_type?: string;
  [key: string]: unknown;
}

interface BucketInfo {
  name: string;
  created_at: string;
  object_count: number;
  total_size: number;
  versioning_enabled: boolean;
  encryption_enabled: boolean;
}

interface UploadProgress {
  name: string;
  progress: number;
  status: 'uploading' | 'done' | 'error';
}

function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function isPreviewable(key: string): 'text' | 'image' | null {
  const ext = key.split('.').pop()?.toLowerCase() || '';
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'bmp'].includes(ext)) return 'image';
  if (['txt', 'md', 'json', 'xml', 'yaml', 'yml', 'csv', 'log', 'js', 'ts', 'py', 'sh', 'html', 'css', 'toml', 'ini', 'cfg', 'conf', 'env'].includes(ext)) return 'text';
  return null;
}

export default function FileBrowser() {
  const { bucketName } = useParams<{ bucketName: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();
  const { confirm } = useConfirm();
  const [objects, setObjects] = useState<S3Object[]>([]);
  const [bucket, setBucket] = useState<BucketInfo | null>(null);
  const [prefix, setPrefix] = useState('');
  const [loading, setLoading] = useState(true);
  const [showShare, setShowShare] = useState(false);
  const [shareKey, setShareKey] = useState('');
  const [shareUrl, setShareUrl] = useState('');
  const [copied, setCopied] = useState(false);

  // Bulk selection
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [bulkMode, setBulkMode] = useState(false);

  // Drag & drop
  const [dragging, setDragging] = useState(false);
  const dropRef = useRef<HTMLDivElement>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Upload progress
  const [uploads, setUploads] = useState<UploadProgress[]>([]);

  // File preview
  const [preview, setPreview] = useState<{ key: string; type: 'text' | 'image'; content: string } | null>(null);

  const fetchObjects = () => {
    if (!bucketName) return;
    setLoading(true);
    api.get(`/api/storage/buckets/${bucketName}/objects`, { params: { prefix } })
      .then((res) => setObjects(res.data.objects || res.data))
      .catch(() => setObjects([]))
      .finally(() => setLoading(false));
  };

  const fetchBucket = () => {
    if (!bucketName) return;
    api.get(`/api/storage/buckets/${bucketName}`).then((res) => setBucket(res.data)).catch(() => {});
  };

  useEffect(() => { fetchBucket(); }, [bucketName]);
  useEffect(fetchObjects, [bucketName, prefix]);
  useEffect(() => { setSelectedKeys(new Set()); }, [prefix]);

  const navigateToFolder = (folder: string) => {
    setPrefix(folder.endsWith('/') ? folder : folder + '/');
  };

  const navigateUp = () => {
    const parts = prefix.split('/').filter(Boolean);
    parts.pop();
    setPrefix(parts.length ? parts.join('/') + '/' : '');
  };

  const uploadFiles = async (files: File[]) => {
    if (!bucketName || files.length === 0) return;

    const newUploads: UploadProgress[] = files.map((f) => ({ name: f.name, progress: 0, status: 'uploading' as const }));
    setUploads((prev) => [...prev, ...newUploads]);

    for (const file of files) {
      const key = prefix + file.name;
      try {
        setUploads((prev) => prev.map((u) => u.name === file.name ? { ...u, progress: 30 } : u));
        await api.put(
          `/api/storage/buckets/${bucketName}/objects/${key}`,
          file,
          {
            headers: { 'Content-Type': file.type || 'application/octet-stream' },
          },
        );
        setUploads((prev) => prev.map((u) => u.name === file.name ? { ...u, progress: 100, status: 'done' } : u));
      } catch (e: any) {
        setUploads((prev) => prev.map((u) => u.name === file.name ? { ...u, status: 'error' } : u));
        toast(e?.response?.data?.detail || `Failed to upload ${file.name}`, 'error');
      }
    }
    const succeeded = files.length - uploads.filter((u) => u.status === 'error').length;
    if (succeeded > 0) toast(`${files.length} file(s) uploaded`, 'success');
    setTimeout(() => {
      setUploads([]);
      fetchObjects();
      fetchBucket();
    }, 1500);
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    uploadFiles(files);
    e.target.value = '';
  };

  // Drag & drop handlers
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (dropRef.current && !dropRef.current.contains(e.relatedTarget as Node)) {
      setDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);

    const files = Array.from(e.dataTransfer.files);
    uploadFiles(files);
  }, [bucketName, prefix]);

  const handleDelete = async (key: string) => {
    if (!await confirm({ title: 'Delete File', message: `Delete "${key}"?` })) return;
    if (!bucketName) return;
    try {
      await api.delete(`/api/storage/buckets/${bucketName}/objects/${key}`);
      toast('File deleted', 'success');
      fetchObjects();
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to delete file', 'error');
    }
  };

  // Bulk operations
  const toggleSelect = (key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const selectAll = () => {
    const fileKeys = objects.filter((o) => !o.is_folder).map((o) => o.key);
    setSelectedKeys(new Set(fileKeys));
  };

  const handleBulkDelete = async () => {
    if (selectedKeys.size === 0) return;
    if (!await confirm({ title: 'Delete Files', message: `Delete ${selectedKeys.size} selected file(s)?` })) return;
    if (!bucketName) return;
    try {
      for (const key of selectedKeys) {
        await api.delete(`/api/storage/buckets/${bucketName}/objects/${key}`);
      }
      toast(`${selectedKeys.size} file(s) deleted`, 'success');
    } catch (e: any) {
      toast(e?.response?.data?.detail || 'Failed to delete some files', 'error');
    }
    setSelectedKeys(new Set());
    setBulkMode(false);
    fetchObjects();
  };

  // File preview
  const openPreview = async (obj: S3Object) => {
    const type = isPreviewable(obj.key);
    if (!type || !bucketName) return;
    try {
      const res = await api.get(`/api/storage/buckets/${bucketName}/objects/${obj.key}`);
      const content = typeof res.data === 'string' ? res.data : (res.data.content || JSON.stringify(res.data, null, 2));
      setPreview({ key: obj.key, type, content });
    } catch {
      setPreview({ key: obj.key, type: 'text', content: 'Failed to load file content.' });
    }
  };

  const handleShare = async (key: string) => {
    if (!bucketName) return;
    setShareKey(key);
    try {
      const res = await api.post(`/api/storage/buckets/${bucketName}/presigned`, { key, expires_in: 3600 });
      setShareUrl(res.data.url || res.data.presigned_url);
    } catch {
      setShareUrl('Error generating link');
    }
    setShowShare(true);
  };

  const copyShareUrl = () => {
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const breadcrumbs = prefix.split('/').filter(Boolean);
  const fileCount = objects.filter((o) => !o.is_folder).length;

  return (
    <div
      ref={dropRef}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="relative"
    >
      {/* Drag overlay */}
      {dragging && (
        <div className="absolute inset-0 z-50 bg-paws-primary/10 border-2 border-dashed border-paws-primary rounded-lg flex items-center justify-center">
          <div className="text-center">
            <Upload className="h-12 w-12 text-paws-primary mx-auto mb-2" />
            <p className="text-lg font-medium text-paws-text">Drop files to upload</p>
            <p className="text-sm text-paws-text-muted">Files will be uploaded to {prefix || '/'}</p>
          </div>
        </div>
      )}

      {/* Upload progress bar */}
      {uploads.length > 0 && (
        <div className="mb-4 space-y-1">
          {uploads.map((u, i) => (
            <div key={i} className="flex items-center gap-3 bg-paws-surface rounded-md px-3 py-2">
              <span className="text-xs text-paws-text truncate flex-1">{u.name}</span>
              <div className="w-32 h-1.5 bg-paws-bg rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${u.status === 'error' ? 'bg-paws-danger' : u.status === 'done' ? 'bg-paws-success' : 'bg-paws-primary'}`}
                  style={{ width: `${u.progress}%` }}
                />
              </div>
              <span className={`text-xs ${u.status === 'error' ? 'text-paws-danger' : u.status === 'done' ? 'text-paws-success' : 'text-paws-text-dim'}`}>
                {u.status === 'error' ? 'Failed' : u.status === 'done' ? 'Done' : `${u.progress}%`}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => navigate('/storage')} className="p-1 rounded hover:bg-paws-surface-hover text-paws-text-dim">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-paws-text">{bucketName}</h1>
          {bucket && (
            <div className="flex gap-3 text-xs text-paws-text-dim mt-0.5">
              <span>{bucket.object_count} objects</span>
              <span>{formatSize(bucket.total_size)}</span>
              {bucket.versioning_enabled && <Badge variant="info">Versioned</Badge>}
              {bucket.encryption_enabled && <Badge variant="success">Encrypted</Badge>}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          {bulkMode ? (
            <>
              <span className="text-xs text-paws-text-muted self-center">{selectedKeys.size} selected</span>
              <Button variant="outline" size="sm" onClick={selectAll}>Select All</Button>
              <Button variant="danger" size="sm" onClick={handleBulkDelete} disabled={selectedKeys.size === 0}>
                <Trash2 className="h-4 w-4 mr-1" /> Delete Selected
              </Button>
              <Button variant="outline" size="sm" onClick={() => { setBulkMode(false); setSelectedKeys(new Set()); }}>Cancel</Button>
            </>
          ) : (
            <>
              {fileCount > 0 && (
                <Button variant="outline" size="sm" onClick={() => setBulkMode(true)}>
                  <CheckSquare className="h-4 w-4 mr-1" /> Select
                </Button>
              )}
              <Button size="sm" onClick={() => fileInputRef.current?.click()}>
                <Upload className="h-4 w-4 mr-1" /> Upload
              </Button>
              <Button variant="outline" size="sm" onClick={fetchObjects}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-sm mb-4 text-paws-text-muted">
        <button onClick={() => setPrefix('')} className="hover:text-paws-text">{bucketName}</button>
        {breadcrumbs.map((part, i) => (
          <span key={i} className="flex items-center gap-1">
            <ChevronRight className="h-3 w-3" />
            <button
              onClick={() => setPrefix(breadcrumbs.slice(0, i + 1).join('/') + '/')}
              className="hover:text-paws-text"
            >
              {part}
            </button>
          </span>
        ))}
      </div>

      {/* Drop zone hint */}
      {objects.length === 0 && !loading && (
        <div className="mb-4 text-center text-xs text-paws-text-dim">
          Drag & drop files here to upload
        </div>
      )}

      {/* Object List */}
      <Card>
        <CardContent className="p-0">
          {prefix && (
            <button
              onClick={navigateUp}
              className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-paws-text-muted hover:bg-paws-surface-hover border-b border-paws-border-subtle"
            >
              <Folder className="h-4 w-4" /> ..
            </button>
          )}
          {loading ? (
            <p className="text-sm text-paws-text-dim p-4">Loading...</p>
          ) : objects.length === 0 ? (
            <div className="p-8">
              <EmptyState
                icon={FileText}
                title="Empty"
                description={prefix ? 'This folder is empty.' : 'Upload files or drag & drop to get started.'}
                action={{ label: 'Upload File', onClick: () => fileInputRef.current?.click() }}
              />
            </div>
          ) : (
            objects.map((obj) => (
              <div
                key={obj.key}
                className="flex items-center gap-3 px-4 py-2.5 border-b border-paws-border-subtle last:border-0 hover:bg-paws-surface-hover group"
              >
                {/* Bulk checkbox */}
                {bulkMode && !obj.is_folder && (
                  <button onClick={() => toggleSelect(obj.key)} className="text-paws-text-dim hover:text-paws-primary">
                    {selectedKeys.has(obj.key)
                      ? <CheckSquare className="h-4 w-4 text-paws-primary" />
                      : <Square className="h-4 w-4" />
                    }
                  </button>
                )}

                {obj.is_folder ? (
                  <button onClick={() => navigateToFolder(obj.key)} className="flex items-center gap-3 flex-1 text-left">
                    <Folder className="h-4 w-4 text-paws-primary" />
                    <span className="text-sm text-paws-text">{obj.key.replace(prefix, '').replace(/\/$/, '')}</span>
                  </button>
                ) : (
                  <div className="flex items-center gap-3 flex-1">
                    {isPreviewable(obj.key) === 'image'
                      ? <Image className="h-4 w-4 text-paws-info" />
                      : isPreviewable(obj.key) === 'text'
                        ? <FileCode className="h-4 w-4 text-paws-warning" />
                        : <FileText className="h-4 w-4 text-paws-text-dim" />
                    }
                    <span className="text-sm text-paws-text">{obj.key.replace(prefix, '')}</span>
                  </div>
                )}
                <span className="text-xs text-paws-text-dim">{obj.is_folder ? '-' : formatSize(obj.size)}</span>
                <span className="text-xs text-paws-text-dim w-28 text-right">
                  {obj.last_modified ? new Date(obj.last_modified).toLocaleDateString() : ''}
                </span>
                {!obj.is_folder && !bulkMode && (
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {isPreviewable(obj.key) && (
                      <button onClick={() => openPreview(obj)} className="p-1 rounded hover:bg-paws-surface text-paws-text-dim" title="Preview">
                        <Eye className="h-3.5 w-3.5" />
                      </button>
                    )}
                    <button onClick={() => handleShare(obj.key)} className="p-1 rounded hover:bg-paws-surface text-paws-text-dim" title="Share link">
                      <Link className="h-3.5 w-3.5" />
                    </button>
                    <button onClick={() => handleDelete(obj.key)} className="p-1 rounded hover:bg-paws-surface text-paws-danger" title="Delete">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {/* Hidden file input for native file picker */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileInput}
      />

      {/* Share Link Modal */}
      <Modal open={showShare} onClose={() => { setShowShare(false); setCopied(false); }} title="Share Link" size="lg">
        <div className="space-y-4">
          <p className="text-sm text-paws-text-muted">Presigned URL for <code className="font-mono text-paws-text">{shareKey}</code> (expires in 1 hour)</p>
          <div className="flex gap-2">
            <Input value={shareUrl} readOnly className="flex-1 font-mono text-xs" />
            <Button variant="outline" size="sm" onClick={copyShareUrl}>
              {copied ? <Check className="h-4 w-4 text-paws-success" /> : <Copy className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </Modal>

      {/* File Preview Modal */}
      <Modal open={!!preview} onClose={() => setPreview(null)} title={`Preview: ${preview?.key.split('/').pop() || ''}`} size="lg">
        {preview && (
          <div className="max-h-[70vh] overflow-auto">
            {preview.type === 'image' ? (
              <div className="flex items-center justify-center p-4 bg-paws-bg rounded">
                <p className="text-sm text-paws-text-dim">[Image preview - base64 rendering requires binary object endpoint]</p>
              </div>
            ) : (
              <pre className="bg-paws-bg rounded-md p-4 text-xs font-mono text-paws-text overflow-x-auto whitespace-pre-wrap">
                {preview.content}
              </pre>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
