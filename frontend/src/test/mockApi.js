// One shared mock of services/api.js so every test file stays in sync with the real exports.
import { vi } from 'vitest'

export const API_NAMES = [
  'getHealth', 'getDbHealth', 'loginRequest', 'registerRequest', 'logoutRequest', 'getMe',
  'listUsers', 'createUser', 'updateUser',
  'getStaffCounters', 'getCounterQueue', 'openCounter', 'closeCounter', 'callNext', 'ticketAction',
  'getServices', 'joinQueue', 'getMyActive', 'getTicket', 'cancelTicket', 'getHistory',
  'getNotifications', 'getUnreadCount', 'markNotificationRead', 'markAllNotificationsRead',
  'updateProfile', 'changePassword',
  'getAdminDashboard', 'getAdminQueue', 'adminListServices', 'adminCreateService', 'adminUpdateService',
  'adminListCounters', 'adminCreateCounter', 'adminUpdateCounter', 'adminAssignStaff', 'adminUnassignStaff',
  'getSettings', 'updateSettings', 'mlListModels', 'mlTrain', 'mlActivate', 'mlPerformance', 'mlPredictionLogs',
  'getQueueLength', 'getWaitingByHour', 'getDailyVolume', 'getServicePerformance', 'getCounterUtilization',
  'getPredictionAccuracy', 'getRecommendations', 'downloadReport',
]

export const apiMock = () => ({ ...Object.fromEntries(API_NAMES.map((n) => [n, vi.fn()])), default: {} })

// Harmless defaults for the calls every customer screen makes, so a test only overrides what it cares about.
export function customerDefaults(api) {
  api.getMyActive.mockResolvedValue({ tickets: [] })
  api.getHistory.mockResolvedValue({ tickets: [], total: 0, pages: 1, page: 1 })
  api.getUnreadCount.mockResolvedValue({ unread: 0 })
  api.getNotifications.mockResolvedValue({ notifications: [], total: 0, pages: 1, page: 1, unread: 0 })
  api.getServices.mockResolvedValue({ services: [] })
  api.getRecommendations.mockResolvedValue({ recommendations: [] })
}
