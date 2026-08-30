import type { ComponentType, ReactNode } from "react";
import { cn } from "@/utils";

interface SectionCardProps {
  title: string;
  /** A small lucide icon, tinted orange against the navy bar — same
   * treatment as TodaysPriorities/ConflictAlerts on the Dashboard. */
  icon?: ComponentType<{ className?: string }>;
  /** Right-aligned slot in the navy bar (a button, badge, link, ...) — style
   * it for a dark background (see e.g. Settings.tsx's "See all" button). */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Padding/layout for the body below the navy bar. Defaults to a plain
   * padded panel; pass "" (or "divide-y divide-border") for content that
   * already paces its own rows, e.g. a list of `divide-y` items. */
  contentClassName?: string;
}

/**
 * The one consistent "bubble" shape used for every card-like section across
 * the app: a navy header bar (icon + title, optional right-aligned action)
 * over a bordered, rounded panel — the same shape Dashboard's
 * TodaysPriorities/ConflictAlerts already used. Centralized here so every
 * page's list/table sections (Essays, My Progress, Settings, Agent
 * Activity, College Detail) share one visual language instead of each
 * inventing its own header treatment.
 */
export function SectionCard({
  title,
  icon: Icon,
  action,
  children,
  className,
  contentClassName = "p-4",
}: SectionCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border shadow-sm bg-card",
        className
      )}
    >
      {/* `rounded-t-lg` here (not `overflow-hidden` on the outer div) is
          what keeps this bar's square corners from poking past the
          panel's own rounded ones — overflow-hidden on the outer div
          instead clipped anything a child popped open outside its box
          (found live: Progress.tsx's college multi-select dropdown got
          cut off/unclickable inside the Recommendations panel). */}
      <div className="bg-navy text-navy-foreground px-4 py-2.5 rounded-t-lg flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide">
          {Icon && <Icon className="h-3.5 w-3.5 text-orange" />}
          {title}
        </h2>
        {action}
      </div>
      <div className={contentClassName}>{children}</div>
    </div>
  );
}
