import type { BadgeTone } from '@/components/ui/Badge'

/**
 * Tone by letter.
 *
 * A is the *softest* matchup — the grade is a percentile where 100 means the
 * defence gives up the most to this position — so A is green. The letter is
 * always rendered, so colour is reinforcement rather than the signal.
 */
export function toneForLetter(letter: string): BadgeTone {
  const head = letter.charAt(0).toUpperCase()
  if (head === 'A') return 'positive'
  if (head === 'B') return 'info'
  if (head === 'C') return 'neutral'
  if (head === 'D') return 'caution'
  return 'negative'
}

/** Width of one letter's band: the API's thirteen-step ladder, A+ to F. */
const BAND = 100 / 13

/**
 * Tone for a 0–100 matchup score, on exactly the bands the API draws letters
 * from (`grading.grade_bands`), so an averaged score and a single letter can
 * never disagree about colour.
 */
export function toneForScore(score: number | null | undefined): BadgeTone {
  if (score === null || score === undefined) return 'neutral'
  if (score >= 10 * BAND) return 'positive' // A-
  if (score >= 7 * BAND) return 'info' // B-
  if (score >= 4 * BAND) return 'neutral' // C-
  if (score >= 1 * BAND) return 'caution' // D-
  return 'negative'
}
