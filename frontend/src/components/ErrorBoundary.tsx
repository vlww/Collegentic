import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Catches a render error from whatever page is currently mounted inside
 * AppLayout's `<Outlet />` so it doesn't take the whole app down — before
 * this, ANY uncaught error anywhere unmounted the entire React tree,
 * leaving a fully blank screen with no way back except a manual reload
 * (found live: deleting the essay selected in the Essay Editor did exactly
 * this). Scoped around the routed page content only, not the whole app, so
 * the sidebar stays usable and "Go to Dashboard" is a real escape hatch
 * rather than requiring a reload.
 *
 * Must be a class component — React has no hook-based equivalent of
 * `getDerivedStateFromError`/`componentDidCatch`.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Page crashed:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Card className="border-destructive/40">
        <CardContent className="space-y-3">
          <p className="flex items-center gap-2 text-sm font-medium text-destructive">
            <AlertTriangle className="h-4 w-4" />
            Something went wrong loading this page.
          </p>
          <p className="text-sm text-muted-foreground">
            Try going back to the dashboard and re-opening it. If it keeps happening,
            let us know what you were doing right before this appeared.
          </p>
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              this.setState({ error: null });
              window.location.assign("/dashboard");
            }}
          >
            Go to Dashboard
          </Button>
        </CardContent>
      </Card>
    );
  }
}
