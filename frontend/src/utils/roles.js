export const roleHome = (role) =>
  ({ CUSTOMER: '/customer', STAFF: '/staff', ADMIN: '/admin' })[role] || '/'
