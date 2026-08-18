import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { BackendStatus } from "./BackendStatus";

export function AppLayout() {
  return (
    <div className="flex h-screen bg-background text-foreground">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 shrink-0 border-b border-border flex items-center justify-end px-6">
          <BackendStatus />
        </header>
        <main className="flex-1 overflow-y-auto px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
