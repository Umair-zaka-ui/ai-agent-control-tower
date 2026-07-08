import { describe, expect, it } from 'vitest'

import { evaluatePassword, MIN_PASSWORD_LENGTH } from '../passwordStrength'

const satisfied = (password: string, id: string) =>
  evaluatePassword(password).rules.find((r) => r.id === id)?.satisfied

describe('evaluatePassword — mirrors the backend policy (ADR-0004)', () => {
  it('reports an empty password as empty, not weak', () => {
    const result = evaluatePassword('')
    expect(result.level).toBe('empty')
    expect(result.meetsPolicy).toBe(false)
    expect(result.score).toBe(0)
  })

  it(`requires ${MIN_PASSWORD_LENGTH} characters`, () => {
    expect(satisfied('Sh0rt!Aa', 'length')).toBe(false)
    expect(satisfied('L0ngEnough!Aa', 'length')).toBe(true)
  })

  it.each([
    ['upper', 'alllowercase123!'],
    ['lower', 'ALLUPPERCASE123!'],
    ['digit', 'NoDigitsHere!!Ab'],
    ['special', 'NoSpecialChar123'],
  ])('flags a missing %s', (rule, password) => {
    expect(satisfied(password, rule)).toBe(false)
    expect(evaluatePassword(password).meetsPolicy).toBe(false)
  })

  it('accepts a password that satisfies every rule', () => {
    const result = evaluatePassword('Str0ngP@ssword!')
    expect(result.meetsPolicy).toBe(true)
    expect(result.level).toBe('good')
  })

  it('calls a long compliant password strong', () => {
    expect(evaluatePassword('Str0ngP@sswordExtra!').level).toBe('strong')
  })
})

describe('common-password blocklist', () => {
  it('rejects a blocklisted password outright', () => {
    expect(satisfied('password1234', 'uncommon')).toBe(false)
  })

  it('sees through light obfuscation — Password123! normalises to password123', () => {
    expect(satisfied('Password123!', 'uncommon')).toBe(false)
    expect(evaluatePassword('Password123!').meetsPolicy).toBe(false)
  })

  it('does not flag an unrelated password', () => {
    expect(satisfied('Str0ngP@ssword!', 'uncommon')).toBe(true)
  })
})

describe('identity-substring rule', () => {
  it('rejects a password containing the email local-part', () => {
    const result = evaluatePassword('Johnsmith99!!X', ['johnsmith'])
    expect(result.rules.find((r) => r.id === 'identity')?.satisfied).toBe(false)
    expect(result.meetsPolicy).toBe(false)
  })

  it('rejects a password containing the first name, case-insensitively', () => {
    const result = evaluatePassword('MyAdaP@ssw0rd!', ['Ada'])
    expect(result.rules.find((r) => r.id === 'identity')?.satisfied).toBe(false)
  })

  it('ignores identity tokens shorter than 3 characters', () => {
    // "Al" is too short to be meaningful; rejecting on it would block half the alphabet.
    const result = evaluatePassword('Str0ngP@ssword!', ['Al'])
    expect(result.rules.find((r) => r.id === 'identity')?.satisfied).toBe(true)
  })

  it('passes when the password shares nothing with the identity', () => {
    expect(evaluatePassword('Str0ngP@ssword!', ['ada', 'lovelace']).meetsPolicy).toBe(true)
  })
})

describe('score', () => {
  it('increases monotonically with strength', () => {
    const weak = evaluatePassword('abc')
    const fair = evaluatePassword('alllowercase123!')
    const good = evaluatePassword('Str0ngP@ssword!')
    const strong = evaluatePassword('Str0ngP@sswordExtra!')
    expect(weak.score).toBeLessThan(fair.score)
    expect(fair.score).toBeLessThan(good.score)
    expect(good.score).toBeLessThan(strong.score)
    expect(strong.score).toBe(4)
  })
})
