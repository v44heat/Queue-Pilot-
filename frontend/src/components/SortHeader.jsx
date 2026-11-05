// A column header that sorts on click (asc -> desc -> asc). Announces its state to assistive technology.
export default function SortHeader({ label, sortKey, sort, order, onSort }) {
  const active = sort === sortKey
  return (
    <th aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="qp-sort" onClick={() => onSort(sortKey, active && order === 'asc' ? 'desc' : 'asc')}>
        {label}<span aria-hidden="true">{active ? (order === 'asc' ? ' ▲' : ' ▼') : ''}</span>
      </button>
    </th>
  )
}
