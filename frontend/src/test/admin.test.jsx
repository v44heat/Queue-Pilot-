import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import App from '../App.jsx'
import * as api from '../services/api.js'
import { customerDefaults } from './mockApi.js'

vi.mock('../services/api.js', async () => (await import('./mockApi.js')).apiMock())

const admin = { id: 1, name: 'Root Admin', email: 'root@example.com', role: 'ADMIN', status: 'ACTIVE', created_at: '2026-01-05T08:00:00Z' }
const renderAt = (path) => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
const gen = { id: 1, name: 'General Enquiry', prefix: 'GEN' }

beforeEach(() => {
  localStorage.setItem('qp_token', 'tok')
  vi.clearAllMocks()
  customerDefaults(api)
  api.getMe.mockResolvedValue({ user: admin })
  api.adminListServices.mockResolvedValue({ services: [] })
  api.listUsers.mockResolvedValue({ users: [], total: 0, pages: 1, page: 1 })
})
afterEach(() => { localStorage.clear(); vi.useRealTimers(); vi.restoreAllMocks() })

// ------------------------------------------------------------------ access control
test('customers and staff cannot open admin pages and no admin API is called', async () => {
  for (const [role, path] of [['CUSTOMER', '/admin'], ['STAFF', '/admin/settings'], ['CUSTOMER', '/admin/ml']]) {
    api.getMe.mockResolvedValue({ user: { ...admin, role } })
    const { unmount } = renderAt(path)
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
    unmount()
  }
  expect(api.getAdminDashboard).not.toHaveBeenCalled()
  expect(api.getSettings).not.toHaveBeenCalled()
  expect(api.mlListModels).not.toHaveBeenCalled()
})

test('the admin sidebar links to every management page', async () => {
  api.getAdminDashboard.mockResolvedValue({ summary: { congestion: { level: 'LOW', thresholds: {} }, ...{} }, services: [], counters: [] })
  renderAt('/admin')
  for (const [label, href] of [['Live queue', '/admin/queue'], ['Services', '/admin/services'], ['Counters', '/admin/counters'],
    ['Users', '/admin/users'], ['ML models', '/admin/ml'], ['ML training', '/admin/ml/training'], ['Settings', '/admin/settings']]) {
    expect(await screen.findByRole('link', { name: new RegExp(label) })).toHaveAttribute('href', href)
  }
})

// ------------------------------------------------------------------ dashboard
const dash = (over = {}) => ({
  summary: {
    served_today: 12, waiting: 7, called: 1, being_served: 2, avg_waiting_time: 14.5, avg_service_duration: 6,
    active_counters: 3, busy_counters: 2, total_counters: 4,
    congestion: { level: 'MODERATE', thresholds: { moderate: 5, high: 11, critical: 21 } }, ...over,
  },
  services: [{ id: 1, name: 'General Enquiry', prefix: 'GEN', waiting: 7, called: 1, serving: 2, counters: { open: 3, busy: 2, available: 1 }, congestion: 'MODERATE' }],
  counters: [{ id: 1, name: 'GEN 1', status: 'OPEN', availability: 'BUSY', service: gen, current_ticket: { queue_number: 'GEN-004', customer: { name: 'Jane' } }, staff: [{ id: 5, name: 'Sam Staff' }] },
    { id: 2, name: 'GEN 2', status: 'CLOSED', availability: 'UNAVAILABLE', service: gen, current_ticket: null, staff: [] }],
})
const stat = (label) => screen.getByText(label).closest('.qp-stat')

