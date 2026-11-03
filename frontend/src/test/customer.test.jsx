import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import App from '../App.jsx'
import * as api from '../services/api.js'
import { customerDefaults } from './mockApi.js'

vi.mock('../services/api.js', async () => (await import('./mockApi.js')).apiMock())

const me = { id: 2, name: 'Jane Customer', email: 'jane@example.com', phone: '+254700000000', role: 'CUSTOMER', status: 'ACTIVE', created_at: '2026-01-05T08:00:00Z' }
const service = { id: 1, name: 'General Enquiry', prefix: 'GEN' }
const ticket = (over = {}) => ({
  id: 10, queue_number: 'GEN-047', service, status: 'WAITING', counter: null, people_ahead: 4, position: 5,
  predicted_waiting_time: 25, actual_waiting_time: null, service_duration: null,
  join_time: '2026-03-02T09:00:00Z', called_time: null, service_start_time: null, service_end_time: null,
  estimated_wait: { minutes: 23.4, source: 'machine_learning', model: 'Random Forest', model_version: '1.0', reason: null },
  ...over,
})
const note = (over = {}) => ({ id: 1, title: 'It\'s your turn', message: 'Ticket GEN-047: please go to Counter 1.', type: 'CALLED', is_read: false, queue_ticket_id: 10, created_at: '2026-03-02T09:10:00Z', ...over })

beforeEach(() => {
  localStorage.setItem('qp_token', 'tok')
  vi.clearAllMocks()
  customerDefaults(api)
  api.getMe.mockResolvedValue({ user: me })
})
afterEach(() => { localStorage.clear(); vi.useRealTimers() })

const renderAt = (path) => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)

// ------------------------------------------------------------------ dashboard
test('dashboard shows the active ticket with real backend values', async () => {
  api.getMyActive.mockResolvedValue({ tickets: [ticket()] })
  renderAt('/customer')
  const card = await screen.findByRole('article', { name: 'Ticket GEN-047' })
  expect(within(card).getByText('General Enquiry')).toBeInTheDocument()
  expect(within(card).getByText('PEOPLE AHEAD').nextElementSibling).toHaveTextContent('4')
  expect(within(card).getByText('23 minutes')).toBeInTheDocument()
  expect(within(card).getByText('Waiting', { selector: '.qp-status' })).toBeInTheDocument()
  expect(within(card).getByText('Estimated by the prediction model.')).toBeInTheDocument()
  expect(screen.getByText('Hello, Jane')).toBeInTheDocument()
})

