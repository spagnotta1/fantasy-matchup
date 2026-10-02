import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

/**
 * tailwind-merge resolves conflicts by knowing which utilities set the same
 * property, and it only knows Tailwind's default names. The project's own
 * tokens (`src/styles/index.css`) have to be declared or they are misread:
 * `text-caption` is taken for a text *colour*, so `cn('text-caption',
 * 'text-ink')` silently drops the size, and `h-control` is not recognised as a
 * height at all, so a caller's `h-11` could not override it.
 *
 * Keep these lists in step with the `@theme` block. `cn.test.ts` pins the
 * cases that matter.
 */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ['hero', 'title', 'section', 'body', 'detail', 'caption', 'chip'],
      spacing: [
        'control',
        'control-sm',
        'control-xs',
        'touch',
        'row-compact',
        'row',
        'row-comfortable',
        'shell-bar',
      ],
      radius: ['card', 'control', 'chip'],
      shadow: ['raised', 'overlay'],
    },
  },
})

/** Merge class names, letting a caller's utility override a component default. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
