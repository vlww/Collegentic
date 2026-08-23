import { useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { exitDemoMode, getUserId, isDemoSession } from "@/lib/api";

export function Settings() {
  const navigate = useNavigate();
  const demo = isDemoSession();

  function handleExitDemo() {
    exitDemoMode();
    navigate("/onboarding", { replace: true });
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Application year, Demo Mode, and cost-control transparency." />

      {demo && (
        <Card className="border-orange/30">
          <CardContent className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="border-orange/30 bg-orange-tint text-orange">
                <Sparkles className="h-3 w-3" />
                Demo Mode
              </Badge>
              <p className="text-sm text-muted-foreground">
                You're viewing a pre-built fictional profile — nothing here is real.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={handleExitDemo}>
              Exit Demo Mode
            </Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Local session</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-1">
          <p>
            No login yet — Collegentic identifies you by a browser-local id
            until Google OAuth is added (explicit future extension).
          </p>
          <p className="font-mono text-xs break-all">{getUserId()}</p>
        </CardContent>
      </Card>
    </div>
  );
}
