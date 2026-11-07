import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { cloneElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import App from '../App.jsx'
import * as api from '../services/api.js'
import { readBlobError } from '../utils/errors.js'
import { todayLocal } from '../utils/download.js'
import { customerDefaults } from './mockApi.js'

vi.mock('../services/api.js', async () => (await import('./mockApi.js')).apiMock())
// jsdom has no layout, so give charts a fixed size (the numbers themselves are asserted through the data tables).
vi.mock('recharts', async (importOriginal) => ({ ...(await importOriginal()), ResponsiveContainer: ({ children }) => cloneElement(children, { width: 600, height: 260 }) }))

const admin = { id: 1, name: 'Root Admin', email: 'root@example.com', role: 'ADMIN', status: 'ACTIVE', created_at: '2026-01-05T08:00:00Z' }
const renderAt = (path) => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
const table = (name) => screen.getByRole('table', { name, hidden: true })
const bodyRows = (name) => within(table(name)).getAllByRole('row', { hidden: true }).slice(1)

beforeEach(() => {
  localStorage.setItem('qp_token', 'tok')
  vi.clearAllMocks()
  customerDefaults(api)
  api.getMe.mockResolvedValue({ user: admin })
  api.adminListServices.mockResolvedValue({ services: [{ id: 1, name: 'General Enquiry', prefix: 'GEN', status: 'ACTIVE' }] })
})
afterEach(() => { localStorage.clear(); vi.useRealTimers(); vi.restoreAllMocks() })

// ------------------------------------------------------------------ fixtures
const zeros = { completed: 0, cancelled: 0, skipped: 0, absent: 0, in_progress: 0 }
const A = {
  queue: { hours: 24, peak: 7, points: [{ time: 't1', label: '09:00', waiting: 2, peak: 2 }, { time: 't2', label: '10:00', waiting: 5, peak: 7 }] },
  wait: { measured: 2, hours: [{ hour: 9, label: '09:00', avg_waiting: 15, n: 2 }, { hour: 10, label: '10:00', avg_waiting: null, n: 0 }] },
  volume: { days: [{ date: '2026-03-02', label: 'Mon 02 Mar', joined: 5, completed: 2, cancelled: 1, skipped: 1, absent: 1, in_progress: 0 }, { date: '2026-03-03', label: 'Tue 03 Mar', joined: 0, ...zeros }],
    totals: { joined: 5, completed: 2, cancelled: 1, skipped: 1, absent: 1, in_progress: 0 } },
  perf: { services: [
    { service_id: 1, service: 'General Enquiry', prefix: 'GEN', joined: 5, completed: 2, completion_rate: 0.4, cancelled: 1, skipped: 1, absent: 1, in_progress: 0, avg_waiting: 15, max_waiting: 20, avg_service_duration: 6 },
    { service_id: 2, service: 'Payments', prefix: 'PAY', joined: 0, completed: 0, completion_rate: null, cancelled: 0, skipped: 0, absent: 0, in_progress: 0, avg_waiting: null, max_waiting: null, avg_service_duration: null }] },
  util: { counters: [
    { counter_id: 1, counter: 'GEN 1', service: 'General Enquiry', open_minutes: 240, serving_minutes: 90, utilization: 0.375, customers_served: 3, avg_service_duration: 40 },
    { counter_id: 2, counter: 'GEN 2', service: 'General Enquiry', open_minutes: 0, serving_minutes: 0, utilization: null, customers_served: 0, avg_service_duration: null }] },
  acc: { overall: { n: 3, mae: 2.3333, rmse: 2.3805, r2: 0.9 }, groups: [], awaiting_outcome: 1, note: 'Bias is the average of (predicted - actual); positive means customers were told longer than they waited.',
    trend: [{ date: '2026-03-02', label: '02 Mar', n: 2, mae: 2, bias: 0 }], points: [{ predicted: 10, actual: 12, source: 'fallback' }, { predicted: 20, actual: 18, source: 'fallback' }] },
}
function mockAnalytics(over = {}) {
  const d = { ...A, ...over }
  api.getQueueLength.mockResolvedValue(d.queue); api.getWaitingByHour.mockResolvedValue(d.wait); api.getDailyVolume.mockResolvedValue(d.volume)
  api.getServicePerformance.mockResolvedValue(d.perf); api.getCounterUtilization.mockResolvedValue(d.util); api.getPredictionAccuracy.mockResolvedValue(d.acc)
}

// ------------------------------------------------------------------ analytics
test('analytics shows every required measure from the API data', async () => {
  mockAnalytics()
  renderAt('/admin/analytics')
  expect(await screen.findByText('Queue length over time')).toBeInTheDocument()
  expect(screen.getByText(/Busiest moment in this window: 7/)).toBeInTheDocument()
  expect(bodyRows('Queue length over time data').map((r) => r.textContent)).toEqual(['09:0022', '10:0057']) // time, waiting then, highest within the hour
  expect(bodyRows('Average waiting time by hour data')).toHaveLength(1) // hours without data are not plotted
  expect(within(bodyRows('Average waiting time by hour data')[0]).getByText('15')).toBeInTheDocument()
  expect(screen.getByText(/Totals: 5 joined, 2 completed, 1 cancelled, 1 skipped, 1 absent/)).toBeInTheDocument()
  expect(bodyRows('Customers per day data')).toHaveLength(2)
  const perf = bodyRows('Service performance data')[0]
  expect(within(perf).getByText('40%')).toBeInTheDocument()
  expect(within(perf).getByText('15 min')).toBeInTheDocument()
  expect(within(bodyRows('Service performance data')[1]).getAllByText('-').length).toBeGreaterThan(0) // never 0% for "no tickets"
  const util = bodyRows('Counter utilization data')
  expect(within(util[0]).getByText('37.5%')).toBeInTheDocument()
  expect(within(util[1]).getByText('-')).toBeInTheDocument()
  expect(screen.getByText(/No open time recorded in this period for: GEN 2/)).toBeInTheDocument()
})

test('prediction accuracy shows MAE, RMSE and R² and explains bias', async () => {
  mockAnalytics()
  renderAt('/admin/analytics')
  await screen.findByText('Prediction accuracy')
  const card = (label) => screen.getByText(label).closest('.qp-stat')
  expect(within(card('MAE')).getByText('2.3 min')).toBeInTheDocument()
  expect(within(card('RMSE')).getByText('2.4 min')).toBeInTheDocument()
  expect(within(card('R²')).getByText('0.900')).toBeInTheDocument()
  expect(within(card('Awaiting outcome')).getByText('1')).toBeInTheDocument()
  expect(screen.getByText(/positive means customers were told longer/)).toBeInTheDocument()
  expect(bodyRows('Predicted vs actual waiting time data')).toHaveLength(2)
  expect(bodyRows('Prediction error trend data')[0].textContent).toBe('02 Mar220') // day, 2 predictions, MAE 2, bias 0
})

test('with nothing measured the page says so instead of showing zeros', async () => {
  mockAnalytics({
    wait: { measured: 0, hours: [] }, volume: { days: [], totals: { joined: 0, completed: 0, cancelled: 0, skipped: 0, absent: 0, in_progress: 0 } },
    perf: { services: [{ ...A.perf.services[1] }] }, util: { counters: [] }, acc: { overall: { n: 0, mae: null, rmse: null, r2: null }, awaiting_outcome: 4, trend: [], points: [], note: '' },
  })
  renderAt('/admin/analytics')
  expect(await screen.findByText('No measured waiting times in this period yet.')).toBeInTheDocument()
  expect(screen.getByText('Nobody joined a queue in this period.')).toBeInTheDocument()
  expect(screen.getByText('No tickets in this period.')).toBeInTheDocument()
  expect(screen.getByText('No counters yet.')).toBeInTheDocument()
  expect(screen.getByText(/No predictions with a measured outcome in this period yet. 4 awaiting an outcome./)).toBeInTheDocument()
  expect(screen.queryByText('MAE')).not.toBeInTheDocument()
})

test('a single measured prediction shows R² as unavailable, not as a number', async () => {
  mockAnalytics({ acc: { ...A.acc, overall: { n: 1, mae: 4, rmse: 4, r2: null } } })
  renderAt('/admin/analytics')
  await screen.findByText('Prediction accuracy')
  const r2 = screen.getByText('R²').closest('.qp-stat')
  expect(within(r2).getByText('-')).toBeInTheDocument()
  expect(within(r2).getByText('Needs at least 10 predictions')).toBeInTheDocument()
})

test('period, window and service controls change the API calls', async () => {
  mockAnalytics()
  renderAt('/admin/analytics')
  await screen.findByText('Queue length over time')
  expect(api.getQueueLength).toHaveBeenLastCalledWith({ hours: 24 })
  expect(api.getDailyVolume).toHaveBeenLastCalledWith({ days: 7 })
  fireEvent.change(screen.getByLabelText('Period'), { target: { value: '14' } })
  await waitFor(() => expect(api.getDailyVolume).toHaveBeenLastCalledWith({ days: 14 }))
  fireEvent.change(screen.getByLabelText('Queue length window'), { target: { value: '48' } })
  await waitFor(() => expect(api.getQueueLength).toHaveBeenLastCalledWith({ hours: 48 }))
  fireEvent.change(await screen.findByLabelText('Service'), { target: { value: '1' } })
  await waitFor(() => expect(api.getDailyVolume).toHaveBeenLastCalledWith({ days: 14, service_id: '1' }))
  expect(api.getQueueLength).toHaveBeenLastCalledWith({ hours: 48, service_id: '1' })
  expect(api.getCounterUtilization).toHaveBeenLastCalledWith({ days: 14 }) // utilization is per counter, not filtered by service
})

test('analytics refreshes itself and reports server failures', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mockAnalytics()
  renderAt('/admin/analytics')
  await screen.findByText('Queue length over time')
  const before = api.getDailyVolume.mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
  expect(api.getDailyVolume.mock.calls.length).toBeGreaterThan(before)
  api.getDailyVolume.mockRejectedValue({ response: { status: 500, data: { message: 'An unexpected error occurred.' } } })
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred.')
})

