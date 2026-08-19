import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/utils";
import type { ConfidenceLevel } from "@/lib/types";

const LABEL: Record<ConfidenceLevel, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

const CLASSES: Record<ConfidenceLevel, string> = {
  high: "border-success/30 bg-success/10 text-success",
  medium: "border-warning/30 bg-warning/10 text-warning",
  low: "border-destructive/30 bg-destructive/10 text-destructive",
};

interface ConfidenceBadgeProps {
  confidence: ConfidenceLevel;
  needsVerification?: boolean;
}

export function ConfidenceBadge({ confidence, needsVerification }: ConfidenceBadgeProps) {
  return (
    <div className="flex items-center gap-1.5">
      <Badge variant="outline" className={cn(CLASSES[confidence])}>
        {LABEL[confidence]}
      </Badge>
      {needsVerification && (
        <span className="inline-flex items-center gap-1 text-xs text-warning" title="Verification recommended">
          <AlertTriangle className="h-3.5 w-3.5" />
        </span>
      )}
    </div>
  );
}
