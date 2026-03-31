import { useEffect, useState } from "react";
import { api, QueuedJob } from "../api";

const STATUS_BADGE: Record<string, string> = {
  queued: "badge-info",
  running: "badge-warning",
  succeeded: "badge-success",
  failed: "badge-error",
  paused: "badge-muted",
  canceled: "badge-muted",
  partial: "badge-warning",
  skipped: "badge-muted",
};

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "-";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function QueuePage() {
  const [jobs, setJobs] = useState<QueuedJob[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<string>("");

  const load = () => {
    const params = filter ? { status: filter } : undefined;
    api.listJobs(params).then((r) => { setJobs(r.items); setTotal(r.total); });
  };

  useEffect(load, [filter]);
  useEffect(() => {
    const i = setInterval(load, 5000);
    return () => clearInterval(i);
  }, [filter]);

  const handleAction = async (id: string, action: string) => {
    try {
      if (action === "pause") await api.pauseJob(id);
      else if (action === "resume") await api.resumeJob(id);
      else if (action === "retry") await api.retryJob(id);
      else if (action === "cancel") await api.cancelJob(id);
      load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  const handleRecoverStalled = async () => {
    try {
      const result = await api.recoverStalled();
      alert(`Recovered ${result.recovered} stalled jobs`);
      load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1>Job Queue</h1>
          <p>{total} jobs total</p>
        </div>
        <div className="btn-group">
          <button className="btn btn-outline" onClick={handleRecoverStalled}>Recover Stalled</button>
        </div>
      </div>

      <div style={{ marginBottom: 16, display: "flex", gap: 8 }}>
        {["", "queued", "running", "succeeded", "failed", "paused"].map((s) => (
          <button
            key={s}
            className={`btn btn-sm ${filter === s ? "btn-primary" : "btn-outline"}`}
            onClick={() => setFilter(s)}
          >
            {s || "All"}
          </button>
        ))}
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Job ID</th>
              <th>Type</th>
              <th>Status</th>
              <th>Worker</th>
              <th>Attempts</th>
              <th>Started</th>
              <th>Heartbeat</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td style={{ fontFamily: "monospace", fontSize: 12 }}>{j.id.slice(0, 8)}</td>
                <td><span className="badge badge-info">{j.job_type}</span></td>
                <td><span className={`badge ${STATUS_BADGE[j.status] || "badge-muted"}`}>{j.status}</span></td>
                <td style={{ fontSize: 12 }}>{j.worker_id || "-"}</td>
                <td>{j.attempt_count}/{j.max_attempts}</td>
                <td>{timeAgo(j.started_at)}</td>
                <td>{timeAgo(j.last_heartbeat_at)}</td>
                <td>
                  <div className="btn-group">
                    {j.status === "running" && (
                      <button className="btn btn-outline btn-sm" onClick={() => handleAction(j.id, "pause")}>Pause</button>
                    )}
                    {j.status === "paused" && (
                      <button className="btn btn-outline btn-sm" onClick={() => handleAction(j.id, "resume")}>Resume</button>
                    )}
                    {j.status === "failed" && (
                      <button className="btn btn-outline btn-sm" onClick={() => handleAction(j.id, "retry")}>Retry</button>
                    )}
                    {(j.status === "queued" || j.status === "paused") && (
                      <button className="btn btn-danger btn-sm" onClick={() => handleAction(j.id, "cancel")}>Cancel</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {jobs.length === 0 && (
              <tr><td colSpan={8} className="empty-state">No jobs found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
