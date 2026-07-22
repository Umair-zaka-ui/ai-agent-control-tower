import { cloneElement, useEffect, useId, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { Check, ClipboardList, Loader2, X } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/common'
import { Button, Card, CardContent, Input, Label, Select, Textarea } from '@/components/ui'
import { ROUTES } from '@/constants/routes'
import { runtimeService, type AgentRegistrationPayload } from '@/services'
import { cn } from '@/utils/cn'
import { RuntimeNav } from '../components/RuntimeNav'

/** Phase 5.1 §22.6 — draft autosave. The wizard has no server-side draft
 * record until the final submit, so an interrupted session (closed tab,
 * crash) would otherwise lose everything typed; this persists the in-flight
 * form to localStorage and restores it on the next visit. */
const DRAFT_STORAGE_KEY = 'runtime.agent.registration.draft.v1'

interface DraftFields {
  step: number
  name: string; displayName: string; description: string; businessPurpose: string
  agentType: string; tagsText: string; externalReference: string
  documentationUrl: string; repositoryUrl: string
  projectId: string; businessUnitId: string; departmentId: string; teamId: string
  ownerType: string; ownerId: string; technicalOwnerId: string; complianceOwnerId: string
  supportContact: string
  framework: string; frameworkVersion: string; entrypointType: string; entrypoint: string
  runtimeLanguage: string; systemInstructions: string
  inputSchemaText: string; outputSchemaText: string; configSchemaText: string
  criticality: string; riskLevel: string; dataClassification: string
  autonomyLevel: string; defaultEnvironment: string
  capabilityDeclarationsText: string; toolDeclarationsText: string
}

function loadDraft(): Partial<DraftFields> {
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Partial<DraftFields>) : {}
  } catch {
    return {}
  }
}

function clearDraft() {
  try { localStorage.removeItem(DRAFT_STORAGE_KEY) } catch { /* storage unavailable */ }
}

/** Phase 5.1 §22, §23 — the 10-step registration wizard. Step 10 (Submit)
 * is the Review step's action rather than its own empty screen — matching
 * this codebase's existing wizard pattern (see PolicyBuilder.tsx), where
 * review and submit are the same step. */
const STEPS = [
  'Basic Info', 'Org Placement', 'Ownership', 'Machine Identity', 'Technical Definition',
  'Contracts', 'Risk & Classification', 'Capabilities & Tools', 'Review',
]

const AGENT_TYPES = ['ASSISTANT', 'ANALYST', 'REVIEWER', 'AUTOMATION', 'WORKFLOW', 'DATA_PROCESSOR',
  'COMMUNICATION', 'SECURITY', 'DECISION_SUPPORT', 'COMPLIANCE', 'CUSTOM'].map((v) => ({ value: v, label: v }))
const FRAMEWORKS = ['NATIVE_PYTHON', 'LANGCHAIN', 'LANGGRAPH', 'SEMANTIC_KERNEL', 'CREWAI', 'AUTOGEN',
  'HTTP_SERVICE', 'SERVERLESS_FUNCTION', 'CONTAINER', 'CUSTOM'].map((v) => ({ value: v, label: v }))
const ENTRYPOINT_TYPES = ['PYTHON_MODULE', 'HTTP_ENDPOINT', 'CONTAINER_IMAGE', 'SERVERLESS_FUNCTION',
  'QUEUE_CONSUMER', 'WORKFLOW_REFERENCE', 'EXTERNAL_SERVICE', 'CUSTOM'].map((v) => ({ value: v, label: v }))
const OWNER_TYPES = ['USER', 'TEAM', 'DEPARTMENT', 'PROJECT', 'SERVICE_OWNER_GROUP'].map((v) => ({ value: v, label: v }))
const CRITICALITIES = ['LOW', 'MEDIUM', 'HIGH', 'MISSION_CRITICAL'].map((v) => ({ value: v, label: v }))
const RISK_LEVELS = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((v) => ({ value: v, label: v }))
const DATA_CLASSIFICATIONS = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED', 'REGULATED']
  .map((v) => ({ value: v, label: v }))
