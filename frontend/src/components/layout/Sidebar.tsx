import { NavLink } from "react-router-dom";
import { cn } from "@/utils";
import logo from "@/assets/logo.png";
import { NAV_ITEMS } from "./nav";

export function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-[276px] md:flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border shrink-0">
      <div className="flex items-center justify-center gap-2 px-4 pt-6 pb-4">
        <img src={logo} alt="" className="h-[62px] w-[62px] shrink-0 object-contain" />
        <span
          className="uppercase text-[58px] leading-none"
          style={{ fontFamily: "'Maintanker', sans-serif" }}
        >
          Collegentic
        </span>
      </div>
      {/* Same color/opacity as the nav labels below (text-sidebar-foreground/75)
          instead of its own hardcoded color — one consistent "muted sidebar
          chrome" tone instead of two unrelated ones. */}
      <div className="mx-auto mb-3 h-[3px] w-[222px] rounded-full bg-sidebar-foreground/75" />
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-1">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2.5 text-base transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              )
            }
          >
            <Icon className="h-5 w-5 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="px-4 py-3 border-t border-sidebar-border text-sm text-center text-sidebar-foreground/50">
        Application year 2026-2027
      </div>
    </aside>
  );
}
