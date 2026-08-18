import { useEffect, useState } from "react";
import { checkHealth, type HealthStatus } from "@/lib/api";
import { cn } from "@/utils";

/**
 * Milestone 1's end-to-end proof: pings the backend's /health route on a
 * short interval and renders live connectivity state in the top bar.
 */
export function BackendStatus() {
  const [status, setStatus] = useState<HealthStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const result = await checkHealth();
      if (!cancelled) setStatus(result);
    };
    poll();
    const interval = setInterval(poll, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const ok = status?.status === "ok";
  const label = status === null ? "Checking backend…" : ok ? "Backend connected" : "Backend unreachable";

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          status === null ? "bg-muted-foreground/40" : ok ? "bg-success" : "bg-destructive"
        )}
      />
      {label}
    </div>
  );
}
