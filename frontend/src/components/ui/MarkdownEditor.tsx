import { useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  minHeight?: string;
  readOnly?: boolean;
}

export default function MarkdownEditor({ value, onChange, placeholder, minHeight = '200px', readOnly = false }: MarkdownEditorProps) {
  const [tab, setTab] = useState<'write' | 'preview'>('write');

  return (
    <div className="border border-paws-border rounded-lg overflow-hidden">
      <div className="flex border-b border-paws-border bg-paws-bg-alt">
        <button
          type="button"
          onClick={() => setTab('write')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === 'write'
              ? 'text-paws-accent border-b-2 border-paws-accent bg-paws-bg-card'
              : 'text-paws-muted hover:text-paws-text'
          }`}
        >
          Write
        </button>
        <button
          type="button"
          onClick={() => setTab('preview')}
          className={`px-4 py-2 text-sm font-medium transition-colors ${
            tab === 'preview'
              ? 'text-paws-accent border-b-2 border-paws-accent bg-paws-bg-card'
              : 'text-paws-muted hover:text-paws-text'
          }`}
        >
          Preview
        </button>
      </div>

      {tab === 'write' ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder || 'Write your markdown here...'}
          readOnly={readOnly}
          className="w-full bg-paws-bg-card text-paws-text p-4 font-mono text-sm resize-y focus:outline-none"
          style={{ minHeight }}
        />
      ) : (
        <div
          className="prose prose-invert max-w-none p-4 bg-paws-bg-card text-paws-text markdown-preview"
          style={{ minHeight }}
        >
          {value ? (
            <Markdown remarkPlugins={[remarkGfm]}>{value}</Markdown>
          ) : (
            <p className="text-paws-muted italic">Nothing to preview</p>
          )}
        </div>
      )}
    </div>
  );
}
