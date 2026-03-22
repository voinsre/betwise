import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col bg-brand-bg">
      {/* Navbar */}
      <header className="border-b border-brand-border bg-brand-surface/50 px-4 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center overflow-hidden">
              <img src="/icon-192.png" alt="WizerBet" className="w-full h-full" />
            </div>
            <h1 className="text-lg font-bold text-white">
              Wizer<span className="text-accent-green">Bet</span>
            </h1>
          </div>
        </div>
        <nav className="flex items-center gap-4">
          <Link
            href="/chat"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            Chat
          </Link>
          <Link
            href="/history"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            History
          </Link>
          <Link
            href="/admin/login"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            Admin
          </Link>
        </nav>
      </header>

      {/* Hero */}
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        {/* Logo */}
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-6 overflow-hidden">
          <img src="/icon-192.png" alt="WizerBet" className="w-full h-full" />
        </div>

        <h2 className="text-4xl font-bold text-white mb-3">
          Wizer<span className="text-accent-green">Bet</span>
        </h2>
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
            href="/history"
            className="px-8 py-3.5 bg-brand-card border border-brand-border hover:border-gray-500 rounded-xl font-medium text-gray-300 hover:text-white transition-colors flex items-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Track Record
          </Link>
        </div>

        {/* Footer */}
        <p className="mt-16 text-xs text-gray-700">
          Predictions are not guaranteed &middot; Always bet responsibly
        </p>
      </div>
    </main>
  );
}
