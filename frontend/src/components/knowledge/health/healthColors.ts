/**
 * Data colours for the health view (dark surface #14171d), checked with the dataviz
 * validator (validate_palette.js --mode dark --surface "#14171d"):
 * - SERIES: categorical slot 1, used by every single-series chart.
 * - SLEEP_STAGES: 4-slot categorical in stack order; worst adjacent CVD ΔE 17.3, normal 20.9.
 * - DIVERGING: two opposite poles for intake minus expenditure; CVD ΔE 26.8, normal 31.8.
 * Text never wears these colours; a swatch or line key beside it carries identity.
 */
export const SERIES = '#3987e5'
export const SLEEP_STAGES = { DEEP: '#3987e5', LIGHT: '#199e70', REM: '#9085e9', AWAKE: '#d95926' } as const
/** Sleep without stage data (classic tracking): a neutral, not a fifth hue. */
export const UNSTAGED = '#7d8590'
export const DIVERGING = { negative: '#3987e5', positive: '#d95926' } as const
