import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Numbers from "./pages/Numbers";
import Templates from "./pages/Templates";
import Faixas from "./pages/Faixas";
import FaixaWizard from "./pages/FaixaWizard";
import FaixaDetail from "./pages/FaixaDetail";

function isAuthenticated() {
  return Boolean(localStorage.getItem("token"));
}

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return children;
}

function Layout({ children }: { children: JSX.Element }) {
  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>FintechCRM</h1>
        <NavLink to="/" end>
          Dashboard
        </NavLink>
        <NavLink to="/numeros">Números</NavLink>
        <NavLink to="/templates">Templates</NavLink>
        <NavLink to="/faixas">Faixas de cobrança</NavLink>
        <button
          className="secondary"
          style={{ marginTop: 24, width: "100%" }}
          onClick={() => {
            localStorage.removeItem("token");
            window.location.href = "/login";
          }}
        >
          Sair
        </button>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout>
              <Dashboard />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/numeros"
        element={
          <RequireAuth>
            <Layout>
              <Numbers />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/templates"
        element={
          <RequireAuth>
            <Layout>
              <Templates />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/faixas"
        element={
          <RequireAuth>
            <Layout>
              <Faixas />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/faixas/nova"
        element={
          <RequireAuth>
            <Layout>
              <FaixaWizard />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/faixas/:id"
        element={
          <RequireAuth>
            <Layout>
              <FaixaDetail />
            </Layout>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
