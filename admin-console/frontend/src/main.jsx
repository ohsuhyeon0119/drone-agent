import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import "./index.css";
import ActionDetail from "./pages/ActionDetail.jsx";
import Actions from "./pages/Actions.jsx";
import Contacts from "./pages/Contacts.jsx";
import Deploy from "./pages/Deploy.jsx";
import Login from "./pages/Login.jsx";
import ScenarioDetail from "./pages/ScenarioDetail.jsx";
import Scenarios from "./pages/Scenarios.jsx";
import { StoreProvider } from "./store.jsx";

function RequireAuth({ children }) {
  const location = useLocation();
  if (!localStorage.getItem("donghaeng-authed")) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return children;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <StoreProvider>
      <HashRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<Navigate to="/scenarios" replace />} />
            <Route path="/scenarios" element={<Scenarios />} />
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
  </React.StrictMode>,
);
