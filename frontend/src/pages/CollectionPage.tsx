import { useEffect, useState, useCallback } from "react";
import {
  api,
  CollectionItem,
  CollectionItemDetail,
  CollectionStats,
  TrustedSource,
} from "../api";

function formatDate(isoDate: number | null, isoEnd: number | null): string {
  if (!isoDate && !isoEnd) return "Unknown";
  const fmt = (n: number) => (n < 0 ? `${Math.abs(n)} BCE` : `${n} CE`);
  if (isoDate && isoEnd && isoDate !== isoEnd) return `${fmt(isoDate)} – ${fmt(isoEnd)}`;
  return fmt(isoDate ?? isoEnd!);
}

function Badge({ label, variant = "default" }: { label: string; variant?: string }) {
  const cls =
    variant === "accent"
      ? "badge badge-info"
      : variant === "success"
      ? "badge badge-success"
      : variant === "warning"
      ? "badge badge-warning"
      : "badge";
  return <span className={cls}>{label}</span>;
}

function resolveImageSrc(img: { id: string; image_url: string; r2_key?: string | null }) {
  if (img.r2_key) return `/api/collection/images/${img.id}/file`;
  return img.image_url;
}

function ImageGallery({ images }: { images: { id: string; image_url: string; r2_key?: string | null; alt_text: string | null }[] }) {
  const [failedIds, setFailedIds] = useState<Set<string>>(new Set());

  if (!images.length) {
    return <div className="collection-no-images">No images</div>;
  }

  const valid = images.filter((i) => !failedIds.has(i.id));
  if (!valid.length) {
    return <div className="collection-no-images">Images unavailable</div>;
  }

  return (
    <div className="collection-gallery">
      {valid.map((img) => (
        <img
          key={img.id}
          src={resolveImageSrc(img)}
          alt={img.alt_text || ""}
          className="collection-thumb"
          loading="lazy"
          onError={() => setFailedIds((s) => new Set(s).add(img.id))}
        />
      ))}
    </div>
  );
}

