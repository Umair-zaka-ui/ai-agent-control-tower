This message itself is the complete instruction.
There is NO attachment and NO external document to read.

Do not look for a file.
Do not execute DT1-S1 yet.
Do not modify the repository.

Your task is to WRITE the revised Stage-1 implementation prompt.

# ACT DT1-S1 — ARCHITECTURE CORRECTION

The previous DT1-S1 prompt is NOT authorized for execution because it reverted
several approved DT1-v2 architecture decisions.

Create a corrected, self-contained:

# ACT DT1 — STAGE 1 IMPLEMENTATION PROMPT v2

that I can later paste into a fresh Claude Code session for execution.

The corrected prompt MUST incorporate every requirement below.

======================================================================
1. CANONICAL ESTATE — NOT ADDITIVE FEATURE COHORTS
======================================================================

Target approximately:

50–60 CANONICAL AGENTS.

Do NOT use additive feature cohorts such as:

20 native
+ 15 gateway
+ 10 observed
+ 8 shadow
+ separate dangerous-dependency agents
+ separate IAM agents
+ separate F6-1 agents.

Those characteristics overlap.

One canonical agent may simultaneously be:

EXTERNAL
SHADOW
UNOWNED
OVER_PRIVILEGED
MCP_DEPENDENT
GATEWAY_ENFORCED
UNKNOWN_PROVENANCE

Example conceptually:

Finance Research Assistant

origin: EXTERNAL
inventory_status: SHADOW
owner: UNKNOWN
credential: finance-shared-service-account
credential_posture: OVER_PRIVILEGED
mcp: finance-mcp-legacy
sensitive_reach: EMPLOYEE_PAYROLL_DATABASE
gateway_relationship: ENFORCED
process_requirement: ACTIVE_REAL_PROCESS_REQUIRED_STAGE2
detection_characteristic: F6-1_RELEVANT

Do NOT assume those are actual ACT field names.

The executing Stage-1 session must first inspect the live schema and use real
ACT terminology.

Stage 1 must create an:

AGENT_PROPERTY_MATRIX

mapping each canonical agent to its overlapping properties.

======================================================================
2. HEALTHY CONTROL GROUP — MANDATORY
======================================================================

Approximately 10–15 of the canonical agents must be deliberately
well-governed control agents.

They should have, where applicable:

known accountable owner
valid lifecycle
approved identity
approved tools
approved MCP
least-privilege credential
expected delegation
appropriate resource access
normal provenance
no serious planted security condition.

The purpose is later measurement of specificity and false positives.

The estate must NOT assume every agent is risky.

Stage 1 records their objective state.

Stage 2 later evaluates whether ACT incorrectly produces serious findings
against them.

======================================================================
3. SCHEMA GROUNDING MUST HAPPEN FIRST
======================================================================

The Stage-1 execution prompt must begin with inspection of the LIVE ACT
repository.

Verify and report the actual relevant architecture, including where present:

canonical agent model
real field names
real enums
origin representation
control-state representation
external-reference representation
ownership representation
lifecycle representation
discovery sources
discovery runs
discovery observations
reconciliation contracts
control-graph edges
edge types
Tool/MCP representation
credential/resource representation
posture/findings representation
external-governance modes
gateway/control semantics
cloud discovery adapter structures
tenant boundaries.

Also record:

git HEAD
branch
origin/main relationship
worktree state
migration head/current where accessible
relevant blocker/merge state.

Repository reality overrides this prompt.

If the live model cannot be inspected or materially contradicts DT1
assumptions:

STOP AND REPORT.

Do not seal a guessed schema.

======================================================================
4. SPLIT OBJECTIVE TRUTH FROM ACT OBSERVABILITY
======================================================================

Do NOT create the old combined manifest containing:

objective truth
+
EXPECTED_FIND
+
EXPECTED_MISS
+
EXPECTED_REFUSAL
+
manually authored expected ACT answers.

Instead Stage 1 must produce TWO conceptually separate artifacts.

----------------------------------------------------------------------
A. estate_truth
----------------------------------------------------------------------

Contains OBJECTIVE SYNTHETIC ENTERPRISE REALITY ONLY.

Examples:

