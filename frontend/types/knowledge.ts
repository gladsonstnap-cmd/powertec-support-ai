export type KnowledgeDocument = {
  id: string;
  title: string;
  description?: string | null;
  category?: string | null;
  product?: string | null;
  version?: string | null;
  manufacturer?: string | null;
  document_type: string;
  status: string;
  valid_until?: string | null;
  sha256: string;
  size_bytes: number;
  mime_type: string;
  created_at: string;
  updated_at: string;
};

export type KnowledgeChunk = {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  keywords: string[];
};

export type KnowledgeSearchResult = {
  document_id: string;
  title: string;
  excerpt: string;
  score: number;
  product?: string | null;
  version?: string | null;
  status: string;
  reference: string;
};
