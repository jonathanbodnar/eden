import { useEffect, useState } from "react";
import { api, QueuedJob } from "../api";

export default function FailuresPage() {
  const [jobs, setJobs] = useState<QueuedJob[]>([]);

  const load = () => {
    api.listJobs({ status: "failed" }).then((r) => setJobs(r.items)).catch(() => {});
  };

  useEffect(() => {
    load();
    const i = setInterval(load, 10000);
    return () => clearInterval(i);
  }, []);

  const handleRetry = async (id: string) => {
    try {
      await api.retryJob(id);
      load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Failures</h1>
        <p>{jobs.length} failed jobs requiring review</p>
      </div>

      {jobs.length === 0 ? (
        <div className="card empty-state">
          <p>No failed jobs. All systems operational.</p>
        </div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Type</th>
                <th>Attempts</th>
                <th>Failed At</th>
                <th>Error</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{j.id.slice(0, 8)}</td>
                  <td><span className="badge badge-error">{j.job_type}</span></td>
                  <td>{j.attempt_count}/{j.max_attempts}</td>
                  <td>{j.completed_at ? new Date(j.completed_at).toLocaleString() : "-"}</td>
                  <td>
                    <div
                      style={{
                        maxWidth: 400,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        fontSize: 12,
                        color: "var(--error)",
                      }}
                      title={j.error_log || ""}
                    >
                      {j.error_log || "No error details"}
                    </div>
                  </td>
                  <td>
                    <div className="btn-group">
                      <button className="btn btn-outline btn-sm" onClick={() => handleRetry(j.id)}>
                        Retry
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
