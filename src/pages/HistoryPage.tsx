import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowUpRight, FileSearch } from 'lucide-react';
import { getHistory, getUsage } from '../lib/api';
import { PullToRefresh } from '../components/PullToRefresh';
import { EmptyState, ErrorState, ProgressBar, Skeleton, TickerChip } from '../components/ui';
import { formatDate } from '../lib/format';
import { useCachedQuery } from '../hooks/hooks';

export function HistoryPage() {
  const usage = useCachedQuery('usage', async () => getUsage(), { ttlMs: 30_000 });
  const hist = useCachedQuery('history', async () => getHistory(), { ttlMs: 30_000 });

  const refresh = async () => {
    await Promise.all([usage.refetch(), hist.refetch()]);
  };

  return (
    <div className="pb-10">
      <div className="sticky top-0 z-30 border-b border-white/10 bg-[#0a0a0c]/95 px-5 py-3 backdrop-blur">
        {usage.data ? (
          <div>
            <div className="flex items-center justify-between text-[13px]">
              <span className="font-medium text-white">{usage.data.used} / {usage.data.limit} used</span>
              <span className="font-mono text-[11px] text-[#a7a29a]">{usage.data.remaining} left · resets in 24h</span>
            </div>
            <ProgressBar value={usage.data.used} max={usage.data.limit} className="mt-2" />
          </div>
        ) : (
          <Skeleton className="h-9 w-full" />
        )}
        {usage.data && usage.data.remaining <= 0 && (
          <p className="mt-2 flex items-center gap-1.5 rounded-xl border border-[#fbbf24]/40 bg-[#fbbf24]/[0.07] p-2.5 text-[13px] text-[#fbbf24]" role="alert">
            <AlertTriangle size={15} /> Out of quota — <Link to="/limit" className="font-semibold underline">read the letter</Link>
          </p>
        )}
      </div>

      <PullToRefresh onRefresh={refresh}>
        <div className="px-5 pt-4">
          <h1 className="font-display text-[22px] font-bold tracking-tight text-white">Research history</h1>

          {hist.loading && !hist.data && (
            <div className="mt-4 space-y-3" aria-label="Loading history">
              {[0, 1, 2].map((i) => <Skeleton key={i} className="h-[132px] w-full" />)}
            </div>
          )}
          {hist.error && !hist.data && (
            <ErrorState message="Couldn't load your history." onRetry={() => { void hist.refetch(); }} />
          )}
          {hist.data && hist.data.length === 0 && (
            <EmptyState
              title="No researches yet"
              body="Run your first investigation — it takes about 10 seconds."
              action={<Link to="/research" className="btn-primary pressable flex min-h-[52px] items-center justify-center rounded-2xl font-display text-[15px] font-semibold text-white">Start your first research</Link>}
            />
          )}

          <ol className="mt-4 space-y-3">
            {hist.data?.map((h, i) => (
              <li key={h.sessionId} className="anim-rise" style={{ animationDelay: `${Math.min(i, 6) * 0.05}s` }}>
                <Link
                  to={`/dashboard?session_id=${h.sessionId}`}
                  className="card-dark pressable group flex gap-3.5 p-4"
                  aria-label={`Open ${h.company} research from ${formatDate(h.date)}`}
                >
                  <span className="num flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-black/40 font-mono text-[13px] text-[#ff8a3d]">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <TickerChip ticker={h.ticker} />
                      <span className="font-mono text-[11px] text-[#6b675c]">{h.period} · {formatDate(h.date)}</span>
                    </span>
                    <span className="mt-1 block truncate font-display text-[16px] font-semibold text-white">{h.company}</span>
                    <span className="mt-0.5 line-clamp-2 block text-[13px] leading-5 text-[#a7a29a]">{h.headline}</span>
                    <span className="mt-1.5 flex items-center gap-3 font-mono text-[11px] text-[#6b675c]">
                      <span className="flex items-center gap-1"><FileSearch size={12} /> {h.metrics} metrics</span>
                      <span>{h.sources} sources</span>
                    </span>
                  </span>
                  <ArrowUpRight size={18} className="mt-1 shrink-0 text-[#6b675c] transition-transform group-active:translate-x-0.5 group-active:-translate-y-0.5" />
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </PullToRefresh>
    </div>
  );
}