test('dashboard empty state offers to join a queue', async () => {
  renderAt('/customer')
  expect(await screen.findByText('No active ticket')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Join a queue' })).toHaveAttribute('href', '/customer/services')
  expect(screen.getByText('No tickets yet.')).toBeInTheDocument()
})

test('dashboard shows an error when the server is unreachable', async () => {
  api.getMyActive.mockRejectedValue({ code: 'ERR_NETWORK' })
  renderAt('/customer')
  expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the server')
})

test('staff are kept out of customer pages', async () => {
  api.getMe.mockResolvedValue({ user: { ...me, role: 'STAFF' } })
  renderAt('/customer/services')
  expect(await screen.findByText('Access denied')).toBeInTheDocument()
  expect(api.getServices).not.toHaveBeenCalled()
})

// ------------------------------------------------------------------ services & joining
const svc = (over = {}) => ({ id: 1, name: 'General Enquiry', prefix: 'GEN', description: 'Questions and help.', waiting_count: 7, counters: { open: 2, busy: 1, available: 1 }, ...over })

test('services list real waiting counts and open counters', async () => {
  api.getServices.mockResolvedValue({ services: [svc(), svc({ id: 2, name: 'Payments', waiting_count: 0, counters: { open: 0, busy: 0, available: 0 } })] })
  renderAt('/customer/services')
  expect(await screen.findByText('General Enquiry')).toBeInTheDocument()
  expect(screen.getByText('7')).toBeInTheDocument()
  expect(screen.getByText(/counters open/)).toBeInTheDocument()
  expect(screen.getByText('No counter open yet')).toBeInTheDocument()
})

test('joining a queue calls the API and opens the new ticket', async () => {
  api.getServices.mockResolvedValue({ services: [svc()] })
  api.joinQueue.mockResolvedValue({ ticket: ticket({ id: 77, queue_number: 'GEN-001' }) })
  api.getTicket.mockResolvedValue({ ticket: ticket({ id: 77, queue_number: 'GEN-001', people_ahead: 0, position: 1 }) })
  renderAt('/customer/services')
  fireEvent.click(await screen.findByRole('button', { name: 'Join queue for General Enquiry' }))
  expect(await screen.findByRole('heading', { name: 'Your ticket' })).toBeInTheDocument()
  expect(api.joinQueue).toHaveBeenCalledWith(1)
  expect(api.getTicket).toHaveBeenCalledWith('77')
  expect(await screen.findByText('You joined the queue: GEN-001')).toBeInTheDocument() // toast
  expect(screen.getByRole('article', { name: 'Ticket GEN-001' })).toBeInTheDocument()
})

test('a service the customer is already queued for links to the existing ticket', async () => {
  api.getServices.mockResolvedValue({ services: [svc()] })
  api.getMyActive.mockResolvedValue({ tickets: [ticket()] })
  renderAt('/customer/services')
  const link = await screen.findByRole('link', { name: /You are in this queue \(GEN-047\)/ })
  expect(link).toHaveAttribute('href', '/customer/tickets/10')
  expect(screen.queryByRole('button', { name: /Join queue/ })).not.toBeInTheDocument()
})

test('a rejected join shows the server message and stays on the page', async () => {
  api.getServices.mockResolvedValue({ services: [svc()] })
  api.joinQueue.mockRejectedValue({ response: { status: 409, data: { message: 'You already have an active ticket for this service.' } } })
  renderAt('/customer/services')
  fireEvent.click(await screen.findByRole('button', { name: 'Join queue for General Enquiry' }))
  expect((await screen.findAllByText('You already have an active ticket for this service.')).length).toBeGreaterThan(0)
  expect(screen.getByRole('heading', { name: 'Available services' })).toBeInTheDocument()
})

// ------------------------------------------------------------------ ticket view
test('ticket page shows the digital ticket and progress', async () => {
  api.getTicket.mockResolvedValue({ ticket: ticket() })
  renderAt('/customer/tickets/10')
  const card = await screen.findByRole('article', { name: 'Ticket GEN-047' })
  for (const label of ['QUEUE NUMBER', 'SERVICE', 'PEOPLE AHEAD', 'ESTIMATED WAIT', 'STATUS']) expect(within(card).getByText(label)).toBeInTheDocument()
  expect(within(card).getByRole('list', { name: 'Queue progress' })).toBeInTheDocument()
  expect(within(card).getByText('Waiting', { selector: '.qp-steps li' })).toHaveAttribute('aria-current', 'step')
})

test('estimate wording is honest about its source', async () => {
  api.getTicket.mockResolvedValue({ ticket: ticket({ estimated_wait: { minutes: 10, source: 'fallback', reason: 'no_active_model' } }) })
  const { unmount } = renderAt('/customer/tickets/10')
  expect(await screen.findByText('Basic estimate (prediction model not active).')).toBeInTheDocument()
  unmount()
  api.getTicket.mockResolvedValue({ ticket: ticket({ estimated_wait: { minutes: null, source: 'unavailable', reason: 'no_open_counters' } }) })
  renderAt('/customer/tickets/10')
  expect(await screen.findByText('Not available')).toBeInTheDocument()
  expect(screen.getByText('No counter is open for this service yet.')).toBeInTheDocument()
})

test('called ticket shows the counter; completed ticket shows the real waited time and no cancel', async () => {
  api.getTicket.mockResolvedValue({ ticket: ticket({ status: 'CALLED', people_ahead: null, position: null, counter: { id: 1, name: 'Counter 3' } }) })
  const { unmount } = renderAt('/customer/tickets/10')
  expect(await screen.findByText('Please go to Counter 3.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Cancel ticket' })).not.toBeInTheDocument()
  unmount()
  api.getTicket.mockResolvedValue({ ticket: ticket({ status: 'COMPLETED', actual_waiting_time: 12.5, service_duration: 7.25 }) })
  renderAt('/customer/tickets/10')
  expect(await screen.findByText('12.5 min')).toBeInTheDocument()
  expect(screen.getByText('Service completed. Thank you!')).toBeInTheDocument()
  expect(screen.queryByText(/Updates automatically/)).not.toBeInTheDocument()
})

