import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles, Loader2 } from "lucide-react";
import { AddCollegeForm } from "@/components/collegentic/AddCollegeForm";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getColleges, startDemoSession } from "@/lib/api";

/**
 * Pre-sidebar full-screen route — .agents-cli-spec.md § Frontend Structure:
 * "shown when no colleges are tracked." Two paths in, both landing on
 * /dashboard: real natural-language college input (AddCollegeForm, same
 * component the Colleges page uses — real web research, can take a
 * minute+), or Demo Mode (instant, hand-authored fictional profile, see
 * app/demo_data.py). A returning user who already has colleges is bounced
 * straight to /dashboard rather than seeing this again.
 */
export function Onboarding() {
  const navigate = useNavigate();
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);

  useEffect(() => {
    getColleges().then((colleges) => {
      if (colleges.length > 0) navigate("/dashboard", { replace: true });
    });
  }, [navigate]);

  async function handleTryDemo() {
    setDemoLoading(true);
    setDemoError(null);
    try {
      await startDemoSession();
      navigate("/dashboard", { replace: true });
    } catch {
      setDemoError("Something went wrong setting up the demo. Please try again.");
      setDemoLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-navy text-navy-foreground flex items-center justify-center px-4 py-12">
      <div className="max-w-lg w-full space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-semibold">Let's get your applications organized.</h1>
          <p className="text-sm text-navy-foreground/70">
            Tell Collegentic which colleges you're applying to — real requirements get
            researched from official sources, with tasks and priorities planned
            automatically.
          </p>
        </div>

        <div className="bg-card text-card-foreground rounded-xl border shadow-sm">
          <AddCollegeForm onDone={() => navigate("/dashboard", { replace: true })} />
        </div>

        <div className="flex items-center gap-3 text-navy-foreground/50">
          <div className="h-px flex-1 bg-navy-foreground/20" />
          <span className="text-xs uppercase tracking-wide">or</span>
          <div className="h-px flex-1 bg-navy-foreground/20" />
        </div>

        <Card className="bg-card text-card-foreground">
          <CardContent className="space-y-3 text-center">
            <p className="text-sm text-muted-foreground">
              Just want to see Collegentic in action? Try a pre-built profile — 6
              colleges, partial essays, a real recommendation conflict, and everything
              else populated instantly, no research wait.
            </p>
            <Button
              variant="outline"
              className="w-full"
              onClick={handleTryDemo}
              disabled={demoLoading}
            >
              {demoLoading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Setting up demo…
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" /> Try Demo Mode
                </>
              )}
            </Button>
            {demoError && <p className="text-sm text-destructive">{demoError}</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
