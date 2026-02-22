import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8 bg-brand-bg">
      {/* Logo */}
      <div className="w-16 h-16 bg-accent-green rounded-2xl flex items-center justify-center mb-6">
        <span className="text-white font-bold text-2xl">BW</span>
      </div>

      <h1 className="text-4xl font-bold text-white mb-3">BetWise</h1>
      <p className="text-gray-500 text-lg text-center max-w-lg mb-2">
        AI-powered football betting intelligence
      </p>
      <p className="text-gray-600 text-sm text-center max-w-md mb-10">
        Blended Poisson + XGBoost predictions across 7 markets and 15 leagues.
        Real-time value detection and optimized ticket building.
      </p>

      <div className="flex gap-4">
        <Link
          href="/chat"
          className="px-8 py-3.5 bg-accent-green hover:bg-accent-green/90 rounded-xl font-medium text-white transition-colors flex items-center gap-2"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
          </svg>
          Open Chat
        </Link>
        <Link
          href="/admin/login"
          className="px-8 py-3.5 bg-brand-card border border-brand-border hover:border-gray-500 rounded-xl font-medium text-gray-300 hover:text-white transition-colors flex items-center gap-2"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          Admin Panel
        </Link>
      </div>

      {/* Footer */}
      <p className="mt-16 text-xs text-gray-700">
        Predictions are not guaranteed &middot; Always bet responsibly
      </p>
    </main>
  );
}
