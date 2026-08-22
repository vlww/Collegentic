import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/utils";
import type { AgentRunStatus } from "@/lib/types";

const CONFIG: Record<
  AgentRunStatus,
  { label: string; className: string; icon: typeof Loader2 }
> = {
  running: {
    label: "Running",
    className: "border-orange/30 bg-orange-tint text-orange",
    icon: Loader2,
  },
  completed: {
    label: "Completed",
    className: "border-success/30 bg-success/10 text-success",
    icon: CheckCircle2,
  },
  waiting_for_user: {
    label: "Waiting for you",
    className: "border-warning/30 bg-warning/10 text-warning",
    icon: Clock,
  },
  failed: {
    label: "Failed",
    className: "border-destructive/30 bg-destructive/10 text-destructive",
    icon: XCircle,
  },
};

export function AgentRunStatusBadge({ status }: { status: AgentRunStatus }) {
  const { label, className, icon: Icon } = CONFIG[status];
  return (
    <Badge variant="outline" className={cn(className)}>
      <Icon className={cn("h-3 w-3", status === "running" && "animate-spin")} />
      {label}
    </Badge>
  );
}
