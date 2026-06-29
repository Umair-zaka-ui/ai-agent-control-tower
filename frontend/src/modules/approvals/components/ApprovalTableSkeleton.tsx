import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

/** Loading placeholder mirroring the approval table layout. */
export function ApprovalTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {['Approval ID', 'Agent', 'Action', 'Resource', 'Risk', 'Priority', 'Created', 'Reviewer', 'Status', ''].map(
            (h, i) => (
              <TableHead key={i}>{h}</TableHead>
            ),
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: rows }).map((_, r) => (
          <TableRow key={r}>
            {Array.from({ length: 10 }).map((__, c) => (
              <TableCell key={c}>
                <Skeleton className="h-4 w-full max-w-[120px]" />
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
