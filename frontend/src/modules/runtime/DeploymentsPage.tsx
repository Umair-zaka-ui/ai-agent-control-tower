import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Layers, Loader2 } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/common'
import {
  Badge, Card, CardContent, Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService } from '@/services'
import { RuntimeNav } from './components/RuntimeNav'
import { DEPLOYMENT_STATUS_VARIANT, formatDate } from './utils'

/** Phase 5.0 §14, §66 — every deployment across every agent and environment. */
export function DeploymentsPage() {
  const deployments = useQuery({ queryKey: ['runtime-deployments'], queryFn: () => runtimeService.deployments() })
  const agents = useQuery({ queryKey: ['runtime-agents'], queryFn: () => runtimeService.agents() })
  const agentName = (id: string) => agents.data?.find((a) => a.id === id)?.name ?? id

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Layers}
        title="Deployments"
        description="Every agent version deployed to an environment, with health and lifecycle status."
        backTo={ROUTES.RUNTIME_DASHBOARD}
        backLabel="Runtime overview"
      />
      <RuntimeNav />

      <Card>
        <CardContent className="p-0">
          {deployments.isLoading ? (
            <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (deployments.data ?? []).length === 0 ? (
            <EmptyState icon={Layers} title="No deployments yet"
                        description="Publish an agent version, then deploy it from the agent's detail page." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent</TableHead>
                  <TableHead>Environment</TableHead>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Health</TableHead>
                  <TableHead>Deployed</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(deployments.data ?? []).map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="font-medium">
                      <Link to={ROUTES.RUNTIME_DEPLOYMENT_DETAIL.replace(':id', d.id)} className="hover:underline">
                        {agentName(d.agent_id)}
                      </Link>
                    </TableCell>
                    <TableCell><Badge variant="outline">{d.environment}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{d.deployment_strategy}</TableCell>
                    <TableCell><Badge variant={DEPLOYMENT_STATUS_VARIANT[d.status]}>{d.status}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{d.health_status}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(d.deployed_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
