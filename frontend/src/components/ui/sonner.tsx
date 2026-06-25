import { Toaster as SonnerToaster } from 'sonner'

/** App toaster, themed to match the dark enterprise palette. */
function Toaster() {
  return (
    <SonnerToaster
      theme="dark"
      position="top-right"
      richColors
      closeButton
      toastOptions={{
        classNames: {
          toast: 'bg-card border border-border text-card-foreground',
          description: 'text-muted-foreground',
        },
      }}
    />
  )
}

export { Toaster }
