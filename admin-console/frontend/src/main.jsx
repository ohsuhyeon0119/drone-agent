import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, RequireAuth } from "./auth.jsx";
import Layout from "./components/Layout.jsx";
import "./index.css";
import ActionDetail from "./pages/ActionDetail.jsx";
import Actions from "./pages/Actions.jsx";
import Contacts from "./pages/Contacts.jsx";
import Deploy from "./pages/Deploy.jsx";
import Login from "./pages/Login.jsx";
import Monitor from "./pages/Monitor.jsx";
import Onboarding from "./pages/Onboarding.jsx";
import Signup from "./pages/Signup.jsx";
import ScenarioDetail from "./pages/ScenarioDetail.jsx";
import ScenarioNew from "./pages/ScenarioNew.jsx";
import Scenarios from "./pages/Scenarios.jsx";
import { StoreProvider } from "./store.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AuthProvider>
    <StoreProvider>
      <HashRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          {/* 온보딩은 사이드바 밖에 둔다 — 아직 설정할 게 없는 단계라
              시나리오·배포 메뉴를 보여주면 주의가 흩어진다. */}
          <Route
            path="/onboarding"
            element={
              <RequireAuth>
                <Onboarding />
              </RequireAuth>
            }
          />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<Navigate to="/monitor" replace />} />
            <Route path="/monitor" element={<Monitor />} />
            <Route path="/scenarios" element={<Scenarios />} />
            <Route path="/scenarios/new" element={<ScenarioNew />} />
            <Route path="/scenarios/:id" element={<ScenarioDetail />} />
            <Route path="/actions" element={<Actions />} />
            <Route path="/actions/:id" element={<ActionDetail />} />
            <Route path="/contacts" element={<Contacts />} />
            <Route path="/deploy" element={<Deploy />} />
          </Route>
          <Route path="*" element={<Navigate to="/scenarios" replace />} />
        </Routes>
      </HashRouter>
    </StoreProvider>
    </AuthProvider>
  </React.StrictMode>,
);