test('unknown or foreign ticket shows not found', async () => {
  api.getTicket.mockRejectedValue({ response: { status: 404, data: { message: 'Ticket not found.' } } })
  renderAt('/customer/tickets/999')
  expect(await screen.findByText('Ticket not found')).toBeInTheDocument()
})

test('cancelling asks for confirmation and respects "keep"', async () => {
  api.getTicket.mockResolvedValue({ ticket: ticket() })
  api.cancelTicket.mockResolvedValue({ ticket: ticket({ status: 'CANCELLED' }) })
  renderAt('/customer/tickets/10')
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel ticket' }))
  const dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Keep my place' }))
  expect(api.cancelTicket).not.toHaveBeenCalled()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Cancel ticket' }))
  api.getTicket.mockResolvedValue({ ticket: ticket({ status: 'CANCELLED' }) })
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel ticket' }))
  await waitFor(() => expect(api.cancelTicket).toHaveBeenCalledWith('10'))
  expect(await screen.findByText('This ticket was cancelled.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Cancel ticket' })).not.toBeInTheDocument()
})

// ------------------------------------------------------------------ live updates
test('an active ticket refreshes itself and stops polling once finished', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  api.getTicket.mockResolvedValue({ ticket: ticket({ people_ahead: 4, position: 5 }) })
  renderAt('/customer/tickets/10')
  await screen.findByRole('article', { name: 'Ticket GEN-047' })
  expect(api.getTicket).toHaveBeenCalledTimes(1)

  api.getTicket.mockResolvedValue({ ticket: ticket({ people_ahead: 2, position: 3, estimated_wait: { minutes: 11, source: 'machine_learning' } }) })
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(api.getTicket).toHaveBeenCalledTimes(2)
  expect(await screen.findByText('11 minutes')).toBeInTheDocument() // no manual refresh needed

  api.getTicket.mockResolvedValue({ ticket: ticket({ status: 'COMPLETED', actual_waiting_time: 9 }) })
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(api.getTicket).toHaveBeenCalledTimes(3)
  await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
  expect(api.getTicket).toHaveBeenCalledTimes(3) // finished: polling has stopped
})

// ------------------------------------------------------------------ history
test('history shows predicted vs actual and supports filtering and paging', async () => {
  const done = ticket({ id: 5, queue_number: 'GEN-010', status: 'COMPLETED', predicted_waiting_time: 20, actual_waiting_time: 14.5, service_duration: 6 })
  api.getHistory.mockResolvedValue({ tickets: [done], total: 25, pages: 3, page: 1 })
  renderAt('/customer/history')
  expect(await screen.findByRole('link', { name: 'GEN-010' })).toHaveAttribute('href', '/customer/tickets/5')
  expect(screen.getByText('20 min')).toBeInTheDocument()
  expect(screen.getByText('14.5 min')).toBeInTheDocument()
  expect(screen.getByText('Tickets (25)')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() => expect(api.getHistory).toHaveBeenLastCalledWith({ page: 2, per_page: 10 }))
  fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'CANCELLED' } })
  await waitFor(() => expect(api.getHistory).toHaveBeenLastCalledWith({ page: 1, per_page: 10, status: 'CANCELLED' }))
})

test('history empty state', async () => {
  renderAt('/customer/history')
  expect(await screen.findByText('You have not joined any queue yet.')).toBeInTheDocument()
})

