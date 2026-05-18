export interface Chunk {
  id: string;
  source: string;
  heading: string;
  url: string;
  text: string;
}

export interface IndexedChunk extends Chunk {
  embedding: number[];
}

export interface SupportIndex {
  generatedAt: string;
  embedModel: string;
  dimension: number;
  chunks: IndexedChunk[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: { source: string; heading: string; url: string }[];
}
