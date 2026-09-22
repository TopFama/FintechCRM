import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, limparAutenticado, pareceAutenticado } from "./api";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Faixas from "./pages/Faixas";
import FaixaWizard from "./pages/FaixaWizard";
import FaixaDetail from "./pages/FaixaDetail";
import Relatorios from "./pages/Relatorios";
import Cobranca from "./pages/Cobranca";
import Leads from "./pages/Leads";
import Blacklist from "./pages/Blacklist";
import Configuracoes from "./pages/Configuracoes";
import {
  IconDashboard,
  IconLayers,
  IconLogout,
  IconReport,
  IconUsers,
  IconList,
  IconBan,
  IconSettings,
} from "./icons";

function RequireAuth({ children }: { children: JSX.Element }) {
  if (!pareceAutenticado()) return <Navigate to="/login" replace />;
  return children;
}

function Layout({ children }: { children: JSX.Element }) {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <img src="/topfama-logo.png" alt="TopFama" className="brand-logo" />
          <span className="brand-tagline">Fintech · Crédito &amp; Cobrança</span>
        </div>

        <div className="nav-section-label">Menu</div>
        <nav>
          <NavLink to="/" end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconDashboard /> Dashboard
          </NavLink>
          <NavLink to="/cobranca" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconUsers /> Cobrança
          </NavLink>
          <NavLink to="/leads" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconList /> Leads
          </NavLink>
          <NavLink to="/blacklist" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconBan /> Blacklist
          </NavLink>
          <NavLink to="/faixas" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconLayers /> Faixas de cobrança
          </NavLink>
          <NavLink to="/relatorios" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconReport /> Relatórios
          </NavLink>
          <NavLink to="/configuracoes" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconSettings /> Configurações
          </NavLink>
        </nav>

        <div className="sidebar-footer">
          <button
            className="logout-btn"
            onClick={() => {
              limparAutenticado();
              api.logout().catch(() => {});
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
        path="/cobranca"
        element={
          <RequireAuth>
            <Layout>
              <Cobranca />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/leads"
        element={
          <RequireAuth>
            <Layout>
              <Leads />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/blacklist"
        element={
          <RequireAuth>
            <Layout>
              <Blacklist />
            </Layout>
          </RequireAuth>
        }
      />
      <Route path="/templates" element={<Navigate to="/configuracoes?aba=templates" replace />} />
      <Route path="/usuarios" element={<Navigate to="/configuracoes?aba=usuarios" replace />} />
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
      <Route
        path="/configuracoes"
        element={
          <RequireAuth>
            <Layout>
              <Configuracoes />
            </Layout>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