agents
owners
business owners
technical owners
identities
service accounts
credentials
permissions
tools
MCP servers
resources
dependencies
delegations
environments
lifecycle
approval state
origin/provenance
actual A2A relationships
actual memory state
actual gateway relationships
actual sensitive-resource reachability.

estate_truth must describe what exists.

It must NOT describe what ACT is expected to output.

----------------------------------------------------------------------
B. observability_contract
----------------------------------------------------------------------

Describes what the CURRENT ACT architecture can legitimately:

OBSERVE
PARTIALLY_OBSERVE
NOT_OBSERVE
ENFORCE
REFUSE

through existing evidence and control boundaries.

Every NOT_OBSERVABLE classification must have an architectural justification.

For example:

relationship exists in estate_truth
+
no current ACT evidence source observes that relationship
=
NOT_OBSERVABLE

Do NOT write:

"ACT is known to miss this, therefore EXPECTED_MISS."

Known product weakness alone is not sufficient justification.

The contract must identify the actual evidence/control boundary.

======================================================================
5. STAGE-2 EXPECTATIONS MUST BE DERIVABLE
======================================================================

Stage 1 does NOT build the ACT evaluator.

However, estate_truth + observability_contract must be designed so Stage 2 can
derive expectations rather than receiving hand-authored answers.

Example:

estate_truth:

Agent A
→ Credential X
→ MCP Y
→ Employee Payroll Database

If all relevant relationships are observable through existing ACT evidence
boundaries, Stage 2 can derive that ACT should reconstruct that path.

Another example:

estate_truth:

Agent A
→ real external A2A handoff
→ Agent B

If repository inspection proves current ACT has no evidence source capable of
observing that external handoff, observability_contract may classify that
relationship:

NOT_OBSERVABLE

with the architectural reason.

A truthful absence can then be evaluated without circularly defining ACT's
known miss as success.

======================================================================
6. ADVERSARIAL HONESTY REMAINS MANDATORY
======================================================================

The estate must still contain conditions exercising known gaps such as:

F6-1
I-1
I-2

where those remain valid according to live repository truth.

But these conditions are OBJECTIVE estate conditions.

Do not encode:

EXPECTED_MISS = PASS

directly into estate_truth.

Instead:

estate_truth records the real condition.

observability_contract records the legitimate evidence boundary.

Stage 2 later derives/evaluates the expected result.

If repository inspection shows any of these gaps have been fixed or changed:

REPORT IT.

Do not preserve stale assumptions for the sake of the demo.

======================================================================
7. F6-1 IS NOT THE FIVE-MINUTE HERO
======================================================================

Do not describe F6-1 as the primary five-minute demo's "hero honesty beat."

F6-1 remains important and must eventually appear in:

technical deep dive
evidence pack
limitations documentation

if still present in repository reality.

The primary five-minute buyer demo later focuses on:

estate
shadow discovery
blast radius
authority
truthful refusal
real effect-verified containment
evidence provenance
design-partner invitation.

Stage 1 itself does not build that demo.

======================================================================
8. GENERIC SENSITIVE RESOURCE
======================================================================

Use generic fictional enterprise-sensitive resources such as:

Employee Payroll Database
Employee Compensation Records
Financial Records

for the canonical scenario.

Do NOT use PHI as the default.

Healthcare-specific scenarios may be future optional vertical demonstrations.

All records are synthetic.

No real employee/customer/patient information.

======================================================================
9. DETERMINISTIC GENERATOR
======================================================================

Stage 1 eventually builds a deterministic seeded generator.

Requirement:

same seed
+
same generator version
+
same schema-grounding version/input
=
byte-identical canonical generated artifacts
=
identical content hashes.

Use canonical serialization.

Stable ordering is mandatory.

Do not allow:

wall-clock time
random UUID generation
unordered maps/sets
environment-dependent paths
database-generated IDs

to make deterministic artifacts differ between identical runs unless those
values are explicitly normalized outside the content being hashed.

The default demo seed must be explicit.

Different seeds may create controlled variation.

The canonical demo always uses the approved fixed seed.

======================================================================
10. HASH / SEAL DESIGN
======================================================================

Do NOT make the anchor timestamp part of the deterministic content hash.

At minimum produce independent hashes for:

estate_truth
observability_contract

and optionally:

agent_property_matrix
combined_root

Use SHA-256 unless repository conventions require an equally appropriate
existing mechanism.

