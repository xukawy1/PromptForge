from pathlib import Path
from app.database.connection import create_connection


MIGRATIONS = [
    (1, "创建 PromptForge 核心业务表", """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT '', url TEXT, source_type TEXT NOT NULL DEFAULT 'manual',
    author TEXT, publish_time TEXT, description TEXT, content_hash TEXT UNIQUE, status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE, title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '', content_hash TEXT UNIQUE, language TEXT, word_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT, raw_html_path TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL, file_path TEXT NOT NULL, original_url TEXT,
    file_hash TEXT UNIQUE, width INTEGER, height INTEGER, format TEXT, metadata TEXT, ocr_text TEXT, vision_result TEXT,
    analysis_status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    image_id INTEGER REFERENCES images(id) ON DELETE SET NULL, title TEXT NOT NULL DEFAULT '', prompt_text TEXT NOT NULL,
    negative_prompt TEXT, prompt_type TEXT NOT NULL DEFAULT 'image', target_model TEXT, language TEXT,
    content_hash TEXT UNIQUE, analysis_result TEXT, analysis_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    name TEXT NOT NULL, description TEXT, sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_id, name)
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS prompt_tags (
    prompt_id INTEGER NOT NULL REFERENCES prompts(id) ON DELETE CASCADE, tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY(prompt_id, tag_id)
);
CREATE TABLE IF NOT EXISTS prompt_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    canonical_name TEXT NOT NULL, name_zh TEXT, name_en TEXT, description TEXT, usage_context TEXT,
    component_type TEXT NOT NULL DEFAULT 'keyword', confidence REAL NOT NULL DEFAULT 0, usage_count INTEGER NOT NULL DEFAULT 0,
    is_favorite INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS prompt_component_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT, component_id INTEGER NOT NULL REFERENCES prompt_components(id) ON DELETE CASCADE,
    variant_text TEXT NOT NULL, language TEXT, style TEXT, source_prompt_id INTEGER REFERENCES prompts(id) ON DELETE SET NULL,
    confidence REAL NOT NULL DEFAULT 0, usage_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS prompt_component_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, component_id INTEGER NOT NULL REFERENCES prompt_components(id) ON DELETE CASCADE,
    related_component_id INTEGER NOT NULL REFERENCES prompt_components(id) ON DELETE CASCADE, relation_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(component_id, related_component_id, relation_type)
);
CREATE TABLE IF NOT EXISTS prompt_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    pattern_structure TEXT NOT NULL DEFAULT '[]', example_prompt TEXT, confidence REAL NOT NULL DEFAULT 0, usage_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT, category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    pattern_id INTEGER REFERENCES prompt_patterns(id) ON DELETE SET NULL, template_content TEXT NOT NULL,
    target_model TEXT, language TEXT, version INTEGER NOT NULL DEFAULT 1, usage_count INTEGER NOT NULL DEFAULT 0,
    is_system INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS template_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT, template_id INTEGER NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
    variable_name TEXT NOT NULL, display_name TEXT NOT NULL, category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    required INTEGER NOT NULL DEFAULT 0, default_value TEXT, sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(template_id, variable_name)
);
CREATE TABLE IF NOT EXISTS knowledge_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL, source_id INTEGER, title TEXT NOT NULL,
    content TEXT NOT NULL, summary TEXT, category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    knowledge_type TEXT NOT NULL DEFAULT 'general', confidence REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, object_type TEXT NOT NULL, object_id INTEGER NOT NULL, content_hash TEXT NOT NULL,
    model_name TEXT NOT NULL, vector_data BLOB NOT NULL, dimensions INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(object_type, object_id, model_name, content_hash)
);
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, provider TEXT NOT NULL, model_type TEXT NOT NULL,
    model_identifier TEXT, local_path TEXT, endpoint TEXT, status TEXT NOT NULL DEFAULT 'unknown', is_default INTEGER NOT NULL DEFAULT 0,
    parameters TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS generation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_input TEXT NOT NULL, prompt_result TEXT NOT NULL, negative_prompt TEXT,
    model_id INTEGER REFERENCES models(id) ON DELETE SET NULL, template_id INTEGER REFERENCES prompt_templates(id) ON DELETE SET NULL,
    retrieved_context TEXT, parameters TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, task_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', progress REAL NOT NULL DEFAULT 0,
    input_data TEXT, result_data TEXT, error_message TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, started_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT, value_type TEXT NOT NULL DEFAULT 'string', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_documents_source_id ON documents(source_id);
CREATE INDEX IF NOT EXISTS idx_images_document_id ON images(document_id);
CREATE INDEX IF NOT EXISTS idx_prompts_source_id ON prompts(source_id);
CREATE INDEX IF NOT EXISTS idx_prompts_image_id ON prompts(image_id);
CREATE INDEX IF NOT EXISTS idx_components_category_id ON prompt_components(category_id);
CREATE INDEX IF NOT EXISTS idx_variants_component_id ON prompt_component_variants(component_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_category_id ON knowledge_items(category_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_object ON embeddings(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""),
    (2, "新增 Skill 工坊表", """
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    description TEXT DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    source_path TEXT DEFAULT '',
    file_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_skills_keyword ON skills(keyword);
"""),
    (3, "分类表历史重复合并（同名同父仅保留最早一条）", """
UPDATE knowledge_items SET category_id = (
    SELECT MIN(c2.id) FROM categories c2
    WHERE c2.name = (SELECT c1.name FROM categories c1 WHERE c1.id = knowledge_items.category_id)
      AND IFNULL(c2.parent_id,-1) = IFNULL((SELECT c1.parent_id FROM categories c1 WHERE c1.id = knowledge_items.category_id),-1)
) WHERE category_id IS NOT NULL
  AND category_id NOT IN (SELECT MIN(id) FROM categories GROUP BY name, IFNULL(parent_id,-1));
UPDATE prompt_components SET category_id = (
    SELECT MIN(c2.id) FROM categories c2
    WHERE c2.name = (SELECT c1.name FROM categories c1 WHERE c1.id = prompt_components.category_id)
      AND IFNULL(c2.parent_id,-1) = IFNULL((SELECT c1.parent_id FROM categories c1 WHERE c1.id = prompt_components.category_id),-1)
) WHERE category_id IS NOT NULL
  AND category_id NOT IN (SELECT MIN(id) FROM categories GROUP BY name, IFNULL(parent_id,-1));
UPDATE prompt_templates SET category_id = (
    SELECT MIN(c2.id) FROM categories c2
    WHERE c2.name = (SELECT c1.name FROM categories c1 WHERE c1.id = prompt_templates.category_id)
      AND IFNULL(c2.parent_id,-1) = IFNULL((SELECT c1.parent_id FROM categories c1 WHERE c1.id = prompt_templates.category_id),-1)
) WHERE category_id IS NOT NULL
  AND category_id NOT IN (SELECT MIN(id) FROM categories GROUP BY name, IFNULL(parent_id,-1));
UPDATE template_components SET category_id = (
    SELECT MIN(c2.id) FROM categories c2
    WHERE c2.name = (SELECT c1.name FROM categories c1 WHERE c1.id = template_components.category_id)
      AND IFNULL(c2.parent_id,-1) = IFNULL((SELECT c1.parent_id FROM categories c1 WHERE c1.id = template_components.category_id),-1)
) WHERE category_id IS NOT NULL
  AND category_id NOT IN (SELECT MIN(id) FROM categories GROUP BY name, IFNULL(parent_id,-1));
UPDATE prompt_patterns SET category_id = (
    SELECT MIN(c2.id) FROM categories c2
    WHERE c2.name = (SELECT c1.name FROM categories c1 WHERE c1.id = prompt_patterns.category_id)
      AND IFNULL(c2.parent_id,-1) = IFNULL((SELECT c1.parent_id FROM categories c1 WHERE c1.id = prompt_patterns.category_id),-1)
) WHERE category_id IS NOT NULL
  AND category_id NOT IN (SELECT MIN(id) FROM categories GROUP BY name, IFNULL(parent_id,-1));
DELETE FROM categories WHERE id NOT IN (SELECT MIN(id) FROM categories GROUP BY name, IFNULL(parent_id,-1));
""")
]


def migrate(db_path: Path):
    conn = create_connection(db_path)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for version, description, sql in MIGRATIONS:
            if version in applied:
                continue
            try:
                with conn:
                    conn.executescript(sql)
                    conn.execute("INSERT INTO schema_migrations(version, description) VALUES (?, ?)", (version, description))
            except Exception:
                conn.rollback()
                raise
    finally:
        conn.close()