// ------------------------------------------------------------------ notifications
test('notification centre lists, marks one read and marks all read', async () => {
  const unread = [note(), note({ id: 2, title: 'Ticket cancelled', type: 'CANCELLED', message: 'Ticket GEN-046 was cancelled.', is_read: false, queue_ticket_id: null })]
  api.getNotifications.mockResolvedValue({ notifications: unread, total: 2, pages: 1, page: 1, unread: 2 })
  api.getUnreadCount.mockResolvedValue({ unread: 2 })
  api.markNotificationRead.mockResolvedValue({})
  api.markAllNotificationsRead.mockResolvedValue({ updated: 2 })
  renderAt('/customer/notifications')
  expect(await screen.findByText('Ticket GEN-047: please go to Counter 1.')).toBeInTheDocument()
  expect(screen.getByText('Inbox (2 unread)')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Mark "It\'s your turn" as read' }))
  await waitFor(() => expect(api.markNotificationRead).toHaveBeenCalledWith(1))
  fireEvent.click(screen.getByRole('button', { name: 'Mark all as read' }))
  await waitFor(() => expect(api.markAllNotificationsRead).toHaveBeenCalled())

  fireEvent.click(screen.getByLabelText('Unread only'))
  await waitFor(() => expect(api.getNotifications).toHaveBeenLastCalledWith({ page: 1, per_page: 10, unread_only: 'true' }))
})

test('the sidebar badge shows the unread count and a new arrival raises a toast', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  api.getUnreadCount.mockResolvedValue({ unread: 2 })
  renderAt('/customer')
  expect(await screen.findByLabelText('2 unread notifications')).toHaveTextContent('2')
  expect(screen.queryByText(/new notification/)).not.toBeInTheDocument() // pre-existing unread: no toast

  api.getUnreadCount.mockResolvedValue({ unread: 3 })
  await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
  expect(await screen.findByLabelText('3 unread notifications')).toBeInTheDocument()
  expect(screen.getByText('You have 1 new notification.')).toBeInTheDocument()
})

test('notification centre empty state', async () => {
  renderAt('/customer/notifications')
  expect(await screen.findByText(/No notifications yet/)).toBeInTheDocument()
})

// ------------------------------------------------------------------ profile
test('profile saves name and phone and the sidebar updates', async () => {
  api.updateProfile.mockResolvedValue({ user: { ...me, name: 'Jane Updated' } })
  renderAt('/customer/profile')
  const name = await screen.findByLabelText('Full name')
  expect(screen.getByText('jane@example.com')).toBeInTheDocument()
  fireEvent.change(name, { target: { value: 'Jane Updated' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await waitFor(() => expect(api.updateProfile).toHaveBeenCalledWith({ name: 'Jane Updated', phone: '+254700000000' }))
  expect(await screen.findByText('Profile updated.')).toBeInTheDocument()
  expect(screen.getAllByText('Jane Updated').length).toBeGreaterThan(0)
})

test('profile shows server validation errors', async () => {
  api.updateProfile.mockRejectedValue({ response: { status: 400, data: { message: 'Please correct the highlighted fields.', details: { phone: 'Enter a valid phone number.' } } } })
  renderAt('/customer/profile')
  fireEvent.change(await screen.findByLabelText(/Phone/), { target: { value: 'abc' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(await screen.findByText('Enter a valid phone number.')).toBeInTheDocument()
})

test('password change: mismatch is blocked locally, success and wrong-current are handled', async () => {
  renderAt('/customer/profile')
  const set = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
  await screen.findByLabelText('Current password')
  set('Current password', 'OldPassw0rd'); set('New password', 'NewPassw0rd'); set('Confirm new password', 'Different1')
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByText('Passwords do not match.')).toBeInTheDocument()
  expect(api.changePassword).not.toHaveBeenCalled()

  api.changePassword.mockRejectedValueOnce({ response: { status: 400, data: { message: 'Your current password is incorrect.', details: { current_password: 'Incorrect password.' } } } })
  fireEvent.change(screen.getByLabelText(/Confirm new password/), { target: { value: 'NewPassw0rd' } })
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByText('Incorrect password.')).toBeInTheDocument()

  api.changePassword.mockResolvedValueOnce({ message: 'Password updated.' })
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByText('Password changed.')).toBeInTheDocument()
  expect(api.changePassword).toHaveBeenLastCalledWith('OldPassw0rd', 'NewPassw0rd')
  expect(screen.getByLabelText('Current password')).toHaveValue('')
})
