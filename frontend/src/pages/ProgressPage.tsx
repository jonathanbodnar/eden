import { useEffect, useState } from "react";
import { api, SourceProgress } from "../api";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function ProgressBar({ value, max, color }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="progress-bar-container" style={{ width: 120 }}>
      <div className={`progress-bar ${color || ""}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function ProgressPage() {
  const [progress, setProgress] = useState<SourceProgress[]>([]);

  const load = () => {
    api.getAllSourceProgress().then(setProgress).catch(() => {});
  };

  useEffect(() => {
    load();
    const i = setInterval(load, 5000);
    return () => clearInterval(i);
  }, []);

  return (
    <div>
      <div className="page-header">
        <h1>Ingestion Progress</h1>
        <p>Source-level and stage-level progress tracking</p>
      </div>

      {progress.length === 0 ? (
        <div className="card empty-state">
          <p>No progress data yet. Run ingestion on a trusted source to see progress here.</p>
        </div>
      ) : (
        progress.map((p) => (
          <div className="card" key={p.id} style={{ marginBottom: 16 }}>
            <div className="card-header">
              <div>
                <span className="card-title">{p.source_name}</span>
                <span style={{ marginLeft: 10 }} className={`badge ${p.active ? "badge-success" : "badge-muted"}`}>
                  {p.active ? "Active" : "Inactive"}
                </span>
              </div>
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                {formatBytes(p.total_bytes_stored)} stored
              </span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 12 }}>
              <StageCard label="Discovered" count={p.discovered_count} total={p.discovered_count} color="success" />
              <StageCard label="Fetched" count={p.fetched_count} total={p.discovered_count} />
              <StageCard label="Normalized" count={p.normalized_count} total={p.fetched_count} />
              <StageCard label="Segmented" count={p.segmented_count} total={p.normalized_count} />
              <StageCard label="Embedded" count={p.embedded_count} total={p.segmented_count} />
            </div>

            {p.failed_count > 0 && (
              <div style={{ color: "var(--error)", fontSize: 13 }}>
                {p.failed_count} failed &middot; {p.skipped_count} skipped
              </div>
            )}

            {p.last_successful_checkpoint && (
              <div style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 6 }}>
                Last checkpoint: {new Date(p.last_successful_checkpoint).toLocaleString()}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

function StageCard({ label, count, total, color }: { label: string; count: number; total: number; color?: string }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text-primary)" }}>
        {count.toLocaleString()}
      </div>
      <ProgressBar value={count} max={total} color={color} />
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
        {total > 0 ? `${pct}%` : "-"}
      </div>
    </div>
  );
}
