import { NavLink } from "react-router-dom";
import { cn } from "@/utils";
import logo from "@/assets/logo.png";
import { NAV_ITEMS } from "./nav";

export function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-60 md:flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border shrink-0">
      <div className="h-16 flex items-center gap-2.5 px-4 border-b border-sidebar-border">
        <img src={logo} alt="" className="h-9 w-9 shrink-0 object-contain" />
        <span className="font-semibold tracking-tight text-xl">Collegentic</span>
      </div>
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="px-4 py-3 border-t border-sidebar-border text-xs text-sidebar-foreground/50">
        Application year 2026–27
      </div>
    </aside>
  );
}