function DetailModal({
  item,
  onClose,
}: {
  item: CollectionItemDetail;
  onClose: () => void;
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{item.canonical_title}</h2>
          <button className="btn btn-ghost" onClick={onClose}>
            &times;
          </button>
        </div>
        <div className="modal-body" style={{ maxHeight: "80vh", overflow: "auto" }}>
          {/* Images */}
          {item.images.length > 0 && (
            <section className="detail-section">
              <h3>Images ({item.images.length})</h3>
              <div className="detail-gallery">
                {item.images.map((img) => (
                  <a key={img.id} href={resolveImageSrc(img)} target="_blank" rel="noopener noreferrer">
                    <img
                      src={resolveImageSrc(img)}
                      alt={img.alt_text || ""}
                      className="detail-img"
                      loading="lazy"
                    />
                    {img.alt_text && <small>{img.alt_text}</small>}
                  </a>
                ))}
              </div>
            </section>
          )}

          {/* Metadata */}
          <section className="detail-section">
            <h3>Details</h3>
            <div className="detail-grid">
              <div><strong>Source:</strong> {item.source_name}</div>
              <div><strong>Category:</strong> {item.source_category.replace(/_/g, " ")}</div>
              {item.culture && <div><strong>Culture:</strong> {item.culture}</div>}
              {item.language_family && <div><strong>Language:</strong> {item.language_family}</div>}
              {item.origin_place_name && <div><strong>Origin:</strong> {item.origin_place_name}</div>}
              {item.repository_institution && <div><strong>Repository:</strong> {item.repository_institution}</div>}
              <div><strong>Provenance:</strong> {item.provenance_status}</div>
              <div><strong>Status:</strong> {item.record_status}</div>
              {item.source_url && (
                <div>
                  <strong>Source URL:</strong>{" "}
                  <a href={item.source_url} target="_blank" rel="noopener noreferrer">
                    View original
                  </a>
                </div>
              )}
            </div>
          </section>

          {/* Dates */}
          {item.dates.length > 0 && (
            <section className="detail-section">
              <h3>Dates</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Date</th>
                    <th>Label</th>
                    <th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {item.dates.map((d) => (
                    <tr key={d.id}>
                      <td>{d.date_type.replace(/_/g, " ")}</td>
                      <td>{formatDate(d.date_start, d.date_end)}</td>
                      <td>{d.date_label || "—"}</td>
                      <td><Badge label={d.dating_confidence} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {/* Versions / Text */}
          {item.versions.length > 0 && (
            <section className="detail-section">
              <h3>Text Versions ({item.versions.length})</h3>
              {item.versions.map((v) => (
                <div key={v.id} className="card" style={{ marginBottom: "0.75rem" }}>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.5rem" }}>
                    <Badge label={v.version_type.replace(/_/g, " ")} variant="accent" />
                    {v.language && <Badge label={v.language} />}
                    {v.is_preferred && <Badge label="preferred" variant="success" />}
                  </div>
                  {v.text_extracted ? (
                    <pre className="text-block">{v.text_extracted}</pre>
                  ) : (
                    <span className="text-muted">No extracted text</span>
                  )}
                </div>
              ))}
            </section>
          )}

          {/* Segments */}
          {item.segments.length > 0 && (
            <section className="detail-section">
              <h3>Segments ({item.segments.length})</h3>
              <div className="segments-list">
                {item.segments.map((s) => (
                  <div key={s.id} className="segment-item">
                    <div className="segment-meta">
                      <Badge label={s.segment_type.replace(/_/g, " ")} />
                      <span className="text-muted">#{s.segment_order}</span>
                    </div>
                    {s.normalized_text ? (
                      <pre className="text-block text-block-sm">{s.normalized_text}</pre>
                    ) : s.original_text ? (
                      <pre className="text-block text-block-sm">{s.original_text}</pre>
                    ) : (
                      <span className="text-muted">Empty segment</span>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Context Statements */}
          {item.context_statements.length > 0 && (
            <section className="detail-section">
              <h3>Context Statements ({item.context_statements.length})</h3>
              {item.context_statements.map((c) => (
                <div key={c.id} className="card" style={{ marginBottom: "0.5rem" }}>
                  <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.25rem" }}>
                    <Badge label={c.context_type.replace(/_/g, " ")} variant="accent" />
                    <Badge label={c.confidence} variant={c.confidence === "high" ? "success" : "default"} />
                    <Badge label={c.review_status} variant={c.review_status === "approved" ? "success" : "warning"} />
                  </div>
                  <p>{c.statement_text}</p>
                </div>
              ))}
            </section>
          )}

          {/* Metadata JSON */}
          {item.metadata_jsonb && Object.keys(item.metadata_jsonb).length > 0 && (
            <section className="detail-section">
              <h3>Raw Metadata</h3>
              <pre className="text-block text-block-sm">
                {JSON.stringify(item.metadata_jsonb, null, 2)}
              </pre>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

export default function CollectionPage() {
  const [items, setItems] = useState<CollectionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<CollectionStats | null>(null);
  const [sources, setSources] = useState<TrustedSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailItem, setDetailItem] = useState<CollectionItemDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [filters, setFilters] = useState({
    trusted_source_id: "",
    source_category: "",
    culture: "",
    search: "",
    has_images: "",
    sort_by: "newest",
    offset: "0",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      for (const [k, v] of Object.entries(filters)) {
        if (v) params[k] = v;
      }
      const [col, st, src] = await Promise.all([
        api.listCollection(params),
        stats ? Promise.resolve(stats) : api.getCollectionStats(),
        sources.length ? Promise.resolve({ items: sources, total: sources.length }) : api.listSources(),
      ]);
      setItems(col.items);
      setTotal(col.total);
      if (!stats) setStats(st);
      if (!sources.length) setSources(src.items);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
  }, [load]);

  const openDetail = async (id: string) => {
    setDetailLoading(true);
    try {
      const item = await api.getCollectionItem(id);
      setDetailItem(item);
    } catch (err) {
      console.error(err);
    } finally {
      setDetailLoading(false);
    }
  };

  const offset = parseInt(filters.offset) || 0;
  const pageSize = 40;
  const totalPages = Math.ceil(total / pageSize);
  const currentPage = Math.floor(offset / pageSize) + 1;

  return (
    <div>
      <header className="page-header">
        <h1>Collection Browser</h1>
        <p className="text-secondary">
          Browse all ingested objects with images, translations, and context
        </p>
      </header>

      {/* Stats Bar */}
      {stats && (
        <div className="stats-row">
          <div className="stat-card">
            <div className="stat-value">{stats.total_records.toLocaleString()}</div>
            <div className="stat-label">Records</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.total_images.toLocaleString()}</div>
            <div className="stat-label">Images</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.total_versions.toLocaleString()}</div>
            <div className="stat-label">Text Versions</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.total_segments.toLocaleString()}</div>
            <div className="stat-label">Segments</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.total_contexts.toLocaleString()}</div>
            <div className="stat-label">Context</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <div className="filter-row">
          <input
            type="text"
            className="input"
            placeholder="Search titles..."
            value={filters.search}
            onChange={(e) => setFilters({ ...filters, search: e.target.value, offset: "0" })}
          />
          <select
            className="input"
            value={filters.trusted_source_id}
            onChange={(e) => setFilters({ ...filters, trusted_source_id: e.target.value, offset: "0" })}
          >
            <option value="">All Sources</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <select
            className="input"
            value={filters.source_category}
            onChange={(e) => setFilters({ ...filters, source_category: e.target.value, offset: "0" })}
          >
            <option value="">All Categories</option>
            <option value="text_corpus">Text Corpus</option>
            <option value="museum_collection">Museum Collection</option>
            <option value="site_archive">Site Archive</option>
            <option value="gazetteer">Gazetteer</option>
            <option value="public_domain_library">Public Domain Library</option>
          </select>
          <select
            className="input"
            value={filters.has_images}
            onChange={(e) => setFilters({ ...filters, has_images: e.target.value, offset: "0" })}
          >
            <option value="">All Records</option>
            <option value="true">With Images</option>
            <option value="false">Without Images</option>
          </select>
          <select
            className="input"
            value={filters.sort_by}
            onChange={(e) => setFilters({ ...filters, sort_by: e.target.value, offset: "0" })}
          >
            <option value="newest">Newest First</option>
            <option value="oldest">Oldest First</option>
            <option value="images">Most Images</option>
            <option value="title">Title A–Z</option>
          </select>
          <button
            className="btn btn-ghost"
            onClick={() =>
              setFilters({ trusted_source_id: "", source_category: "", culture: "", search: "", has_images: "", sort_by: "newest", offset: "0" })
            }
          >
            Clear
          </button>
        </div>
      </div>

      {/* Results */}
      {loading ? (
        <div className="text-center text-secondary" style={{ padding: "3rem" }}>
          Loading collection...
        </div>
      ) : items.length === 0 ? (
        <div className="card text-center" style={{ padding: "3rem" }}>
          <p className="text-secondary">
            No records found. Objects will appear here as the pipeline processes sources.
          </p>
        </div>
      ) : (
        <>
          <div className="collection-grid">
            {items.map((item) => (
              <div
                key={item.id}
                className="collection-card"
                onClick={() => openDetail(item.id)}
              >
                <ImageGallery images={item.images} />
                <div className="collection-card-body">
                  <h3 className="collection-card-title">{item.canonical_title}</h3>
                  <div className="collection-card-meta">
                    <span className="text-muted">{item.source_name}</span>
                    {item.culture && <Badge label={item.culture} />}
                    {item.language_family && <Badge label={item.language_family} />}
                  </div>
                  {item.dates.length > 0 && (
                    <div className="collection-card-dates">
                      {item.dates.slice(0, 2).map((d) => (
                        <span key={d.id} className="text-muted" style={{ fontSize: "0.8rem" }}>
                          {d.date_type.replace(/_/g, " ")}: {formatDate(d.date_start, d.date_end)}
                        </span>
                      ))}
                    </div>
                  )}
                  {item.versions.some((v) => v.text_extracted) && (
                    <div className="collection-card-preview">
                      {item.versions
                        .find((v) => v.text_extracted)
                        ?.text_extracted?.slice(0, 200)}
                      ...
                    </div>
                  )}
                  <div className="collection-card-footer">
                    <span>{item.versions.length} version{item.versions.length !== 1 ? "s" : ""}</span>
                    <span>{item.segment_count} segment{item.segment_count !== 1 ? "s" : ""}</span>
                    <span>{item.images.length} image{item.images.length !== 1 ? "s" : ""}</span>
                    {item.context_count > 0 && <span>{item.context_count} context</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="pagination">
              <button
                className="btn btn-ghost"
                disabled={currentPage <= 1}
                onClick={() =>
                  setFilters({ ...filters, offset: String(Math.max(0, offset - pageSize)) })
                }
              >
                Previous
              </button>
              <span className="text-secondary">
                Page {currentPage} of {totalPages} ({total.toLocaleString()} records)
              </span>
              <button
                className="btn btn-ghost"
                disabled={currentPage >= totalPages}
                onClick={() =>
                  setFilters({ ...filters, offset: String(offset + pageSize) })
                }
              >
                Next
              </button>
            </div>
          )}
        </>
      )}

      {/* Detail Modal */}
      {detailItem && <DetailModal item={detailItem} onClose={() => setDetailItem(null)} />}

      {detailLoading && (
        <div className="modal-overlay">
          <div className="text-center" style={{ color: "white", fontSize: "1.2rem" }}>
            Loading details...
          </div>
        </div>
      )}
    </div>
  );
}
