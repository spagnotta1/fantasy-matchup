import { describe, expect, it } from 'vitest'

import { cn } from './cn'

describe('cn with the project tokens', () => {
  it('keeps a type token beside a text colour', () => {
    // The failure this guards: an unregistered `text-caption` is read as a
    // colour and dropped in favour of the later `text-ink-muted`.
    expect(cn('text-caption', 'text-ink-muted')).toBe('text-caption text-ink-muted')
    expect(cn('text-ink', 'text-chip')).toBe('text-ink text-chip')
  })

  it('lets a later type token replace an earlier size', () => {
    expect(cn('text-body', 'text-detail')).toBe('text-detail')
    expect(cn('text-sm', 'text-caption')).toBe('text-caption')
    expect(cn('text-title', 'text-xs')).toBe('text-xs')
  })

  it('treats control and row heights as heights', () => {
    expect(cn('h-control', 'h-control-sm')).toBe('h-control-sm')
    expect(cn('h-control-xs', 'h-11')).toBe('h-11')
    expect(cn('h-10', 'h-row-compact')).toBe('h-row-compact')
    expect(cn('size-control-sm', 'size-touch')).toBe('size-touch')
  })

  it('treats radius tokens as radii', () => {
    expect(cn('rounded-card', 'rounded-control')).toBe('rounded-control')
    expect(cn('rounded-full', 'rounded-chip')).toBe('rounded-chip')
  })

  it('treats elevation tokens as shadows', () => {
    expect(cn('shadow-raised', 'shadow-none')).toBe('shadow-none')
    expect(cn('shadow-overlay', 'shadow-raised')).toBe('shadow-raised')
  })
})
