import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/collegentic/StatusBadge";
import { RequirementsList } from "@/components/collegentic/RequirementsList";
import { Card, CardContent } from "@/components/ui/card";
import { getCollege, getRequirements } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { College, Requirement } from "@/lib/types";

export function CollegeDetail() {
  const { collegeId } = useParams<{ collegeId: string }>();
  const [college, setCollege] = useState<College | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!collegeId) return;
    getCollege(collegeId)
      .then(setCollege)
      .catch(() => setNotFound(true));
    getRequirements([collegeId]).then(setRequirements);
  }, [collegeId]);

  if (notFound) {
    return (
      <div>
        <Link to="/colleges" className="text-sm text-muted-foreground hover:underline inline-flex items-center gap-1">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Colleges
        </Link>
        <p className="mt-4 text-sm text-muted-foreground">College not found.</p>
      </div>
    );
  }

  if (!college) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  const { deadlines } = college;

  return (
    <div className="space-y-6">
      <Link to="/colleges" className="text-sm text-muted-foreground hover:underline inline-flex items-center gap-1">
        <ArrowLeft className="h-3.5 w-3.5" /> Back to Colleges
      </Link>

      <div className="flex items-center gap-3">
        <PageHeader title={college.name} />
        <StatusBadge status={college.status} />
      </div>

      <Card>
        <CardContent className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Early Action</p>
            <p>{formatDate(deadlines.ea)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Early Decision</p>
            <p>{formatDate(deadlines.ed)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Regular Decision</p>
            <p>{formatDate(deadlines.rd)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Financial Aid</p>
            <p>{formatDate(deadlines.financialAid)}</p>
          </div>
        </CardContent>
      </Card>

      <div>
        <h2 className="text-sm font-semibold mb-3">Requirements</h2>
        <RequirementsList requirements={requirements} />
      </div>
    </div>
  );
}