Then create a SEPARATE anchor record containing approximately:

seed
generator_version
schema_grounding_version
git_commit
estate_truth_sha256
observability_contract_sha256
agent_property_matrix_sha256 if applicable
combined_root_sha256
created_at

The CONTENT hashes must reproduce.

The anchor timestamp records when those already-computed hashes were sealed.

Avoid circular/self-referential hashing.

Stage 2 later verifies that this anchor predates ACT's first DT1 execution.

======================================================================
11. REALITY CLASSIFICATION
======================================================================

Every canonical agent must carry a Stage-1 execution/reality classification.

Use concepts equivalent to:

ACTIVE_REAL_PROCESS_REQUIRED_STAGE2
REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2
SIMULATED_ASSET
DORMANT_ASSET

unless live repository conventions suggest better names.

Stage 1 specifies these classifications only.

Stage 1 does NOT instantiate external processes.

Gateway/containment proof agents must later become genuinely independent
processes in Stage 2.

External A2A proof agents must later become genuinely independent processes
where required.

At least one later discovery path must cross a genuine process/network
boundary.

Stage 1 only specifies those requirements.

======================================================================
12. TRUTHFUL-REFUSAL SCENARIO MUST EXIST IN THE ESTATE
======================================================================

The objective estate must contain at least one external agent for which:

ACT does NOT own/control the external process

but

ACT DOES control a meaningful boundary capability such as a gateway/tool grant.

This enables Stage 2/3 to prove:

"ACT cannot truthfully suspend this process."

followed by:

"ACT can revoke authority it genuinely controls."

The estate must make that distinction objectively real.

Stage 1 does not execute containment.

======================================================================
13. SELF-VALIDATOR
======================================================================

Stage 1 must eventually build an independent lab self-validator.

It validates the GENERATED ARTIFACTS, not ACT product behavior.

It must check at least:

canonical schema validity
referential integrity
canonical-agent uniqueness
stable identifiers
ownership consistency
identity references
credential references
tool references
MCP references
resource references
dependency references
delegation references
tenant isolation
healthy control-group count
adversarial-condition presence
F6-1 condition represented where still applicable
I-1 condition represented where still applicable
I-2 condition represented where still applicable
truthful-refusal scenario represented
Stage-2 real-process markings
no forbidden real data
no real secrets
deterministic canonical serialization
deterministic content hashes
no ACT execution artifacts
empty production ACT diff.

The validator MUST be capable of failing.

======================================================================
14. NEGATIVE VALIDATOR TESTS
======================================================================

Stage 1 must include negative tests proving the validator rejects malformed
artifacts.

Examples:

duplicate canonical agent
missing owner reference
invalid credential reference
invalid MCP reference
cross-tenant relationship
missing healthy control group
missing required adversarial condition
missing truthful-refusal scenario
non-deterministic artifact
tampered estate_truth after sealing
tampered observability_contract after sealing
real-looking secret accidentally inserted.

Do not merely test the happy path.

======================================================================
15. EMPTY ACT PRODUCT DIFF — HARD GATE
======================================================================

DT1-S1 must not modify production ACT merely to make the Digital Twin work.

Stage 1 may add isolated:

lab tooling
fixtures/specifications
DT1 documentation
DT1 tests

according to repository architecture.

It must not change:

production ACT runtime behavior
production models
production APIs
production policy behavior
production graph behavior
production containment behavior.

No ACT migration.

If schema grounding reveals that DT1 cannot be represented without modifying
ACT:

STOP.

Record the issue as a DEMO_GAP / architecture conflict.

Do not fix ACT inside S1.

======================================================================
16. STAGE-1 BOUNDARY
======================================================================

DT1-S1 MAY eventually build:

SCHEMA_GROUNDING
ESTATE_GENERATOR
AGENT_PROPERTY_MATRIX
ESTATE_TRUTH
OBSERVABILITY_CONTRACT
HASH_ANCHOR
MANIFEST_SELF_VALIDATOR
VALIDATOR_NEGATIVE_TESTS
DT1_S1_REPORT

DT1-S1 MUST NOT:

run ACT against the estate
run ACT discovery against the estate
produce ACT findings
stand up real external agent cohorts
perform containment
build the Stage-2 ACT evaluator
build the five-minute demo
build the technical demo
modify ACT production behavior
create ACT schema migrations
begin V10
begin M6.

