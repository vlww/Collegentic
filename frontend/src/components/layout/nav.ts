import type { LucideIcon } from "lucide-react";
import {
  LayoutDashboard,
  GraduationCap,
  ListChecks,
  FileText,
  CheckSquare,
  ArrowUpNarrowWide,
  Network,
  Gauge,
  Activity,
  Settings as SettingsIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

/** Sidebar navigation — mirrors .agents-cli-spec.md § Frontend Structure. */
export const NAV_ITEMS: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/colleges", label: "Colleges", icon: GraduationCap },
  { to: "/requirements", label: "Requirements", icon: ListChecks },
  { to: "/essays", label: "Essays", icon: FileText },
  { to: "/tasks", label: "Tasks", icon: CheckSquare },
  { to: "/priorities", label: "Priorities", icon: ArrowUpNarrowWide },
  { to: "/essay-map", label: "Essay Map", icon: Network },
  { to: "/readiness", label: "Application Readiness", icon: Gauge },
  { to: "/agent-activity", label: "Agent Activity", icon: Activity },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];
