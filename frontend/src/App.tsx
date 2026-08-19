import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { Onboarding } from "@/pages/Onboarding";
import { Dashboard } from "@/pages/Dashboard";
import { Colleges } from "@/pages/Colleges";
import { CollegeDetail } from "@/pages/CollegeDetail";
import { Requirements } from "@/pages/Requirements";
import { Essays } from "@/pages/Essays";
import { Tasks } from "@/pages/Tasks";
import { Priorities } from "@/pages/Priorities";
import { EssayMap } from "@/pages/EssayMap";
import { Readiness } from "@/pages/Readiness";
import { AgentActivity } from "@/pages/AgentActivity";
import { Settings } from "@/pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route path="/onboarding" element={<Onboarding />} />
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/colleges" element={<Colleges />} />
        <Route path="/colleges/:collegeId" element={<CollegeDetail />} />
        <Route path="/requirements" element={<Requirements />} />
        <Route path="/essays" element={<Essays />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/priorities" element={<Priorities />} />
        <Route path="/essay-map" element={<EssayMap />} />
        <Route path="/readiness" element={<Readiness />} />
        <Route path="/agent-activity" element={<AgentActivity />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
