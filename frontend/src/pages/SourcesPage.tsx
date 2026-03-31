import { useEffect, useState } from "react";
import { api, TrustedSource } from "../api";

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
  notes: "",
};

export default function SourcesPage() {
  const [sources, setSources] = useState<TrustedSource[]>([]);
  const [total, setTotal] = useState(0);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [editId, setEditId] = useState<string | null>(null);

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
      load();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : String(e));
    }
  };

  const handleEdit = (s: TrustedSource) => {
    setEditId(s.id);
    setForm({
      name: s.name, slug: s.slug, domain: s.domain, base_url: s.base_url,
      source_category: s.source_category, trust_tier: s.trust_tier,
      ingestion_method: s.ingestion_method, parser_type: s.parser_type,
      license_notes: s.license_notes || "", default_language: s.default_language || "",
      priority: s.priority, rate_limit_rpm: s.rate_limit_rpm || 60,
      crawl_frequency_hours: s.crawl_frequency_hours || 24, notes: s.notes || "",
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

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1>Trusted Sources</h1>
          <p>{total} registered sources</p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => { setEditId(null); setForm(emptyForm); setShowModal(true); }}
        >
          + Add Source
        </button>
      </div>

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

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{editId ? "Edit Source" : "Add Trusted Source"}</h2>
            <div className="form-row">
              <div className="form-group">
                <label>Name</label>
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="form-group">
                <label>Slug</label>
                <input value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} disabled={!!editId} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Domain</label>
                <input value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} />
              </div>
              <div className="form-group">
                <label>Base URL</label>
                <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Category</label>
                <select value={form.source_category} onChange={(e) => setForm({ ...form, source_category: e.target.value })}>
                  {SOURCE_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Trust Tier</label>
                <select value={form.trust_tier} onChange={(e) => setForm({ ...form, trust_tier: e.target.value })}>
                  {TRUST_TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Ingestion Method</label>
                <select value={form.ingestion_method} onChange={(e) => setForm({ ...form, ingestion_method: e.target.value })}>
                  {INGESTION_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Parser Type</label>
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
                <label>Default Language</label>
                <input value={form.default_language} onChange={(e) => setForm({ ...form, default_language: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Rate Limit (RPM)</label>
                <input type="number" value={form.rate_limit_rpm} onChange={(e) => setForm({ ...form, rate_limit_rpm: +e.target.value })} />
              </div>
              <div className="form-group">
                <label>Crawl Frequency (hours)</label>
                <input type="number" value={form.crawl_frequency_hours} onChange={(e) => setForm({ ...form, crawl_frequency_hours: +e.target.value })} />
              </div>
            </div>
            <div className="form-group">
              <label>License Notes</label>
              <textarea rows={2} value={form.license_notes} onChange={(e) => setForm({ ...form, license_notes: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Notes</label>
              <textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
            <div className="btn-group" style={{ justifyContent: "flex-end", marginTop: 20 }}>
              <button className="btn btn-outline" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSubmit}>{editId ? "Save" : "Create"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
