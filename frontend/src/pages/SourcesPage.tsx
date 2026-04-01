import { useEffect, useState } from "react";
import { api, TrustedSource, IntakeDomainGroup } from "../api";

const SOURCE_CATEGORIES = [
  "text_corpus", "museum_collection", "site_archive", "gazetteer", "public_domain_library",
];
const INGESTION_METHODS = ["api", "xml_feed", "html_scrape", "iiif", "pdf_download", "manual_import"];
const PARSER_TYPES = ["tei_parser", "museum_html_parser", "json_api_parser", "pdf_parser"];
const TRUST_TIERS = ["primary", "secondary", "tertiary"];

const emptyForm = {
  name: "", slug: "", domain: "", base_url: "",
  source_category: "text_corpus", trust_tier: "secondary",
  ingestion_method: "api", parser_type: "json_api_parser",
  license_notes: "", default_language: "",
  priority: 100, rate_limit_rpm: 60, crawl_frequency_hours: 24,
  notes: "", is_secondary_source: false,
};

function confidenceBadge(score: number) {
  if (score >= 0.8) return <span className="badge badge-success" style={{ fontSize: 10, marginLeft: 4 }}>high</span>;
  if (score >= 0.5) return <span className="badge badge-warning" style={{ fontSize: 10, marginLeft: 4 }}>medium</span>;
  if (score > 0) return <span className="badge badge-error" style={{ fontSize: 10, marginLeft: 4 }}>low</span>;
  return null;
}

