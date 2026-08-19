import { Badge } from "@/components/ui/badge";
import { cn } from "@/utils";
import type { CollegeStatus } from "@/lib/types";

const CLASSES: Record<CollegeStatus, string> = {
  Planning: "border-border bg-secondary text-secondary-foreground",
  InProgress: "border-orange-tint bg-orange-tint text-orange",
  Ready: "border-success/30 bg-success/10 text-success",
  Submitted: "border-navy/20 bg-navy/10 text-navy dark:text-foreground",
};

export function StatusBadge({ status }: { status: CollegeStatus }) {
  const label = status === "InProgress" ? "In Progress" : status;
  return (
    <Badge variant="outline" className={cn(CLASSES[status])}>
      {label}
    </Badge>
  );
}
