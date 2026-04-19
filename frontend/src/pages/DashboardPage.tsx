import { useEffect, useState } from "react";
import { api, Overview } from "../api";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

export default function DashboardPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getOverview().then(setOverview).catch((e) => setError(e.message));
    const interval = setInterval(() => {
      api.getOverview().then(setOverview).catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  if (error) {
    return (
      <div>
        <div className="page-header">
          <h1>Dashboard</h1>
        </div>
        <div className="card">
          <p style={{ color: "var(--text-muted)" }}>
            Unable to connect to API. Ensure the FastAPI server is running on port 8000.
          </p>
          <p style={{ color: "var(--error)", marginTop: 8, fontSize: 13 }}>{error}</p>
        </div>
      </div>
    );
  }

  if (!overview) {
    return <div className="loading">Loading dashboard...</div>;
  }

  return (
    <div>
      <div className="page-header">
        <h1>Dashboard</h1>
        <p>Eden Ingestion Platform overview</p>
      </div>

      <div className="stat-grid">
        <StatCard label="Trusted Sources" value={overview.total_trusted_sources} className="accent" />
        <StatCard label="Active Sources" value={overview.active_trusted_sources} className="success" />
        <StatCard label="Raw Objects" value={overview.total_raw_objects} />
        <StatCard label="Source Records" value={overview.total_source_records} />
        <StatCard label="Versions" value={overview.total_versions} />
        <StatCard label="Segments" value={overview.total_segments} />
        <StatCard label="Embeddings" value={overview.total_embeddings} />
        <StatCard label="Total Storage" value={formatBytes(overview.total_bytes_stored)} />
      </div>

      <div className="stat-grid">
        <StatCard label="Jobs Running" value={overview.jobs_running} className="info" />
        <StatCard label="Jobs Queued" value={overview.jobs_queued} className="warning" />
        <StatCard label="Jobs Failed" value={overview.jobs_failed} className="error" />
      </div>
    </div>
  );
}

function StatCard({ label, value, className }: { label: string; value: string | number; className?: string }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${className || ""}`}>{value.toLocaleString()}</div>
    </div>
  );
}
