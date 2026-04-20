"use client";

import React from "react";

interface EmptyStateProps {
  title: string;
  description?: string;
  code?: string;
  action?: {
    label: string;
    onClick?: () => void;
    href?: string;
  };
  secondaryAction?: {
    label: string;
    href: string;
  };
  icon?: React.ReactNode;
}

export default function EmptyState({
  title,
  description,
  code,
  action,
  secondaryAction,
  icon,
}: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon !== undefined ? (
        <div className="empty-state-icon">{icon}</div>
      ) : (
        <div className="empty-state-icon empty-state-icon-default" aria-hidden>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      )}
      <div className="empty-state-title">{title}</div>
      {description && <div className="empty-state-desc">{description}</div>}
      {code && (
        <code className="empty-state-code">
          {code.split("\n").map((line, i) => (
            <div key={i}>
              <span className="empty-state-code-prompt">$</span> {line}
            </div>
          ))}
        </code>
      )}
      {(action || secondaryAction) && (
        <div className="empty-state-actions">
          {action && (action.href ? (
            <a href={action.href} className="btn btn-cyan">{action.label}</a>
          ) : (
            <button className="btn btn-cyan" onClick={action.onClick}>{action.label}</button>
          ))}
          {secondaryAction && (
            <a href={secondaryAction.href} className="btn">{secondaryAction.label}</a>
          )}
        </div>
      )}
    </div>
  );
}