test('dashboard cards show the figures returned by the backend', async () => {
  api.getAdminDashboard.mockResolvedValue(dash())
  renderAt('/admin')
  await screen.findByText('Customers served today')
  expect(within(stat('Customers served today')).getByText('12')).toBeInTheDocument()
  expect(within(stat('Customers waiting')).getByText('7')).toBeInTheDocument()
  expect(within(stat('Being served')).getByText('2')).toBeInTheDocument()
  expect(within(stat('Average waiting time')).getByText('14.5 min')).toBeInTheDocument()
  expect(within(stat('Average service duration')).getByText('6 min')).toBeInTheDocument()
  expect(within(stat('Active counters')).getByText('3 / 4')).toBeInTheDocument()
  expect(within(stat('Congestion level')).getByText('MODERATE')).toBeInTheDocument()
  expect(screen.getByText(/Moderate from 5, high from 11, critical from 21/)).toBeInTheDocument()
  expect(screen.getByText('GEN-004 (Jane)')).toBeInTheDocument()
  expect(screen.getByText('Sam Staff')).toBeInTheDocument()
})

test('dashboard shows a dash, not zero, when nothing has been measured', async () => {
  api.getAdminDashboard.mockResolvedValue(dash({ avg_waiting_time: null, avg_service_duration: null }))
  renderAt('/admin')
  await screen.findByText('Customers served today')
  expect(within(stat('Average waiting time')).getByText('-')).toBeInTheDocument()
  expect(within(stat('Average service duration')).getByText('-')).toBeInTheDocument()
})

test('dashboard refreshes itself so figures follow the database', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  api.getAdminDashboard.mockResolvedValue(dash())
  renderAt('/admin')
  await screen.findByText('Customers served today')
  expect(api.getAdminDashboard).toHaveBeenCalledTimes(1)
  api.getAdminDashboard.mockResolvedValue(dash({ waiting: 9, congestion: { level: 'HIGH', thresholds: { moderate: 5, high: 11, critical: 21 } } }))
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  await waitFor(() => expect(within(stat('Customers waiting')).getByText('9')).toBeInTheDocument())
  expect(within(stat('Congestion level')).getByText('HIGH')).toBeInTheDocument()
})

test('dashboard reports a server failure', async () => {
  api.getAdminDashboard.mockRejectedValue({ response: { status: 500, data: { message: 'An unexpected error occurred.' } } })
  renderAt('/admin')
  expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred.')
})

// ------------------------------------------------------------------ live queue monitor
const qrow = (over = {}) => ({
  id: 1, queue_number: 'GEN-001', service: gen, customer: { id: 9, name: 'Alice Wonder', email: 'alice@example.com' },
  status: 'WAITING', position: 2, people_ahead: 1, estimated_wait: { minutes: 23.4, source: 'machine_learning' }, counter: null, ...over,
})
const queue = (tickets, extra = {}) => ({ tickets, total: tickets.length, page: 1, per_page: 20, pages: 1, ...extra })
const lastQueueParams = () => api.getAdminQueue.mock.calls.at(-1)[0]

test('live queue shows the required columns with real values', async () => {
  api.getAdminQueue.mockResolvedValue(queue([
    qrow(),
    qrow({ id: 2, queue_number: 'GEN-002', position: 3, estimated_wait: { minutes: 10, source: 'fallback' }, customer: { id: 10, name: 'Bob', email: 'bob@example.com' } }),
    qrow({ id: 3, queue_number: 'PAY-001', service: { id: 2, name: 'Payments', prefix: 'PAY' }, position: 1, estimated_wait: { minutes: null, source: 'unavailable' } }),
    qrow({ id: 4, queue_number: 'GEN-000', status: 'SERVING', position: null, estimated_wait: null, counter: { id: 1, name: 'GEN 1' } }),
  ]))
  renderAt('/admin/queue')
  await screen.findByText('GEN-001')
  for (const h of ['Queue Number', 'Service', 'Customer', 'Position', 'Estimated Wait', 'Status', 'Counter']) {
    expect(screen.getByRole('columnheader', { name: new RegExp(h) })).toBeInTheDocument()
  }
  expect(screen.getByText('23 min')).toBeInTheDocument()
  expect(screen.getByText('10 min (basic)')).toBeInTheDocument()
  expect(screen.getByText('No counter open')).toBeInTheDocument()
  expect(screen.getAllByText('alice@example.com')).toHaveLength(3) // rows 1, 3 and 4 belong to Alice; row 2 to Bob
  expect(screen.getByText('bob@example.com')).toBeInTheDocument()
  const serving = screen.getByText('GEN-000').closest('tr')
  expect(within(serving).getByText('GEN 1')).toBeInTheDocument()
  expect(within(serving).getByText('Being served')).toBeInTheDocument()
})

