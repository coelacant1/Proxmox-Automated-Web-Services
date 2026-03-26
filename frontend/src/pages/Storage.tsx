import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { HardDrive, BookOpen, ChevronDown, ChevronRight, Terminal, Code2, Copy, Check, ExternalLink } from 'lucide-react';
import api from '../api/client';
import { Button, Card, CardContent, CardHeader, CardTitle, Input, Badge, QuotaBar, useToast, useConfirm } from '@/components/ui';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';

interface Bucket {
  id: string;
  name: string;
  bucket_name: string;
  object_count?: number;
  total_size?: number;
  created_at: string;
}

interface S3Info {
  endpoint_url: string;
  region: string;
  note: string;
}

interface StorageQuota {
  buckets_used: number;
  buckets_max: number;
  storage_used_bytes: number;
  storage_used_gb: number;
  storage_max_gb: number;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button onClick={copy} className="ml-2 p-1 rounded hover:bg-paws-border/30 text-paws-text-muted hover:text-paws-text transition-colors" title="Copy">
      {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}

function CodeBlock({ children, copyText }: { children: string; copyText?: string }) {
  return (
    <div className="relative group bg-black/40 border border-paws-border/30 rounded-lg p-3 font-mono text-xs text-paws-text-muted overflow-x-auto">
      <pre className="whitespace-pre-wrap">{children}</pre>
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <CopyButton text={copyText || children} />
      </div>
    </div>
  );
}

export default function Storage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { confirm } = useConfirm();
  const [buckets, setBuckets] = useState<Bucket[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState('');
  const [error, setError] = useState('');
  const [s3Info, setS3Info] = useState<S3Info | null>(null);
  const [quota, setQuota] = useState<StorageQuota | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideTab, setGuideTab] = useState<'cli' | 'python' | 'js' | 'presigned'>('cli');

  const fetchBuckets = () => {
    api.get('/api/storage/buckets').then((res) => setBuckets(res.data)).catch(() => {}).finally(() => setLoading(false));
  };

  const fetchQuota = () => {
    api.get('/api/storage/quota').then((res) => setQuota(res.data)).catch(() => {});
  };

  useEffect(() => {
    fetchBuckets();
    fetchQuota();
    api.get('/api/storage/s3-info').then((res) => setS3Info(res.data)).catch(() => {});
  }, []);

