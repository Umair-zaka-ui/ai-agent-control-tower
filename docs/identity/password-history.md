# Password History (Phase 4 Part 4.2.2.3.2)

> You cannot return to a password you have used recently. Enforced by comparing
> against stored hashes, never plaintext.

## The table (§10, §21)

```
password_history
  id · user_id (FK, cascade) · password_hash · created_at
  index (user_id, created_at)
```

Only former argon2id hashes — never plaintext, never the current live hash (that stays on
`users.password_hash`). When a password changes, the hash being *replaced* is appended
here, so the just-set password does not count against its own history but every prior one
does.

## Reuse detection

[`PasswordHistoryService.is_reused`](../../backend/app/identity/credentials/history_service.py)
verifies the candidate against the current hash **and** the last `PASSWORD_HISTORY_DEPTH`
(default 10) stored hashes, exactly as a login would verify it — a hash comparison, because
the plaintext is never stored to compare against. A hit raises `PASSWORD_REUSED` (422) and
records a `PASSWORD_REUSED_ATTEMPT` event.

The current password is checked explicitly: the most common "reuse" is setting the same
password again, and it is not yet in the history table when a change begins.

## Pruning

After each change the service keeps only the newest `depth` rows and deletes the rest —
older hashes can never be re-checked, so retaining them would only grow the table. An
argon2id verify is deliberately expensive, so the depth is bounded on purpose: reuse
detection is at most `depth` verifications per change.

## Interaction with minimum age

History stops you cycling *forward* through new passwords back to an old favourite;
[minimum age](./credential-management.md) (`PASSWORD_MIN_AGE_HOURS`) stops you cycling
*fast*. Together they make "change it 10 times to get my old one back" impractical.

## Related

- [Credential management](./credential-management.md)
- [Password policy](./password-policy.md)