test('live queue filters, search and sorting are sent to the API', async () => {
  api.adminListServices.mockResolvedValue({ services: [{ ...gen, status: 'ACTIVE' }] })
  api.getAdminQueue.mockResolvedValue(queue([qrow()], { total: 45, pages: 3 }))
  renderAt('/admin/queue')
  await screen.findByText('GEN-001')
  expect(lastQueueParams()).toEqual({ status: 'ACTIVE', page: 1, per_page: 20 })

  fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'CALLED' } })
  await waitFor(() => expect(lastQueueParams()).toMatchObject({ status: 'CALLED', page: 1 }))
  fireEvent.change(await screen.findByRole('option', { name: 'General Enquiry' }).then((o) => o.closest('select')), { target: { value: '1' } })
  await waitFor(() => expect(lastQueueParams()).toMatchObject({ service_id: '1' }))
  fireEvent.change(screen.getByLabelText('Search tickets'), { target: { value: 'alice' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => expect(lastQueueParams()).toMatchObject({ search: 'alice' }))

  const header = screen.getByRole('columnheader', { name: /Customer/ })
  expect(header).toHaveAttribute('aria-sort', 'none')
  fireEvent.click(within(header).getByRole('button'))
  await waitFor(() => expect(lastQueueParams()).toMatchObject({ sort: 'customer', order: 'asc' }))
  expect(screen.getByRole('columnheader', { name: /Customer/ })).toHaveAttribute('aria-sort', 'ascending')
  fireEvent.click(within(screen.getByRole('columnheader', { name: /Customer/ })).getByRole('button'))
  await waitFor(() => expect(lastQueueParams()).toMatchObject({ sort: 'customer', order: 'desc' }))

  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() => expect(lastQueueParams()).toMatchObject({ page: 2, sort: 'customer' }))
})

test('live queue refreshes automatically and keeps the filters', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  api.getAdminQueue.mockResolvedValue(queue([qrow()]))
  renderAt('/admin/queue')
  await screen.findByText('GEN-001')
  fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'WAITING' } })
  await waitFor(() => expect(lastQueueParams().status).toBe('WAITING'))
  const before = api.getAdminQueue.mock.calls.length
  api.getAdminQueue.mockResolvedValue(queue([qrow({ id: 8, queue_number: 'GEN-099' })]))
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(await screen.findByText('GEN-099')).toBeInTheDocument()
  expect(api.getAdminQueue.mock.calls.length).toBeGreaterThan(before)
  expect(lastQueueParams().status).toBe('WAITING')
})

test('live queue empty state', async () => {
  api.getAdminQueue.mockResolvedValue(queue([]))
  renderAt('/admin/queue')
  expect(await screen.findByText(/Nobody is in a queue right now/)).toBeInTheDocument()
})

// ------------------------------------------------------------------ services management
const svc = (over = {}) => ({ id: 1, name: 'General Enquiry', prefix: 'GEN', description: 'Help', default_service_duration: 10, status: 'ACTIVE',
  waiting_count: 3, active_tickets: 3, total_tickets: 40, counters: 2, open_counters: 1, ...over })

