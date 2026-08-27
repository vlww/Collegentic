import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { RootRedirect } from "@/components/RootRedirect";
import { Onboarding } from "@/pages/Onboarding";
import { Dashboard } from "@/pages/Dashboard";
import { Colleges } from "@/pages/Colleges";
import { CollegeDetail } from "@/pages/CollegeDetail";
import { Essays } from "@/pages/Essays";
import { Progress } from "@/pages/Progress";
import { Tasks } from "@/pages/Tasks";
import { Readiness } from "@/pages/Readiness";
import { AgentActivity } from "@/pages/AgentActivity";
import { Settings } from "@/pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route path="/onboarding" element={<Onboarding />} />
      <Route element={<AppLayout />}>
        <Route path="/" element={<RootRedirect />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/colleges" element={<Colleges />} />
        <Route path="/colleges/:collegeId" element={<CollegeDetail />} />
        <Route path="/essays" element={<Essays />} />
        <Route path="/progress" element={<Progress />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/readiness" element={<Readiness />} />
        <Route path="/agent-activity" element={<AgentActivity />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
