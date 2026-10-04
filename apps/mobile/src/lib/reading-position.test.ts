import { expect, it, vi } from 'vitest'
import { captureReadingPosition, restoreReadingPosition } from './reading-position'
it('keeps the visible message at the same viewport offset when earlier pages prepend', () => {
  const container = document.createElement('div')
  container.innerHTML = '<article data-message-id="older"></article><article data-message-id="visible"></article>'
  const rows = container.querySelectorAll('article')
  rows[0].getBoundingClientRect = () => ({ top: -100, bottom: -10 }) as DOMRect
  rows[1].getBoundingClientRect = () => ({ top: -10, bottom: 100 }) as DOMRect
  const captured = captureReadingPosition(container)
  expect(captured).toEqual({ id: 'visible', top: -10 })
  rows[1].getBoundingClientRect = () => ({ top: 300, bottom: 410 }) as DOMRect
  const scroll = vi.spyOn(window, 'scrollBy').mockImplementation(() => {})
  restoreReadingPosition(container, captured!)
  expect(scroll).toHaveBeenCalledWith({ top: 310, behavior: 'instant' })
  scroll.mockRestore()
})