// ------------------------------------------------------------------ recommendations
const rec = (over = {}) => ({
  service: { id: 1, name: 'General Enquiry', prefix: 'GEN' }, action: 'OPEN_COUNTER', priority: 'HIGH', suggested_additional_counters: 1,
  headline: 'High congestion detected. 12 customers are waiting, the estimated waiting time is 120 minutes, and 1 counter is active. Consider opening 1 additional counter.',
  reasons: ['12 customers are waiting, which is HIGH congestion (HIGH starts at 11 waiting).', 'A new customer would wait about 120 minutes (the alert threshold is 30 minutes).'],
  candidate_counters: [{ id: 2, name: 'GEN 2' }],
  data: { waiting: 12, congestion: 'HIGH', estimated_wait: 120, estimate_source: 'machine_learning', arrival_rate_per_hour: 16, arrival_window_minutes: 30, avg_service_minutes: 10,
    offered_load: 2.67, counters: { open: 1, busy: 1, available: 0 }, staff_on_open_counters: 1 }, ...over })
const none = rec({ service: { id: 2, name: 'Payments', prefix: 'PAY' }, action: 'NONE', priority: 'NONE', suggested_additional_counters: 0, headline: 'No action needed for Payments.',
  reasons: ['1 customer is waiting (low congestion; HIGH starts at 11).'], candidate_counters: [], data: { ...rec().data, waiting: 1, congestion: 'LOW', estimated_wait: null, estimate_source: 'unavailable', offered_load: null, counters: { open: 0, busy: 0, available: 0 } } })

