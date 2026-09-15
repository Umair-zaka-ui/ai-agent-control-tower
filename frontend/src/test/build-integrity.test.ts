import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const run = promisify(execFile)
const ROOT = resolve(process.cwd())

/**
 * Build integrity — the guard that should have existed already.
 *
 * Phase 4.9 shipped `TraceDetailPage.tsx` importing `TraceContentResponse` from
 * the `@/services` barrel, which only ever re-exported the *value*
 * `observabilityService`. `tsc -b` had been failing on `main` ever since, and
 * `npm run build` with it — while the test suite stayed green through four
 * subsequent phases, because **vitest transpiles; it does not typecheck**. A
 * green suite was actively masking a broken production build.
 *
 * That is the failure this test exists to make impossible to repeat. It runs
 * the real compiler over the real project and fails loudly here, in the surface
 * everyone already watches, rather than at a deploy nobody runs locally.
 *
 * It is deliberately a *test* and not only a CI step: this repository has no CI
 * workflows, so a check that lives only in a pipeline would not exist at all.
 * If CI is added later this becomes redundant belt-and-braces, which is a much
 * better problem than the one it replaces.
 */
describe('build integrity', () => {
  it(
    'typechecks the whole frontend — vitest does not, and a broken build once hid behind it',
    async () => {
      try {
        await run('npx', ['tsc', '-b', '--noEmit'], { cwd: ROOT, shell: true })
      } catch (error) {
        const e = error as { stdout?: string; stderr?: string }
        const output = `${e.stdout ?? ''}${e.stderr ?? ''}`.trim()
        throw new Error(
          'tsc -b failed, so `npm run build` is broken even though the rest of '
          + 'this suite passes. vitest does not typecheck, which is exactly how '
          + `this went unnoticed for four phases once before:\n\n${output}`,
        )
      }
    },
    180_000,
  )
})
