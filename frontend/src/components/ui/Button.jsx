export default function Button({ variant = 'primary', className = '', ...props }) {
  return <button className={`qp-btn qp-btn--${variant} ${className}`} {...props} />
}
