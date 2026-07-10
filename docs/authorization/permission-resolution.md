# Permission resolution (Phase 4.3.2 §8, §11, §12)

Resolving an identity's **grant list** is the DB-heavy part of authorization. It is
done once per identity and cached.

## Sources (§8)

An identity's grants are the union of:

1. **Legacy fallback** — the built-in permission set for the identity's `User.role`
   enum (SUPER_ADMIN/ADMIN/REVIEWER/VIEWER), treated as `GLOBAL` **allow** grants. This
   is what keeps every pre-4.3 user working with exactly their old access.
2. **Scoped role assignments** (`user_roles`) — for each non-expired assignment, the
   assigned role **and every role it inherits** (via `role_hierarchy`), and for each of
   those roles every `role_permissions` row, carried as a grant with the assignment's
   **scope** and the role's name as `source_role`.

## Normalization (§11)

`PermissionResolver.resolve_grants(user)` returns a flat `list[Grant]`. Each grant is:

```
Grant(pattern, effect, scope, source_role,
      organization_id?, department_id?, team_id?, project_id?, resource_type?, resource_id?)
```

`pattern` may be a concrete code (`agent.delete`), a resource wildcard (`agent.*`) or
the global wildcard (`*`). `effect` is `ALLOW` or `DENY`. Duplicates are harmless — the
evaluator treats the grant list as a set of rules and lets conflict resolution decide.

## Role resolution + inheritance (§12)

`RoleResolver` builds the hierarchy adjacency once and walks parent→child edges to
collect a role's descendants. A senior role therefore contributes its own permissions
**plus** those of every role beneath it. Cycles cannot occur — they are rejected when an
edge is created (see [role hierarchy](role-hierarchy.md)).

## Evaluation

Given the resolved grants, a check for `code` (optionally on a resource):

1. keep grants whose `pattern` **matches** `code` ([wildcards](wildcards.md)) **and**
   whose scope **applies** ([scopes](scopes.md));
2. hand those to the [conflict resolver](permission-engine.md#decision-17): deny wins,
   else allow, else default deny.
