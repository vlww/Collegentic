import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CalendarDays, ClipboardList, Gauge } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/collegentic/StatusBadge";
import { CollegeAvatar } from "@/components/collegentic/CollegeAvatar";
import { RequirementsList } from "@/components/collegentic/RequirementsList";
import { ReadinessCard } from "@/components/collegentic/ReadinessCard";
import { SectionCard } from "@/components/collegentic/SectionCard";
import { getCollege, getRequirements, getTasks, recomputeReadiness } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { College, Requirement, RequirementStatus } from "@/lib/types";

export function CollegeDetail() {
  const { collegeId } = useParams<{ collegeId: string }>();
  const [college, setCollege] = useState<College | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [hasTasks, setHasTasks] = useState(false);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!collegeId) return;
    getCollege(collegeId)
      .then(setCollege)
      .catch(() => setNotFound(true));
    getRequirements([collegeId]).then(setRequirements);
    getTasks(collegeId).then((tasks) => setHasTasks(tasks.length > 0));
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

  async function handleProgressChange(requirementId: string, status: RequirementStatus) {
    setRequirements((prev) =>
      prev.map((r) => (r.id === requirementId ? { ...r, status } : r))
    );
    await recomputeReadiness();
    if (collegeId) getCollege(collegeId).then(setCollege);
  }

  if (!college) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  const { deadlines, readiness } = college;

  return (
    <div className="space-y-6">
      <Link to="/colleges" className="text-sm text-muted-foreground hover:underline inline-flex items-center gap-1">
        <ArrowLeft className="h-3.5 w-3.5" /> Back to Colleges
      </Link>

      <div className="flex items-center justify-center gap-3">
        <CollegeAvatar college={college} size="lg" />
        <PageHeader title={college.name} />
        <StatusBadge status={college.status} />
      </div>

      <SectionCard title="Deadlines" icon={CalendarDays}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
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
        </div>
      </SectionCard>

      <div>
        <h2 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
          <Gauge className="h-4 w-4 text-orange" />
          Application Readiness
        </h2>
        <ReadinessCard college={college} readiness={readiness} hasTasks={hasTasks} />
      </div>

      <SectionCard title="Requirements" icon={ClipboardList} contentClassName="">
        <RequirementsList
          requirements={requirements}
          onProgressChange={handleProgressChange}
        />
      </SectionCard>
    </div>
  );
}
