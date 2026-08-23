import { Sparkles } from "lucide-react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { BackendStatus } from "./BackendStatus";
import { Badge } from "@/components/ui/badge";
import { isDemoSession } from "@/lib/api";

export function AppLayout() {
  return (
    <div className="flex h-screen bg-background text-foreground">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 shrink-0 border-b border-border flex items-center justify-end gap-3 px-6">
          {isDemoSession() && (
            <Badge variant="outline" className="border-orange/30 bg-orange-tint text-orange">
              <Sparkles className="h-3 w-3" />
              Demo Mode
            </Badge>
          )}
          <BackendStatus />
        </header>
        <main className="flex-1 overflow-y-auto px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