test('recommendations show the headline, every reason, candidates and the data', async () => {
  api.getRecommendations.mockResolvedValue({ recommendations: [rec(), none] })
  renderAt('/admin/recommendations')
  const card = (await screen.findByText(/High congestion detected\. 12 customers are waiting/)).closest('section')
  expect(within(card).getByText('High priority')).toBeInTheDocument()
  expect(within(card).getByText(/HIGH starts at 11 waiting/)).toBeInTheDocument()
  expect(within(card).getByText(/alert threshold is 30 minutes/)).toBeInTheDocument()
  expect(within(card).getByText('GEN 2')).toBeInTheDocument()
  expect(within(card).getByText(/Offered load per open counter/)).toBeInTheDocument()
  expect(within(card).getByText('120 min')).toBeInTheDocument() // the estimate in the data list
  expect(screen.getByText(/It is advisory: nothing is opened automatically/)).toBeInTheDocument()
  const calm = screen.getByText('No action needed for Payments.').closest('section')
  expect(within(calm).getByText('No action')).toBeInTheDocument()
  expect(within(calm).queryByText(/Counters you could open/)).not.toBeInTheDocument()
  expect(within(calm).getByText(/not available \(no open counter\)/)).toBeInTheDocument()
})

test('when no staffed counter exists the page points to assigning staff', async () => {
  api.getRecommendations.mockResolvedValue({ recommendations: [rec({ candidate_counters: [], suggested_additional_counters: 0 })] })
  renderAt('/admin/recommendations')
  expect(await screen.findByText(/No staffed closed counter exists for this service/)).toBeInTheDocument()
  expect(within(screen.getByRole('main')).getByRole('link', { name: 'Counters' })).toHaveAttribute('href', '/admin/counters')
})

