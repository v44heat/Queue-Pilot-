import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import App from '../App.jsx'
import * as api from '../services/api.js'

vi.mock('../services/api.js', () => ({
  getHealth: vi.fn(),
  getDbHealth: vi.fn(),
  loginRequest: vi.fn(),
  registerRequest: vi.fn(),
  logoutRequest: vi.fn(),
  getMe: vi.fn(),
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  default: {},
}))

const customer = { id: 2, name: 'Jane Customer', email: 'jane@example.com', role: 'CUSTOMER', status: 'ACTIVE' }
const admin = { id: 1, name: 'Root Admin', email: 'root@example.com', role: 'ADMIN', status: 'ACTIVE' }

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  api.listUsers.mockResolvedValue({ users: [admin, customer], total: 2, pages: 1, page: 1 })
})

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )

test('anonymous user is redirected from protected page to login', async () => {
  renderAt('/admin/users')
  expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
  expect(api.listUsers).not.toHaveBeenCalled()
})

test('customer is denied the admin page and the admin API is never called', async () => {
  localStorage.setItem('qp_token', 'tok')
  api.getMe.mockResolvedValue({ user: customer })
  renderAt('/admin/users')
  expect(await screen.findByText('Access denied')).toBeInTheDocument()
  expect(api.listUsers).not.toHaveBeenCalled()
})

test('admin sees the user list with real API data', async () => {
  localStorage.setItem('qp_token', 'tok')
  api.getMe.mockResolvedValue({ user: admin })
  renderAt('/admin/users')
  expect(await screen.findByText('jane@example.com')).toBeInTheDocument()
  expect(screen.getByText('Users (2)')).toBeInTheDocument()
  // admin cannot edit their own role
  expect(screen.getByLabelText('Role for root@example.com')).toBeDisabled()
})

test('login stores token and lands on the role dashboard', async () => {
  api.loginRequest.mockResolvedValue({ access_token: 'abc', user: customer })
  renderAt('/login')
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'jane@example.com' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Passw0rd!x' } })
  fireEvent.click(screen.getByRole('button', { name: 'Log in' }))
  expect(await screen.findByText('Customer dashboard')).toBeInTheDocument()
  expect(api.loginRequest).toHaveBeenCalledWith('jane@example.com', 'Passw0rd!x')
  expect(localStorage.getItem('qp_token')).toBe('abc')
})

test('failed login shows the server message and does not store a token', async () => {
  api.loginRequest.mockRejectedValue({ response: { status: 401, data: { message: 'Invalid email or password.' } } })
  renderAt('/login')
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'x@example.com' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'nope' } })
  fireEvent.click(screen.getByRole('button', { name: 'Log in' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
  expect(localStorage.getItem('qp_token')).toBeNull()
})

test('register blocks mismatched passwords without calling the API', async () => {
  renderAt('/register')
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Passw0rd!x' } })
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'different1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Register' }))
  expect(await screen.findByText('Passwords do not match.')).toBeInTheDocument()
  expect(api.registerRequest).not.toHaveBeenCalled()
})

test('register maps server field errors onto the form', async () => {
  api.registerRequest.mockRejectedValue({
    response: { status: 409, data: { message: 'An account with this email already exists.', details: { email: 'Email already registered.' } } },
  })
  renderAt('/register')
  for (const [label, value] of [['Full name', 'Jane Doe'], ['Email', 'jane@example.com'], ['Password', 'Passw0rd!x'], ['Confirm password', 'Passw0rd!x']]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } })
  }
  fireEvent.click(screen.getByRole('button', { name: 'Register' }))
  expect(await screen.findByText('Email already registered.')).toBeInTheDocument()
})

test('logout clears the token and returns to login', async () => {
  localStorage.setItem('qp_token', 'tok')
  api.getMe.mockResolvedValue({ user: customer })
  api.logoutRequest.mockResolvedValue({})
  renderAt('/customer')
  fireEvent.click(await screen.findByRole('button', { name: /log out/i }))
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Log in' })).toBeInTheDocument())
  expect(localStorage.getItem('qp_token')).toBeNull()
  expect(api.logoutRequest).toHaveBeenCalled()
})