======================================================================
17. REPOSITORY LOCATION
======================================================================

Do not assume:

lab/dt1

or:

docs/validation/dt1

until the executing session inspects repository conventions.

Choose the location consistent with existing architecture.

The Digital Twin must remain isolated from production ACT dependencies.

Where useful, add a mechanical architecture guard proving production ACT does
not import Digital Twin code.

======================================================================
18. STAGE-1 REPORT
======================================================================

The eventual executing S1 prompt must require:

# ACT DT1 — STAGE 1 REPORT

including:

A. EXECUTIVE VERDICT

B. VERIFIED REPOSITORY / SCHEMA GROUNDING
- branch
- HEAD
- origin/main relationship
- worktree
- migrations
- relevant closures/merges
- actual canonical models/enums/fields used.

C. CANONICAL ESTATE
- total canonical agents
- property distribution
- overlapping-property examples
- healthy control-group count
- reality classifications.

D. ESTATE_TRUTH
- schema
- counts
- objective relationships
- adversarial conditions.

E. OBSERVABILITY_CONTRACT
- OBSERVE
- PARTIALLY_OBSERVE
- NOT_OBSERVE
- ENFORCE
- REFUSE
- architectural justification for each non-observable/control boundary.

F. HASH / SEAL
- seed
- generator version
- schema-grounding version
- individual content hashes
- combined root
- anchor timestamp
- git commit.

G. DETERMINISM PROOF
Regenerate at least 3 times from the same seed and prove byte-identical
canonical artifacts and identical content hashes.

H. SELF-VALIDATOR
- positive validation
- negative tests
- proof validator can fail.

I. SECURITY / PRIVACY
- no real secrets
- no real PII
- synthetic-data confirmation.

J. PRODUCT BOUNDARY
- no ACT execution
- no ACT product changes
- no ACT migrations
- empty production ACT diff.

K. CONFLICTS / DEMO GAPS

L. ARTIFACTS

M. GIT
- branch
- commits
- push state
- no merge.

N. STAGE-2 READINESS
- which assets later require real processes
- which services must later be instantiated
- what Stage 2 must evaluate.

End the eventual S1 execution report with exactly one:

VERDICT: DT1-S1 PASSED — READY FOR STAGE-2 REVIEW

VERDICT: DT1-S1 CONDITIONAL — REVIEW REQUIRED

VERDICT: DT1-S1 BLOCKED

Then STOP.

======================================================================
19. YOUR TASK NOW
======================================================================

You are NOT executing any of the above now.

You are WRITING the implementation prompt that a later fresh Claude Code
session will execute.

Return:

# ACT DT1 — STAGE 1 IMPLEMENTATION PROMPT v2

It must be self-contained.

It must instruct the future executing session to:

1. inspect repository/schema first;
2. STOP on material conflict;
3. implement Stage 1 only;
4. run Stage-1 tests/validator;
5. prove determinism;
6. seal the objective artifacts;
7. verify empty ACT product diff;
8. commit/push the DT1-S1 branch;
9. return the required report;
10. STOP before Stage 2.

Do NOT execute it now.

======================================================================
20. ARCHITECTURE DELTA FROM REJECTED S1
======================================================================

At the end of your response include:

# ARCHITECTURE DELTA FROM REJECTED S1

Explicitly demonstrate that the revised prompt fixes all seven rejected issues:

1. additive cohorts
   → replaced by 50–60 canonical agents with overlapping properties.

2. missing healthy control group
   → 10–15 well-governed agents added.

3. combined truth/expectation manifest
   → split into estate_truth and observability_contract.

4. manually declared expected misses
   → Stage-2 expectations become derivable from objective truth + justified
     evidence boundaries.

5. F6-1 hero positioning
   → retained as technical/evidence gap, removed from primary five-minute hero.

6. PHI default
   → replaced by generic payroll/compensation/financial synthetic resources.

7. hash/timestamp ambiguity
   → deterministic content hashes separated from non-deterministic anchor
     timestamp.

If any correction cannot be incorporated because of an architectural conflict,
state it explicitly instead of silently weakening the requirement.

End exactly:

VERDICT: DT1-S1 v2 PROMPT READY FOR ARCHITECTURE APPROVAL

Then STOP.

Do not execute Stage 1.
