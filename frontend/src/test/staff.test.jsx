import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import App from '../App.jsx'
import * as api from '../services/api.js'
import { customerDefaults } from './mockApi.js'

vi.mock('../services/api.js', async () => (await import('./mockApi.js')).apiMock())

const staff = { id: 5, name: 'Sam Staff', email: 's@example.com', role: 'STAFF', status: 'ACTIVE' }
const service = { id: 1, name: 'General Enquiry', prefix: 'GEN' }
const ticket = (over = {}) => ({
  id: 10, queue_number: 'GEN-001', status: 'CALLED', customer: { id: 2, name: 'Jane Customer' },
  called_time: '2026-03-02T09:05:00Z', service_start_time: null, ...over,
})
const view = ({ status = 'OPEN', current = null, waiting = [] } = {}) => ({
  counter: { id: 1, name: 'Counter 1', status, availability: 'AVAILABLE', service, current_ticket: current },
  waiting,
  stats: { served_today: 3, avg_service_duration_today: 6.5, waiting_for_service: waiting.length },
})
const waitingRow = { id: 11, queue_number: 'GEN-002', customer: { name: 'Bob Waiting' }, position: 1, join_time: '2026-03-02T09:00:00Z' }

beforeEach(() => {
  localStorage.setItem('qp_token', 'tok')
  vi.clearAllMocks()
  customerDefaults(api)
  api.getMe.mockResolvedValue({ user: staff })
  api.getStaffCounters.mockResolvedValue({ counters: [{ id: 1, name: 'Counter 1' }] })
})
afterEach(() => localStorage.clear())

const renderStaff = () => render(<MemoryRouter initialEntries={['/staff']}><App /></MemoryRouter>)

test('shows real counter data: stats and waiting customers', async () => {
  api.getCounterQueue.mockResolvedValue(view({ waiting: [waitingRow] }))
  renderStaff()
  expect(await screen.findByText(/Counter 1 · General Enquiry/)).toBeInTheDocument()
  expect(screen.getByText('6.5 min')).toBeInTheDocument()
  expect(screen.getByText('Bob Waiting')).toBeInTheDocument()
  expect(screen.getByText('Waiting (1)')).toBeInTheDocument()
})

test('call next calls the API then shows the called customer', async () => {
  api.getCounterQueue
    .mockResolvedValueOnce(view({ waiting: [waitingRow] }))
    .mockResolvedValue(view({ current: ticket(), waiting: [] }))
  api.callNext.mockResolvedValue({ ticket: ticket() })
  renderStaff()
  fireEvent.click(await screen.findByRole('button', { name: 'Call next customer' }))
  expect(await screen.findByText('Jane Customer')).toBeInTheDocument()
  expect(api.callNext).toHaveBeenCalledWith(1)
  expect(screen.getByRole('button', { name: 'Start service' })).toBeInTheDocument()
})

test('start and complete use the correct ticket actions', async () => {
  const serving = view({ current: ticket({ status: 'SERVING', service_start_time: '2026-03-02T09:07:00Z' }) })
  api.getCounterQueue
    .mockResolvedValueOnce(view({ current: ticket() }))  // initial load: CALLED
    .mockResolvedValue(serving)                          // after Start, the server reports SERVING
  api.ticketAction.mockResolvedValue({})
  renderStaff()
  fireEvent.click(await screen.findByRole('button', { name: 'Start service' }))
  await waitFor(() => expect(api.ticketAction).toHaveBeenCalledWith(10, 'start'))

  fireEvent.click(await screen.findByRole('button', { name: 'Complete service' }))
  await waitFor(() => expect(api.ticketAction).toHaveBeenCalledWith(10, 'complete'))
  expect(screen.queryByRole('button', { name: 'Start service' })).not.toBeInTheDocument()
})

test('absent asks for confirmation and respects cancel', async () => {
  api.getCounterQueue.mockResolvedValue(view({ current: ticket() }))
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  renderStaff()
  fireEvent.click(await screen.findByRole('button', { name: 'Mark absent' }))
  expect(window.confirm).toHaveBeenCalled()
  expect(api.ticketAction).not.toHaveBeenCalled()
  window.confirm.mockReturnValue(true)
  api.ticketAction.mockResolvedValue({})
  fireEvent.click(screen.getByRole('button', { name: 'Mark absent' }))
  await waitFor(() => expect(api.ticketAction).toHaveBeenCalledWith(10, 'absent'))
})

test('closed counter offers Open and cannot call customers', async () => {
  api.getCounterQueue.mockResolvedValue(view({ status: 'CLOSED', waiting: [waitingRow] }))
  api.openCounter.mockResolvedValue({})
  renderStaff()
  expect(await screen.findByRole('button', { name: 'Call next customer' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Open counter' }))
  await waitFor(() => expect(api.openCounter).toHaveBeenCalledWith(1))
})

test('server rejection is shown to the staff member', async () => {
  api.getCounterQueue.mockResolvedValue(view({ waiting: [waitingRow] }))
  api.callNext.mockRejectedValue({ response: { status: 409, data: { message: 'This counter already has a customer.' } } })
  renderStaff()
  fireEvent.click(await screen.findByRole('button', { name: 'Call next customer' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('This counter already has a customer.')
})

test('staff with no counters sees an explanatory empty state', async () => {
  api.getStaffCounters.mockResolvedValue({ counters: [] })
  renderStaff()
  expect(await screen.findByText('No counters assigned')).toBeInTheDocument()
  expect(api.getCounterQueue).not.toHaveBeenCalled()
})