test('recommendations: empty state, error and auto-refresh', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  api.getRecommendations.mockResolvedValue({ recommendations: [] })
  renderAt('/admin/recommendations')
  expect(await screen.findByText('No active services')).toBeInTheDocument()
  api.getRecommendations.mockResolvedValue({ recommendations: [rec()] })
  await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
  expect(await screen.findByText(/High congestion detected/)).toBeInTheDocument()
  api.getRecommendations.mockRejectedValue({ response: { status: 500, data: { message: 'An unexpected error occurred.' } } })
  await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
  expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred.')
})

// ------------------------------------------------------------------ dashboard card
const dash = () => ({ summary: { served_today: 1, waiting: 12, called: 0, being_served: 1, avg_waiting_time: null, avg_service_duration: null, active_counters: 1, busy_counters: 1, total_counters: 2,
  congestion: { level: 'HIGH', thresholds: { moderate: 5, high: 11, critical: 21 } } }, services: [], counters: [] })

test('dashboard lists only actionable recommendations, at most three', async () => {
  api.getAdminDashboard.mockResolvedValue(dash())
  const many = [1, 2, 3, 4].map((i) => rec({ service: { id: i, name: `Svc ${i}`, prefix: `S${i}` }, headline: `Headline ${i}` }))
  api.getRecommendations.mockResolvedValue({ recommendations: [none, ...many] }) // the no-action service comes FIRST: the card must still skip it
  renderAt('/admin')
  expect(await screen.findByText('Headline 1')).toBeInTheDocument()
  expect(screen.getByText('Headline 3')).toBeInTheDocument()
  expect(screen.queryByText('Headline 4')).not.toBeInTheDocument()
  expect(screen.queryByText('No action needed for Payments.')).not.toBeInTheDocument()
})

test('dashboard says nothing is needed when every service is fine, and survives an advice failure', async () => {
  api.getAdminDashboard.mockResolvedValue(dash())
  api.getRecommendations.mockResolvedValue({ recommendations: [none] })
  const { unmount } = renderAt('/admin')
  expect(await screen.findByText(/No action needed: every service is within the configured limits/)).toBeInTheDocument()
  unmount()
  api.getRecommendations.mockRejectedValue({ response: { status: 500, data: { message: 'boom' } } })
  renderAt('/admin')
  expect(await screen.findByText('Customers served today')).toBeInTheDocument() // the dashboard itself is unaffected
})

// ------------------------------------------------------------------ reports
function stubDownload() {
  URL.createObjectURL = vi.fn(() => 'blob:fake')
  URL.revokeObjectURL = vi.fn()
  return vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
}
const blob = new Blob(['a,b\n1,2\n'], { type: 'text/csv' })

