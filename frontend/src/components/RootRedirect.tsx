import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { getColleges } from "@/lib/api";

/** The `/` landing check — .agents-cli-spec.md § Frontend Structure:
 * onboarding is "shown when no colleges are tracked." A demo profile
 * always seeds 6 colleges, so this single check already covers "and demo
 * mode is off" too — no separate demo flag needed here. Fails open to
 * /dashboard on a fetch error rather than trapping the user in a redirect
 * loop if the backend is briefly unreachable. */
export function RootRedirect() {
  const [target, setTarget] = useState<"/onboarding" | "/dashboard" | null>(null);

  useEffect(() => {
    getColleges()
      .then((colleges) => setTarget(colleges.length > 0 ? "/dashboard" : "/onboarding"))
      .catch(() => setTarget("/dashboard"));
  }, []);

  if (target === null) return null;
  return <Navigate to={target} replace />;
}
