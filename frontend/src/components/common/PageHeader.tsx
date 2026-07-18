import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'

interface PageHeaderProps {
  title: string
  description?: string
  /** Optional leading icon chip next to the title. */
  icon?: LucideIcon
  /** Route to the parent page. When set, renders a "← label" link above the
   * title — the only way back for pages reached by deep link rather than the
   * primary sidebar (SRS §8). */
  backTo?: string
  /** Label for the back link, e.g. "Audit overview". Defaults to "Back". */
  backLabel?: string
  /** Right-aligned actions (buttons, filters). */
  actions?: ReactNode
}

/** Consistent page title block used at the top of every page. */
export function PageHeader({ title, description, icon: Icon, backTo, backLabel, actions }: PageHeaderProps) {
  return (
    <div className="space-y-3">
      {backTo ? (
        <Link
          to={backTo}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          {backLabel ?? 'Back'}
        </Link>
      ) : null}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          {Icon ? (
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
              <Icon className="h-5 w-5" aria-hidden />
            </span>
          ) : null}
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
            {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
          </div>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  )
}
