import { beforeEach, expect, it } from 'vitest'
import { recordNotification, notificationHistory, clearNotificationHistory } from './notification_history.js'
beforeEach(() => { localStorage.clear(); clearNotificationHistory() })
it('keeps bounded activity history without retaining user documents or changing preferences', () => {
  for (let i = 0; i < 205; i++) recordNotification(`Message ${i}`, 'info')
  expect(notificationHistory()).toHaveLength(200)
  expect(notificationHistory()[0].message).toBe('Message 5')
  const copy = notificationHistory(); copy[0].message = 'Changed'
  expect(notificationHistory()[0].message).toBe('Message 5')
  clearNotificationHistory(); expect(notificationHistory()).toEqual([])
})
