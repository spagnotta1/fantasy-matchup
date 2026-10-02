import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Checkbox } from './Checkbox'

const noop = () => {}

describe('Checkbox', () => {
  it('is a real checkbox named by its label, inside the label that is its hit area', () => {
    const html = renderToStaticMarkup(<Checkbox label="Select Derrick Henry to compare" checked={false} onChange={noop} />)
    expect(html).toMatch(/^<label class="[^"]*cursor-pointer[^"]*">/)
    expect(html).toMatch(/<input type="checkbox" aria-label="Select Derrick Henry to compare"/)
    // The name is not drawn: the row it sits in says whose box it is.
    expect(html).not.toContain('>Select Derrick Henry')
  })

  it('carries its state on the input, where a screen reader reads it', () => {
    const html = renderToStaticMarkup(<Checkbox label="Select" checked onChange={noop} />)
    expect(html).toMatch(/<input[^>]* checked=""/)
  })

  it('sizes the hit area, not the box, from the caller', () => {
    const html = renderToStaticMarkup(<Checkbox label="Select" checked={false} onChange={noop} className="h-10 w-full" />)
    expect(html).toMatch(/^<label class="[^"]*h-10 w-full[^"]*">/)
    expect(html).toMatch(/<input[^>]*class="[^"]*size-4[^"]*"/)
  })

  it('says so when it cannot be ticked', () => {
    const html = renderToStaticMarkup(<Checkbox label="Select" checked={false} disabled onChange={noop} />)
    expect(html).toMatch(/<input[^>]* disabled=""/)
    expect(html).toMatch(/^<label class="[^"]*cursor-not-allowed[^"]*">/)
    expect(html).not.toMatch(/^<label class="[^"]*cursor-pointer/)
  })
})
