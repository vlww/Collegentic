import type { LucideIcon } from "lucide-react";
import {
  LayoutDashboard,
  GraduationCap,
  CheckSquare,
  FileText,
  ClipboardList,
  Gauge,
  Settings as SettingsIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

/** Sidebar navigation — mirrors .agents-cli-spec.md § Frontend Structure.
 * Tasks absorbs Requirements (one unified to-do view instead of two
 * overlapping lists). Essay Map AND essay-requirement progress both live
 * inside Essays, and Agent Activity inside Settings, to keep the sidebar
 * itself short for demos. My Progress is the one place a student
 * self-reports account-wide (not per-college) test scores and
 * recommendations rather than an agent inferring it — feeds
 * compute_readiness_score directly. */
export const NAV_ITEMS: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/colleges", label: "Colleges", icon: GraduationCap },
  { to: "/tasks", label: "Tasks", icon: CheckSquare },
  { to: "/essays", label: "Essays", icon: FileText },
  { to: "/progress", label: "My Progress", icon: ClipboardList },
  { to: "/readiness", label: "Application Readiness", icon: Gauge },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];