export default function SourcesPage() {
  const [sources, setSources] = useState<TrustedSource[]>([]);
  const [total, setTotal] = useState(0);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [editId, setEditId] = useState<string | null>(null);
  const [confidence, setConfidence] = useState<Record<string, number> | null>(null);

  // Intake state
  const [intakeUrls, setIntakeUrls] = useState("");
  const [intakeLoading, setIntakeLoading] = useState(false);
  const [intakeResults, setIntakeResults] = useState<IntakeDomainGroup[] | null>(null);
  const [intakeError, setIntakeError] = useState("");

  const load = () => {
    api.listSources().then((r) => { setSources(r.items); setTotal(r.total); });
  };

  useEffect(load, []);

  const handleSubmit = async () => {
    try {
      if (editId) {
        await api.updateSource(editId, form);
      } else {
        await api.createSource(form);
      }
      setShowModal(false);
      setEditId(null);
      setForm(emptyForm);
      setConfidence(null);
      load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  const handleEdit = (s: TrustedSource) => {
    setEditId(s.id);
    setConfidence(null);
    setForm({
      name: s.name, slug: s.slug, domain: s.domain, base_url: s.base_url,
      source_category: s.source_category, trust_tier: s.trust_tier,
      ingestion_method: s.ingestion_method, parser_type: s.parser_type,
      license_notes: s.license_notes || "", default_language: s.default_language || "",
      priority: s.priority, rate_limit_rpm: s.rate_limit_rpm || 60,
      crawl_frequency_hours: s.crawl_frequency_hours || 24, notes: s.notes || "",
      is_secondary_source: false,
    });
    setShowModal(true);
  };

  const handleAction = async (id: string, action: string) => {
    try {
      if (action === "pause") await api.pauseSource(id);
      else if (action === "resume") await api.resumeSource(id);
      else if (action === "run") await api.runSource(id);
      else if (action === "reprocess") await api.reprocessSource(id);
      load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  const handleAnalyze = async () => {
    const urls = intakeUrls
      .split("\n")
      .map((u) => u.trim())
      .filter((u) => u.length > 0);

    if (urls.length === 0) return;

    setIntakeLoading(true);
    setIntakeError("");
    setIntakeResults(null);

    try {
      const result = await api.analyzeIntake(urls);
      setIntakeResults(result.groups);
    } catch (e: unknown) {
      setIntakeError(e instanceof Error ? e.message : String(e));
    } finally {
      setIntakeLoading(false);
    }
  };

  const handleUseSuggestion = (group: IntakeDomainGroup) => {
    const s = group.suggested_source;
    setEditId(null);
    setForm({
      name: s.name,
      slug: s.slug,
      domain: s.domain,
      base_url: s.base_url,
      source_category: s.source_category,
      trust_tier: s.trust_tier,
      ingestion_method: s.ingestion_method,
      parser_type: s.parser_type,
      license_notes: s.license_notes,
      default_language: s.default_language,
      priority: s.priority,
      rate_limit_rpm: s.rate_limit_rpm,
      crawl_frequency_hours: s.crawl_frequency_hours,
      notes: s.notes,
      is_secondary_source: s.is_secondary_source,
    });
    setConfidence(group.confidence);
    setShowModal(true);
  };

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1>Trusted Sources</h1>
          <p>{total} registered sources</p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => { setEditId(null); setForm(emptyForm); setConfidence(null); setShowModal(true); }}
        >
          + Add Source
        </button>
      </div>

      {/* Quick Add by URL */}
      <div className="card" style={{ marginBottom: 20, padding: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>Quick Add by URL</span>
          <span className="badge badge-info" style={{ fontSize: 10 }}>AI-assisted</span>
        </div>
        <textarea
          rows={3}
          style={{ width: "100%", marginBottom: 12, fontFamily: "monospace", fontSize: 13 }}
          placeholder="Paste one or many URLs, one per line..."
          value={intakeUrls}
          onChange={(e) => setIntakeUrls(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            className="btn btn-primary"
            onClick={handleAnalyze}
            disabled={intakeLoading || !intakeUrls.trim()}
          >
            {intakeLoading ? "Analyzing..." : "Analyze with AI"}
          </button>
          {intakeLoading && (
            <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
              Fetching pages and classifying sources...
            </span>
          )}
        </div>
        {intakeError && (
          <div style={{ marginTop: 12, padding: 10, background: "var(--error-bg, rgba(239,68,68,0.1))", borderRadius: 6, color: "var(--error)", fontSize: 13 }}>
            {intakeError}
          </div>
        )}
      </div>

      {/* Intake Results */}
      {intakeResults && intakeResults.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: 15, fontWeight: 600 }}>
              Analysis Results
            </span>
            <span className="badge badge-success">{intakeResults.length} source{intakeResults.length > 1 ? "s" : ""} detected</span>
          </div>
          {intakeResults.map((group) => (
            <div key={group.domain} className="card" style={{ marginBottom: 12, padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 600 }}>
                    {group.suggested_source.name || group.domain}
                  </div>
                  <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>
                    {group.domain} &middot; {group.urls.length} URL{group.urls.length > 1 ? "s" : ""} analyzed
                  </div>
                </div>
                <button className="btn btn-primary btn-sm" onClick={() => handleUseSuggestion(group)}>
                  Review &amp; Create
                </button>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 12, fontSize: 13 }}>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Category</span>{confidenceBadge(group.confidence.source_category)}
                  <div style={{ fontWeight: 500 }}>{group.suggested_source.source_category}</div>
                </div>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Trust Tier</span>{confidenceBadge(group.confidence.trust_tier)}
                  <div style={{ fontWeight: 500 }}>{group.suggested_source.trust_tier}</div>
                </div>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Method</span>{confidenceBadge(group.confidence.ingestion_method)}
                  <div style={{ fontWeight: 500 }}>{group.suggested_source.ingestion_method}</div>
                </div>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Parser</span>{confidenceBadge(group.confidence.parser_type)}
                  <div style={{ fontWeight: 500 }}>{group.suggested_source.parser_type}</div>
                </div>
              </div>

              {group.evidence.length > 0 && (
                <div style={{ fontSize: 12, color: "var(--text-muted)", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>Evidence</div>
                  {group.evidence.map((e, i) => (
                    <div key={i} style={{ marginBottom: 2 }}>
                      {e.startsWith("[AI]") ? (
                        <><span className="badge badge-info" style={{ fontSize: 9, marginRight: 4 }}>AI</span>{e.replace("[AI] ", "")}</>
                      ) : (
                        <><span className="badge badge-muted" style={{ fontSize: 9, marginRight: 4 }}>rules</span>{e}</>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {intakeResults && intakeResults.length === 0 && (
        <div className="card" style={{ marginBottom: 20, padding: 16, textAlign: "center", color: "var(--text-muted)" }}>
          No valid URLs could be analyzed. Check the URLs and try again.
        </div>
      )}

      {/* Sources Table */}
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Domain</th>
              <th>Category</th>
              <th>Method</th>
              <th>Status</th>
              <th>Priority</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id}>
                <td style={{ color: "var(--text-primary)", fontWeight: 500 }}>{s.name}</td>
                <td>{s.domain}</td>
                <td><span className="badge badge-info">{s.source_category}</span></td>
                <td>{s.ingestion_method}</td>
                <td>
                  <span className={`badge ${s.active ? "badge-success" : "badge-muted"}`}>
                    {s.active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td>{s.priority}</td>
                <td>
                  <div className="btn-group">
                    <button className="btn btn-outline btn-sm" onClick={() => handleEdit(s)}>Edit</button>
                    <button className="btn btn-outline btn-sm" onClick={() => handleAction(s.id, "run")}>Run</button>
                    {s.active ? (
                      <button className="btn btn-outline btn-sm" onClick={() => handleAction(s.id, "pause")}>Pause</button>
                    ) : (
                      <button className="btn btn-outline btn-sm" onClick={() => handleAction(s.id, "resume")}>Resume</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {sources.length === 0 && (
              <tr><td colSpan={7} className="empty-state">No sources registered yet</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={() => { setShowModal(false); setConfidence(null); }}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>
              {editId ? "Edit Source" : "Add Trusted Source"}
              {confidence && !editId && (
                <span className="badge badge-info" style={{ fontSize: 11, marginLeft: 8, verticalAlign: "middle" }}>AI-suggested — review before creating</span>
              )}
            </h2>
            <div className="form-row">
              <div className="form-group">
                <label>Name {confidence && confidenceBadge(confidence.name)}</label>
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="form-group">
                <label>Slug {confidence && confidenceBadge(confidence.slug)}</label>
                <input value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} disabled={!!editId} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Domain {confidence && confidenceBadge(confidence.domain)}</label>
                <input value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} />
              </div>
              <div className="form-group">
                <label>Base URL {confidence && confidenceBadge(confidence.base_url)}</label>
                <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Category {confidence && confidenceBadge(confidence.source_category)}</label>
                <select value={form.source_category} onChange={(e) => setForm({ ...form, source_category: e.target.value })}>
                  {SOURCE_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Trust Tier {confidence && confidenceBadge(confidence.trust_tier)}</label>
                <select value={form.trust_tier} onChange={(e) => setForm({ ...form, trust_tier: e.target.value })}>
                  {TRUST_TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Ingestion Method {confidence && confidenceBadge(confidence.ingestion_method)}</label>
                <select value={form.ingestion_method} onChange={(e) => setForm({ ...form, ingestion_method: e.target.value })}>
                  {INGESTION_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Parser Type {confidence && confidenceBadge(confidence.parser_type)}</label>
                <select value={form.parser_type} onChange={(e) => setForm({ ...form, parser_type: e.target.value })}>
                  {PARSER_TYPES.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Priority</label>
                <input type="number" value={form.priority} onChange={(e) => setForm({ ...form, priority: +e.target.value })} />
              </div>
              <div className="form-group">
                <label>Default Language {confidence && confidenceBadge(confidence.default_language)}</label>
                <input value={form.default_language} onChange={(e) => setForm({ ...form, default_language: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Rate Limit (RPM) {confidence && confidenceBadge(confidence.rate_limit_rpm)}</label>
                <input type="number" value={form.rate_limit_rpm} onChange={(e) => setForm({ ...form, rate_limit_rpm: +e.target.value })} />
              </div>
              <div className="form-group">
                <label>Crawl Frequency (hours) {confidence && confidenceBadge(confidence.crawl_frequency_hours)}</label>
                <input type="number" value={form.crawl_frequency_hours} onChange={(e) => setForm({ ...form, crawl_frequency_hours: +e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={form.is_secondary_source}
                    onChange={(e) => setForm({ ...form, is_secondary_source: e.target.checked })}
                    style={{ width: "auto" }}
                  />
                  Secondary Source (scholarly commentary, not primary data)
                </label>
              </div>
            </div>
            <div className="form-group">
              <label>License Notes {confidence && confidenceBadge(confidence.license_notes)}</label>
              <textarea rows={2} value={form.license_notes} onChange={(e) => setForm({ ...form, license_notes: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Notes {confidence && confidenceBadge(confidence.notes)}</label>
              <textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
            <div className="btn-group" style={{ justifyContent: "flex-end", marginTop: 20 }}>
              <button className="btn btn-outline" onClick={() => { setShowModal(false); setConfidence(null); }}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSubmit}>{editId ? "Save" : "Create"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