test('services list shows real stats and creating a service sends the entered values', async () => {
  api.adminListServices.mockResolvedValue({ services: [svc()] })
  api.adminCreateService.mockResolvedValue({ service: svc({ id: 2, name: 'Visa Desk', prefix: 'VIS' }) })
  renderAt('/admin/services')
  const row = (await screen.findByText('General Enquiry')).closest('tr')
  expect(within(row).getByText('GEN')).toBeInTheDocument()
  expect(within(row).getByText('1 open / 2')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Add service' }))
  const form = screen.getByRole('form', { name: 'Create service' })
  fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'Visa Desk' } })
  fireEvent.change(within(form).getByLabelText(/Ticket prefix/), { target: { value: 'VIS' } })
  fireEvent.change(within(form).getByLabelText(/Typical service time/), { target: { value: '20' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Create service' }))
  await waitFor(() => expect(api.adminCreateService).toHaveBeenCalledWith({ name: 'Visa Desk', prefix: 'VIS', description: '', default_service_duration: 20 }))
  expect(await screen.findByText('Service created.')).toBeInTheDocument()
})

test('server validation errors appear next to the fields', async () => {
  api.adminListServices.mockResolvedValue({ services: [] })
  api.adminCreateService.mockRejectedValue({ response: { status: 400, data: { message: 'Please correct the highlighted fields.', details: { prefix: 'Prefix must be 2-6 letters or digits (it starts every ticket number).' } } } })
  renderAt('/admin/services')
  expect(await screen.findByText(/No services yet/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Add service' }))
  fireEvent.click(within(screen.getByRole('form', { name: 'Create service' })).getByRole('button', { name: 'Create service' }))
  expect(await screen.findByText(/Prefix must be 2-6 letters or digits/)).toBeInTheDocument()
})

test('editing locks the prefix once tickets exist', async () => {
  api.adminListServices.mockResolvedValue({ services: [svc(), svc({ id: 2, name: 'Fresh', prefix: 'FRE', total_tickets: 0 })] })
  api.adminUpdateService.mockResolvedValue({ service: svc() })
  renderAt('/admin/services')
  fireEvent.click(await screen.findByRole('button', { name: 'Edit General Enquiry' }))
  expect(screen.getByLabelText(/Ticket prefix/)).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'General Help' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await waitFor(() => expect(api.adminUpdateService).toHaveBeenCalledWith(1, expect.objectContaining({ name: 'General Help', prefix: 'GEN' })))
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Fresh' }))
  expect(screen.getByLabelText(/Ticket prefix/)).not.toBeDisabled()
})

test('deactivating asks for confirmation, can be cancelled, and shows the business-rule refusal', async () => {
  api.adminListServices.mockResolvedValue({ services: [svc()] })
  api.adminUpdateService.mockRejectedValue({ response: { status: 409, data: { error: 'service_in_use', message: '3 customers are still in this queue. Wait until they are served or cancelled before deactivating.' } } })
  renderAt('/admin/services')
  fireEvent.click(await screen.findByRole('button', { name: 'Deactivate General Enquiry' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
  expect(api.adminUpdateService).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Deactivate General Enquiry' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Deactivate' }))
  await waitFor(() => expect(api.adminUpdateService).toHaveBeenCalledWith(1, { status: 'INACTIVE' }))
  expect(await screen.findByText(/3 customers are still in this queue/)).toBeInTheDocument()
})

test('an inactive service can be activated', async () => {
  api.adminListServices.mockResolvedValue({ services: [svc({ status: 'INACTIVE' })] })
  api.adminUpdateService.mockResolvedValue({ service: svc() })
  renderAt('/admin/services')
  fireEvent.click(await screen.findByRole('button', { name: 'Activate General Enquiry' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Activate' }))
  await waitFor(() => expect(api.adminUpdateService).toHaveBeenCalledWith(1, { status: 'ACTIVE' }))
})

// ------------------------------------------------------------------ counters management
const counter = (over = {}) => ({ id: 1, name: 'GEN 1', status: 'CLOSED', availability: 'UNAVAILABLE', service: gen, current_ticket: null,
  staff: [{ id: 5, name: 'Sam Staff', email: 's@example.com' }], ...over })
const staffUsers = [{ id: 5, name: 'Sam Staff' }, { id: 7, name: 'Tess Teller' }]

function countersSetup(counters = [counter()]) {
  api.adminListCounters.mockResolvedValue({ counters })
  api.adminListServices.mockResolvedValue({ services: [{ ...gen, status: 'ACTIVE' }] })
  api.listUsers.mockResolvedValue({ users: staffUsers, total: 2, pages: 1, page: 1 })
}

test('counters page lists staff and assigns only staff who are not already assigned', async () => {
  countersSetup()
  api.adminAssignStaff.mockResolvedValue({})
  renderAt('/admin/counters')
  await screen.findByText('GEN 1')
  expect(api.listUsers).toHaveBeenCalledWith({ role: 'STAFF', status: 'ACTIVE', per_page: 100 })
  const select = screen.getByLabelText('Staff to assign to GEN 1')
  expect(within(select).queryByRole('option', { name: 'Sam Staff' })).not.toBeInTheDocument() // already assigned
  fireEvent.change(select, { target: { value: '7' } })
  fireEvent.click(screen.getByRole('button', { name: 'Assign staff to GEN 1' }))
  await waitFor(() => expect(api.adminAssignStaff).toHaveBeenCalledWith(1, 7))
  expect(await screen.findByText('Staff assigned.')).toBeInTheDocument()
})

test('removing staff and deactivating a counter need confirmation', async () => {
  countersSetup()
  api.adminUnassignStaff.mockResolvedValue({})
  api.adminUpdateCounter.mockResolvedValue({})
  renderAt('/admin/counters')
  fireEvent.click(await screen.findByRole('button', { name: 'Remove Sam Staff from GEN 1' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
  expect(api.adminUnassignStaff).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Remove Sam Staff from GEN 1' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))
  await waitFor(() => expect(api.adminUnassignStaff).toHaveBeenCalledWith(1, 5))

  fireEvent.click(await screen.findByRole('button', { name: 'Deactivate GEN 1' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Deactivate' }))
  await waitFor(() => expect(api.adminUpdateCounter).toHaveBeenCalledWith(1, { status: 'INACTIVE' }))
})

test('an inactive counter can be re-enabled', async () => {
  countersSetup([counter({ status: 'INACTIVE' })])
  api.adminUpdateCounter.mockResolvedValue({})
  renderAt('/admin/counters')
  fireEvent.click(await screen.findByRole('button', { name: 'Re-enable GEN 1' }))
  await waitFor(() => expect(api.adminUpdateCounter).toHaveBeenCalledWith(1, { status: 'CLOSED' }))
})

test('counter business-rule refusals are shown, and a counter can be created and re-assigned to a service', async () => {
  countersSetup()
  api.adminUpdateCounter.mockRejectedValue({ response: { status: 409, data: { message: 'This counter is serving a customer. Try again when it is free.' } } })
  api.adminCreateCounter.mockResolvedValue({})
  renderAt('/admin/counters')
  fireEvent.change(await screen.findByLabelText('Service for GEN 1'), { target: { value: '' } })
  expect(await screen.findByText(/This counter is serving a customer/)).toBeInTheDocument()

  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'GEN 2' } })
  const serviceSelect = screen.getAllByRole('combobox').find((s) => within(s).queryByText('Not assigned yet'))
  fireEvent.change(serviceSelect, { target: { value: '1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create counter' }))
  await waitFor(() => expect(api.adminCreateCounter).toHaveBeenCalledWith({ name: 'GEN 2', service_id: 1 }))
})

// ------------------------------------------------------------------ ML models
const model = (over = {}) => ({
  id: 1, model_name: 'Random Forest', version: '1.0', run_id: 'r1', mae: 5.123, rmse: 8.4, r2: 0.912, training_date: '2026-03-02T09:00:00Z',
  is_active: false, data_source: 'synthetic', eligible: true, selected_in_run: false, rows: 6000, seed: 42,
  validation: { mae: 5.4, rmse: 8.7, r2: 0.9 }, split: { strategy: 'chronological by day, 60/20/20', n_train: 3600, n_validation: 1200, n_test: 1200 },
  baseline: { validation: { mae: 9.1, rmse: 14, r2: 0.8 }, test: { mae: 8.3, rmse: 13.5, r2: 0.822 } }, ...over,
})
const models = [model(), model({ id: 2, model_name: 'Gradient Boosting', mae: 4.9, selected_in_run: true, is_active: true }),
  model({ id: 3, model_name: 'Linear Regression', eligible: false })]
const lg = (over = {}) => ({ id: 1, queue_number: 'GEN-001', source: 'machine_learning', model: 'Gradient Boosting 1.0', prediction: 20, actual_value: 18, prediction_error: 2, created_at: '2026-03-02T09:00:00Z', ...over })

test('model comparison shows measured metrics, baseline, synthetic warning and the active model', async () => {
  api.mlListModels.mockResolvedValue({ models })
  api.mlPerformance.mockResolvedValue({ groups: [], predictions_awaiting_outcome: 4 })
  api.mlPredictionLogs.mockResolvedValue({ logs: [], total: 0, pages: 1, page: 1 })
  renderAt('/admin/ml')
  expect(await screen.findByText(/trained on/)).toHaveTextContent('synthetic')
  expect(screen.getByText(/Gradient Boosting 1.0/, { selector: 'strong' })).toBeInTheDocument() // active model summary
  const rf = screen.getByText('Random Forest').closest('tr')
  expect(within(rf).getByText('5.123')).toBeInTheDocument()
  expect(within(rf).getByText('0.912')).toBeInTheDocument()
  expect(screen.getByText('Rule-based baseline')).toBeInTheDocument()
  expect(screen.getByText('0.822')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Activate Gradient Boosting 1.0' })).toBeDisabled() // already active
  expect(screen.getByRole('button', { name: 'Activate Linear Regression 1.0' })).toBeDisabled() // ineligible
  expect(within(screen.getByText('Linear Regression').closest('tr')).getByText('Ineligible')).toBeInTheDocument()
  expect(screen.getByText(/4 prediction\(s\) are awaiting an outcome/)).toBeInTheDocument()
})

test('activating a model needs confirmation and then calls the API', async () => {
  api.mlListModels.mockResolvedValue({ models })
  api.mlPerformance.mockResolvedValue({ groups: [], predictions_awaiting_outcome: 0 })
  api.mlPredictionLogs.mockResolvedValue({ logs: [], total: 0, pages: 1, page: 1 })
  api.mlActivate.mockResolvedValue({})
  renderAt('/admin/ml')
  fireEvent.click(await screen.findByRole('button', { name: 'Activate Random Forest 1.0' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
  expect(api.mlActivate).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Activate Random Forest 1.0' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Activate' }))
  await waitFor(() => expect(api.mlActivate).toHaveBeenCalledWith(1))
  expect(await screen.findByText('Random Forest 1.0 is now active.')).toBeInTheDocument()
})

test('live accuracy and prediction errors come from the logs', async () => {
  api.mlListModels.mockResolvedValue({ models: [] })
  api.mlPerformance.mockResolvedValue({ groups: [{ source: 'machine_learning', model_version_id: 2, model: 'Gradient Boosting 1.0', n: 14, mae: 3.456, rmse: 4.5, r2: 0.7 }], predictions_awaiting_outcome: 2 })
  api.mlPredictionLogs.mockResolvedValue({ logs: [lg(), lg({ id: 2, queue_number: 'GEN-002', prediction: 10, actual_value: 11.5, prediction_error: -1.5 }), lg({ id: 3, queue_number: 'GEN-003', actual_value: null, prediction_error: null })], total: 3, pages: 2, page: 1 })
  renderAt('/admin/ml')
  expect(await screen.findByText(/No models trained yet/)).toBeInTheDocument()
  expect(await screen.findByText('3.46')).toBeInTheDocument() // live MAE
  const rows = (await screen.findByText('GEN-001')).closest('table').querySelectorAll('tbody tr')
  expect(rows[0]).toHaveTextContent('+2.00')
  expect(rows[1]).toHaveTextContent('-1.50')
  expect(rows[2]).toHaveTextContent('pending')
  expect(api.mlPredictionLogs).toHaveBeenLastCalledWith({ page: 1, per_page: 10, with_actual: 'true' })
  fireEvent.click(screen.getByLabelText('Only measured outcomes'))
  await waitFor(() => expect(api.mlPredictionLogs).toHaveBeenLastCalledWith({ page: 1, per_page: 10 }))
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() => expect(api.mlPredictionLogs).toHaveBeenLastCalledWith({ page: 2, per_page: 10 }))
})

// ------------------------------------------------------------------ ML training
test('training sends the chosen options and shows the measured comparison', async () => {
  api.mlTrain.mockResolvedValue({ models })
  renderAt('/admin/ml/training')
  fireEvent.click(await screen.findByRole('button', { name: 'Start training' }))
  await waitFor(() => expect(api.mlTrain).toHaveBeenCalledWith({ source: 'synthetic', rows: 6000, seed: 42, activate_best: false }))
  expect(await screen.findByText('Results')).toBeInTheDocument()
  expect(screen.getByText('Random Forest')).toBeInTheDocument()
  expect(screen.getByText('Rule-based baseline')).toBeInTheDocument()
})

test('training options: historical hides row count, activate-best is passed, errors are shown', async () => {
  api.mlTrain.mockRejectedValue({ response: { status: 409, data: { message: 'At least 200 valid records are required; found 12.' } } })
  renderAt('/admin/ml/training')
  fireEvent.change(await screen.findByLabelText(/Training data/), { target: { value: 'historical' } })
  expect(screen.queryByLabelText(/Synthetic rows/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByLabelText(/Activate the selected model/))
  fireEvent.change(screen.getByLabelText('Random seed'), { target: { value: '7' } })
  fireEvent.click(screen.getByRole('button', { name: 'Start training' }))
  await waitFor(() => expect(api.mlTrain).toHaveBeenCalledWith({ source: 'historical', seed: 7, activate_best: true }))
  expect(await screen.findByRole('alert')).toHaveTextContent('At least 200 valid records are required; found 12.')
  expect(screen.queryByText('Results')).not.toBeInTheDocument()
})

// ------------------------------------------------------------------ system settings
const setting = (over = {}) => ({ key: 'congestion.moderate_min', value: 5, default: 5, is_default: true, type: 'int', min: 1, max: 1000, group: 'Congestion',
  label: 'MODERATE starts at', description: 'First MODERATE count.', ...over })
const settingsList = [
  setting(),
  setting({ key: 'congestion.high_min', value: 12, default: 11, is_default: false, label: 'HIGH starts at' }),
  setting({ key: 'notifications.wait_change_ratio', value: 0.25, default: 0.25, type: 'float', group: 'Customer notifications', label: 'Change fraction', min: 0.05, max: 5 }),
]

test('settings show current values grouped, and save sends only what changed', async () => {
  api.getSettings.mockResolvedValue({ settings: settingsList })
  api.updateSettings.mockResolvedValue({ settings: settingsList.map((s) => (s.key === 'congestion.moderate_min' ? { ...s, value: 3, is_default: false } : s)) })
  renderAt('/admin/settings')
  expect(await screen.findByLabelText(/^MODERATE starts at/)).toHaveValue(5)
  expect(screen.getByLabelText(/^HIGH starts at/)).toHaveValue(12)
  expect(screen.getByRole('heading', { name: 'Customer notifications' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText(/^MODERATE starts at/), { target: { value: '3' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  await waitFor(() => expect(api.updateSettings).toHaveBeenCalledWith({ 'congestion.moderate_min': 3 }))
  expect(await screen.findByText('Settings saved.')).toBeInTheDocument()
  expect(screen.getByLabelText(/^MODERATE starts at/)).toHaveValue(3)
})

test('saving without changes does not call the API', async () => {
  api.getSettings.mockResolvedValue({ settings: settingsList })
  renderAt('/admin/settings')
  await screen.findByLabelText(/^MODERATE starts at/)
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByText('No changes to save.')).toBeInTheDocument()
  expect(api.updateSettings).not.toHaveBeenCalled()
})

test('reset to default sends null and is disabled for settings already at default', async () => {
  api.getSettings.mockResolvedValue({ settings: settingsList })
  api.updateSettings.mockResolvedValue({ settings: settingsList.map((s) => ({ ...s, value: s.default, is_default: true })) })
  renderAt('/admin/settings')
  await screen.findByLabelText(/^HIGH starts at/)
  expect(screen.getByRole('button', { name: /Reset MODERATE starts at to default/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /Reset HIGH starts at to default/ }))
  expect(screen.getByLabelText(/^HIGH starts at/)).toHaveValue(11)
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  await waitFor(() => expect(api.updateSettings).toHaveBeenCalledWith({ 'congestion.high_min': null }))
})

test('server validation errors appear beside the right setting', async () => {
  api.getSettings.mockResolvedValue({ settings: settingsList })
  api.updateSettings.mockRejectedValue({ response: { status: 400, data: { message: 'Please correct the highlighted settings.', details: { 'congestion.high_min': 'Must be greater than the MODERATE value.' } } } })
  renderAt('/admin/settings')
  fireEvent.change(await screen.findByLabelText(/^HIGH starts at/), { target: { value: '2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  expect(await screen.findByText('Must be greater than the MODERATE value.')).toBeInTheDocument()
  expect(screen.getByLabelText(/^HIGH starts at/)).toHaveValue(2) // the admin's input is kept for correction
})

// ------------------------------------------------------------------ users: sorting and confirmation
const users = [{ id: 1, name: 'Root Admin', email: 'root@example.com', role: 'ADMIN', status: 'ACTIVE', created_at: '2026-01-05T08:00:00Z' },
  { id: 2, name: 'Jane Customer', email: 'jane@example.com', role: 'CUSTOMER', status: 'ACTIVE', created_at: '2026-02-05T08:00:00Z' }]

test('user table sorting is sent to the API and announced', async () => {
  api.listUsers.mockResolvedValue({ users, total: 2, pages: 1, page: 1 })
  renderAt('/admin/users')
  await screen.findByText('jane@example.com')
  expect(api.listUsers).toHaveBeenLastCalledWith({ page: 1, per_page: 10, sort: 'created', order: 'desc' })
  fireEvent.click(within(screen.getByRole('columnheader', { name: /Name/ })).getByRole('button'))
  await waitFor(() => expect(api.listUsers).toHaveBeenLastCalledWith({ page: 1, per_page: 10, sort: 'name', order: 'asc' }))
  fireEvent.click(within(screen.getByRole('columnheader', { name: /Name/ })).getByRole('button'))
  await waitFor(() => expect(api.listUsers).toHaveBeenLastCalledWith({ page: 1, per_page: 10, sort: 'name', order: 'desc' }))
  expect(screen.getByRole('columnheader', { name: /Name/ })).toHaveAttribute('aria-sort', 'descending')
})

test('changing a role or deactivating a user uses a confirmation dialog', async () => {
  api.listUsers.mockResolvedValue({ users, total: 2, pages: 1, page: 1 })
  api.updateUser.mockResolvedValue({})
  const confirmSpy = vi.spyOn(window, 'confirm')
  renderAt('/admin/users')
  fireEvent.change(await screen.findByLabelText('Role for jane@example.com'), { target: { value: 'STAFF' } })
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
  expect(api.updateUser).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Role for jane@example.com'), { target: { value: 'STAFF' } })
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Change role' }))
  await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith(2, { role: 'STAFF' }))

  fireEvent.click(within(screen.getByText('Jane Customer').closest('tr')).getByRole('button', { name: 'Deactivate' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Deactivate' }))
  await waitFor(() => expect(api.updateUser).toHaveBeenLastCalledWith(2, { status: 'INACTIVE' }))
  expect(confirmSpy).not.toHaveBeenCalled() // no more browser confirm() popups
})
