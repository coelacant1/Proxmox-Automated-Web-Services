import { cn } from '@/lib/utils';
import { ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';
import { Button } from './Button';

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
  className?: string;
}

interface PaginationInfo {
  page: number;
  per_page: number;
  total: number;
  pages: number;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  pagination?: PaginationInfo;
  onPageChange?: (page: number) => void;
  loading?: boolean;
  emptyMessage?: string;
  className?: string;
  onRowClick?: (row: T) => void;
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  pagination,
  onPageChange,
  loading,
  emptyMessage = 'No data found',
  className,
  onRowClick,
}: DataTableProps<T>) {
  return (
    <div className={cn('rounded-lg border border-paws-border overflow-hidden', className)}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-paws-border bg-paws-surface">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={cn(
                    'px-4 py-3 text-left font-medium text-paws-text-muted',
                    col.className,
                  )}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-paws-text-muted">
                  <div className="flex flex-col items-center gap-2">
                    <Loader2 className="h-6 w-6 animate-spin" />
                    <span>Loading...</span>
                  </div>
                </td>
              </tr>
            ) : data.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-paws-text-muted">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              data.map((row, i) => (
                <tr
                  key={i}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    'border-b border-paws-border-subtle',
                    onRowClick && 'cursor-pointer hover:bg-paws-surface-hover',
                  )}
                >
                  {columns.map((col) => (
                    <td key={col.key} className={cn('px-4 py-3 text-paws-text', col.className)}>
                      {col.render ? col.render(row) : String(row[col.key] ?? '')}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {pagination && pagination.pages > 1 && (
        <div className="flex items-center justify-between border-t border-paws-border bg-paws-surface px-4 py-3">
          <span className="text-xs text-paws-text-muted">
            Showing {(pagination.page - 1) * pagination.per_page + 1}–
            {Math.min(pagination.page * pagination.per_page, pagination.total)} of {pagination.total}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={pagination.page <= 1}
              onClick={() => onPageChange?.(pagination.page - 1)}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-xs text-paws-text-muted">
              Page {pagination.page} of {pagination.pages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={pagination.page >= pagination.pages}
              onClick={() => onPageChange?.(pagination.page + 1)}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
