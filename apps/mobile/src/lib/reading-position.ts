export interface ReadingPosition {
  id: string
  top: number
}
export function captureReadingPosition(container: HTMLElement): ReadingPosition | null {
  const row = [...container.querySelectorAll<HTMLElement>('[data-message-id]')].find(
    row => row.getBoundingClientRect().bottom > 0
  )
  return row ? { id: row.dataset.messageId!, top: row.getBoundingClientRect().top } : null
}
export function restoreReadingPosition(container: HTMLElement, position: ReadingPosition): void {
  const row = [...container.querySelectorAll<HTMLElement>('[data-message-id]')].find(
    row => row.dataset.messageId === position.id
  )
  if (row) window.scrollBy({ top: row.getBoundingClientRect().top - position.top, behavior: 'instant' })
}
