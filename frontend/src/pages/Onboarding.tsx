import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { AddCollegeForm } from "@/components/collegentic/AddCollegeForm";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getColleges, startDemoSession } from "@/lib/api";
import logo from "@/assets/logo.png";

// 8-direction stacked drop-shadow — the standard way to fake a solid
// outline around a transparent PNG's actual silhouette in CSS (a single
// drop-shadow only offsets one copy; `filter` accepts a space-separated
// list of drop-shadows natively, unlike Tailwind's own drop-shadow-[...]
// utility, which overwrites rather than stacks when repeated).
const LOGO_OUTLINE_FILTER = [
  "drop-shadow(2px 0 0 #fff)",
  "drop-shadow(-2px 0 0 #fff)",
  "drop-shadow(0 2px 0 #fff)",
  "drop-shadow(0 -2px 0 #fff)",
  "drop-shadow(1.4px 1.4px 0 #fff)",
  "drop-shadow(-1.4px 1.4px 0 #fff)",
  "drop-shadow(1.4px -1.4px 0 #fff)",
  "drop-shadow(-1.4px -1.4px 0 #fff)",
].join(" ");

/**
 * Pre-sidebar full-screen route — .agents-cli-spec.md § Frontend Structure:
 * "shown when no colleges are tracked." Two paths in, both landing on
 * /colleges: real natural-language college input (AddCollegeForm, same
 * component the Colleges page uses — real web research, can take a
 * minute+), or Demo Mode (instant, hand-authored fictional profile, see
 * app/demo_data.py). A returning user who already has colleges is bounced
 * straight to /dashboard rather than seeing this again.
 *
 * Both paths navigate to /colleges the INSTANT the student acts (submits
 * the form / clicks Try Demo Mode), not after the request resolves —
 * found live: waiting for a real research call (a minute or more) or even
 * demo seeding to finish before leaving this screen just left a student
 * staring at a static loading spinner the whole time, when the Colleges
 * table (CollegeTable.tsx, ResearchProgressBar.tsx) is built specifically
 * to show that exact process live, field by field, as it happens. The
 * request itself is still fired from here (not abandoned) — Colleges.tsx's
 * own polling picks up the pipeline's progress the moment this page hands
 * off to it, via the `justSubmitted` navigation state (see its docstring).
 */
export function Onboarding() {
  const navigate = useNavigate();

  useEffect(() => {
    getColleges().then((colleges) => {
      if (colleges.length > 0) navigate("/dashboard", { replace: true });
    });
  }, [navigate]);

  function goToCollegesNow() {
    navigate("/colleges", { replace: true, state: { justSubmitted: true } });
  }

  function handleTryDemo() {
    goToCollegesNow();
    // Fire-and-forget: Colleges.tsx's own polling (bootstrapped by the
    // justSubmitted nav state above) picks up the seeded colleges the
    // moment they land, and its existing error/failed-pipeline handling
    // covers a failure here just as well as anything shown on this page
    // could, without making the student wait here to find out either way.
    startDemoSession().catch(() => {});
  }

  return (
    <div className="min-h-screen bg-navy text-navy-foreground flex items-center justify-center px-4 py-12">
      <div className="max-w-lg w-full space-y-6">
        <div className="flex flex-col items-center gap-2">
          <img
            src={logo}
            alt=""
            className="h-20 w-20 object-contain"
            style={{ filter: LOGO_OUTLINE_FILTER }}
          />
          <span
            className="uppercase text-4xl leading-none text-white"
            style={{ fontFamily: "'Maintanker', sans-serif" }}
          >
            Collegentic
          </span>
        </div>

        <div className="text-center space-y-2">
          <h1 className="text-2xl font-semibold">Let's get your applications organized.</h1>
        </div>

        <div className="bg-card text-card-foreground rounded-xl border shadow-sm">
          <AddCollegeForm onDone={() => {}} onSubmitStart={goToCollegesNow} />
        </div>

        <div className="flex items-center gap-3 text-navy-foreground/50">
          <div className="h-px flex-1 bg-navy-foreground/20" />
          <span className="text-xs uppercase tracking-wide">or</span>
          <div className="h-px flex-1 bg-navy-foreground/20" />
        </div>

        <Card className="bg-card text-card-foreground">
          <CardContent className="space-y-3 text-center">
            <p className="text-sm text-muted-foreground">
              Just want to see it in action? Try a pre-built profile, populated
              instantly, no research wait.
            </p>
            <Button variant="outline" className="w-full" onClick={handleTryDemo}>
              <Sparkles className="h-4 w-4" /> Try Demo Mode
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
