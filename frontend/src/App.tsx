import { NavLink, Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import SourcesPage from "./pages/SourcesPage";
import QueuePage from "./pages/QueuePage";
import ProgressPage from "./pages/ProgressPage";
import FailuresPage from "./pages/FailuresPage";
import ContextPage from "./pages/ContextPage";
import CollectionPage from "./pages/CollectionPage";

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span>&#9670;</span> Eden
        </div>
        <nav>
          <ul className="sidebar-nav">
            <li>
              <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
                Dashboard
              </NavLink>
            </li>
            <li>
              <NavLink to="/sources" className={({ isActive }) => (isActive ? "active" : "")}>
                Trusted Sources
              </NavLink>
            </li>
            <li>
              <NavLink to="/queue" className={({ isActive }) => (isActive ? "active" : "")}>
                Queue
              </NavLink>
            </li>
            <li>
              <NavLink to="/progress" className={({ isActive }) => (isActive ? "active" : "")}>
                Progress
              </NavLink>
            </li>
            <li>
              <NavLink to="/failures" className={({ isActive }) => (isActive ? "active" : "")}>
                Failures
              </NavLink>
            </li>
            <li>
              <NavLink to="/context" className={({ isActive }) => (isActive ? "active" : "")}>
                Context Layer
              </NavLink>
            </li>
            <li>
              <NavLink to="/collection" className={({ isActive }) => (isActive ? "active" : "")}>
                Collection
              </NavLink>
            </li>
          </ul>
        </nav>
      </aside>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/queue" element={<QueuePage />} />
          <Route path="/progress" element={<ProgressPage />} />
          <Route path="/failures" element={<FailuresPage />} />
          <Route path="/context" element={<ContextPage />} />
          <Route path="/collection" element={<CollectionPage />} />
        </Routes>
      </main>
    </div>
  );
}
