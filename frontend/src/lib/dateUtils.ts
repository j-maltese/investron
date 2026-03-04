/**
 * Centralized date/time formatting — all UI timestamps go through here.
 * Uses Intl.DateTimeFormat with timeZoneName:'short' so users see their
 * local timezone abbreviation (e.g., "EST", "PST", "CET").
 *
 * Backend sends UTC ISO strings; the browser's Date constructor converts
 * to local time automatically. These formatters just control the display.
 */

/** Full date + time with timezone: "3/3/2026, 12:42 PM EST" */
export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(new Date(iso))
}

/** Date only: "3/3/2026" */
export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  }).format(new Date(iso))
}

/** Time only with timezone: "12:42 PM EST" */
export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(new Date(iso))
}
