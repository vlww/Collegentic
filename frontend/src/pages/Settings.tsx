import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getUserId } from "@/lib/api";

export function Settings() {
  return (
    <div>
      <PageHeader title="Settings" description="Application year, Demo Mode, and cost-control transparency." />
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
