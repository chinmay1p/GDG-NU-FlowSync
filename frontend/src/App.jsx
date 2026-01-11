import { useEffect, Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { getAuth } from "firebase/auth";

import useAuthStore from "./store/authStore";
import useThemeStore from "./store/themeStore";

import LandingPage from "./pages/LandingPage";
import CreateOrganization from "./pages/CreateOrganization";
import JoinOrganization from "./pages/JoinOrganization";
import SignIn from "./pages/SignIn";
import SignUp from "./pages/SignUp";
import OrgOnboarding from "./pages/OrgOnboarding";
import DashboardRedirect from "./pages/DashboardRedirect";

import DashboardLayout from "./components/layout/DashboardLayout";

import Overview from "./pages/dashboard/Overview";
import Teams from "./pages/dashboard/Teams";
import Members from "./pages/dashboard/Members";
import Tasks from "./pages/dashboard/Tasks";
import Calendar from "./pages/dashboard/Calendar";
import Meetings from "./pages/Meetings";
import Integrations from "./pages/dashboard/Integrations";
import ChangePassword from "./pages/dashboard/ChangePassword";

import OrganizationSettings from "./pages/settings/OrganizationSettings";
import TeamSettings from "./pages/settings/TeamSettings";
import ProfileSettings from "./pages/settings/ProfileSettings";

import Profile from "./components/layout/Profile";
import AudioControl from "./pages/AudioControl";

import { TaskApprovalProvider } from "./context/TaskApprovalContext";
import TaskApprovalPopup from "./components/TaskApprovalPopup";

// Lazy-loaded Zoom test page (for development/testing only)
const ZoomTest = lazy(() => import("./pages/ZoomTest"));

function App() {
  const setFromFirebase = useAuthStore((state) => state.setFromFirebase);
  const initializeSubscription = useAuthStore(
    (state) => state.initializeSubscription
  );
  const initTheme = useThemeStore((state) => state.initTheme);

  useEffect(() => {
    // Initialize theme (dark/light)
    initTheme();

    // Handle redirect-based Google auth
    import("./store/authStore").then((module) => {
      const store = module.default.getState();
      store.checkRedirectAuth();
    });

    // Firebase auth state sync
    const auth = getAuth();
    const unsubscribeAuth = auth.onAuthStateChanged(async (user) => {
      if (user) {
        try {
          const token = await user.getIdToken();
          setFromFirebase({
            uid: user.uid,
            email: user.email,
            displayName: user.displayName,
            photoURL: user.photoURL,
            idToken: token,
          });
        } catch (err) {
          console.error("Failed to fetch Firebase ID token", err);
        }
      }
    });

    // Firestore / backend auth subscription
    const unsubscribeStore = initializeSubscription();

    return () => {
      unsubscribeAuth();
      unsubscribeStore();
    };
  }, [initTheme, setFromFirebase, initializeSubscription]);

  return (
    <TaskApprovalProvider>
      <BrowserRouter
        future={{ v7_relativeSplatPath: true, v7_startTransition: true }}
      >
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/signin" element={<SignIn />} />
          <Route path="/signup" element={<SignUp />} />
          <Route path="/loading" element={<DashboardRedirect />} />
          <Route path="/get-started" element={<OrgOnboarding />} />
          <Route path="/create-org" element={<CreateOrganization />} />
          <Route path="/join-org" element={<JoinOrganization />} />
          <Route
            path="/zoom-test"
            element={
              <Suspense fallback={<div>Loading...</div>}>
                <ZoomTest />
              </Suspense>
            }
          />
          <Route path="/audio-control" element={<AudioControl />} />
          <Route path="/dashboard" element={<DashboardLayout />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<Overview />} />
            <Route path="teams" element={<Teams />} />
            <Route path="members" element={<Members />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="calendar" element={<Calendar />} />
            <Route path="meetings" element={<Meetings />} />
            <Route path="integrations" element={<Integrations />} />
            <Route path="settings">
              <Route index element={<Navigate to="organization" replace />} />
              <Route path="organization" element={<OrganizationSettings />} />
              <Route path="teams" element={<TeamSettings />} />
              <Route path="profile" element={<ProfileSettings />} />
            </Route>
          </Route>
        </Routes>

        {/* Global task approval popup for managers */}
        <TaskApprovalPopup />
      </BrowserRouter>
    </TaskApprovalProvider>
  );
}

export default App;

