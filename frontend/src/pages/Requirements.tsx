import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { RequirementsList } from "@/components/collegentic/RequirementsList";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getColleges, getRequirements } from "@/lib/api";
import type { College, Requirement } from "@/lib/types";

const ALL_COLLEGES = "__all__";

export function Requirements() {
  const [colleges, setColleges] = useState<College[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [collegeFilter, setCollegeFilter] = useState(ALL_COLLEGES);

  useEffect(() => {
    getColleges().then(async (result) => {
      setColleges(result);
      if (result.length > 0) {
        setRequirements(await getRequirements(result.map((c) => c.id)));
      }
    });
  }, []);

  const collegeNameById = useMemo(
    () => Object.fromEntries(colleges.map((c) => [c.id, c.name])),
    [colleges]
  );

  const filtered =
    collegeFilter === ALL_COLLEGES
      ? requirements
      : requirements.filter((r) => r.collegeId === collegeFilter);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Requirements"
        description="Every requirement across every college, with status, confidence, and source transparency."
      />

      {colleges.length > 0 && (
        <Select value={collegeFilter} onValueChange={setCollegeFilter}>
          <SelectTrigger className="w-64">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_COLLEGES}>All colleges</SelectItem>
            {colleges.map((college) => (
              <SelectItem key={college.id} value={college.id}>
                {college.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      <RequirementsList
        requirements={filtered}
        collegeName={collegeFilter === ALL_COLLEGES ? (id) => collegeNameById[id] ?? id : undefined}
      />
    </div>
  );
}
