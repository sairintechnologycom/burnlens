export interface Chunk {
  id: string;
  source: string;
  heading: string;
  url: string;
  text: string;
}

export interface SupportIndex {
  generatedAt: string;
  chunks: Chunk[];
}

export interface SearchResult {
  chunk: Chunk;
  score: number;
}
