import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import { useNotifications } from '../../context/NotificationContext.jsx'
import usePolling from '../../hooks/usePolling.js'
import { getNotifications, markAllNotificationsRead, markNotificationRead } from '../../services/api.js'
import { apiError } from '../../utils/errors.js'
import { fmtDateTime } from '../../utils/format.js'

export default function Notifications() {
  const { refresh: refreshBadge } = useNotifications()
  const [query, setQuery] = useState({ unreadOnly: false, page: 1 })
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const params = { page: query.page, per_page: 10 }
      if (query.unreadOnly) params.unread_only = 'true'
      setData(await getNotifications(params))
      setError('')
    } catch (e) {
      setError(apiError(e).message)
    }
  }, [query])

  useEffect(() => { load() }, [load])
  usePolling(load, 15000, true)

  const after = async () => { await load(); refreshBadge() }
  const markRead = async (id) => { try { await markNotificationRead(id); await after() } catch (e) { setError(apiError(e).message) } }
  const markAll = async () => { try { await markAllNotificationsRead(); await after() } catch (e) { setError(apiError(e).message) } }

  return (
    <>
      <h1>Notifications</h1>
      <Card
        title={`Inbox${data ? ` (${data.unread} unread)` : ''}`}
        action={
          <span className="qp-actions">
            <label className="qp-check"><input type="checkbox" checked={query.unreadOnly}
              onChange={(e) => setQuery({ unreadOnly: e.target.checked, page: 1 })} /> Unread only</label>
            <Button variant="ghost" onClick={markAll} disabled={!data || data.unread === 0}>Mark all as read</Button>
          </span>
        }
      >
        {error && <div className="qp-alert" role="alert">{error}</div>}
        {!data ? <p className="qp-muted">Loading…</p> : data.notifications.length === 0 ? (
          <p className="qp-muted">{query.unreadOnly ? 'No unread notifications.' : 'No notifications yet. They appear here when you join a queue.'}</p>
        ) : (
          <ul className="qp-notes">
            {data.notifications.map((n) => (
              <li key={n.id} className={n.is_read ? 'is-read' : 'is-unread'}>
                <div>
                  <strong>{n.title}</strong>{!n.is_read && <span className="qp-dot" aria-label="unread" />}
                  <p>{n.message}</p>
                  <small className="qp-muted">{fmtDateTime(n.created_at)}</small>
                </div>
                <div className="qp-actions">
                  {n.queue_ticket_id && <Link to={`/customer/tickets/${n.queue_ticket_id}`} onClick={() => !n.is_read && markNotificationRead(n.id).then(refreshBadge).catch(() => {})}>View ticket</Link>}
                  {!n.is_read && <Button variant="ghost" onClick={() => markRead(n.id)} aria-label={`Mark "${n.title}" as read`}>Mark read</Button>}
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="qp-pager">
          <Button variant="ghost" disabled={query.page <= 1} onClick={() => setQuery({ ...query, page: query.page - 1 })}>Previous</Button>
          <span>Page {query.page} of {data?.pages || 1}</span>
          <Button variant="ghost" disabled={query.page >= (data?.pages || 1)} onClick={() => setQuery({ ...query, page: query.page + 1 })}>Next</Button>
        </div>
      </Card>
    </>
  )
}
