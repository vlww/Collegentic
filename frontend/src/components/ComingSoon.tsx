import { Card, CardContent } from "@/components/ui/card";

interface ComingSoonProps {
  milestone: string;
  children: React.ReactNode;
}

/** Marks a page's real implementation as a specific future milestone, per
 * the "label unbuilt features rather than fake them" rule in the spec. */
export function ComingSoon({ milestone, children }: ComingSoonProps) {
  return (
    <Card className="border-dashed">
      <CardContent className="text-sm text-muted-foreground space-y-2">
        <p>{children}</p>
        <p className="text-xs uppercase tracking-wide text-orange font-medium">
          {milestone}
        </p>
      </CardContent>
    </Card>
  );
}
