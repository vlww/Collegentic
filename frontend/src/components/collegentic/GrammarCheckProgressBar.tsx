import { useEffect, useState } from "react";

// Capped short of 100, same reasoning as every other fake-progress bar in
// this app (TaskPlanningProgressBar, EssayProgressBar, CollegeTable's
// FakeRequirementsProgressCell): the real response always swaps this out
// first in practice, but staying short of full means even a slow real
// response can't make the fake climb and the real completion collide.
const _CAP_PERCENT = 92;

/**
 * Shown while the Essay Editor's grammar check (a real two-model backend
 * round trip, Gemma then Gemini, see agent/app/tools/grammar_check.py) is
 * in flight. No real fraction to report (one request, not an "N of M"
 * batch), so this fakes a climb client-side. Found live: the real check now
 * routinely takes 15-20+ seconds (two sequential LLM calls, not one quick
 * one), and even the once-slowed tick rate still reached the 92% cap well
 * before a real response came back and then sat there looking stuck.
 * Slowed further so the bar is still visibly climbing for most of the real
 * wait instead of parking early.
 */
export function GrammarCheckProgressBar() {
  const [percent, setPercent] = useState(15);

  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    function scheduleTick() {
      const delay = 700 + Math.random() * 1600;
      timeoutId = setTimeout(() => {
        if (cancelled) return;
        setPercent((p) => Math.min(_CAP_PERCENT, p + 6 + Math.random() * 12));
        scheduleTick();
      }, delay);
    }
    scheduleTick();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, []);

  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
      <div
        className="h-full rounded-full bg-orange transition-[width] duration-300 ease-out"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
