import enum


class SourceCategory(str, enum.Enum):
    TEXT_CORPUS = "text_corpus"
    MUSEUM_COLLECTION = "museum_collection"
    SITE_ARCHIVE = "site_archive"
    GAZETTEER = "gazetteer"
    PUBLIC_DOMAIN_LIBRARY = "public_domain_library"


class IngestionMethod(str, enum.Enum):
    API = "api"
    XML_FEED = "xml_feed"
    HTML_SCRAPE = "html_scrape"
    IIIF = "iiif"
    PDF_DOWNLOAD = "pdf_download"
    MANUAL_IMPORT = "manual_import"


class ParserType(str, enum.Enum):
    TEI_PARSER = "tei_parser"
    MUSEUM_HTML_PARSER = "museum_html_parser"
    JSON_API_PARSER = "json_api_parser"
    PDF_PARSER = "pdf_parser"


class TrustTier(str, enum.Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"


class DiscoveredRecordStatus(str, enum.Enum):
    NEW = "new"
    QUEUED = "queued"
    FETCHED = "fetched"
    FAILED = "failed"
    SKIPPED = "skipped"


class RecordStatus(str, enum.Enum):
    DRAFT = "draft"
    NORMALIZED = "normalized"
    REVIEWED = "reviewed"
    PUBLISHED = "published"


class ProvenanceStatus(str, enum.Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class DateType(str, enum.Enum):
    COMPOSITION = "composition"
    COPY_WITNESS = "copy_witness"
    OBJECT_CREATION = "object_creation"
    ARCHAEOLOGICAL_CONTEXT = "archaeological_context"
    DISCOVERY = "discovery"
    RECORDED = "recorded"
    PUBLICATION = "publication"


class DatingConfidence(str, enum.Enum):
    CERTAIN = "certain"
    PROBABLE = "probable"
    APPROXIMATE = "approximate"
    UNCERTAIN = "uncertain"
    SPECULATIVE = "speculative"


class VersionType(str, enum.Enum):
    ORIGINAL = "original"
    TRANSLITERATION = "transliteration"
    TRANSLATION = "translation"
    OCR = "ocr"
    MUSEUM_DESCRIPTION = "museum_description"
    EDITION = "edition"


class CopyrightStatus(str, enum.Enum):
    PUBLIC_DOMAIN = "public_domain"
    CC_BY = "cc_by"
    CC_BY_SA = "cc_by_sa"
    CC_BY_NC = "cc_by_nc"
    FAIR_USE = "fair_use"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class SegmentType(str, enum.Enum):
    TABLET = "tablet"
    SECTION = "section"
    LINE_RANGE = "line_range"
    PARAGRAPH = "paragraph"
    VERSE = "verse"
    OBJECT_SUMMARY = "object_summary"
    INSCRIPTION_BLOCK = "inscription_block"
    PROVENANCE_BLOCK = "provenance_block"
    DESCRIPTION_BLOCK = "description_block"
    TRENCH_LAYER_BLOCK = "trench_layer_block"
    FINDINGS_BLOCK = "findings_block"
    DATING_BLOCK = "dating_block"
    SPEAKER_BLOCK = "speaker_block"
    EPISODE_BLOCK = "episode_block"
    MOTIF_BLOCK = "motif_block"


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class JobType(str, enum.Enum):
    DISCOVER = "discover"
    FETCH = "fetch"
    NORMALIZE = "normalize"
    SEGMENT = "segment"
    EMBED = "embed"
    REPROCESS = "reprocess"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    PAUSED = "paused"
    CANCELED = "canceled"


class RunType(str, enum.Enum):
    DISCOVERY = "discovery"
    FULL_INGEST = "full_ingest"
    REPROCESS = "reprocess"


class RunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    PARTIAL = "partial"