  const createBucket = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setError('');
    try {
      await api.post('/api/storage/buckets', { name: newName.toLowerCase().trim() });
      setNewName('');
      fetchBuckets();
      fetchQuota();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Failed to create bucket');
    }
  };

  const deleteBucket = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!await confirm({ title: 'Delete Bucket', message: 'Delete this bucket and all its contents? This action cannot be undone.' })) return;
    try {
      await api.delete(`/api/storage/buckets/${id}?force=true`);
      toast('Bucket deleted successfully', 'success');
    } catch {
      setError('Failed to delete bucket');
    }
    fetchBuckets();
    fetchQuota();
  };

  const formatSize = (bytes: number) => {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
  };

  const endpoint = s3Info?.endpoint_url || 'https://s3.example.com';
  const region = s3Info?.region || 'us-east-1';

  const guideContent: Record<string, { title: string; icon: React.ReactNode; code: string }> = {
    cli: {
      title: 'AWS CLI',
      icon: <Terminal className="w-4 h-4" />,
      code: `# Install AWS CLI
pip install awscli

# Configure credentials
aws configure
  AWS Access Key ID: <your-access-key>
  AWS Secret Access Key: <your-secret-key>
  Default region name: ${region}

# List buckets
aws --endpoint-url ${endpoint} s3 ls

# Upload a file
aws --endpoint-url ${endpoint} s3 cp myfile.txt s3://my-bucket/

# Download a file
aws --endpoint-url ${endpoint} s3 cp s3://my-bucket/myfile.txt ./

# Sync a directory
aws --endpoint-url ${endpoint} s3 sync ./my-folder s3://my-bucket/my-folder/

# Remove a file
aws --endpoint-url ${endpoint} s3 rm s3://my-bucket/myfile.txt`,
    },
    python: {
      title: 'Python (boto3)',
      icon: <Code2 className="w-4 h-4" />,
      code: `# pip install boto3
import boto3

s3 = boto3.client(
    "s3",
    endpoint_url="${endpoint}",
    aws_access_key_id="<your-access-key>",
    aws_secret_access_key="<your-secret-key>",
    region_name="${region}",
)

# Upload a file
s3.upload_file("local-file.txt", "my-bucket", "remote-key.txt")

# Download a file
s3.download_file("my-bucket", "remote-key.txt", "local-file.txt")

# List objects
response = s3.list_objects_v2(Bucket="my-bucket")
for obj in response.get("Contents", []):
    print(obj["Key"], obj["Size"])

# Generate a presigned URL (shareable link)
url = s3.generate_presigned_url(
    "get_object",
    Params={"Bucket": "my-bucket", "Key": "myfile.txt"},
    ExpiresIn=3600,  # 1 hour
)
print(url)`,
    },
    js: {
      title: 'JavaScript (AWS SDK)',
      icon: <Code2 className="w-4 h-4" />,
      code: `// npm install @aws-sdk/client-s3
import { S3Client, PutObjectCommand, GetObjectCommand } from "@aws-sdk/client-s3";

const s3 = new S3Client({
  endpoint: "${endpoint}",
  region: "${region}",
  credentials: {
    accessKeyId: "<your-access-key>",
    secretAccessKey: "<your-secret-key>",
  },
  forcePathStyle: true,
});

// Upload
await s3.send(new PutObjectCommand({
  Bucket: "my-bucket",
  Key: "hello.txt",
  Body: "Hello, world!",
}));

// Download
const resp = await s3.send(new GetObjectCommand({
  Bucket: "my-bucket",
  Key: "hello.txt",
}));
const body = await resp.Body.transformToString();
console.log(body);`,
    },
    presigned: {
      title: 'Presigned URLs',
      icon: <ExternalLink className="w-4 h-4" />,
      code: `Presigned URLs let you share temporary download links to
files without exposing your credentials.

From the File Browser:
  1. Navigate to a file in your bucket
  2. Click the link icon on the file row
  3. A shareable URL is generated (valid for 1 hour)
  4. Copy and share - anyone with the link can download

From the AWS CLI:
  aws --endpoint-url ${endpoint} s3 presign \\
    s3://my-bucket/myfile.txt --expires-in 3600

From Python:
  url = s3.generate_presigned_url(
      "get_object",
      Params={"Bucket": "my-bucket", "Key": "myfile.txt"},
      ExpiresIn=3600,
  )`,
    },
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-paws-text">Object Storage</h1>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setGuideOpen(!guideOpen)}
          className="flex items-center gap-2 text-paws-text-muted hover:text-paws-text"
        >
          <BookOpen className="w-4 h-4" />
          S3 Guide
          {guideOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </Button>
      </div>

      {quota && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <QuotaBar label="Buckets" used={quota.buckets_used} limit={quota.buckets_max} />
          <QuotaBar label="Storage" used={quota.storage_used_gb} limit={quota.storage_max_gb} unit=" GB" />
        </div>
      )}

      {guideOpen && (
        <Card className="border-paws-accent/30 bg-paws-accent/5">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-paws-accent" />
              Connecting to Object Storage
            </CardTitle>
            {s3Info && (
              <div className="flex flex-wrap gap-4 mt-2 text-xs text-paws-text-muted">
                <span className="flex items-center gap-1.5">
                  Endpoint: <code className="bg-black/30 px-1.5 py-0.5 rounded font-mono">{s3Info.endpoint_url}</code>
                  <CopyButton text={s3Info.endpoint_url} />
                </span>
                <span className="flex items-center gap-1.5">
                  Region: <code className="bg-black/30 px-1.5 py-0.5 rounded font-mono">{s3Info.region}</code>
                </span>
              </div>
            )}
            <p className="text-xs text-paws-text-dim mt-2">
              PAWS storage is S3-compatible. Use any S3 client, SDK, or CLI tool with the endpoint above and your API credentials.
            </p>
          </CardHeader>
          <CardContent>
            <div className="flex gap-1 mb-3 border-b border-paws-border/30">
              {Object.entries(guideContent).map(([key, val]) => (
                <button
                  key={key}
                  onClick={() => setGuideTab(key as typeof guideTab)}
                  className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-t transition-colors ${
                    guideTab === key
                      ? 'text-paws-accent border-b-2 border-paws-accent bg-paws-accent/10'
                      : 'text-paws-text-muted hover:text-paws-text'
                  }`}
                >
                  {val.icon}
                  {val.title}
                </button>
              ))}
            </div>
            <CodeBlock copyText={guideContent[guideTab]?.code ?? ''}>{guideContent[guideTab]?.code ?? ''}</CodeBlock>
          </CardContent>
        </Card>
      )}

      <div>
        <form onSubmit={createBucket} className="flex gap-2">
          <div className="flex-1">
            <Input
              placeholder="New bucket name (lowercase, 3-63 chars)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </div>
          <Button type="submit" variant="primary">Create Bucket</Button>
        </form>
        {error && <p className="mt-2 text-sm text-paws-danger">{error}</p>}
        <p className="mt-1 text-xs text-paws-text-dim">Lowercase letters, numbers, dots, hyphens only. Must start/end with alphanumeric.</p>
      </div>

      {loading ? (
        <LoadingSpinner message="Loading buckets..." />
      ) : buckets.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="py-12 text-center">
            <HardDrive className="w-12 h-12 mx-auto text-paws-text-dim mb-3" />
            <p className="text-paws-text-dim font-medium">No buckets yet</p>
            <p className="text-xs text-paws-text-muted mt-1">Create a bucket above to start storing objects.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {buckets.map((b) => (
            <div
              key={b.id}
              role="button"
              tabIndex={0}
              className="w-full text-left cursor-pointer"
              onClick={() => navigate(`/storage/${b.bucket_name || b.name}`)}
              onKeyDown={(e) => e.key === 'Enter' && navigate(`/storage/${b.bucket_name || b.name}`)}
            >
            <Card
              className="flex items-center justify-between hover:border-paws-accent/40 transition-colors"
            >
              <div className="flex items-center gap-3">
                <HardDrive className="w-5 h-5 text-paws-accent" />
                <div>
                  <p className="font-bold text-paws-text">{b.name}</p>
                  <div className="flex items-center gap-3 text-xs text-paws-text-muted mt-0.5">
                    {b.object_count !== undefined && (
                      <span>{b.object_count} object{b.object_count !== 1 ? 's' : ''}</span>
                    )}
                    {b.total_size !== undefined && <span>{formatSize(b.total_size)}</span>}
                    <span>Created {new Date(b.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="info" className="text-xs">Browse</Badge>
                <Button variant="danger" size="sm" onClick={(e) => deleteBucket(b.id, e)}>
                  Delete
                </Button>
              </div>
            </Card>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