test('every report downloads with the chosen parameters and is saved as a file', async () => {
  const click = stubDownload()
  api.downloadReport.mockImplementation(async (name) => ({ blob, filename: `queuepilot-${name}.csv` }))
  renderAt('/admin/reports')
  const today = todayLocal()
  fireEvent.click(await screen.findByRole('button', { name: 'Download Daily report CSV' }))
  await waitFor(() => expect(api.downloadReport).toHaveBeenCalledWith('daily', { date: today }))
  expect(await screen.findByText('Downloaded queuepilot-daily.csv')).toBeInTheDocument()
  expect(click).toHaveBeenCalled()
  expect(URL.createObjectURL).toHaveBeenCalledWith(blob)

  fireEvent.change(screen.getByLabelText('Weekly report: Any date in the week'), { target: { value: '2026-03-05' } })
  fireEvent.click(screen.getByRole('button', { name: 'Download Weekly report CSV' }))
  await waitFor(() => expect(api.downloadReport).toHaveBeenCalledWith('weekly', { date: '2026-03-05' }))
  fireEvent.change(screen.getByLabelText('Monthly report: Month'), { target: { value: '2026-02' } })
  fireEvent.click(screen.getByRole('button', { name: 'Download Monthly report CSV' }))
  await waitFor(() => expect(api.downloadReport).toHaveBeenCalledWith('monthly', { month: '2026-02' }))
  fireEvent.change(screen.getByLabelText('Service performance: From'), { target: { value: '2026-03-01' } })
  fireEvent.change(screen.getByLabelText('Service performance: To'), { target: { value: '2026-03-09' } })
  fireEvent.click(screen.getByRole('button', { name: 'Download Service performance CSV' }))
  await waitFor(() => expect(api.downloadReport).toHaveBeenCalledWith('services', { from: '2026-03-01', to: '2026-03-09' }))
  fireEvent.click(screen.getByRole('button', { name: 'Download Counter performance CSV' }))
  await waitFor(() => expect(api.downloadReport).toHaveBeenCalledWith('counters', expect.objectContaining({ to: today })))
  fireEvent.click(screen.getByRole('button', { name: 'Download ML model performance CSV' }))
  await waitFor(() => expect(api.downloadReport).toHaveBeenCalledWith('models', {}))
})

test('a refused report shows the server message and the button recovers', async () => {
  stubDownload()
  api.downloadReport.mockRejectedValue({ response: { status: 400, data: { message: 'month must look like 2026-03.' } } })
  renderAt('/admin/reports')
  fireEvent.click(await screen.findByRole('button', { name: 'Download Monthly report CSV' }))
  expect(await screen.findByText('month must look like 2026-03.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Download Monthly report CSV' })).not.toBeDisabled()
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})

test('the download button is disabled while the report is being prepared', async () => {
  stubDownload()
  let release
  api.downloadReport.mockReturnValue(new Promise((r) => { release = r }))
  renderAt('/admin/reports')
  fireEvent.click(await screen.findByRole('button', { name: 'Download Daily report CSV' }))
  expect(await screen.findByText('Preparing…')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Download Daily report CSV' })).toBeDisabled()
  await act(async () => { release({ blob, filename: 'x.csv' }) })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Download Daily report CSV' })).not.toBeDisabled())
})

test('a JSON error returned for a blob download is turned back into a readable error', async () => {
  const err = { response: { status: 400, data: new Blob([JSON.stringify({ error: 'validation_error', message: 'date must look like 2026-03-02.' })]) } }
  expect((await readBlobError(err)).response.data.message).toBe('date must look like 2026-03-02.')
  const plain = { response: { status: 500, data: new Blob(['<html>oops</html>']) } }
  expect(await readBlobError(plain)).toBe(plain) // not JSON: left alone, no crash
  const noBody = { message: 'Network Error' }
  expect(await readBlobError(noBody)).toBe(noBody)
})

// ------------------------------------------------------------------ access and navigation
test('only admins reach analytics, recommendations and reports', async () => {
  for (const [role, path] of [['CUSTOMER', '/admin/analytics'], ['STAFF', '/admin/recommendations'], ['CUSTOMER', '/admin/reports']]) {
    api.getMe.mockResolvedValue({ user: { ...admin, role } })
    const { unmount } = renderAt(path)
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
    unmount()
    cleanup()
  }
  expect(api.getQueueLength).not.toHaveBeenCalled()
  expect(api.getRecommendations).not.toHaveBeenCalled()
  expect(api.downloadReport).not.toHaveBeenCalled()
})

test('the admin sidebar links to the new pages', async () => {
  api.getAdminDashboard.mockResolvedValue(dash())
  renderAt('/admin')
  for (const [label, href] of [['Analytics', '/admin/analytics'], ['Recommendations', '/admin/recommendations'], ['Reports', '/admin/reports']]) {
    expect(await screen.findByRole('link', { name: new RegExp(`^${label}`) })).toHaveAttribute('href', href)
  }
})
