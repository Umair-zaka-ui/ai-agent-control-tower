import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const COLUMNS = ['Policy', 'Resource', 'Action', 'Decision', 'Severity', 'Status', 'Triggers', 'Last Triggered', 'Created', '']

export function PolicyTableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {COLUMNS.map((c, i) => (
            <TableHead key={i}>{c}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: rows }).map((_, r) => (
          <TableRow key={r}>
            {COLUMNS.map((_c, i) => (
              <TableCell key={i}>
                <Skeleton className="h-4 w-full max-w-[110px]" />
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
