# API reference

All mounted under `/api/v1/runtime` alongside Phase 5.0's existing routes
(`app/runtime/routes.py`), delegating to services in
`app/runtime/registry/*`.

## Registry & search

```
GET    /agents                                   search/filter/saved views (query, project_id,
                                                   owner_id, status, agent_type, framework,
                                                   criticality, risk_level, data_classification,
                                                   autonomy_level, tag, view, page, page_size, sort)
POST   /agents                                    create a DRAFT agent
GET    /agents/{agentId}
PUT/PATCH /agents/{agentId}                        row_version-aware edit; editable states only
DELETE /agents/{agentId}                           DRAFT only
GET    /agents/{agentId}/definitions               (also aliased /definition)
```

## Lifecycle

```
POST /agents/{agentId}/register
POST /agents/{agentId}/validate
POST /agents/{agentId}/submit-for-approval
POST /agents/{agentId}/approve
POST /agents/{agentId}/reject           (reason required)
POST /agents/{agentId}/activate
POST /agents/{agentId}/suspend
POST /agents/{agentId}/resume
POST /agents/{agentId}/deprecate
POST /agents/{agentId}/archive
POST /agents/{agentId}/restore
POST /agents/{agentId}/retire
```

## Ownership

```
GET  /agents/{agentId}/ownership
POST /agents/{agentId}/ownership/transfer
GET  /agents/{agentId}/ownership/history
```

## Machine identity

```
GET  /agents/{agentId}/identity
POST /agents/{agentId}/identity/associate
POST /agents/{agentId}/identity/create-and-associate
POST /agents/{agentId}/identity/replace
```

## Validation

```
GET  /agents/{agentId}/validations
GET  /agents/{agentId}/validations/{validationId}
POST /agents/{agentId}/validations/run   (alias for /validate that returns the report, not the agent)
POST /agents/{agentId}/schemas/test
```

## Duplicate detection

```
POST /agents/{agentId}/duplicate-check
GET  /agents/{agentId}/duplicate-matches
POST /agents/{agentId}/duplicate-matches/{matchId}/review
```

## Lifecycle & audit history

```
GET /agents/{agentId}/lifecycle-events
GET /agents/{agentId}/events
```

## Import / export

```
POST /agents/import
GET  /agents/import/{jobId}
GET  /agents/import/{jobId}/items
POST /agents/export
GET  /agents/export/{jobId}
GET  /agents/export/{jobId}/download
```

## Legacy migration

```
POST /agents/migration/classify
GET  /agents/migration/records
```

## Permissions

~25 new `runtime.agent.*` codes in `PERMISSION_CATALOG`
(`app/services/rbac_service.py`) — `register`, `submit`, `reject`, `resume`,
`deprecate`, `archive`, `restore`, `identity.associate`, `identity.create`,
`identity.replace`, `ownership.view`, `ownership.transfer`,
`validation.view`, `duplicate.review`, `import`, `export`, `audit.view`.
Every `runtime.*` code is automatically part of `ROLE_RUNTIME_ADMIN`
(`_RUNTIME_ADMIN` in `app/authorization/catalog.py`), and `ADMIN`/
`SUPER_ADMIN` legacy roles get the full catalog either way.
