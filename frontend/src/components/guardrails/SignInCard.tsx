import type { ReactNode } from 'react'

export default function SignInCard({ title, subtitle, children }: {
  title: string; subtitle: string; children: ReactNode
}) {
  return (
    <main className="fixed inset-0 z-[90] overflow-y-auto bg-[#f6f7f6] text-[#111827]">
      <div className="flex min-h-full items-center justify-center px-4 py-6 sm:py-8">
        <section aria-label="Account access"
          className="w-full max-w-[440px] rounded-3xl border border-black/5 bg-white px-6 py-8 shadow-lg sm:px-10">
          <img src="/cgiar-logo.svg" alt="CGIAR" width="52" height="60"
            className="mx-auto mb-4 h-[60px] w-auto" />
          <p className="text-center text-base font-semibold tracking-tight text-[#3c6e37]">Innovation Analytics</p>
          <h1 className="mt-7 text-center font-sans text-[28px] font-bold tracking-tight">{title}</h1>
          <p className="mt-2 text-center text-sm leading-relaxed text-[#6b7280]">{subtitle}</p>
          <div className="my-7 border-t border-black/5" />
          {children}
          <p className="mt-8 text-center text-xs leading-relaxed text-[#8b93a1]">
            CGIAR Portfolio Performance Team · Office of the Chief Scientist
          </p>
        </section>
      </div>
    </main>
  )
}
