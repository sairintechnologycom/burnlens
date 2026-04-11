"use client";

import React, { createContext, useContext, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, CheckCircle, AlertCircle, Info, AlertTriangle } from "lucide-react";

type ToastType = "success" | "error" | "info" | "warning";

interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToast = useCallback((message: string, type: ToastType = "success") => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div style={{
        position: "fixed",
        bottom: 24,
        right: 24,
        zIndex: 9999,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        pointerEvents: "none"
      }}>
        <AnimatePresence>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              initial={{ opacity: 0, y: 20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95, transition: { duration: 0.2 } }}
              style={{
                pointerEvents: "auto",
                minWidth: 320,
                maxWidth: 420,
                background: "rgba(20, 20, 25, 0.95)",
                backdropFilter: "blur(12px)",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                borderRadius: 16,
                padding: "16px 20px",
                display: "flex",
                alignItems: "center",
                gap: 16,
                boxShadow: "0 12px 32px rgba(0, 0, 0, 0.4)",
              }}
            >
              <div style={{ flexShrink: 0 }}>
                {toast.type === "success" && <CheckCircle size={20} color="var(--primary)" />}
                {toast.type === "error" && <AlertCircle size={20} color="#ef4444" />}
                {toast.type === "warning" && <AlertTriangle size={20} color="var(--accent)" />}
                {toast.type === "info" && <Info size={20} color="#3b82f6" />}
              </div>
              <div style={{ flex: 1, fontSize: 14, color: "#fff", fontWeight: 500, lineHeight: 1.4 }}>
                {toast.message}
              </div>
              <button 
                onClick={() => removeToast(toast.id)}
                style={{ 
                  background: "none", 
                  border: "none", 
                  color: "var(--muted)", 
                  cursor: "pointer",
                  padding: 4,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: 6,
                  transition: "background 0.2s"
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.05)"}
                onMouseLeave={(e) => e.currentTarget.style.background = "none"}
              >
                <X size={16} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within a ToastProvider");
  return context;
}
