-- Cancel all current jobs
UPDATE queued_jobs SET status = 'canceled' WHERE status IN ('queued', 'running');

-- Deactivate irrelevant sources (news sites, not archaeological archives)
UPDATE trusted_sources SET active = false WHERE slug IN (
  'sciencedaily',
  'google-scholar',
  'ancient-origins',
  'ancient-pages',
  'heritage-daily',
  'smithsonian-magazine',
  'archeo-news',
  'arkeonews',
  '4archaeology',
  'redalyc',
  'scielo',
  'web-kanzaki',
  'gita-society',
  'penn-precolumbian-society'
);

-- Fix base URLs to point to actual collection/catalog pages

-- Cuneiform / Sumerian / Akkadian sources
UPDATE trusted_sources SET base_url = 'https://cdli.earth/search', domain = 'cdli.earth' WHERE slug = 'cdli-ucla';
UPDATE trusted_sources SET base_url = 'https://etcsl.orinst.ox.ac.uk/edition2/etcslfullcat.php' WHERE slug = 'etcsl';
UPDATE trusted_sources SET base_url = 'https://oracc.museum.upenn.edu/projectlist.html' WHERE slug = 'oracc-upenn';
UPDATE trusted_sources SET base_url = 'https://www.thesaurus-linguae-aegyptiae.de/search/sentence' WHERE slug = 'thesaurus-linguae-aegyptiae';
UPDATE trusted_sources SET base_url = 'https://ramses.ulg.ac.be/search' WHERE slug = 'ramses-online-late-egyptian';

-- Egyptian sources
UPDATE trusted_sources SET base_url = 'https://www.digitalegypt.ucl.ac.uk/', domain = 'digitalegypt.ucl.ac.uk' WHERE slug = 'ucl-digital-egypt';

-- Museum collections
UPDATE trusted_sources SET base_url = 'https://www.britishmuseum.org/collection', domain = 'www.britishmuseum.org' WHERE slug = 'british-museum';
UPDATE trusted_sources SET base_url = 'https://www.metmuseum.org/art/collection/search', domain = 'www.metmuseum.org' WHERE slug = 'metmuseum';
UPDATE trusted_sources SET base_url = 'https://collections.louvre.fr/en/recherche' WHERE slug = 'louvre-collections';

-- Classical / Digital libraries
UPDATE trusted_sources SET base_url = 'https://www.perseus.tufts.edu/hopper/collection?collection=Perseus:collection:Greco-Roman', domain = 'www.perseus.tufts.edu' WHERE slug = 'perseus-digital-library';
UPDATE trusted_sources SET base_url = 'https://www.sacred-texts.com/ane/index.htm' WHERE slug = 'sacred-texts';
UPDATE trusted_sources SET base_url = 'https://www.gutenberg.org/ebooks/bookshelf/34' WHERE slug = 'project-gutenberg';

-- East Asian sources
UPDATE trusted_sources SET base_url = 'https://ctext.org/pre-qin-and-han' WHERE slug = 'chinese-text-project';
UPDATE trusted_sources SET base_url = 'https://www.chinaknowledge.de/Literature/literature.html' WHERE slug = 'chinaknowledge';
UPDATE trusted_sources SET base_url = 'https://japanese-wiki-corpus.org/culture/' WHERE slug = 'japanese-wiki-corpus';
UPDATE trusted_sources SET base_url = 'https://zh.wikisource.org/wiki/Portal:古典文学' WHERE slug = 'zh-wikisource';

-- South/Southeast Asian sources
UPDATE trusted_sources SET base_url = 'https://wisdomlib.org/hinduism' WHERE slug = 'wisdom-library';
UPDATE trusted_sources SET base_url = 'https://holybooks.com/category/hinduism/' WHERE slug = 'holybooks-com';
UPDATE trusted_sources SET base_url = 'https://srimadbhagavatam.org/canto/' WHERE slug = 'srimadbhagavatam-org';
UPDATE trusted_sources SET base_url = 'https://www.buddhanet.net/e-learning/history.htm' WHERE slug = 'buddhanet';
UPDATE trusted_sources SET base_url = 'https://www.daoiststudies.org/dao/texts' WHERE slug = 'daoist-studies';
UPDATE trusted_sources SET base_url = 'https://tibetanlibrary.org/digital-collection/' WHERE slug = 'tibetan-library-dharamshala';

-- European / French sources
UPDATE trusted_sources SET base_url = 'https://www.bl.uk/collection-guides' WHERE slug = 'british-library';
UPDATE trusted_sources SET base_url = 'https://gallica.bnf.fr/html/und/manuscrits/manuscrits' WHERE slug = 'gallica-bnf';
UPDATE trusted_sources SET base_url = 'https://www.persee.fr/collection/syria' WHERE slug = 'persee-digital-library';

-- Mesoamerican sources
UPDATE trusted_sources SET base_url = 'https://mesoweb.com/resources/index.html' WHERE slug = 'mesoweb';

-- Clear all garbage scraped data
UPDATE source_progress SET last_run_id = NULL, discovered_count = 0, fetched_count = 0, normalized_count = 0, segmented_count = 0, embedded_count = 0, failed_count = 0, skipped_count = 0;
DELETE FROM job_checkpoints;
DELETE FROM queued_jobs;
DELETE FROM source_runs;
DELETE FROM contextual_statements;
DELETE FROM embeddings;
DELETE FROM segments;
DELETE FROM source_versions;
DELETE FROM source_dates;
DELETE FROM source_records;
DELETE FROM object_images;
DELETE FROM raw_objects;
DELETE FROM discovered_records;
