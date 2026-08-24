/** Markdown files the support chat answers from. */
export interface SupportSource {
  /** Path relative to the repo root. */
  path: string;
  /** Stable label stored on every chunk. */
  source: string;
  /** Where a citation should link. */
  baseUrl: string;
}

export const CHUNK_MAX_CHARS = 1200;

export const SUPPORT_SOURCES: SupportSource[] = [
  {
    path: "README.md",
    source: "README.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/README.md",
  },
  {
    path: "docs/PROVIDERS.md",
    source: "docs/PROVIDERS.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/docs/PROVIDERS.md",
  },
  {
    path: "docs/KEY_ROTATION_RUNBOOK.md",
    source: "docs/KEY_ROTATION_RUNBOOK.md",
    baseUrl: "https://github.com/sairintechnologycom/burnlens/blob/main/docs/KEY_ROTATION_RUNBOOK.md",
  },
  {
    path: "frontend/support-knowledge/faq.md",
    source: "support-knowledge/faq.md",
    baseUrl: "https://burnlens.app/faq",
  },
  {
    path: "frontend/support-knowledge/evidence.md",
    source: "support-knowledge/evidence.md",
    baseUrl: "https://burnlens.app/docs/evidence",
  },
  {
    path: "frontend/support-knowledge/limitations.md",
    source: "support-knowledge/limitations.md",
    baseUrl: "https://burnlens.app/docs/limitations",
  },
  {
    path: "frontend/support-knowledge/troubleshooting.md",
    source: "support-knowledge/troubleshooting.md",
    baseUrl: "https://burnlens.app/troubleshooting",
  },
];
