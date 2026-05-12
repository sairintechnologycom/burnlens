"use client";
import { useEffect, useRef, useState } from "react";

interface EditKeyLabelInlineProps {
  initialName: string;
  onSave: (newName: string) => Promise<void>;
  onCancel: () => void;
}

export default function EditKeyLabelInline({
  initialName,
  onSave,
  onCancel,
}: EditKeyLabelInlineProps) {
  const [value, setValue] = useState(initialName);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const handleSave = async () => {
    if (saving) return;
    if (value.trim().length === 0) return;
    setSaving(true);
    try {
      await onSave(value);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input
        ref={inputRef}
        className="form-input"
        value={value}
        maxLength={128}
        placeholder="Label or note"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            handleSave();
          }
          if (e.key === "Escape") onCancel();
        }}
        aria-label="Edit key label"
        disabled={saving}
        style={{ fontSize: 14, flex: 1 }}
      />
      <button
        className="btn btn-cyan"
        onClick={handleSave}
        disabled={saving || value.trim().length === 0}
        type="button"
      >
        {saving ? "Saving…" : "Save label"}
      </button>
      <button
        className="btn"
        onClick={onCancel}
        disabled={saving}
        type="button"
      >
        Discard changes
      </button>
    </div>
  );
}
