import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { Button, ButtonLink, IconButton, IconButtonLink } from './Button'
import { buttonClasses } from './buttonStyles'

const render = (element: ReactElement) => renderToStaticMarkup(<MemoryRouter>{element}</MemoryRouter>)

describe('buttonClasses', () => {
  it('gives each size its height token, and the touch size where the pointer is coarse', () => {
    expect(buttonClasses({ size: 'md' })).toContain('h-control ')
    expect(buttonClasses({ size: 'md' })).toContain('pointer-coarse:h-touch')
    expect(buttonClasses({ size: 'sm' })).toContain('h-control-sm')
    expect(buttonClasses({ size: 'sm' })).toContain('pointer-coarse:h-touch')
  })

  // A 28px control lives in table rows. Growing it to 44px would make every
  // row 44px, so it keeps its size and is given a larger hit area instead.
  it('keeps the row-sized control at 28px on touch and widens its hit area instead', () => {
    const classes = buttonClasses({ size: 'xs' })
    expect(classes).toContain('h-control-xs')
    expect(classes).not.toContain('pointer-coarse:h-touch')
    expect(classes).toContain('pointer-coarse:after:absolute')
  })

  it('draws every variant from tokens, never a literal colour', () => {
    for (const variant of ['primary', 'secondary', 'ghost', 'danger', 'link'] as const) {
      expect(buttonClasses({ variant })).not.toMatch(/(?:bg|text|border)-(?:white|black)\b|#[0-9a-f]{3,6}\b|oklch|rgb/i)
    }
    expect(buttonClasses({ variant: 'danger' })).toContain('bg-danger')
    expect(buttonClasses({ variant: 'danger' })).toContain('text-on-danger')
  })

  it('gives the link variant no box: no height, no padding', () => {
    const classes = buttonClasses({ variant: 'link', size: 'md' })
    expect(classes).not.toContain('h-control')
    expect(classes).not.toContain('px-4')
  })

  it("lets a caller's class override a default", () => {
    expect(buttonClasses({ className: 'rounded-full' })).not.toContain('rounded-control')
  })
})

describe('Button', () => {
  it('is a button that does not submit unless asked to', () => {
    expect(render(<Button>Save</Button>)).toMatch(/^<button type="button"/)
    expect(render(<Button type="submit">Save</Button>)).toMatch(/^<button type="submit"/)
  })

  it('announces a loading button as busy and unavailable, without disabling it', () => {
    const html = render(<Button loading>Run simulation</Button>)
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('aria-disabled="true"')
    // Not the `disabled` attribute: that would drop keyboard focus.
    expect(html).not.toMatch(/\sdisabled=""/)
    // The label stays in the markup, holding the width and the name.
    expect(html).toContain('Run simulation')
  })

  it('puts the spinner where the icon was while loading', () => {
    const icon = <svg data-icon="play" />
    expect(render(<Button icon={icon}>Run</Button>)).toContain('data-icon="play"')
    const loading = render(<Button icon={icon} loading>Run</Button>)
    expect(loading).not.toContain('data-icon="play"')
    expect(loading).toContain('animate-spin')
  })

  it('passes a real disabled attribute through', () => {
    expect(render(<Button disabled>Save</Button>)).toMatch(/\sdisabled=""/)
  })
})

describe('ButtonLink', () => {
  it('is an anchor with the button look', () => {
    const html = render(<ButtonLink to="/my-team" variant="primary">Add your roster</ButtonLink>)
    expect(html).toMatch(/^<a /)
    expect(html).toContain('href="/my-team"')
    expect(html).toContain('bg-accent')
  })
})

describe('icon-only controls', () => {
  it('names an icon button from its label, and hides the glyph', () => {
    const html = render(
      <IconButton label="Remove Jahmyr Gibbs">
        <svg />
      </IconButton>,
    )
    expect(html).toContain('aria-label="Remove Jahmyr Gibbs"')
    expect(html).toContain('title="Remove Jahmyr Gibbs"')
    expect(html).toMatch(/<span aria-hidden="true"[^>]*><svg/)
  })

  it('is square at its size', () => {
    const html = render(
      <IconButton size="xs" label="Clear search">
        <svg />
      </IconButton>,
    )
    expect(html).toContain('h-control-xs')
    expect(html).toContain('w-control-xs')
  })

  it('names an icon link the same way', () => {
    const html = render(
      <IconButtonLink to="/settings" label="Settings">
        <svg />
      </IconButtonLink>,
    )
    expect(html).toMatch(/^<a /)
    expect(html).toContain('aria-label="Settings"')
  })
})
