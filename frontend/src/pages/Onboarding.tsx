import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

/**
 * Full onboarding (NL college parsing via the Orchestrator, Demo Mode seed)
 * lands in Milestone 14. This placeholder proves the routing shell and lets
 * a user reach the sidebar app during earlier milestones.
 */
export function Onboarding() {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-navy text-navy-foreground flex items-center justify-center px-4">
      <Card className="max-w-md w-full bg-card text-card-foreground">
        <CardContent className="space-y-4 text-center">
          <h1 className="text-2xl font-semibold">Let's get your applications organized.</h1>
          <p className="text-sm text-muted-foreground">
            Onboarding (natural-language college input + Demo Mode) arrives in
            Milestone 14. For now, continue into the app shell.
          </p>
          <Button className="w-full" onClick={() => navigate("/dashboard")}>
            Continue
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
