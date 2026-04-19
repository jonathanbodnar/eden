import { useEffect, useState } from "react";
import { api, ContextualStatement, ContextStats } from "../api";

const REVIEW_BADGE: Record<string, string> = {
  pending: "badge-warning",
  approved: "badge-success",
  rejected: "badge-error",
  needs_review: "badge-info",
};

const TYPE_LABELS: Record<string, string> = {
  descriptive: "Descriptive",
  comparative: "Comparative",
  scholarly_consensus: "Scholarly Consensus",
  scholarly_debate: "Scholarly Debate",
  functional_hypothesis: "Functional Hypothesis",
  uncertain: "Uncertain",
};

const CONFIDENCE_BADGE: Record<string, string> = {
  high: "badge-success",
  medium: "badge-info",
  low: "badge-warning",
  uncertain: "badge-muted",
};

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function ContextPage() {
  const [statements, setStatements] = useState<ContextualStatement[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<ContextStats | null>(null);
  const [typeFilter, setTypeFilter] = useState("");
  const [reviewFilter, setReviewFilter] = useState("");
  const [confidenceFilter, setConfidenceFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = () => {
    const params: Record<string, string> = {};
    if (typeFilter) params.context_type = typeFilter;
    if (reviewFilter) params.review_status = reviewFilter;
    if (confidenceFilter) params.confidence = confidenceFilter;

    api.listContextStatements(params).then((r) => {
      setStatements(r.items);
      setTotal(r.total);
    });
    api.getContextStats().then(setStats);
  };

  useEffect(load, [typeFilter, reviewFilter, confidenceFilter]);

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selected.size === statements.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(statements.map((s) => s.id)));
    }
  };

  const handleBatchReview = async (status: string) => {
    if (selected.size === 0) return;
    try {
      await api.batchReviewStatements(Array.from(selected), status);
      setSelected(new Set());
      load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  const handleSingleReview = async (id: string, status: string) => {
    try {
      await api.updateContextStatement(id, { review_status: status });
      load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Context Layer</h1>
        <p>{total} contextual statements</p>
      </div>

      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
          <div className="card" style={{ padding: 16, textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 700 }}>{stats.total}</div>
            <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Total Statements</div>
          </div>
          <div className="card" style={{ padding: 16, textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 700 }}>{stats.by_review_status["pending"] || 0}</div>
            <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Pending Review</div>
          </div>
          <div className="card" style={{ padding: 16, textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 700 }}>{stats.by_review_status["approved"] || 0}</div>
            <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Approved</div>
          </div>
          <div className="card" style={{ padding: 16, textAlign: "center" }}>
            <div style={{ fontSize: 28, fontWeight: 700 }}>
              {Object.values(stats.by_extraction_method).reduce((a, b) => a + b, 0) > 0
                ? `${Math.round(((stats.by_extraction_method["rules_based"] || 0) / stats.total) * 100)}%`
                : "0%"}
            </div>
            <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Rules-based</div>
          </div>
        </div>
      )}

      <div style={{ marginBottom: 16, display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>Type:</span>
          {["", "descriptive", "comparative", "scholarly_consensus", "scholarly_debate", "functional_hypothesis", "uncertain"].map((t) => (
            <button
              key={t}
              className={`btn btn-sm ${typeFilter === t ? "btn-primary" : "btn-outline"}`}
              onClick={() => setTypeFilter(t)}
            >
              {t ? TYPE_LABELS[t] || t : "All"}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>Review:</span>
          {["", "pending", "approved", "rejected", "needs_review"].map((s) => (
            <button
              key={s}
              className={`btn btn-sm ${reviewFilter === s ? "btn-primary" : "btn-outline"}`}
              onClick={() => setReviewFilter(s)}
            >
              {s || "All"}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>Confidence:</span>
          {["", "high", "medium", "low", "uncertain"].map((c) => (
            <button
              key={c}
              className={`btn btn-sm ${confidenceFilter === c ? "btn-primary" : "btn-outline"}`}
              onClick={() => setConfidenceFilter(c)}
            >
              {c || "All"}
            </button>
          ))}
        </div>
      </div>

      {selected.size > 0 && (
        <div style={{ marginBottom: 12, padding: "8px 12px", background: "var(--bg-accent)", borderRadius: 6, display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 13 }}>{selected.size} selected</span>
          <button className="btn btn-sm btn-success" onClick={() => handleBatchReview("approved")}>Approve</button>
          <button className="btn btn-sm btn-danger" onClick={() => handleBatchReview("rejected")}>Reject</button>
          <button className="btn btn-sm btn-outline" onClick={() => handleBatchReview("needs_review")}>Needs Review</button>
          <button className="btn btn-sm btn-outline" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th style={{ width: 30 }}>
                <input type="checkbox" checked={selected.size === statements.length && statements.length > 0} onChange={selectAll} />
              </th>
              <th>Statement</th>
              <th>Type</th>
              <th>Confidence</th>
              <th>Method</th>
              <th>Review</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {statements.map((s) => (
              <>
                <tr key={s.id} style={{ cursor: "pointer" }} onClick={() => setExpanded(expanded === s.id ? null : s.id)}>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(s.id)} onChange={() => toggleSelect(s.id)} />
                  </td>
                  <td style={{ maxWidth: 400 }}>
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.statement_text}
                    </div>
                  </td>
                  <td><span className="badge badge-info">{TYPE_LABELS[s.context_type] || s.context_type}</span></td>
                  <td><span className={`badge ${CONFIDENCE_BADGE[s.confidence] || "badge-muted"}`}>{s.confidence}</span></td>
                  <td style={{ fontSize: 12 }}>{s.extraction_method.replace("_", " ")}</td>
                  <td><span className={`badge ${REVIEW_BADGE[s.review_status] || "badge-muted"}`}>{s.review_status}</span></td>
                  <td style={{ fontSize: 12, whiteSpace: "nowrap" }}>{timeAgo(s.created_at)}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="btn-group">
                      {s.review_status !== "approved" && (
                        <button className="btn btn-outline btn-sm" onClick={() => handleSingleReview(s.id, "approved")}>Approve</button>
                      )}
                      {s.review_status !== "rejected" && (
                        <button className="btn btn-outline btn-sm" onClick={() => handleSingleReview(s.id, "rejected")}>Reject</button>
                      )}
                    </div>
                  </td>
                </tr>
                {expanded === s.id && (
                  <tr key={`${s.id}-detail`}>
                    <td colSpan={8} style={{ padding: 16, background: "var(--bg-accent)" }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                        <div>
                          <strong style={{ fontSize: 12, color: "var(--text-muted)" }}>Full Statement</strong>
                          <p style={{ margin: "4px 0", fontSize: 14 }}>{s.statement_text}</p>
                        </div>
                        <div>
                          <strong style={{ fontSize: 12, color: "var(--text-muted)" }}>Supporting Quote</strong>
                          <p style={{ margin: "4px 0", fontSize: 14, fontStyle: "italic" }}>{s.supporting_quote || "—"}</p>
                        </div>
                        <div>
                          <strong style={{ fontSize: 12, color: "var(--text-muted)" }}>Provenance</strong>
                          <div style={{ fontSize: 13 }}>
                            <div>Record: <code>{s.source_record_id?.slice(0, 8) || "—"}</code></div>
                            <div>Version: <code>{s.source_version_id?.slice(0, 8) || "—"}</code></div>
                            <div>Segment: <code>{s.segment_id?.slice(0, 8) || "—"}</code></div>
                          </div>
                        </div>
                        <div>
                          <strong style={{ fontSize: 12, color: "var(--text-muted)" }}>Classification</strong>
                          <div style={{ fontSize: 13 }}>
                            <div>Model: {s.classifier_model || "rules engine"}</div>
                            <div>Version: {s.classifier_version || "—"}</div>
                            <div>Method: {s.extraction_method}</div>
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
            {statements.length === 0 && (
              <tr><td colSpan={8} className="empty-state">No contextual statements found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
