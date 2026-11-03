import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import App from '../App.jsx'
import * as api from '../services/api.js'
import { customerDefaults } from './mockApi.js'

vi.mock('../services/api.js', async () => (await import('./mockApi.js')).apiMock())

beforeEach(() => {
  localStorage.clear()
  customerDefaults(api)
  api.getHealth.mockResolvedValue({ status: 'ok' })
  api.getDbHealth.mockRejectedValue(new Error('down'))
})

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )

test('renders shell and shows API online, DB unavailable', async () => {
  renderAt('/')
  expect(screen.getByText('Welcome to QueuePilot')).toBeInTheDocument()
  expect(screen.getByText('Smarter Queues. Less Waiting.')).toBeInTheDocument()
  await waitFor(() => {
    expect(screen.getByText('Online')).toBeInTheDocument()
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
  })
})

test('unknown route renders not-found page', () => {
  renderAt('/does-not-exist')
  expect(screen.getByText('Page not found')).toBeInTheDocument()
})
