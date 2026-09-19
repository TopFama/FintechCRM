import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Numbers from "./pages/Numbers";
import Templates from "./pages/Templates";
import Faixas from "./pages/Faixas";
import FaixaWizard from "./pages/FaixaWizard";
import FaixaDetail from "./pages/FaixaDetail";
import Relatorios from "./pages/Relatorios";
import { IconDashboard, IconLayers, IconLogout, IconPhone, IconReport, IconTemplate } from "./icons";

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
        <div className="brand">
          <div className="brand-mark">TF</div>
          <div className="brand-text">
            <div className="name">TopFama</div>
            <div className="tagline">Fintech · Crédito &amp; Cobrança</div>
          </div>
        </div>

        <div className="nav-section-label">Menu</div>
        <nav>
          <NavLink to="/" end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconDashboard /> Dashboard
          </NavLink>
          <NavLink to="/numeros" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconPhone /> Números
          </NavLink>
          <NavLink to="/templates" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconTemplate /> Templates
          </NavLink>
          <NavLink to="/faixas" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconLayers /> Faixas de cobrança
          </NavLink>
          <NavLink to="/relatorios" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconReport /> Relatórios
          </NavLink>
        </nav>

        <div className="sidebar-footer">
          <button
            className="logout-btn"
            onClick={() => {
              localStorage.removeItem("token");
              window.location.href = "/login";
            }}
          >
            <IconLogout /> Sair
          </button>
        </div>
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
      <Route
        path="/relatorios"
        element={
          <RequireAuth>
            <Layout>
              <Relatorios />
            </Layout>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
