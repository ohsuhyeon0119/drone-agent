/* 공용 컴포넌트 — ADMIN_DESIGN.md §3 컴포넌트 규칙 */

export function Button({ variant = "outline", className = "", ...props }) {
  const base =
    "inline-flex items-center justify-center gap-2 h-14 px-6 text-[15px] rounded-(--radius-ctl) " +
    "font-bold transition-colors duration-150 cursor-pointer disabled:opacity-40 disabled:cursor-default";
  const styles = {
    primary: "bg-accent text-white hover:bg-[#2257c4]",
    outline: "border border-line bg-surface hover:border-accent text-ink",
    ghost: "text-muted hover:text-ink",
    danger: "border border-warn/40 text-warn bg-surface hover:bg-warnsoft",
  };
  return <button className={`${base} ${styles[variant]} ${className}`} {...props} />;
}

export function Toggle({ checked, onChange, label }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative w-14 h-8 rounded-full transition-colors duration-150 cursor-pointer flex-none
        ${checked ? "bg-accent" : "bg-line"}`}
    >
      <span
        className={`absolute top-1 left-1 w-6 h-6 rounded-full bg-white shadow transition-transform duration-150
          ${checked ? "translate-x-6" : "translate-x-0"}`}
      />
    </button>
  );
}

export function Modal({ open, title, children, onClose }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-[448px] max-h-[90vh] overflow-y-auto bg-surface rounded-(--radius-card) p-9 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-[19px] font-bold mb-5">{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function EmptyState({ children }) {
  return (
    <div className="border border-dashed border-line rounded-(--radius-card) py-14 px-6 text-center text-muted text-[15px]">
      {children}
    </div>
  );
}

export function PageHeader({ title, sub }) {
  return (
    <header className="mb-9">
      <h1 className="text-[27px] font-bold [text-wrap:balance]">{title}</h1>
      {sub && <p className="text-muted mt-2 text-[15px]">{sub}</p>}
    </header>
  );
}

export function Field({ label, help, children }) {
  return (
    <label className="block mb-5">
      <span className="block text-[15px] font-bold mb-2">{label}</span>
      {children}
      {help && <span className="block text-[14px] text-muted mt-1.5">{help}</span>}
    </label>
  );
}

export const inputCls =
  "w-full h-14 px-4 text-[15px] rounded-(--radius-ctl) border border-line bg-surface " +
  "placeholder:text-muted/60 focus:border-accent";
