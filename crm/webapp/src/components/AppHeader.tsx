import logoCrown from '/logo.svg'

interface Props {
  title: string
  children?: React.ReactNode
}

export default function AppHeader({ title, children }: Props) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5 sticky top-0 z-20"
      style={{
        background: 'linear-gradient(180deg, rgba(5, 5, 5, 0.95), rgba(5, 5, 5, 0.85))',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderBottom: '1px solid rgba(16, 185, 129, 0.04)',
      }}
    >
      <div className="flex items-center gap-2.5">
        <div
          className="flex items-center justify-center flex-shrink-0"
          style={{
            width: 30,
            height: 30,
            borderRadius: '50%',
            background: 'rgba(16, 185, 129, 0.08)',
            border: '1px solid rgba(16, 185, 129, 0.15)',
            boxShadow: '0 0 12px rgba(16, 185, 129, 0.1)',
          }}
        >
          <img src={logoCrown} alt="" width={18} height={18} />
        </div>
        <div className="flex items-baseline gap-1.5">
          <span className="text-gradient font-bold text-sm">ProcessingHub</span>
          <span className="text-gray-600 text-[10px]">/</span>
          <span className="text-gray-400 text-sm font-medium">{title}</span>
        </div>
      </div>
      {children && (
        <div className="flex items-center gap-2">
          {children}
        </div>
      )}
    </div>
  )
}