const AUTONOMY_LEVELS = ['ASSISTIVE', 'SUPERVISED', 'SEMI_AUTONOMOUS', 'AUTONOMOUS', 'CRITICAL_AUTONOMOUS']
  .map((v) => ({ value: v, label: v }))
const ENVIRONMENTS = ['DEVELOPMENT', 'TEST', 'STAGING', 'PRODUCTION', 'SANDBOX'].map((v) => ({ value: v, label: v }))

function parseJson(text: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  if (!text.trim()) return { ok: true, value: {} }
  try {
    const value = JSON.parse(text)
    return { ok: true, value }
  } catch (e) {
    return { ok: false, error: (e as Error).message }
  }
}

function parseTags(text: string): string[] {
  return text.split(',').map((t) => t.trim()).filter(Boolean)
}

export function RegistrationWizardPage() {
  const navigate = useNavigate()
  const draftRef = useRef<Partial<DraftFields> | undefined>(undefined)
  if (draftRef.current === undefined) draftRef.current = loadDraft()
  const draft = draftRef.current
  const [draftRestored, setDraftRestored] = useState(() => Boolean(draft.name || draft.entrypoint))

  const [step, setStep] = useState(() => draft.step ?? 0)
  const [errors, setErrors] = useState<string[]>([])

  // Step 1 — basic info
  const [name, setName] = useState(() => draft.name ?? '')
  const [displayName, setDisplayName] = useState(() => draft.displayName ?? '')
  const [description, setDescription] = useState(() => draft.description ?? '')
  const [businessPurpose, setBusinessPurpose] = useState(() => draft.businessPurpose ?? '')
  const [agentType, setAgentType] = useState(() => draft.agentType ?? 'ASSISTANT')
  const [tagsText, setTagsText] = useState(() => draft.tagsText ?? '')
  const [externalReference, setExternalReference] = useState(() => draft.externalReference ?? '')
  const [documentationUrl, setDocumentationUrl] = useState(() => draft.documentationUrl ?? '')
  const [repositoryUrl, setRepositoryUrl] = useState(() => draft.repositoryUrl ?? '')

  // Step 2 — org placement
  const [projectId, setProjectId] = useState(() => draft.projectId ?? '')
  const [businessUnitId, setBusinessUnitId] = useState(() => draft.businessUnitId ?? '')
  const [departmentId, setDepartmentId] = useState(() => draft.departmentId ?? '')
  const [teamId, setTeamId] = useState(() => draft.teamId ?? '')

  // Step 3 — ownership
  const [ownerType, setOwnerType] = useState(() => draft.ownerType ?? 'USER')
  const [ownerId, setOwnerId] = useState(() => draft.ownerId ?? '')
  const [technicalOwnerId, setTechnicalOwnerId] = useState(() => draft.technicalOwnerId ?? '')
  const [complianceOwnerId, setComplianceOwnerId] = useState(() => draft.complianceOwnerId ?? '')
  const [supportContact, setSupportContact] = useState(() => draft.supportContact ?? '')

  // Step 5 — technical definition
  const [framework, setFramework] = useState(() => draft.framework ?? 'CUSTOM')
  const [frameworkVersion, setFrameworkVersion] = useState(() => draft.frameworkVersion ?? '')
  const [entrypointType, setEntrypointType] = useState(() => draft.entrypointType ?? 'PYTHON_MODULE')
  const [entrypoint, setEntrypoint] = useState(() => draft.entrypoint ?? '')
  const [runtimeLanguage, setRuntimeLanguage] = useState(() => draft.runtimeLanguage ?? '')
  const [systemInstructions, setSystemInstructions] = useState(() => draft.systemInstructions ?? '')

  // Step 6 — contracts
  const [inputSchemaText, setInputSchemaText] = useState(() => draft.inputSchemaText ?? '{}')
  const [outputSchemaText, setOutputSchemaText] = useState(() => draft.outputSchemaText ?? '{}')
  const [configSchemaText, setConfigSchemaText] = useState(() => draft.configSchemaText ?? '{}')
  const [samplePayloadText, setSamplePayloadText] = useState('{}')
  const [sampleResult, setSampleResult] = useState<string | null>(null)

  // Step 7 — risk/data/autonomy
  const [criticality, setCriticality] = useState(() => draft.criticality ?? 'MEDIUM')
  const [riskLevel, setRiskLevel] = useState(() => draft.riskLevel ?? 'LOW')
  const [dataClassification, setDataClassification] = useState(() => draft.dataClassification ?? 'INTERNAL')
  const [autonomyLevel, setAutonomyLevel] = useState(() => draft.autonomyLevel ?? 'ASSISTIVE')
  const [defaultEnvironment, setDefaultEnvironment] = useState(() => draft.defaultEnvironment ?? 'DEVELOPMENT')

  // Step 8 — capability/tool intent
  const [capabilityDeclarationsText, setCapabilityDeclarationsText] = useState(() => draft.capabilityDeclarationsText ?? '')
  const [toolDeclarationsText, setToolDeclarationsText] = useState(() => draft.toolDeclarationsText ?? '')

  useEffect(() => {
    const fields: DraftFields = {
      step, name, displayName, description, businessPurpose, agentType, tagsText, externalReference,
      documentationUrl, repositoryUrl, projectId, businessUnitId, departmentId, teamId, ownerType, ownerId,
      technicalOwnerId, complianceOwnerId, supportContact, framework, frameworkVersion, entrypointType,
      entrypoint, runtimeLanguage, systemInstructions, inputSchemaText, outputSchemaText, configSchemaText,
      criticality, riskLevel, dataClassification, autonomyLevel, defaultEnvironment,
      capabilityDeclarationsText, toolDeclarationsText,
    }
    try { localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(fields)) } catch { /* storage unavailable */ }
  }, [step, name, displayName, description, businessPurpose, agentType, tagsText, externalReference,
      documentationUrl, repositoryUrl, projectId, businessUnitId, departmentId, teamId, ownerType, ownerId,
      technicalOwnerId, complianceOwnerId, supportContact, framework, frameworkVersion, entrypointType,
      entrypoint, runtimeLanguage, systemInstructions, inputSchemaText, outputSchemaText, configSchemaText,
      criticality, riskLevel, dataClassification, autonomyLevel, defaultEnvironment,
      capabilityDeclarationsText, toolDeclarationsText])

  const discardDraft = () => {
    clearDraft()
    setDraftRestored(false)
    window.location.reload()
  }

  const register = useMutation({
    mutationFn: (payload: AgentRegistrationPayload) => runtimeService.registerAgent(payload),
    onSuccess: (agent) => {
      clearDraft()
      toast.success(`${agent.name} registered as a draft.`)
      navigate(ROUTES.RUNTIME_AGENT_DETAIL.replace(':id', agent.id))
    },
    onError: (e: unknown) => toast.error((e as { message?: string }).message ?? 'Registration failed'),
  })

  const validateStep = (): boolean => {
    const found: string[] = []
    if (step === 0) {
      if (!name.trim()) found.push('Name is required.')
      if (!description.trim()) found.push('Description is required.')
      if (!businessPurpose.trim()) found.push('Business purpose is required.')
    }
    if (step === 2 && !ownerId.trim()) {
      found.push('A business owner (user ID) is required.')
    }
    if (step === 4 && !entrypoint.trim()) {
      found.push('Entrypoint is required.')
    }
    if (step === 5) {
      for (const [label, text] of [['Input schema', inputSchemaText], ['Output schema', outputSchemaText],
                                    ['Configuration schema', configSchemaText]] as const) {
        const parsed = parseJson(text)
        if (!parsed.ok) found.push(`${label} is not valid JSON: ${parsed.error}`)
      }
    }
    setErrors(found)
    return found.length === 0
  }

  const next = () => { if (validateStep()) setStep((s) => Math.min(s + 1, STEPS.length - 1)) }
  const back = () => setStep((s) => Math.max(s - 1, 0))

  const testSample = () => {
    const schema = parseJson(inputSchemaText)
    const payload = parseJson(samplePayloadText)
    if (!schema.ok || !payload.ok) { setSampleResult('Fix the JSON above first.'); return }
    try {
      // Lightweight client-side structural check; the authoritative check is
      // the server's /schemas/test endpoint, run after the agent exists.
      setSampleResult('Sample payload is well-formed JSON — full schema validation runs after registration '
        + '(Contracts tab → Validation) once the agent exists.')
    } catch (e) {
      setSampleResult((e as Error).message)
    }
  }

  const submit = () => {
    if (!validateStep()) return
    const payload: AgentRegistrationPayload = {
      name: name.trim(), display_name: displayName.trim() || undefined,
      description: description.trim(), business_purpose: businessPurpose.trim(),
      agent_type: agentType, tags: parseTags(tagsText),
      external_reference: externalReference.trim() || undefined,
      documentation_url: documentationUrl.trim() || undefined,
      repository_url: repositoryUrl.trim() || undefined,
      project_id: projectId.trim() || undefined, business_unit_id: businessUnitId.trim() || undefined,
      department_id: departmentId.trim() || undefined, team_id: teamId.trim() || undefined,
      owner_type: ownerType, owner_id: ownerId.trim(),
      technical_owner_id: technicalOwnerId.trim() || undefined,
      compliance_owner_id: complianceOwnerId.trim() || undefined,
      support_contact: supportContact.trim() || undefined,
      definition: {
        name: `${name.trim()} definition`, framework, framework_version: frameworkVersion.trim() || undefined,
        entrypoint_type: entrypointType, entrypoint: entrypoint.trim(),
        runtime_language: runtimeLanguage.trim() || undefined,
        system_instructions: systemInstructions.trim() || undefined,
        input_schema: (parseJson(inputSchemaText) as { ok: true; value: Record<string, unknown> }).value,
        output_schema: (parseJson(outputSchemaText) as { ok: true; value: Record<string, unknown> }).value,
        configuration_schema: (parseJson(configSchemaText) as { ok: true; value: Record<string, unknown> }).value,
        capability_declarations: parseTags(capabilityDeclarationsText),
        tool_declarations: parseTags(toolDeclarationsText),
      },
      criticality, risk_level: riskLevel, data_classification: dataClassification,
      autonomy_level: autonomyLevel, default_environment: defaultEnvironment,
    }
    register.mutate(payload)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={ClipboardList}
        title="Register a new agent"
        description="Complete the registration wizard, then validate, approve and activate it from its detail page."
        backTo={ROUTES.RUNTIME_AGENTS}
        backLabel="Agent inventory"
      />
      <RuntimeNav />

      {draftRestored && (
        <div className="flex items-center justify-between rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
          <span className="text-muted-foreground">Restored your unsaved draft from a previous session.</span>
          <Button type="button" variant="ghost" size="sm" onClick={discardDraft}>
            <X className="h-3.5 w-3.5" /> Discard draft
          </Button>
        </div>
      )}

      <Stepper current={step} />

      <Card>
        <CardContent className="space-y-5 p-6">
          {errors.length > 0 && (
            <ul className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {errors.map((e) => <li key={e}>{e}</li>)}
            </ul>
          )}

          {step === 0 && (
            <div className="space-y-4">
              <Field label="Agent name *">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Claims Denial Review Agent" />
              </Field>
              <Field label="Display name">
                <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
              </Field>
              <Field label="Description *">
                <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
              </Field>
              <Field label="Business purpose *">
                <Textarea value={businessPurpose} onChange={(e) => setBusinessPurpose(e.target.value)} rows={2}
                          placeholder="Reduce manual denial analysis and improve resubmission accuracy." />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Agent type"><Select options={AGENT_TYPES} value={agentType}
                                                  onChange={(e) => setAgentType(e.target.value)} /></Field>
                <Field label="Tags (comma-separated)">
                  <Input value={tagsText} onChange={(e) => setTagsText(e.target.value)} placeholder="healthcare, claims" />
                </Field>
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="External reference">
                  <Input value={externalReference} onChange={(e) => setExternalReference(e.target.value)} />
                </Field>
                <Field label="Documentation URL">
                  <Input value={documentationUrl} onChange={(e) => setDocumentationUrl(e.target.value)} />
                </Field>
                <Field label="Repository URL">
                  <Input value={repositoryUrl} onChange={(e) => setRepositoryUrl(e.target.value)} />
                </Field>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Optional — scope this agent to a project and org-hierarchy level. Business unit/department/team
                are derived automatically from the project when left blank.
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Project ID"><Input value={projectId} onChange={(e) => setProjectId(e.target.value)} /></Field>
                <Field label="Business unit ID">
                  <Input value={businessUnitId} onChange={(e) => setBusinessUnitId(e.target.value)} />
                </Field>
                <Field label="Department ID"><Input value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} /></Field>
                <Field label="Team ID"><Input value={teamId} onChange={(e) => setTeamId(e.target.value)} /></Field>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Owner type"><Select options={OWNER_TYPES} value={ownerType}
                                                  onChange={(e) => setOwnerType(e.target.value)} /></Field>
                <Field label="Business owner (user ID) *">
                  <Input value={ownerId} onChange={(e) => setOwnerId(e.target.value)} />
                </Field>
                <Field label="Technical owner (user ID)">
                  <Input value={technicalOwnerId} onChange={(e) => setTechnicalOwnerId(e.target.value)} />
                </Field>
                <Field label="Compliance owner (user ID)">
                  <Input value={complianceOwnerId} onChange={(e) => setComplianceOwnerId(e.target.value)} />
                </Field>
              </div>
              <Field label="Support contact">
                <Input value={supportContact} onChange={(e) => setSupportContact(e.target.value)} />
              </Field>
              <p className="text-xs text-muted-foreground">
                A technical owner is required for HIGH/MISSION_CRITICAL agents before activation; a compliance
                owner is required for MISSION_CRITICAL or HIGH/CRITICAL-risk agents.
              </p>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3 rounded-md border border-border bg-muted/30 p-4 text-sm">
              <p className="font-medium text-foreground">Machine identity is associated after registration.</p>
              <p className="text-muted-foreground">
                An agent&apos;s machine identity can only be created once the agent record exists. Once this
                wizard finishes, open the agent&apos;s <strong>Identity</strong> tab to create or associate one —
                it&apos;s required before the agent can be activated.
              </p>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Framework"><Select options={FRAMEWORKS} value={framework}
                                                 onChange={(e) => setFramework(e.target.value)} /></Field>
                <Field label="Framework version">
                  <Input value={frameworkVersion} onChange={(e) => setFrameworkVersion(e.target.value)} />
                </Field>
                <Field label="Entrypoint type"><Select options={ENTRYPOINT_TYPES} value={entrypointType}
                                                        onChange={(e) => setEntrypointType(e.target.value)} /></Field>
                <Field label="Runtime language">
                  <Input value={runtimeLanguage} onChange={(e) => setRuntimeLanguage(e.target.value)} placeholder="python" />
                </Field>
              </div>
              <Field label="Entrypoint *">
                <Input value={entrypoint} onChange={(e) => setEntrypoint(e.target.value)}
                       placeholder="agents.claims:handle" className="font-mono text-xs" />
              </Field>
              <Field label="System instructions">
                <Textarea value={systemInstructions} onChange={(e) => setSystemInstructions(e.target.value)} rows={3} />
              </Field>
            </div>
          )}

          {step === 5 && (
            <div className="space-y-4">
              <Field label="Input JSON Schema">
                <Textarea value={inputSchemaText} onChange={(e) => setInputSchemaText(e.target.value)} rows={4}
                          className="font-mono text-xs" />
              </Field>
              <Field label="Output JSON Schema">
                <Textarea value={outputSchemaText} onChange={(e) => setOutputSchemaText(e.target.value)} rows={4}
                          className="font-mono text-xs" />
              </Field>
              <Field label="Configuration JSON Schema">
                <Textarea value={configSchemaText} onChange={(e) => setConfigSchemaText(e.target.value)} rows={4}
                          className="font-mono text-xs" />
              </Field>
              <div className="space-y-2 rounded-md border border-border p-3">
                <Label>Sample input payload</Label>
                <Textarea value={samplePayloadText} onChange={(e) => setSamplePayloadText(e.target.value)} rows={3}
                          className="font-mono text-xs" />
                <Button type="button" variant="outline" size="sm" onClick={testSample}>Check JSON</Button>
                {sampleResult && <p className="text-xs text-muted-foreground">{sampleResult}</p>}
              </div>
            </div>
          )}

          {step === 6 && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Criticality"><Select options={CRITICALITIES} value={criticality}
                                                  onChange={(e) => setCriticality(e.target.value)} /></Field>
              <Field label="Risk level"><Select options={RISK_LEVELS} value={riskLevel}
                                                onChange={(e) => setRiskLevel(e.target.value)} /></Field>
              <Field label="Data classification"><Select options={DATA_CLASSIFICATIONS} value={dataClassification}
                                                          onChange={(e) => setDataClassification(e.target.value)} /></Field>
              <Field label="Autonomy level"><Select options={AUTONOMY_LEVELS} value={autonomyLevel}
                                                     onChange={(e) => setAutonomyLevel(e.target.value)} /></Field>
              <Field label="Default environment"><Select options={ENVIRONMENTS} value={defaultEnvironment}
                                                          onChange={(e) => setDefaultEnvironment(e.target.value)} /></Field>
            </div>
          )}

          {step === 7 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Declare intended capabilities and tools — these are declarations of intent only and do not grant
                access; real assignment happens on the agent&apos;s Capabilities/Tools tabs after registration.
              </p>
              <Field label="Capability declarations (comma-separated)">
                <Input value={capabilityDeclarationsText} onChange={(e) => setCapabilityDeclarationsText(e.target.value)}
                       placeholder="read_claims_db, generate_summary" />
              </Field>
              <Field label="Tool declarations (comma-separated)">
                <Input value={toolDeclarationsText} onChange={(e) => setToolDeclarationsText(e.target.value)}
                       placeholder="crm_lookup, email_notify" />
              </Field>
            </div>
          )}

          {step === 8 && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium">Review</h3>
              <dl className="divide-y divide-border rounded-md border border-border text-sm">
                {[
                  ['Name', name || '—'], ['Agent type', agentType], ['Business owner', ownerId || '—'],
                  ['Framework', framework], ['Entrypoint', entrypoint || '—'],
                  ['Criticality', criticality], ['Risk level', riskLevel],
                  ['Data classification', dataClassification], ['Autonomy level', autonomyLevel],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between px-3 py-2">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="text-right font-medium">{value}</dd>
                  </div>
                ))}
              </dl>
              <p className="text-xs text-muted-foreground">
                Submitting creates the agent as a DRAFT. Duplicate detection, full validation and approval happen
                as separate steps from the agent&apos;s detail page.
              </p>
            </div>
          )}

          <div className="flex items-center justify-between pt-2">
            <Button type="button" variant="ghost" onClick={() => (step === 0 ? navigate(ROUTES.RUNTIME_AGENTS) : back())}>
              {step === 0 ? 'Cancel' : 'Back'}
            </Button>
            {step < STEPS.length - 1 ? (
              <Button type="button" onClick={next}>Next</Button>
            ) : (
              <Button type="button" disabled={register.isPending} onClick={submit}>
                {register.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Register agent
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactElement<{ id?: string }> }) {
  const id = useId()
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {cloneElement(children, { id })}
    </div>
  )
}

function Stepper({ current }: { current: number }) {
  return (
    <ol className="flex items-center gap-1 overflow-x-auto pb-1">
      {STEPS.map((label, i) => (
        <li key={label} className="flex shrink-0 items-center gap-1.5">
          <span
            className={cn(
              'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-medium',
              i < current && 'bg-success text-success-foreground',
              i === current && 'bg-primary text-primary-foreground',
              i > current && 'bg-muted text-muted-foreground',
            )}
          >
            {i < current ? <Check className="h-3 w-3" /> : i + 1}
          </span>
          <span className={cn('hidden text-[11px] whitespace-nowrap xl:block',
                              i === current ? 'text-foreground' : 'text-muted-foreground')}>
            {label}
          </span>
          {i < STEPS.length - 1 ? <span className="mx-1 h-px w-3 shrink-0 bg-border" /> : null}
        </li>
      ))}
    </ol>
  )
}
